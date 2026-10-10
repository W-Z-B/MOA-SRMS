"""Academic calendar, course offerings, enrolments and results."""

from django.conf import settings
from django.db import models
from django.db.models import F, Q

from core.models import TimeStampedModel


class AcademicYear(TimeStampedModel):
    code = models.CharField(max_length=12, unique=True, help_text="e.g. 2026-2027")
    starts = models.DateField()
    ends = models.DateField()

    class Meta:
        ordering = ["-starts"]

    def __str__(self) -> str:
        return self.code


class Term(TimeStampedModel):
    year = models.ForeignKey(AcademicYear, on_delete=models.PROTECT, related_name="terms")
    code = models.CharField(max_length=16, unique=True, help_text="e.g. 2026-27-S1")
    number = models.PositiveSmallIntegerField()
    name = models.CharField(max_length=60)
    starts = models.DateField()
    ends = models.DateField()
    is_current = models.BooleanField(default=False)

    class Meta:
        unique_together = [("year", "number")]
        ordering = ["-starts"]

    def __str__(self) -> str:
        return self.code


class CourseOffering(TimeStampedModel):
    """A course taught in a term at a campus by a lecturer. The LMS builds its course site from this."""

    code = models.CharField(max_length=40, unique=True, help_text="e.g. AGR101-2026-27-S1-MRP")
    course = models.ForeignKey("programmes.Course", on_delete=models.PROTECT, related_name="offerings")
    term = models.ForeignKey(Term, on_delete=models.PROTECT, related_name="offerings")
    campus_code = models.CharField(max_length=10)
    lecturer_employee_no = models.CharField(max_length=20, blank=True, help_text="HRMS employee number")
    capacity = models.PositiveIntegerField(default=40)
    coursework_weight = models.DecimalField(max_digits=5, decimal_places=2, default=40)
    exam_weight = models.DecimalField(max_digits=5, decimal_places=2, default=60)

    class Meta:
        ordering = ["term", "code"]
        constraints = [
            models.CheckConstraint(
                condition=Q(coursework_weight__gte=0) & Q(exam_weight=100 - F("coursework_weight")),
                name="offering_weights_total_100",
            )
        ]

    def __str__(self) -> str:
        return self.code


class Enrolment(TimeStampedModel):
    class Status(models.TextChoices):
        ENROLLED = "enrolled", "Enrolled"
        WAITLISTED = "waitlisted", "Waitlisted"
        DROPPED = "dropped", "Dropped"
        COMPLETED = "completed", "Completed"

    student = models.ForeignKey("students.Student", on_delete=models.PROTECT, related_name="enrolments")
    offering = models.ForeignKey(CourseOffering, on_delete=models.PROTECT, related_name="enrolments")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ENROLLED)
    waitlist_rank = models.PositiveIntegerField(
        null=True, blank=True, help_text="Position in the offering's waitlist; set only while waitlisted"
    )

    class Meta:
        unique_together = [("student", "offering")]
        ordering = ["offering", "student"]

    def __str__(self) -> str:
        return f"{self.student.student_no} in {self.offering.code} ({self.status})"


class RegistrationHold(TimeStampedModel):
    """Blocks new course registration until resolved. A source system creates it; a records
    officer, or an automated job (e.g. the fees module's overdue-balance check, S-W07), resolves
    it or leaves it active. Dropping an existing enrolment is never blocked by a hold.
    """

    class Reason(models.TextChoices):
        MISSING_DOCUMENT = "missing_document", "Missing document"
        FINANCIAL = "financial", "Outstanding balance"
        ACADEMIC_STANDING = "academic_standing", "Academic standing"
        OTHER = "other", "Other"

    student = models.ForeignKey(
        "students.Student", on_delete=models.CASCADE, related_name="registration_holds"
    )
    reason = models.CharField(max_length=20, choices=Reason.choices)
    source = models.CharField(
        max_length=40, help_text="The process that placed the hold, e.g. 'admissions', 'fees'"
    )
    detail = models.CharField(max_length=300, blank=True)
    is_active = models.BooleanField(default=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["student", "is_active"])]

    def __str__(self) -> str:
        return f"{self.student.student_no} {self.reason} ({'active' if self.is_active else 'resolved'})"


class GradeBand(TimeStampedModel):
    """Effective-dated grading scale. The Registrar maintains it; nothing is hard-coded."""

    letter = models.CharField(max_length=3)
    min_mark = models.DecimalField(max_digits=5, decimal_places=2)
    points = models.DecimalField(max_digits=3, decimal_places=2)
    is_pass = models.BooleanField(default=True)
    effective_from = models.DateField()

    class Meta:
        unique_together = [("letter", "effective_from")]
        ordering = ["-effective_from", "-min_mark"]

    def __str__(self) -> str:
        return f"{self.letter} from {self.min_mark}"


class Result(TimeStampedModel):
    class State(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted by lecturer"
        APPROVED = "approved", "Approved by Head of Department"
        PUBLISHED = "published", "Published"

    class Source(models.TextChoices):
        MANUAL = "manual", "Entered in the SRMS"
        LMS = "lms", "Received from the LMS"

    enrolment = models.OneToOneField(Enrolment, on_delete=models.CASCADE, related_name="result")
    coursework_mark = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    exam_mark = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    final_mark = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    letter = models.CharField(max_length=3, blank=True)
    points = models.DecimalField(max_digits=3, decimal_places=2, null=True, blank=True)
    is_pass = models.BooleanField(null=True)
    state = models.CharField(max_length=12, choices=State.choices, default=State.DRAFT)
    coursework_source = models.CharField(max_length=10, choices=Source.choices, default=Source.MANUAL)
    decision_comment = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["enrolment"]
        constraints = [
            models.CheckConstraint(
                condition=(Q(coursework_mark__isnull=True) | Q(coursework_mark__range=(0, 100)))
                & (Q(exam_mark__isnull=True) | Q(exam_mark__range=(0, 100))),
                name="result_marks_between_0_and_100",
            )
        ]

    def __str__(self) -> str:
        return f"{self.enrolment} {self.final_mark or '-'} ({self.state})"
