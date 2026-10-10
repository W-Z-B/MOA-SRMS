from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from academics.models import RegistrationHold, Result
from academics.services import compute
from notifications.models import Notification
from standing.models import AcademicStanding, StandingAppeal
from standing.services import (
    APPEAL_DAYS,
    StandingError,
    apply_override,
    hear_appeal,
    lodge_appeal,
    recompute_student,
    tier_for,
)
from standing.tasks import recompute_all


@pytest.mark.parametrize(
    "gpa, expected",
    [
        (Decimal("4.00"), AcademicStanding.Tier.GOOD),
        (Decimal("2.00"), AcademicStanding.Tier.GOOD),
        (Decimal("1.99"), AcademicStanding.Tier.PROBATION),
        (Decimal("1.50"), AcademicStanding.Tier.PROBATION),
        (Decimal("1.49"), AcademicStanding.Tier.SUSPENSION),
        (Decimal("1.00"), AcademicStanding.Tier.SUSPENSION),
        (Decimal("0.99"), AcademicStanding.Tier.DISMISSAL),
        (Decimal("0.00"), AcademicStanding.Tier.DISMISSAL),
    ],
)
def test_tier_for_thresholds(gpa, expected):
    assert tier_for(gpa) == expected


def _publish(result: Result, coursework, exam):
    result.coursework_mark, result.exam_mark = coursework, exam
    compute(result)
    result.state = Result.State.PUBLISHED
    result.save(update_fields=["state", "updated_at"])
    return result


@pytest.mark.django_db
def test_recompute_places_a_hold_once_dismissed_and_lifts_it_on_recovery(result, student):
    _publish(result, 40, 40)  # F, 0.0 points -> dismissal
    decision = recompute_student(student)
    assert decision is not None and decision.tier == AcademicStanding.Tier.DISMISSAL
    standing = AcademicStanding.objects.get(student=student)
    assert standing.tier == AcademicStanding.Tier.DISMISSAL
    hold = RegistrationHold.objects.get(student=student, source="standing")
    assert hold.reason == RegistrationHold.Reason.ACADEMIC_STANDING and hold.is_active

    # A correction (or a second, stronger course) lifting the GPA back above the threshold
    # recovers standing and lifts the hold the same way fees' overdue job already does.
    _publish(result, 90, 90)
    decision2 = recompute_student(student)
    assert decision2.tier == AcademicStanding.Tier.GOOD
    hold.refresh_from_db()
    assert hold.is_active is False
    assert Notification.objects.filter(recipient=student.user).count() == 2


@pytest.mark.django_db
def test_recompute_is_a_noop_without_a_tier_change(result, student):
    _publish(result, 90, 90)  # A, good standing
    first = recompute_student(student)
    assert first is None  # was already "good" by default, nothing changed
    assert AcademicStanding.objects.get(student=student).decisions.count() == 0


@pytest.mark.django_db
def test_recompute_all_only_considers_active_students(result, student):
    _publish(result, 30, 30)
    student.status = "withdrawn"
    student.save(update_fields=["status"])
    summary = recompute_all()
    assert summary["considered"] == 0
    assert not AcademicStanding.objects.filter(student=student, tier=AcademicStanding.Tier.DISMISSAL).exists()


@pytest.mark.django_db
def test_manual_override_requires_a_reason(student, offering, registrar):
    with pytest.raises(StandingError):
        apply_override(student, term=offering.term, tier="probation", reason="  ", actor=registrar)
    decision = apply_override(
        student, term=offering.term, tier="probation", reason="Extenuating circumstances", actor=registrar
    )
    assert decision.decided_by == registrar and decision.is_automatic is False
    no_hold = RegistrationHold.objects.filter(student=student, source="standing", is_active=True)
    assert no_hold.exists() is False


@pytest.mark.django_db
def test_appeal_is_heard_by_someone_other_than_who_decided_it(student, offering, registrar, principal):
    decision = apply_override(
        student, term=offering.term, tier="suspension", reason="Policy breach", actor=registrar
    )
    appeal = lodge_appeal(decision, grounds="I was not given notice", student_user=student.user)

    with pytest.raises(StandingError) as exc:
        hear_appeal(appeal, outcome=StandingAppeal.Outcome.UPHELD, reason="Reconsidered", heard_by=registrar)
    assert exc.value.code == "not_independent"

    heard = hear_appeal(
        appeal, outcome=StandingAppeal.Outcome.UPHELD, reason="Notice was not given", heard_by=principal
    )
    assert heard.outcome == StandingAppeal.Outcome.UPHELD and heard.heard_by == principal
    standing = AcademicStanding.objects.get(student=student)
    assert standing.tier == AcademicStanding.Tier.GOOD  # reverted to the previous_tier on the decision


@pytest.mark.django_db
def test_a_decision_that_stayed_in_good_standing_cannot_be_appealed(student, offering, registrar):
    decision = apply_override(student, term=offering.term, tier="good", reason="Reinstated", actor=registrar)
    with pytest.raises(StandingError) as exc:
        lodge_appeal(decision, grounds="Disagree anyway", student_user=student.user)
    assert exc.value.code == "not_adverse"


@pytest.mark.django_db
def test_an_appeal_lodged_after_the_window_is_refused(student, offering, registrar):
    decision = apply_override(
        student, term=offering.term, tier="probation", reason="Low GPA", actor=registrar
    )
    decision.created_at = timezone.now() - timedelta(days=APPEAL_DAYS + 1)
    decision.save(update_fields=["created_at"])
    with pytest.raises(StandingError) as exc:
        lodge_appeal(decision, grounds="Too slow to appeal", student_user=student.user)
    assert exc.value.code == "late"


@pytest.mark.django_db
def test_my_standing_and_appeal_api(student, offering, registrar, principal, client_for):
    registry, board, me = client_for(registrar), client_for(principal), client_for(student.user)
    decision = apply_override(
        student, term=offering.term, tier="suspension", reason="Low GPA", actor=registrar
    )
    mine = me.get("/api/v1/standing/my-standing/").json()
    assert mine["tier"] == "suspension" and mine["decisions"][0]["reason"] == "Low GPA"

    appeal_url = f"/api/v1/standing/decisions/{decision.id}/appeal/"
    appeal = me.post(appeal_url, {"grounds": "Unfair"}, format="json")
    assert appeal.status_code == 201

    hear_url = f"/api/v1/standing/appeals/{appeal.json()['id']}/hear/"
    refused = registry.post(hear_url, {"outcome": "upheld", "reason": "x"}, format="json")
    assert refused.status_code == 403 and refused.json()["code"] == "not_independent"

    heard = board.post(hear_url, {"outcome": "upheld", "reason": "Reviewed and agreed"}, format="json")
    assert heard.json()["outcome"] == "upheld"


@pytest.mark.django_db
def test_lecturer_cannot_see_the_standing_register(student, lecturer, client_for):
    teacher = client_for(lecturer)
    assert teacher.get("/api/v1/standing/students/").status_code == 403


@pytest.mark.django_db
def test_only_the_student_can_appeal_their_own_decision(student, offering, registrar, make_user, client_for):
    decision = apply_override(
        student, term=offering.term, tier="probation", reason="Low GPA", actor=registrar
    )
    stranger = make_user("26MRP0999", "student", campus_code="MRP")
    with pytest.raises(StandingError) as exc:
        lodge_appeal(decision, grounds="Not mine", student_user=stranger)
    assert exc.value.code == "forbidden"
