"""Advisor assignment (S-M04 / S-C04): one advisor at a time per student, with history kept."""

from django.db import transaction
from django.utils import timezone

from advising.models import AdvisorAssignment


class AdvisingError(Exception):
    code = "invalid"

    def __init__(self, detail: str, code: str | None = None):
        super().__init__(detail)
        if code:
            self.code = code


def current_assignment(student) -> AdvisorAssignment | None:
    return AdvisorAssignment.objects.filter(student=student, ended_at__isnull=True).first()


@transaction.atomic
def assign(student, advisor_employee_no: str, *, actor=None, reason: str = "") -> AdvisorAssignment:
    """Make `advisor_employee_no` the student's current advisor.

    Idempotent if that advisor is already current. Otherwise ends the existing current
    assignment, if any (one advisor at a time; the ended row is kept as history), and starts a
    new one.
    """
    advisor_employee_no = (advisor_employee_no or "").strip()
    if not advisor_employee_no:
        raise AdvisingError("An advisor employee number is required.", code="advisor_required")
    current = current_assignment(student)
    if current and current.advisor_employee_no == advisor_employee_no:
        return current
    if current:
        current.ended_at = timezone.now()
        current.ended_reason = reason.strip() or "Reassigned"
        current.updated_by = actor
        current.save(update_fields=["ended_at", "ended_reason", "updated_by", "updated_at"])
    return AdvisorAssignment.objects.create(
        student=student,
        advisor_employee_no=advisor_employee_no,
        created_by=actor,
        updated_by=actor,
    )


@transaction.atomic
def unassign(student, *, actor=None, reason: str = "") -> AdvisorAssignment | None:
    """End the student's current advisor assignment without starting a new one. A no-op (returns
    None) if the student has no current advisor."""
    current = current_assignment(student)
    if current is None:
        return None
    current.ended_at = timezone.now()
    current.ended_reason = reason.strip() or "Unassigned"
    current.updated_by = actor
    current.save(update_fields=["ended_at", "ended_reason", "updated_by", "updated_at"])
    return current


def bulk_assign(students, advisor_employee_no: str, *, actor=None) -> int:
    """Assign every student in `students` to `advisor_employee_no`. Returns how many changed; a
    student already assigned to this advisor is left untouched and not counted again."""
    changed = 0
    for student in students:
        current = current_assignment(student)
        if current and current.advisor_employee_no == advisor_employee_no:
            continue
        assign(student, advisor_employee_no, actor=actor, reason="Bulk assignment")
        changed += 1
    return changed
