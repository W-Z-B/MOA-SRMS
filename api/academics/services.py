"""Grading (final marks, letters, grade point averages, transcripts) and registration (S-W02):
prerequisite checking, registration holds, and the offering waitlist.
"""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction

from academics.models import Enrolment, GradeBand, RegistrationHold, Result, ResultCorrection
from programmes.models import CoursePrerequisite

TWO_PLACES = Decimal("0.01")


def band_for(mark: Decimal, on: date) -> GradeBand | None:
    """The band for a mark under the scale in force on a date."""
    latest = GradeBand.objects.filter(effective_from__lte=on).order_by("-effective_from").first()
    if latest is None:
        return None
    return (
        GradeBand.objects.filter(effective_from=latest.effective_from, min_mark__lte=mark)
        .order_by("-min_mark")
        .first()
    )


def compute(result: Result, *, save: bool = True) -> Result:
    """Derive final mark, letter and points once both components are present; clear them otherwise."""
    offering = result.enrolment.offering
    if result.coursework_mark is None or result.exam_mark is None:
        result.final_mark, result.letter, result.points, result.is_pass = None, "", None, None
    else:
        final = (
            result.coursework_mark * offering.coursework_weight + result.exam_mark * offering.exam_weight
        ) / Decimal(100)
        result.final_mark = final.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        band = band_for(result.final_mark, offering.term.ends)
        result.letter = band.letter if band else ""
        result.points = band.points if band else None
        result.is_pass = band.is_pass if band else None
    if save:
        result.save()
    return result


@transaction.atomic
def apply_correction(
    result: Result,
    *,
    actor,
    reason: str,
    coursework_mark: Decimal | None = None,
    exam_mark: Decimal | None = None,
) -> ResultCorrection:
    """Amend a PUBLISHED result's marks under a formal, reasoned correction (S-W03). The prior
    values are kept on the returned ResultCorrection row permanently, even across a later
    correction of the same result; the caller is responsible for checking `result.state` first
    and for writing the general audit-log entry (see `academics.api.ResultViewSet.correct`).
    """
    correction = ResultCorrection.objects.create(
        result=result,
        reason=reason,
        previous_coursework_mark=result.coursework_mark,
        previous_exam_mark=result.exam_mark,
        previous_final_mark=result.final_mark,
        previous_letter=result.letter,
        previous_points=result.points,
        created_by=actor,
        updated_by=actor,
    )
    if coursework_mark is not None:
        result.coursework_mark = coursework_mark
        result.coursework_source = Result.Source.MANUAL
    if exam_mark is not None:
        result.exam_mark = exam_mark
    result.updated_by = actor
    compute(result)
    correction.new_coursework_mark = result.coursework_mark
    correction.new_exam_mark = result.exam_mark
    correction.new_final_mark = result.final_mark
    correction.new_letter = result.letter
    correction.new_points = result.points
    correction.save(
        update_fields=["new_coursework_mark", "new_exam_mark", "new_final_mark", "new_letter", "new_points"]
    )
    return correction


def _results(student, *, published_only: bool, term=None):
    qs = Result.objects.filter(enrolment__student=student, points__isnull=False).select_related(
        "enrolment__offering__course", "enrolment__offering__term"
    )
    if published_only:
        qs = qs.filter(state=Result.State.PUBLISHED)
    if term is not None:
        qs = qs.filter(enrolment__offering__term=term)
    return qs


def gpa(student, *, term=None, published_only: bool = True) -> Decimal | None:
    """Credit-weighted grade point average, or None when there are no graded results."""
    credits = Decimal(0)
    weighted = Decimal(0)
    for result in _results(student, published_only=published_only, term=term):
        course_credits = result.enrolment.offering.course.credits
        credits += course_credits
        weighted += course_credits * result.points
    if credits == 0:
        return None
    return (weighted / credits).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def transcript(student, *, published_only: bool = True) -> dict:
    """Results grouped by term with term and cumulative averages. JSON now; PDF in a later sprint."""
    terms: dict[str, dict] = {}
    for result in _results(student, published_only=published_only).order_by(
        "enrolment__offering__term__starts"
    ):
        offering = result.enrolment.offering
        entry = terms.setdefault(
            offering.term.code,
            {"term": offering.term.code, "name": offering.term.name, "courses": [], "gpa": None},
        )
        entry["courses"].append(
            {
                "course_code": offering.course.code,
                "title": offering.course.title,
                "credits": str(offering.course.credits),
                "final_mark": str(result.final_mark),
                "letter": result.letter,
                "points": str(result.points),
                "state": result.state,
                "corrected": result.corrections.exists(),
            }
        )
        term_gpa = gpa(student, term=offering.term, published_only=published_only)
        entry["gpa"] = str(term_gpa) if term_gpa is not None else None
    cumulative = gpa(student, published_only=published_only)
    return {
        "student_no": student.student_no,
        "name": student.full_name,
        "programme": student.programme.name,
        "campus_code": student.campus_code,
        "intake_year": student.intake_year,
        "status": student.status,
        "terms": list(terms.values()),
        "cumulative_gpa": str(cumulative) if cumulative is not None else None,
        "published_only": published_only,
    }


def missing_prerequisites(student, course) -> list[str]:
    """Prerequisite course codes the student has not yet passed in a published result."""
    required = set(
        CoursePrerequisite.objects.filter(course=course).values_list("prerequisite__code", flat=True)
    )
    if not required:
        return []
    passed = set(
        Result.objects.filter(
            enrolment__student=student,
            enrolment__offering__course__code__in=required,
            state=Result.State.PUBLISHED,
            is_pass=True,
        ).values_list("enrolment__offering__course__code", flat=True)
    )
    return sorted(required - passed)


def active_holds(student):
    return RegistrationHold.objects.filter(student=student, is_active=True)


def next_enrolment_status(offering) -> tuple[str, int | None]:
    """Where a new registration against this offering lands: a seat, or a place on the waitlist."""
    taken = offering.enrolments.filter(status=Enrolment.Status.ENROLLED).count()
    if taken < offering.capacity:
        return Enrolment.Status.ENROLLED, None
    last_rank = (
        offering.enrolments.filter(status=Enrolment.Status.WAITLISTED)
        .order_by("-waitlist_rank")
        .values_list("waitlist_rank", flat=True)
        .first()
        or 0
    )
    return Enrolment.Status.WAITLISTED, last_rank + 1


@transaction.atomic
def promote_next_waitlisted(offering, *, actor=None) -> Enrolment | None:
    """Move the first-ranked waitlisted enrolment for this offering into the freed seat, if any."""
    next_up = (
        offering.enrolments.select_for_update()
        .filter(status=Enrolment.Status.WAITLISTED)
        .order_by("waitlist_rank")
        .first()
    )
    if next_up is None:
        return None
    next_up.status = Enrolment.Status.ENROLLED
    next_up.waitlist_rank = None
    next_up.updated_by = actor
    next_up.save(update_fields=["status", "waitlist_rank", "updated_by", "updated_at"])
    Result.objects.get_or_create(enrolment=next_up, defaults={"created_by": actor, "updated_by": actor})
    from notifications.services import notify

    notify(
        [next_up.student.user],
        title=f"You are enrolled: {next_up.offering.course.code}",
        body=f"A place opened in {next_up.offering.course.title}; you have moved off the waitlist.",
        link="/students",
        dedupe_key=f"enrolment:{next_up.id}:promoted",
    )
    return next_up
