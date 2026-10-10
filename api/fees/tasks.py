"""S-A04: an overdue balance past its grace period places a registration hold; a settled one lifts
the hold fees placed. Daily, after the night's other registration-affecting jobs.
"""

import logging
from datetime import date

from django.utils import timezone
from procrastinate.contrib.django import app

from academics.models import RegistrationHold
from fees.services import balance, overdue_students

log = logging.getLogger(__name__)
HOLD_SOURCE = "fees"


def apply_overdue_holds(today: date) -> dict:
    """Place a hold for every account overdue past the grace period; lift one no longer owed."""
    overdue_ids: set[int] = set()
    placed = 0
    for student, owed in overdue_students(today):
        overdue_ids.add(student.id)
        _, created = RegistrationHold.objects.get_or_create(
            student=student,
            source=HOLD_SOURCE,
            reason=RegistrationHold.Reason.FINANCIAL,
            is_active=True,
            defaults={"detail": f"Balance of {owed} overdue by more than the grace period"},
        )
        placed += int(created)

    resolved = 0
    stale = RegistrationHold.objects.filter(
        source=HOLD_SOURCE, reason=RegistrationHold.Reason.FINANCIAL, is_active=True
    ).exclude(student_id__in=overdue_ids)
    for hold in stale:
        if balance(hold.student) > 0:
            continue  # still owed, just not yet past the grace period again after a partial payment
        hold.is_active = False
        hold.resolved_at = timezone.now()
        hold.save(update_fields=["is_active", "resolved_at", "updated_at"])
        resolved += 1

    return {"placed": placed, "resolved": resolved}


@app.periodic(cron="15 1 * * *")  # 01:15, ahead of the HRMS and LMS syncs
@app.task(name="fees.overdue_balance_holds", queue="fees")
def overdue_balance_holds(timestamp: int | None = None) -> dict:
    result = apply_overdue_holds(date.today())
    log.info("fees.overdue_balance_holds %s", result)
    return result
