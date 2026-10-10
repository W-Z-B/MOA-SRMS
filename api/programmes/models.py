"""Programmes, courses and curricula. The SRMS is the system of record for all three."""

from django.db import models

from core.models import TimeStampedModel


class Programme(TimeStampedModel):
    class Award(models.TextChoices):
        CERTIFICATE = "certificate", "Certificate"
        DIPLOMA = "diploma", "Diploma"

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=160)
    award = models.CharField(max_length=20, choices=Award.choices)
    duration_years = models.PositiveSmallIntegerField(default=2)
    campus_codes = models.JSONField(default=list, help_text="Campuses offering the programme, e.g. ['MRP']")
    intake_capacity = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Maximum applicants admitted per intake year, across all campuses. Blank is unlimited.",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.code} {self.name}"


class Course(TimeStampedModel):
    code = models.CharField(max_length=20, unique=True)
    title = models.CharField(max_length=160)
    credits = models.DecimalField(max_digits=4, decimal_places=1, default=3)
    department_code = models.CharField(max_length=20, blank=True, help_text="HRMS organisational unit code")
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.code} {self.title}"


class ProgrammeCourse(TimeStampedModel):
    """Places a course in a programme's curriculum."""

    programme = models.ForeignKey(Programme, on_delete=models.CASCADE, related_name="curriculum")
    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name="programmes")
    year = models.PositiveSmallIntegerField(default=1)
    semester = models.PositiveSmallIntegerField(default=1)
    is_core = models.BooleanField(default=True)

    class Meta:
        unique_together = [("programme", "course")]
        ordering = ["programme", "year", "semester", "course"]

    def __str__(self) -> str:
        return f"{self.programme.code} Y{self.year}S{self.semester} {self.course.code}"


class CoursePrerequisite(TimeStampedModel):
    """A course that a student must have already passed before enrolling in another (S-W02).

    The simplest useful shape: a course may require any number of other courses, with no
    partial credit and no minimum grade beyond a pass. A richer rule (a minimum letter grade,
    "one of" groups, a corequisite allowed at the same time) can be added later if GSA needs it.
    """

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="prerequisites")
    prerequisite = models.ForeignKey(Course, on_delete=models.PROTECT, related_name="required_for")

    class Meta:
        unique_together = [("course", "prerequisite")]
        ordering = ["course", "prerequisite"]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(course=models.F("prerequisite")), name="course_prerequisite_not_itself"
            )
        ]

    def __str__(self) -> str:
        return f"{self.course.code} requires {self.prerequisite.code}"
