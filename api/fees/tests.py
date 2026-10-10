from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.management import CommandError, call_command

from academics.models import RegistrationHold
from fees.models import FeeCharge, FeeItem, Payment
from fees.services import GRACE_PERIOD_DAYS, balance, charge_student_for_term, ledger, overdue_students
from fees.tasks import apply_overdue_holds


@pytest.fixture
def term(offering):
    return offering.term


@pytest.fixture
def tuition(programme, term):
    return FeeItem.objects.create(
        programme=programme,
        fee_type=FeeItem.FeeType.TUITION,
        amount=Decimal("50000.00"),
        effective_from=date(2020, 1, 1),
    )


@pytest.mark.django_db
def test_amount_on_picks_the_latest_effective_row(programme):
    FeeItem.objects.create(
        programme=programme, fee_type="tuition", amount=Decimal("40000"), effective_from=date(2020, 1, 1)
    )
    FeeItem.objects.create(
        programme=programme, fee_type="tuition", amount=Decimal("55000"), effective_from=date(2026, 1, 1)
    )
    assert FeeItem.amount_on(programme, "tuition", date(2025, 6, 1)) == Decimal("40000")
    assert FeeItem.amount_on(programme, "tuition", date(2026, 6, 1)) == Decimal("55000")
    assert FeeItem.amount_on(programme, "lab", date(2026, 6, 1)) is None


@pytest.mark.django_db
def test_charging_a_term_is_idempotent_and_snapshots_the_amount(student, term, tuition):
    first = charge_student_for_term(student, term)
    assert len(first) == 1 and first[0].amount == Decimal("50000.00")

    # A later rate change never touches a charge already raised.
    tuition.amount = Decimal("60000.00")
    tuition.save()
    second = charge_student_for_term(student, term)
    assert second == []
    assert FeeCharge.objects.get(student=student, term=term).amount == Decimal("50000.00")


@pytest.mark.django_db
def test_apply_fee_schedule_command_charges_the_cohort(student, programme, term, tuition):
    call_command("apply_fee_schedule", term=term.code, programme=programme.code)
    assert FeeCharge.objects.filter(student=student, term=term).count() == 1
    call_command("apply_fee_schedule", term=term.code, programme=programme.code)  # idempotent
    assert FeeCharge.objects.filter(student=student, term=term).count() == 1

    with pytest.raises(CommandError):
        call_command("apply_fee_schedule", term="not-a-real-term")


@pytest.mark.django_db
def test_ledger_and_balance_combine_charges_and_payments(student, term, tuition):
    charge_student_for_term(student, term)
    due_date = FeeCharge.objects.get(student=student, term=term).due_date
    Payment.objects.create(student=student, amount=Decimal("20000.00"), paid_on=due_date + timedelta(days=5))
    assert balance(student) == Decimal("30000.00")
    data = ledger(student)
    assert data["balance"] == "30000.00"
    assert [e["kind"] for e in data["entries"]] == ["charge", "payment"]


@pytest.mark.django_db
def test_my_balance_and_finance_ledger_endpoints(student, finance, client_for, term, tuition):
    charge_student_for_term(student, term)
    me, fin = client_for(student.user), client_for(finance)

    own = me.get("/api/v1/fees/my-balance/").json()
    assert own["balance"] == "50000.00"

    seen = fin.get(f"/api/v1/fees/ledger/{student.id}/").json()
    assert seen["balance"] == "50000.00"

    recorded = fin.post(
        "/api/v1/fees/payments/",
        {"student": student.id, "amount": "50000.00", "paid_on": "2026-09-15", "method": "cash"},
        format="json",
    )
    assert recorded.status_code == 201, recorded.content
    assert fin.get(f"/api/v1/fees/ledger/{student.id}/").json()["balance"] == "0.00"

    # A student may not read anyone else's balance through the finance endpoint.
    assert me.get(f"/api/v1/fees/ledger/{student.id}/").status_code == 403


@pytest.mark.django_db
def test_overdue_balance_places_and_lifts_a_registration_hold(student, term, tuition):
    charge_student_for_term(student, term)
    due_date = FeeCharge.objects.get(student=student, term=term).due_date
    just_inside_grace = due_date + timedelta(days=GRACE_PERIOD_DAYS - 1)
    just_past_grace = due_date + timedelta(days=GRACE_PERIOD_DAYS)

    assert list(overdue_students(just_inside_grace)) == []  # the grace period has not elapsed yet

    result = apply_overdue_holds(just_past_grace)
    assert result == {"placed": 1, "resolved": 0}
    hold = RegistrationHold.objects.get(student=student, source="fees")
    assert hold.is_active and hold.reason == RegistrationHold.Reason.FINANCIAL

    Payment.objects.create(student=student, amount=Decimal("50000.00"), paid_on=just_past_grace)
    again = apply_overdue_holds(just_past_grace)
    assert again == {"placed": 0, "resolved": 1}
    hold.refresh_from_db()
    assert not hold.is_active
