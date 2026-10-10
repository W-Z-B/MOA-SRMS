"""Standing computation, manual override and the appeals process (S-W04)."""

from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from standing.models import AcademicStanding, StandingAppeal, StandingDecision

# GPA thresholds, flagged for GSA to confirm (the same convention as fees/services.py's own
# placeholders): a 4.00 scale, matching academics.GradeBand's existing points scale.
GOOD_STANDING_MIN_GPA = Decimal("2.00")
PROBATION_MIN_GPA = Decimal("1.50")
SUSPENSION_MIN_GPA = Decimal("1.00")
# below SUSPENSION_MIN_GPA is Dismissal.

APPEAL_DAYS = 14  # an appeal is lodged within this many days of the decision (GSA to confirm)
HOLD_SOURCE = "standing"
HOLD_TIERS = frozenset({AcademicStanding.Tier.SUSPENSION, AcademicStanding.Tier.DISMISSAL})


class StandingError(Exception):
    code = "invalid"

    def __init__(self, detail: str, code: str | None = None):
        super().__init__(detail)
        if code:
            self.code = code


def tier_for(cumulative_gpa: Decimal) -> str:
    if cumulative_gpa >= GOOD_STANDING_MIN_GPA:
        return AcademicStanding.Tier.GOOD
    if cumulative_gpa >= PROBATION_MIN_GPA:
        return AcademicStanding.Tier.PROBATION
    if cumulative_gpa >= SUSPENSION_MIN_GPA:
        return AcademicStanding.Tier.SUSPENSION
    return AcademicStanding.Tier.DISMISSAL


def _sync_hold(standing: AcademicStanding) -> None:
    """A tier of suspension or dismissal blocks new registration, through the generic
    RegistrationHold mechanism S-W02 already built (`Reason.ACADEMIC_STANDING`); recovering
    lifts it. This never touches a hold placed by another source (e.g. fees).
    """
    from academics.models import RegistrationHold

    if standing.tier in HOLD_TIERS:
        RegistrationHold.objects.get_or_create(
            student=standing.student,
            source=HOLD_SOURCE,
            reason=RegistrationHold.Reason.ACADEMIC_STANDING,
            is_active=True,
            defaults={"detail": f"Academic standing: {standing.get_tier_display()}"},
        )
    else:
        RegistrationHold.objects.filter(
            student=standing.student,
            source=HOLD_SOURCE,
            reason=RegistrationHold.Reason.ACADEMIC_STANDING,
            is_active=True,
        ).update(is_active=False, resolved_at=timezone.now())


def _latest_published_term(student):
    """The term of the student's most recently started published result, used only as the
    "as of" bookkeeping term on the standing row and decision — the GPA itself is always
    cumulative across every published result, not just this term's.
    """
    from academics.models import Result

    latest = (
        Result.objects.filter(enrolment__student=student, state=Result.State.PUBLISHED)
        .select_related("enrolment__offering__term")
        .order_by("-enrolment__offering__term__starts")
        .first()
    )
    return latest.enrolment.offering.term if latest else None


@transaction.atomic
def recompute_student(student) -> StandingDecision | None:
    """Recompute one student's standing from their published-results cumulative GPA (S-W04:
    never from a result still in the S-W03 approval chain, since `academics.services.gpa`
    defaults to `published_only=True`). Returns the new StandingDecision if the tier changed, or
    None if there was nothing to compute (no published results yet) or nothing changed.
    """
    from academics.services import gpa

    cumulative = gpa(student, published_only=True)
    standing, _ = AcademicStanding.objects.get_or_create(student=student)
    if cumulative is None:
        return None
    term = _latest_published_term(student)
    tier = tier_for(cumulative)
    standing.cumulative_gpa = cumulative
    standing.as_of_term = term
    standing.computed_at = timezone.now()
    if tier == standing.tier:
        standing.save(update_fields=["cumulative_gpa", "as_of_term", "computed_at", "updated_at"])
        return None
    decision = StandingDecision.objects.create(
        standing=standing,
        term=term,
        previous_tier=standing.tier,
        tier=tier,
        cumulative_gpa=cumulative,
        is_automatic=True,
    )
    standing.tier = tier
    standing.save()
    _sync_hold(standing)
    _notify(standing, decision)
    return decision


def _notify(standing: AcademicStanding, decision: StandingDecision) -> None:
    from notifications.services import notify

    notify(
        [standing.student.user],
        title=f"Academic standing: {standing.get_tier_display()}",
        body=f"Your academic standing changed from {decision.get_previous_tier_display()} to "
        f"{decision.get_tier_display()} ({decision.term.code}, GPA {decision.cumulative_gpa}).",
        link="/my-standing",
        dedupe_key=f"standing:{decision.id}",
    )


@transaction.atomic
def apply_override(student, *, term, tier: str, reason: str, actor) -> StandingDecision:
    """A Registrar's manual override (e.g. an extenuating-circumstances decision outside the
    GPA formula). Unlike an automatic recompute, this always creates a decision row, even if the
    tier is unchanged, since the override itself — and its reason — is the record worth keeping.
    """
    if not reason.strip():
        raise StandingError("A reason is required for a manual override.", code="reason_required")
    standing, _ = AcademicStanding.objects.get_or_create(student=student)
    decision = StandingDecision.objects.create(
        standing=standing,
        term=term,
        previous_tier=standing.tier,
        tier=tier,
        cumulative_gpa=standing.cumulative_gpa,
        is_automatic=False,
        reason=reason,
        decided_by=actor,
    )
    standing.tier = tier
    standing.save()
    _sync_hold(standing)
    _notify(standing, decision)
    return decision


@transaction.atomic
def lodge_appeal(decision: StandingDecision, *, grounds: str, student_user) -> StandingAppeal:
    if decision.standing.student.user_id != getattr(student_user, "id", None):
        raise StandingError("You can only appeal your own standing decision.", code="forbidden")
    if decision.tier == AcademicStanding.Tier.GOOD:
        raise StandingError(
            "A decision that improved or kept good standing cannot be appealed.", code="not_adverse"
        )
    if hasattr(decision, "appeal"):
        raise StandingError("This decision has already been appealed.", code="already_appealed")
    if timezone.now() > decision.created_at + timedelta(days=APPEAL_DAYS):
        raise StandingError(f"An appeal is lodged within {APPEAL_DAYS} days of the decision.", code="late")
    if not grounds.strip():
        raise StandingError("Grounds for the appeal are required.", code="grounds_required")
    return StandingAppeal.objects.create(decision=decision, grounds=grounds)


@transaction.atomic
def hear_appeal(appeal: StandingAppeal, *, outcome: str, reason: str, heard_by) -> StandingAppeal:
    if appeal.outcome:
        raise StandingError("This appeal has already been decided.", code="already_decided")
    decision = appeal.decision
    if decision.decided_by_id and decision.decided_by_id == getattr(heard_by, "id", None):
        raise StandingError(
            "An appeal is heard by someone other than whoever made the decision.", code="not_independent"
        )
    if not reason.strip():
        raise StandingError("A reason is required to decide an appeal.", code="reason_required")
    appeal.outcome = outcome
    appeal.outcome_reason = reason
    appeal.heard_by = heard_by
    appeal.heard_at = timezone.now()
    appeal.save()
    if outcome == StandingAppeal.Outcome.UPHELD:
        apply_override(
            decision.standing.student,
            term=decision.term,
            tier=decision.previous_tier,
            reason=f"Appeal upheld: {reason}",
            actor=heard_by,
        )
    return appeal
