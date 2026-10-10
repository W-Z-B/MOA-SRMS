"""Fees and billing (S-W07): a dated fee amount per programme, a per-student ledger of charges and
manually-recorded payments, and the running balance that drives a registration hold once overdue.

No payment gateway is integrated here and none has been chosen; payments are recorded by a Finance
Officer after money has already changed hands by some other means (bank deposit, cashier's receipt).
"""

from decimal import Decimal

from django.db import models

from core.models import TimeStampedModel


class FeeItem(TimeStampedModel):
    """What a programme charges for one fee type, effective from a date.

    Mirrors this ecosystem's existing effective-dated pattern (SRMS's own GradeBand, and HRMS's
    Grade.amount_on): a revised amount is a new row from its date, rather than editing history.
    The simplest useful granularity is one row per programme and fee type; a future need for a
    campus-specific or cohort-specific override can extend this without changing charges already
    raised, since a charge snapshots the amount it was raised for (see FeeCharge.amount).
    """

    class FeeType(models.TextChoices):
        TUITION = "tuition", "Tuition"
        REGISTRATION = "registration", "Registration"
        LAB = "lab", "Laboratory"
        OTHER = "other", "Other"

    programme = models.ForeignKey(
        "programmes.Programme", on_delete=models.PROTECT, related_name="fee_items"
    )
    fee_type = models.CharField(max_length=20, choices=FeeType.choices)
    amount = models.DecimalField(max_digits=10, decimal_places=2, help_text="Amount in GYD")
    effective_from = models.DateField()

    class Meta:
        unique_together = [("programme", "fee_type", "effective_from")]
        ordering = ["programme", "fee_type", "-effective_from"]

    def __str__(self) -> str:
        return f"{self.programme.code} {self.fee_type} {self.amount} from {self.effective_from}"

    @classmethod
    def amount_on(cls, programme, fee_type: str, day) -> Decimal | None:
        """The amount in force for a programme and fee type on a day, or None if never set."""
        row = (
            cls.objects.filter(programme=programme, fee_type=fee_type, effective_from__lte=day)
            .order_by("-effective_from")
            .first()
        )
        return row.amount if row else None


class FeeCharge(TimeStampedModel):
    """One charge raised against a student for a term. The amount is captured at charge time, so a
    later revision to FeeItem never changes a charge already on the ledger.
    """

    student = models.ForeignKey("students.Student", on_delete=models.PROTECT, related_name="fee_charges")
    term = models.ForeignKey("academics.Term", on_delete=models.PROTECT, related_name="fee_charges")
    fee_type = models.CharField(max_length=20, choices=FeeItem.FeeType.choices)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    due_date = models.DateField()
    description = models.CharField(max_length=200, blank=True)

    class Meta:
        unique_together = [("student", "term", "fee_type")]
        ordering = ["due_date", "student"]

    def __str__(self) -> str:
        return f"{self.student.student_no} {self.fee_type} {self.amount} due {self.due_date}"


class Payment(TimeStampedModel):
    """A payment recorded against a student's ledger, against no charge in particular (fees are
    billed per term but paid as a running balance, matching how GSA's cashiers work today).
    """

    class Method(models.TextChoices):
        CASH = "cash", "Cash"
        BANK_TRANSFER = "bank_transfer", "Bank transfer"
        CHEQUE = "cheque", "Cheque"
        OTHER = "other", "Other"

    student = models.ForeignKey("students.Student", on_delete=models.PROTECT, related_name="payments")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    paid_on = models.DateField()
    method = models.CharField(max_length=20, choices=Method.choices, default=Method.CASH)
    reference = models.CharField(max_length=80, blank=True, help_text="Receipt or transaction number")
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-paid_on", "student"]

    def __str__(self) -> str:
        return f"{self.student.student_no} paid {self.amount} on {self.paid_on}"
