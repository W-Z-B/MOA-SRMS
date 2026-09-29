"""Grading: final marks, letters, grade point averages and transcripts."""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from academics.models import GradeBand, Result

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
