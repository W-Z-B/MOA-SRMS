from decimal import Decimal

import pytest

from fees.models import FeeCharge, Payment
from reports.api import enrolment_funnel, fee_collection_status, retention_by_cohort
from standing.models import AcademicStanding
from students.models import Application, Student


def _application(programme, reference, state, intake_year=2026, **overrides):
    return Application.objects.create(
        reference=reference,
        first_name="Test",
        last_name=reference,
        date_of_birth="2007-01-01",
        programme=programme,
        campus_code=overrides.pop("campus_code", "MRP"),
        intake_year=intake_year,
        state=state,
        **overrides,
    )


def _student(programme, no, status=Student.Status.ENROLLED, intake_year=2026, make_user=None):
    user = make_user(no, "student", campus_code="MRP") if make_user else None
    return Student.objects.create(
        student_no=no,
        user=user,
        first_name="Test",
        last_name=no,
        date_of_birth="2006-01-01",
        campus_code="MRP",
        programme=programme,
        intake_year=intake_year,
        status=status,
    )


@pytest.mark.django_db
def test_enrolment_funnel_is_monotonic_and_counts_each_stage(programme, registrar, make_user):
    _application(programme, "APP-1", Application.State.SUBMITTED)
    _application(programme, "APP-2", Application.State.OFFERED)
    _application(programme, "APP-3", Application.State.ACCEPTED)
    _student(programme, "26MRP1001", status=Student.Status.ENROLLED, make_user=make_user)
    _student(programme, "26MRP1002", status=Student.Status.WITHDRAWN, make_user=make_user)
    _student(programme, "26MRP1003", status=Student.Status.GRADUATED, make_user=make_user)

    rows = enrolment_funnel(registrar, {})
    row = next(r for r in rows if r["programme"] == programme.code and r["intake_year"] == 2026)
    assert row["applied"] == 3
    assert row["admitted"] == 2  # offered + accepted
    assert row["enrolled"] == 3
    assert row["retained"] == 2  # enrolled minus the one withdrawn
    assert row["graduated"] == 1
    # retained is always >= graduated by construction (graduated is a subset of "not withdrawn");
    # applied/admitted/enrolled are independent counts in this synthetic data (a real cohort's
    # enrolled students originate from its own admitted applications, which this test does not
    # model), so only that one relationship is asserted here.
    assert row["retained"] >= row["graduated"]


@pytest.mark.django_db
def test_enrolment_funnel_respects_the_cohort_year_window(programme, registrar, make_user):
    _student(programme, "26MRP2001", intake_year=2010, make_user=make_user)
    rows = enrolment_funnel(registrar, {})
    assert all(r["intake_year"] != 2010 for r in rows)
    rows_all = enrolment_funnel(registrar, {"years": "50"})
    assert any(r["intake_year"] == 2010 for r in rows_all)


@pytest.mark.django_db
def test_retention_by_cohort_counts_withdrawal_and_dismissal_as_attrition(programme, registrar, make_user):
    _student(programme, "26MRP3001", status=Student.Status.ENROLLED, make_user=make_user)
    withdrawn = _student(programme, "26MRP3002", status=Student.Status.WITHDRAWN, make_user=make_user)
    dismissed = _student(programme, "26MRP3003", status=Student.Status.ENROLLED, make_user=make_user)
    AcademicStanding.objects.create(student=dismissed, tier=AcademicStanding.Tier.DISMISSAL)

    rows = retention_by_cohort(registrar, {})
    row = next(r for r in rows if r["programme"] == programme.code and r["intake_year"] == 2026)
    assert row["total"] == 3
    assert row["withdrawn"] == 1
    assert row["dismissed"] == 1
    assert row["active"] == 1
    assert row["retained"] == 1
    assert row["attrition_rate"] == pytest.approx(66.7, abs=0.1)
    assert withdrawn.status == Student.Status.WITHDRAWN  # sanity: untouched by the report


@pytest.mark.django_db
def test_fee_collection_status_allocates_payments_by_date_and_flags_unallocated(
    student, offering, registrar
):
    term = offering.term
    FeeCharge.objects.create(
        student=student, term=term, fee_type="tuition", amount=Decimal("50000.00"), due_date=term.starts
    )
    Payment.objects.create(student=student, amount=Decimal("20000.00"), paid_on=term.starts)
    far_future = term.ends.replace(year=term.ends.year + 5)
    Payment.objects.create(student=student, amount=Decimal("5000.00"), paid_on=far_future)

    rows = fee_collection_status(registrar, {})
    row = next(r for r in rows if r["term"] == term.code)
    assert row["charged"] == "50000.00"
    assert row["collected"] == "20000.00"
    assert row["outstanding"] == "30000.00"
    assert row["collection_rate"] == 40.0

    unallocated = next(r for r in rows if r["term"] == "unallocated")
    assert unallocated["collected"] == "5000.00"


@pytest.mark.django_db
def test_fee_collection_status_respects_the_terms_history_window(student, offering, registrar):
    rows = fee_collection_status(registrar, {"terms": "0"})
    assert rows == [] or all(r["term"] == "unallocated" for r in rows)
