"""Academic standing (S-W04): a GPA-threshold tier per student, computed nightly from published
results only (never from a result still in the S-W03 approval chain), its history, and an appeals
process for a student to contest a standing decision.

A student's current tier also drives a registration hold: `academics.RegistrationHold` already
had an `ACADEMIC_STANDING` reason reserved for this (unused until now) — see `standing.tasks`.
"""

from django.conf import settings
from django.db import models

from core.models import TimeStampedModel


class AcademicStanding(TimeStampedModel):
    """One row per student: the tier currently in force, kept up to date by the nightly job
    (see `standing.tasks.recompute_all`) and by a Registrar's manual override.
    """

    class Tier(models.TextChoices):
        GOOD = "good", "Good standing"
        PROBATION = "probation", "Probation"
        SUSPENSION = "suspension", "Suspension"
        DISMISSAL = "dismissal", "Dismissal"

    student = models.OneToOneField(
        "students.Student", on_delete=models.CASCADE, related_name="standing"
    )
    tier = models.CharField(max_length=12, choices=Tier.choices, default=Tier.GOOD)
    cumulative_gpa = models.DecimalField(max_digits=3, decimal_places=2, null=True, blank=True)
    as_of_term = models.ForeignKey(
        "academics.Term", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    computed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["student"]
        indexes = [models.Index(fields=["tier"])]

    def __str__(self) -> str:
        return f"{self.student.student_no}: {self.get_tier_display()}"


class StandingDecision(TimeStampedModel):
    """One change of tier, kept forever. Automatic (nightly, `decided_by` blank) unless a
    Registrar overrode it by hand, in which case `decided_by` and `reason` are set — and that is
    exactly the person an appeal of this decision may not be heard by (see `StandingAppeal`).
    """

    standing = models.ForeignKey(AcademicStanding, on_delete=models.CASCADE, related_name="decisions")
    term = models.ForeignKey("academics.Term", on_delete=models.PROTECT, related_name="+")
    previous_tier = models.CharField(max_length=12, choices=AcademicStanding.Tier.choices)
    tier = models.CharField(max_length=12, choices=AcademicStanding.Tier.choices)
    cumulative_gpa = models.DecimalField(max_digits=3, decimal_places=2, null=True, blank=True)
    is_automatic = models.BooleanField(default=True)
    reason = models.CharField(
        max_length=300,
        blank=True,
        help_text="Set on a manual override or an appeal outcome; blank for an automatic nightly computation",
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.standing.student.student_no} {self.previous_tier} -> {self.tier} ({self.term.code})"


class StandingAppeal(TimeStampedModel):
    """A student's appeal against one StandingDecision. Heard by someone other than whoever made
    that decision (mirrors the HRMS `cases` app's disciplinary-appeal pattern) — enforced in
    `standing.services.hear_appeal`, since an automatic decision has no `decided_by` to conflict
    with in the first place.
    """

    class Outcome(models.TextChoices):
        UPHELD = "upheld", "Appeal upheld"
        DENIED = "denied", "Appeal denied"

    decision = models.OneToOneField(StandingDecision, on_delete=models.CASCADE, related_name="appeal")
    grounds = models.TextField()
    heard_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    heard_at = models.DateTimeField(null=True, blank=True)
    outcome = models.CharField(max_length=10, choices=Outcome.choices, blank=True)
    outcome_reason = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Appeal of {self.decision} ({self.outcome or 'pending'})"
