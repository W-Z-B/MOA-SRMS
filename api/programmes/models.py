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
    attendance_required = models.BooleanField(
        default=False,
        help_text="Attendance is a condition of passing; the LMS sends attendance totals for its courses",
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


class CourseOutcome(TimeStampedModel):
    """A learning outcome in a course outline. The LMS reads them to align its assessments."""

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="outcomes")
    code = models.CharField(max_length=20, help_text="e.g. LO1")
    text = models.CharField(max_length=500)
    position = models.PositiveSmallIntegerField(default=0, help_text="Order in the course outline")

    class Meta:
        ordering = ["course", "position", "code"]
        constraints = [models.UniqueConstraint(fields=["course", "code"], name="course_outcome_code_once")]

    def __str__(self) -> str:
        return f"{self.course.code} {self.code}"


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
