"""Charging a term, the running balance and ledger, and the overdue check behind a registration hold."""

from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum

from fees.models import FeeCharge, FeeItem, Payment

# Placeholders, both flagged for GSA to confirm:
DUE_DAYS_AFTER_TERM_START = 30  # a charge raised for a term falls due this many days into it
GRACE_PERIOD_DAYS = 14  # days a charge may sit overdue before a registration hold is placed


@transaction.atomic
def charge_student_for_term(student, term, *, actor=None) -> list[FeeCharge]:
    """Raise one charge per fee type set for the student's programme as of the term's start.

    Idempotent: a fee type already charged for this student and term is left alone, even if the
    programme's rate has since changed (FeeItem.amount_on is read once, at charge time).
    """
    created = []
    due_date = term.starts + timedelta(days=DUE_DAYS_AFTER_TERM_START)
    for fee_type, _ in FeeItem.FeeType.choices:
        amount = FeeItem.amount_on(student.programme, fee_type, term.starts)
        if amount is None:
            continue
        charge, was_created = FeeCharge.objects.get_or_create(
            student=student,
            term=term,
            fee_type=fee_type,
            defaults={
                "amount": amount,
                "due_date": due_date,
                "created_by": actor,
                "updated_by": actor,
            },
        )
        if was_created:
            created.append(charge)
    return created


def balance(student) -> Decimal:
    """Total charged minus total paid. Positive means the student owes GSA money."""
    charged = FeeCharge.objects.filter(student=student).aggregate(total=Sum("amount"))["total"] or Decimal(0)
    paid = Payment.objects.filter(student=student).aggregate(total=Sum("amount"))["total"] or Decimal(0)
    return charged - paid


def ledger(student) -> dict:
    """The student's charges and payments in date order, with the running and final balance."""
    entries = [
        {
            "kind": "charge",
            "date": c.due_date.isoformat(),
            "description": c.description or f"{c.get_fee_type_display()} ({c.term.code})",
            "amount": str(c.amount),
        }
        for c in FeeCharge.objects.filter(student=student).select_related("term")
    ] + [
        {
            "kind": "payment",
            "date": p.paid_on.isoformat(),
            "description": p.note or f"Payment ({p.get_method_display()}, {p.reference})".strip(),
            "amount": str(-p.amount),
        }
        for p in Payment.objects.filter(student=student)
    ]
    entries.sort(key=lambda e: e["date"])
    running = Decimal(0)
    for entry in entries:
        running += Decimal(entry["amount"])
        entry["running_balance"] = str(running)
    return {
        "student_no": student.student_no,
        "name": student.full_name,
        "entries": entries,
        "balance": str(running),
    }


def oldest_unpaid_due_date(student) -> date | None:
    """The earliest charge on record, used as a simple stand-in for "the oldest unpaid charge".

    Payments are not allocated against specific charges (S-W07 keeps a running balance, not a
    per-charge paid/unpaid flag), so once any balance is owed, the earliest charge's due date is
    the simplest useful signal for how long the account has been behind.
    """
    return (
        FeeCharge.objects.filter(student=student)
        .order_by("due_date")
        .values_list("due_date", flat=True)
        .first()
    )


def overdue_students(as_of: date):
    """Yield (student, balance) for every student whose account is overdue past the grace period."""
    from students.models import Student

    for student in Student.objects.filter(fee_charges__isnull=False).distinct():
        owed = balance(student)
        if owed <= 0:
            continue
        due = oldest_unpaid_due_date(student)
        if due and (as_of - due).days >= GRACE_PERIOD_DAYS:
            yield student, owed
