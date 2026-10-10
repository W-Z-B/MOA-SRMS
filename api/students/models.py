"""Admissions and student records. The SRMS is the system of record for students."""

from django.conf import settings
from django.db import models

from core.fields import EncryptedTextField
from core.models import TimeStampedModel
from core.validators import validate_upload


class Gender(models.TextChoices):
    FEMALE = "F", "Female"
    MALE = "M", "Male"
    OTHER = "X", "Other or not stated"


class PersonFields(TimeStampedModel):
    """Fields shared by applicants and students."""

    first_name = models.CharField(max_length=80)
    last_name = models.CharField(max_length=80)
    other_names = models.CharField(max_length=120, blank=True)
    date_of_birth = models.DateField()
    gender = models.CharField(max_length=1, choices=Gender.choices, default=Gender.OTHER)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    address = models.CharField(max_length=255, blank=True)
    region = models.CharField(max_length=40, blank=True, help_text="Administrative region or country")
    nationality = models.CharField(max_length=60, default="Guyanese")

    class Meta:
        abstract = True

    @property
    def full_name(self) -> str:
        return " ".join(p for p in (self.first_name, self.other_names, self.last_name) if p)


class Student(PersonFields):
    class Status(models.TextChoices):
        ENROLLED = "enrolled", "Enrolled"
        DEFERRED = "deferred", "Deferred"
        SUSPENDED = "suspended", "Suspended"
        WITHDRAWN = "withdrawn", "Withdrawn"
        GRADUATED = "graduated", "Graduated"

    class Sponsor(models.TextChoices):
        SELF = "self", "Self-funded"
        GOVERNMENT = "government", "Government of Guyana"
        OTHER = "other", "Other sponsor"

    student_no = models.CharField(max_length=20, unique=True)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="student"
    )
    national_id = EncryptedTextField(null=True, blank=True)
    campus_code = models.CharField(max_length=10)
    programme = models.ForeignKey("programmes.Programme", on_delete=models.PROTECT, related_name="students")
    intake_year = models.PositiveSmallIntegerField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ENROLLED)
    is_residential = models.BooleanField(default=False, help_text="Lives in campus accommodation")
    sponsor = models.CharField(max_length=20, choices=Sponsor.choices, default=Sponsor.SELF)
    next_of_kin_name = models.CharField(max_length=120, blank=True)
    next_of_kin_phone = models.CharField(max_length=40, blank=True)

    class Meta:
        ordering = ["last_name", "first_name"]
        indexes = [
            models.Index(fields=["campus_code", "status"]),
            models.Index(fields=["programme", "intake_year"]),
        ]

    def __str__(self) -> str:
        return f"{self.student_no} {self.first_name} {self.last_name}"


class Application(PersonFields):
    class State(models.TextChoices):
        SUBMITTED = "submitted", "Submitted"
        UNDER_REVIEW = "under_review", "Under review"
        INTERVIEW = "interview", "Interview or assessment scheduled"
        ASSESSED = "assessed", "Interview or assessment scored"
        OFFERED = "offered", "Offer made"
        WAITLISTED = "waitlisted", "Waitlisted"
        ACCEPTED = "accepted", "Accepted and admitted"
        DECLINED = "declined", "Declined by the applicant"
        REJECTED = "rejected", "Rejected"
        WITHDRAWN = "withdrawn", "Withdrawn"

    reference = models.CharField(max_length=20, unique=True)
    qualifications = models.TextField(blank=True, help_text="Summary of entry qualifications")
    programme = models.ForeignKey(
        "programmes.Programme", on_delete=models.PROTECT, related_name="applications"
    )
    campus_code = models.CharField(max_length=10)
    intake_year = models.PositiveSmallIntegerField()
    state = models.CharField(max_length=20, choices=State.choices, default=State.SUBMITTED)
    assessment_score = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Interview or entrance assessment score, 0-100",
    )
    assessment_notes = models.TextField(blank=True)
    decision_comment = models.CharField(max_length=300, blank=True)
    student = models.OneToOneField(
        Student, null=True, blank=True, on_delete=models.SET_NULL, related_name="application"
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(assessment_score__isnull=True)
                | models.Q(assessment_score__range=(0, 100)),
                name="application_assessment_score_between_0_and_100",
            )
        ]

    def __str__(self) -> str:
        return f"{self.reference} {self.first_name} {self.last_name} ({self.state})"


class ApplicationDocument(TimeStampedModel):
    """A supporting document uploaded against an application. Served only via an audited download."""

    class DocType(models.TextChoices):
        TRANSCRIPT = "transcript", "School transcript or results"
        IDENTIFICATION = "identification", "Proof of identity"
        MEDICAL = "medical", "Medical certificate"
        OTHER = "other", "Other supporting document"

    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name="documents")
    doc_type = models.CharField(max_length=20, choices=DocType.choices, default=DocType.OTHER)
    file = models.FileField(upload_to="applications/%Y/", validators=[validate_upload])
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.application.reference} {self.get_doc_type_display()}"


class WaitlistEntry(TimeStampedModel):
    """An application's place in its programme's waitlist for one intake year, when capacity is full."""

    application = models.OneToOneField(Application, on_delete=models.CASCADE, related_name="waitlist_entry")
    programme = models.ForeignKey(
        "programmes.Programme", on_delete=models.PROTECT, related_name="waitlist_entries"
    )
    intake_year = models.PositiveSmallIntegerField()
    rank = models.PositiveIntegerField()

    class Meta:
        ordering = ["programme", "intake_year", "rank"]
        unique_together = [("programme", "intake_year", "rank")]

    def __str__(self) -> str:
        return f"{self.application.reference} rank {self.rank} ({self.programme.code} {self.intake_year})"
