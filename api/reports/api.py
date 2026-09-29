"""SRMS reports (JSON for now; PDF and Excel follow the HRMS report pack)."""

from django.db.models import Count, Q
from django.urls import path
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from academics.models import Result
from iam.models import Role
from iam.permissions import RolePermission
from iam.services import has_role, scope_queryset
from students.models import Application, Student

REPORT_ROLES = (
    Role.REGISTRAR,
    Role.ADMISSIONS_OFFICER,
    Role.PRINCIPAL,
    Role.HOD,
    Role.AUDITOR,
    Role.ADMINISTRATOR,
)


def enrolment_by_programme(user) -> list[dict]:
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


def results_summary(user) -> list[dict]:
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


def admissions_funnel(user) -> list[dict]:
    rows = (
        scope_queryset(user, Application.objects.all())
        .values("intake_year", "campus_code", "state")
        .annotate(count=Count("id"))
        .order_by("-intake_year", "campus_code", "state")
    )
    return [dict(r) for r in rows]


REPORTS = {
    "enrolment-by-programme": ("Enrolment by programme and campus", enrolment_by_programme),
    "results-summary": ("Published results and pass rates by offering", results_summary),
    "admissions-funnel": ("Applications by intake, campus and state", admissions_funnel),
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
    return Response({"key": key, "name": name, "rows": query(request.user)})


urlpatterns = [
    path("", list_reports, name="report-list"),
    path("<slug:key>/", run_report, name="report-run"),
]
