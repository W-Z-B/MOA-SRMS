"""SRMS reports (JSON for now; PDF and Excel follow the HRMS report pack). Dashboards (S-D01,
S-D02, S-D06) are built from these, plus S-D07's replacement of the placeholder DashboardScreen.
"""

from datetime import date
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.urls import path
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from academics.models import Result, Term
from iam.models import Role
from iam.permissions import RolePermission
from iam.services import has_role, scope_queryset
from students.models import Application, Student

# How much history a dashboard shows by default when the caller doesn't ask for more (GSA to
# confirm): the four most recent terms (about two years), and cohorts admitted in the last four
# intake years. Overridable per request with ?terms= or ?years=.
DEFAULT_TERMS_HISTORY = 4
DEFAULT_COHORT_YEARS = 4

REPORT_ROLES = (
    Role.REGISTRAR,
    Role.ADMISSIONS_OFFICER,
    Role.PRINCIPAL,
    Role.HOD,
    Role.AUDITOR,
    Role.ADMINISTRATOR,
)


def _cohort_floor(params) -> int:
    years = int(params.get("years", DEFAULT_COHORT_YEARS))
    return date.today().year - years


def enrolment_by_programme(user, params) -> list[dict]:
    rows = (
        scope_queryset(user, Student.objects.all())
        .values("programme__code", "programme__name", "campus_code")
        .annotate(
            enrolled=Count("id", filter=Q(status=Student.Status.ENROLLED)),
            graduated=Count("id", filter=Q(status=Student.Status.GRADUATED)),
            total=Count("id"),
        )
        .order_by("programme__code", "campus_code")
    )
    return [
        {
            "programme": r["programme__code"],
            "name": r["programme__name"],
            "campus": r["campus_code"],
            "enrolled": r["enrolled"],
            "graduated": r["graduated"],
            "total": r["total"],
        }
        for r in rows
    ]


def results_summary(user, params) -> list[dict]:
    rows = (
        scope_queryset(user, Result.objects.all(), campus_field="enrolment__offering__campus_code")
        .filter(state=Result.State.PUBLISHED)
        .values("enrolment__offering__code")
        .annotate(graded=Count("id"), passed=Count("id", filter=Q(is_pass=True)))
        .order_by("enrolment__offering__code")
    )
    return [
        {
            "offering": r["enrolment__offering__code"],
            "graded": r["graded"],
            "passed": r["passed"],
            "pass_rate": round(100 * r["passed"] / r["graded"], 1) if r["graded"] else None,
        }
        for r in rows
    ]


def admissions_funnel(user, params) -> list[dict]:
    rows = (
        scope_queryset(user, Application.objects.all())
        .values("intake_year", "campus_code", "state")
        .annotate(count=Count("id"))
        .order_by("-intake_year", "campus_code", "state")
    )
    return [dict(r) for r in rows]


def enrolment_funnel(user, params) -> list[dict]:
    """S-D01: applied -> admitted -> enrolled -> retained -> graduated, by programme and intake
    year, limited by default to the last `DEFAULT_COHORT_YEARS` intake years.

    "Admitted" is an application that reached an offer (OFFERED or ACCEPTED); "enrolled" is one
    that actually produced a Student record; "retained" is enrolled students minus those who
    later withdrew — so it includes a currently-active, suspended or already-graduated student,
    and is always >= graduated, keeping every stage a monotonic funnel.
    """
    floor_year = _cohort_floor(params)
    buckets: dict[tuple[str, int], dict] = {}
    apps = scope_queryset(user, Application.objects.select_related("programme")).filter(
        intake_year__gte=floor_year
    )
    for row in apps.values("programme__code", "programme__name", "intake_year").annotate(
        applied=Count("id"),
        admitted=Count(
            "id", filter=Q(state__in=[Application.State.OFFERED, Application.State.ACCEPTED])
        ),
    ):
        key = (row["programme__code"], row["intake_year"])
        buckets[key] = {
            "programme": row["programme__code"],
            "name": row["programme__name"],
            "intake_year": row["intake_year"],
            "applied": row["applied"],
            "admitted": row["admitted"],
            "enrolled": 0,
            "retained": 0,
            "graduated": 0,
        }
    students = scope_queryset(user, Student.objects.select_related("programme")).filter(
        intake_year__gte=floor_year
    )
    for row in students.values("programme__code", "programme__name", "intake_year").annotate(
        enrolled=Count("id"),
        withdrawn=Count("id", filter=Q(status=Student.Status.WITHDRAWN)),
        graduated=Count("id", filter=Q(status=Student.Status.GRADUATED)),
    ):
        key = (row["programme__code"], row["intake_year"])
        entry = buckets.setdefault(
            key,
            {
                "programme": row["programme__code"],
                "name": row["programme__name"],
                "intake_year": row["intake_year"],
                "applied": 0,
                "admitted": 0,
            },
        )
        entry["enrolled"] = row["enrolled"]
        entry["retained"] = row["enrolled"] - row["withdrawn"]
        entry["graduated"] = row["graduated"]
    return sorted(buckets.values(), key=lambda r: (-r["intake_year"], r["programme"]))


def retention_by_cohort(user, params) -> list[dict]:
    """S-D02: for each programme and intake-year cohort, how many are still active, how many
    were lost (withdrawn, or dismissed on academic standing — S-W04 — which never changes
    Student.status, so it is counted here from the `standing` app directly), and the resulting
    attrition rate. Limited by default to the last `DEFAULT_COHORT_YEARS` intake years.
    """
    from standing.models import AcademicStanding

    floor_year = _cohort_floor(params)
    dismissed_qs = AcademicStanding.objects.filter(tier=AcademicStanding.Tier.DISMISSAL)
    dismissed_ids = set(
        scope_queryset(user, dismissed_qs, campus_field="student__campus_code").values_list(
            "student_id", flat=True
        )
    )
    buckets: dict[tuple[str, int], dict] = {}
    students = scope_queryset(user, Student.objects.select_related("programme")).filter(
        intake_year__gte=floor_year
    )
    for student in students:
        key = (student.programme.code, student.intake_year)
        bucket = buckets.setdefault(
            key,
            {
                "programme": student.programme.code,
                "name": student.programme.name,
                "intake_year": student.intake_year,
                "total": 0,
                "withdrawn": 0,
                "dismissed": 0,
                "graduated": 0,
                "active": 0,
            },
        )
        bucket["total"] += 1
        if student.status == Student.Status.WITHDRAWN:
            bucket["withdrawn"] += 1
        elif student.id in dismissed_ids:
            bucket["dismissed"] += 1
        elif student.status == Student.Status.GRADUATED:
            bucket["graduated"] += 1
        else:
            bucket["active"] += 1
    rows = []
    for bucket in buckets.values():
        lost = bucket["withdrawn"] + bucket["dismissed"]
        bucket["retained"] = bucket["total"] - lost
        bucket["attrition_rate"] = round(100 * lost / bucket["total"], 1) if bucket["total"] else None
        rows.append(bucket)
    return sorted(rows, key=lambda r: (-r["intake_year"], r["programme"]))


def fee_collection_status(user, params) -> list[dict]:
    """S-D06: charged vs. collected by term, from the fees ledger (Phase A). A payment carries
    no term of its own (fees.Payment is a running balance, not allocated per charge), so it is
    attributed to the term whose date range contains its payment date; one outside every known
    term's range is reported separately as "unallocated" rather than silently dropped. Limited
    by default to the most recent `DEFAULT_TERMS_HISTORY` terms.
    """
    from fees.models import FeeCharge, Payment

    limit = int(params.get("terms", DEFAULT_TERMS_HISTORY))
    terms = list(Term.objects.order_by("-starts")[:limit])
    codes = {t.code for t in terms}

    by_term: dict[str, dict] = {
        t.code: {"term": t.code, "charged": Decimal(0), "collected": Decimal(0)} for t in terms
    }
    charges = (
        scope_queryset(user, FeeCharge.objects.filter(term__in=terms), campus_field="student__campus_code")
        .values("term__code")
        .annotate(total=Sum("amount"))
    )
    for row in charges:
        by_term[row["term__code"]]["charged"] = row["total"] or Decimal(0)

    payments = scope_queryset(user, Payment.objects.all(), campus_field="student__campus_code")
    unallocated = Decimal(0)
    for payment in payments:
        term = next((t for t in terms if t.starts <= payment.paid_on <= t.ends), None)
        if term is None or term.code not in codes:
            unallocated += payment.amount
            continue
        by_term[term.code]["collected"] += payment.amount

    rows = []
    for entry in by_term.values():
        charged, collected = entry["charged"], entry["collected"]
        rows.append(
            {
                "term": entry["term"],
                "charged": str(charged),
                "collected": str(collected),
                "outstanding": str(charged - collected),
                "collection_rate": round(100 * collected / charged, 1) if charged else None,
            }
        )
    rows.sort(key=lambda r: r["term"], reverse=True)
    if unallocated:
        rows.append(
            {
                "term": "unallocated",
                "charged": "0",
                "collected": str(unallocated),
                "outstanding": "0",
                "collection_rate": None,
            }
        )
    return rows


REPORTS = {
    "enrolment-by-programme": ("Enrolment by programme and campus", enrolment_by_programme),
    "results-summary": ("Published results and pass rates by offering", results_summary),
    "admissions-funnel": ("Applications by intake, campus and state", admissions_funnel),
    "enrolment-funnel": (
        "Enrolment funnel: applied, admitted, enrolled, retained, graduated",
        enrolment_funnel,
    ),
    "retention-by-cohort": ("Retention and attrition by programme and intake cohort", retention_by_cohort),
    "fee-collection-status": ("Fee collection status by term", fee_collection_status),
}


@api_view(["GET"])
@permission_classes([RolePermission])
def list_reports(request):
    if not has_role(request.user, *REPORT_ROLES):
        return Response([])
    return Response([{"key": key, "name": name} for key, (name, _) in REPORTS.items()])


@api_view(["GET"])
@permission_classes([RolePermission])
def run_report(request, key: str):
    if key not in REPORTS:
        return Response({"code": "not_found", "detail": "Unknown report."}, status=404)
    if not has_role(request.user, *REPORT_ROLES):
        return Response({"code": "forbidden", "detail": "Your role cannot run reports."}, status=403)
    name, query = REPORTS[key]
    return Response({"key": key, "name": name, "rows": query(request.user, request.query_params)})


urlpatterns = [
    path("", list_reports, name="report-list"),
    path("<slug:key>/", run_report, name="report-run"),
]
