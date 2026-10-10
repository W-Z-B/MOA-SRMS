"""S-W04: recompute every active student's academic standing nightly, from published results
only, after the term's grading is done. Scheduled after the night's other registration-affecting
jobs (fees at 01:15, the HRMS sync at 01:30), matching this ecosystem's batch-not-event-driven
integration pattern (X-05).
"""

import logging

from procrastinate.contrib.django import app

from standing.services import recompute_student

log = logging.getLogger(__name__)


def recompute_all() -> dict:
    from students.models import Student

    students = Student.objects.filter(status__in=[Student.Status.ENROLLED, Student.Status.SUSPENDED])
    changed = 0
    for student in students:
        if recompute_student(student) is not None:
            changed += 1
    return {"considered": students.count(), "changed": changed}


@app.periodic(cron="0 2 * * *")  # 02:00
@app.task(name="standing.recompute_all", queue="standing")
def recompute_all_task(timestamp: int | None = None) -> dict:
    result = recompute_all()
    log.info("standing.recompute_all %s", result)
    return result
