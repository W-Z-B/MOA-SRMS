"""Academic advising (S-M04): an advisor/advisee relationship (closes the S-C04 data-capture gap)
and a record of advising conversations.

The advisor is HRMS staff. Following the convention `academics.CourseOffering` already set with
`lecturer_employee_no`, the advisor is referenced only by HRMS employee number, a plain field, not
a foreign key into another system's table — the SRMS never duplicates HRMS identity data, it only
stores the code. Where a local `auth.User` happens to be linked to that employee number (via
`integration.StaffRef.user`, the same link `academics` uses to resolve "my own offerings"), the API
resolves the advisor's name and lets an advisor see their own advisees without the Registrar
re-keying anything.

Decisions made without being asked (see the PR description for the full list):
- One advisor at a time per student; reassigning ends the previous AdvisorAssignment row rather
  than deleting it, so history is kept (mirrors `standing.StandingDecision` keeping every change).
- Advising notes are never edited or deleted once logged (mirrors `academics.Result` once
  published, and the audit log generally) — a correction is a further note.
"""

from django.db import models

from core.models import TimeStampedModel


class AdvisorAssignment(TimeStampedModel):
    """The advisor for one student over one period. At most one row per student has
    `ended_at IS NULL` (the current advisor) at any time — enforced in `advising.services.assign`,
    not as a DB constraint, since a partial-unique constraint isn't portable to the SQLite backend
    `manage.py check` and some local runs use.
    """

    student = models.ForeignKey(
        "students.Student", on_delete=models.CASCADE, related_name="advisor_assignments"
    )
    advisor_employee_no = models.CharField(max_length=20, help_text="HRMS employee number")
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    ended_reason = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["student", "ended_at"]),
            models.Index(fields=["advisor_employee_no", "ended_at"]),
        ]

    def __str__(self) -> str:
        status = "current" if self.ended_at is None else f"ended {self.ended_at:%Y-%m-%d}"
        return f"{self.student.student_no} -> {self.advisor_employee_no} ({status})"


class AdvisingNote(TimeStampedModel):
    """One logged conversation or meeting between an advisor and their advisee."""

    class Concern(models.TextChoices):
        NONE = "none", "No concern"
        ACADEMIC = "academic", "Academic concern"
        FINANCIAL = "financial", "Financial concern"
        ATTENDANCE = "attendance", "Attendance concern"
        PERSONAL = "personal", "Personal or welfare concern"

    student = models.ForeignKey(
        "students.Student", on_delete=models.CASCADE, related_name="advising_notes"
    )
    advisor_employee_no = models.CharField(max_length=20, help_text="HRMS employee number")
    met_on = models.DateField()
    summary = models.TextField()
    concern = models.CharField(max_length=20, choices=Concern.choices, default=Concern.NONE)
    flagged_for_registrar = models.BooleanField(
        default=False, help_text="Escalate this note to the Registrar as a concern worth following up"
    )

    class Meta:
        ordering = ["-met_on", "-created_at"]
        indexes = [models.Index(fields=["student", "-met_on"])]

    def __str__(self) -> str:
        return f"{self.student.student_no} advising note {self.met_on} ({self.get_concern_display()})"
