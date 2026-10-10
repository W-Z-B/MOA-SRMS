"""Admissions services: references, student numbers, admitting an accepted applicant, the waitlist."""

from django.db import transaction

from students.models import Application, Student, WaitlistEntry


def next_reference(intake_year: int) -> str:
    count = Application.objects.filter(intake_year=intake_year).count() + 1
    while Application.objects.filter(reference=f"APP-{intake_year}-{count:04d}").exists():
        count += 1
    return f"APP-{intake_year}-{count:04d}"


def next_student_no(intake_year: int, campus_code: str) -> str:
    """Year, campus and a sequence, e.g. 26MRP0001. The format is configurable once GSA confirms its own."""
    prefix = f"{intake_year % 100:02d}{campus_code}"
    count = Student.objects.filter(student_no__startswith=prefix).count() + 1
    while Student.objects.filter(student_no=f"{prefix}{count:04d}").exists():
        count += 1
    return f"{prefix}{count:04d}"


@transaction.atomic
def admit(application: Application, *, actor=None) -> Student:
    """Create the student record from an accepted application. Idempotent."""
    if application.student_id:
        return application.student
    student = Student.objects.create(
        student_no=next_student_no(application.intake_year, application.campus_code),
        first_name=application.first_name,
        last_name=application.last_name,
        other_names=application.other_names,
        date_of_birth=application.date_of_birth,
        gender=application.gender,
        email=application.email,
        phone=application.phone,
        address=application.address,
        region=application.region,
        nationality=application.nationality,
        campus_code=application.campus_code,
        programme=application.programme,
        intake_year=application.intake_year,
        created_by=actor,
        updated_by=actor,
    )
    application.student = student
    application.save(update_fields=["student", "updated_at"])
    return student


def capacity_remaining(programme, intake_year: int) -> int | None:
    """Places left in a programme's intake, or None when the programme has no capacity limit.

    Counts applicants already offered or accepted, since both hold a place until declined/withdrawn.
    """
    if programme.intake_capacity is None:
        return None
    held = Application.objects.filter(
        programme=programme,
        intake_year=intake_year,
        state__in=(Application.State.OFFERED, Application.State.ACCEPTED),
    ).count()
    return programme.intake_capacity - held


@transaction.atomic
def waitlist(application: Application, *, actor=None) -> WaitlistEntry:
    """Place an application at the back of its programme's waitlist for its intake year. Idempotent."""
    existing = WaitlistEntry.objects.filter(application=application).first()
    if existing is not None:
        return existing
    last_rank = (
        WaitlistEntry.objects.filter(
            programme=application.programme, intake_year=application.intake_year
        )
        .order_by("-rank")
        .values_list("rank", flat=True)
        .first()
        or 0
    )
    return WaitlistEntry.objects.create(
        application=application,
        programme=application.programme,
        intake_year=application.intake_year,
        rank=last_rank + 1,
        created_by=actor,
        updated_by=actor,
    )


def unwaitlist(application: Application) -> None:
    WaitlistEntry.objects.filter(application=application).delete()
