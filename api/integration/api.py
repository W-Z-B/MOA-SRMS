"""Integration API of the SRMS: the system of record for students, offerings, enrolments and results.

Consumed by the LMS. Reference endpoints for the SRMS web app are here too.
"""

from django.db import transaction
from django.urls import path
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from academics.models import AttendanceTotal, CompetencyResult, CourseOffering, Enrolment, Result, Term
from academics.services import compute
from audit.models import AuditLog
from iam.permissions import RolePermission
from integration.auth import ServiceKeyAuthentication, scope
from integration.models import CampusRef, StaffRef
from programmes.models import Course, Programme


class Pager(PageNumberPagination):
    page_size = 200
    max_page_size = 500
    page_size_query_param = "page_size"


def _audit(request, action: str, detail: dict) -> None:
    AuditLog.objects.create(
        action=f"integration:{action}",
        entity="integration.serviceclient",
        entity_id=request.auth.pk,
        after={"client": request.auth.name, **detail},
        source_ip=request.META.get("REMOTE_ADDR") or None,
    )


@api_view(["GET"])
@authentication_classes([ServiceKeyAuthentication])
@permission_classes([scope("academics:read")])
def offerings(request):
    qs = CourseOffering.objects.select_related("course", "term").order_by("code")
    if request.query_params.get("term"):
        qs = qs.filter(term__code=request.query_params["term"])
    if request.query_params.get("current") == "1":
        qs = qs.filter(term__is_current=True)
    pager = Pager()
    page = pager.paginate_queryset(qs, request)
    _audit(request, "offerings.read", {"count": len(page)})
    return pager.get_paginated_response(
        [
            {
                "code": o.code,
                "course_code": o.course.code,
                "title": o.course.title,
                "term_code": o.term.code,
                "campus_code": o.campus_code,
                "lecturer_employee_no": o.lecturer_employee_no,
                "coursework_weight": str(o.coursework_weight),
            }
            for o in page
        ]
    )


@api_view(["GET"])
@authentication_classes([ServiceKeyAuthentication])
@permission_classes([scope("academics:read")])
def enrolments(request):
    code = request.query_params.get("offering")
    if not code:
        return Response({"code": "bad_request", "detail": "offering (code) is required."}, status=400)
    qs = (
        Enrolment.objects.filter(offering__code=code)
        .exclude(status=Enrolment.Status.DROPPED)
        .select_related("student")
        .order_by("student__student_no")
    )
    pager = Pager()
    page = pager.paginate_queryset(qs, request)
    _audit(request, "enrolments.read", {"offering": code, "count": len(page)})
    return pager.get_paginated_response(
        [
            {
                "student_no": e.student.student_no,
                "first_name": e.student.first_name,
                "last_name": e.student.last_name,
                "email": e.student.email,
                "campus_code": e.student.campus_code,
                "status": e.status,
            }
            for e in page
        ]
    )


class MarkSerializer(serializers.Serializer):
    student_no = serializers.CharField(max_length=20)
    mark = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=0, max_value=100)


class CourseworkSerializer(serializers.Serializer):
    offering_code = serializers.CharField(max_length=40)
    marks = MarkSerializer(many=True, allow_empty=False)


@api_view(["POST"])
@authentication_classes([ServiceKeyAuthentication])
@permission_classes([scope("marks:write")])
def coursework_marks(request):
    """Coursework percentages from the LMS. Only draft results accept them; locked ones are reported."""
    data = CourseworkSerializer(data=request.data)
    data.is_valid(raise_exception=True)
    code = data.validated_data["offering_code"]
    if not CourseOffering.objects.filter(code=code).exists():
        return Response({"code": "unknown_offering", "detail": "No offering with that code."}, status=404)
    accepted, locked, unknown = [], [], []
    with transaction.atomic():
        for row in data.validated_data["marks"]:
            result = (
                Result.objects.select_for_update()
                .filter(enrolment__offering__code=code, enrolment__student__student_no=row["student_no"])
                .select_related("enrolment__offering__term")
                .first()
            )
            if result is None:
                unknown.append(row["student_no"])
            elif result.state != Result.State.DRAFT:
                locked.append(row["student_no"])
            else:
                result.coursework_mark = row["mark"]
                result.coursework_source = Result.Source.LMS
                compute(result)
                accepted.append(row["student_no"])
        _audit(request, "marks.write", {"offering": code, "accepted": len(accepted), "locked": len(locked)})
    return Response({"offering_code": code, "accepted": accepted, "locked": locked, "unknown": unknown})


# --- Attendance totals, course outcomes, competency results and terms (the LMS's further needs) ---------

INTEGRATION = ["integration"]
ERROR = inline_serializer(
    "IntegrationError", {"code": serializers.CharField(), "detail": serializers.CharField()}
)


def _paged(name: str, row: dict):
    return inline_serializer(
        name,
        {
            "count": serializers.IntegerField(),
            "next": serializers.URLField(allow_null=True),
            "previous": serializers.URLField(allow_null=True),
            "results": inline_serializer(f"{name}Row", row, many=True),
        },
    )


class AttendanceRowSerializer(serializers.Serializer):
    student_no = serializers.CharField(max_length=20)
    sessions = serializers.IntegerField(min_value=0)
    present = serializers.IntegerField(min_value=0)
    late = serializers.IntegerField(min_value=0)
    excused = serializers.IntegerField(min_value=0)
    absent = serializers.IntegerField(min_value=0)
    not_recorded = serializers.IntegerField(min_value=0)
    percent = serializers.DecimalField(
        max_digits=5, decimal_places=2, min_value=0, max_value=100, allow_null=True
    )

    def validate(self, attrs):
        counted = sum(attrs[k] for k in ("present", "late", "excused", "absent", "not_recorded"))
        if counted != attrs["sessions"]:
            raise serializers.ValidationError(
                "present, late, excused, absent and not_recorded must add up to sessions."
            )
        return attrs


class AttendanceTotalsSerializer(serializers.Serializer):
    offering_code = serializers.CharField(max_length=40)
    totals = AttendanceRowSerializer(many=True, allow_empty=False)


def attendance_required(offering: CourseOffering) -> bool:
    """An offering takes attendance totals when any programme whose curriculum holds its course makes
    attendance a condition of passing (Programme.attendance_required)."""
    return Programme.objects.filter(
        curriculum__course_id=offering.course_id, attendance_required=True
    ).exists()


ACCEPTED = inline_serializer(
    "IntegrationAccepted",
    {
        "offering_code": serializers.CharField(),
        "accepted": serializers.ListField(child=serializers.CharField()),
        "locked": serializers.ListField(child=serializers.CharField()),
        "unknown": serializers.ListField(child=serializers.CharField()),
    },
)


@extend_schema(
    tags=INTEGRATION,
    summary="Attendance totals from the LMS (scope attendance:write)",
    description=(
        "Each student's attendance totals for one offering. Only offerings of a programme that makes "
        "attendance a condition of passing take them (409 `attendance_not_required` otherwise). Idempotent: "
        "the latest totals replace the last. Totals for a result past draft are not changed and are listed "
        "as locked; students not enrolled in the offering are listed as unknown."
    ),
    request=AttendanceTotalsSerializer,
    responses={200: ACCEPTED, 400: ERROR, 403: ERROR, 404: ERROR, 409: ERROR},
)
@api_view(["POST"])
@authentication_classes([ServiceKeyAuthentication])
@permission_classes([scope("attendance:write")])
def attendance_totals(request):
    data = AttendanceTotalsSerializer(data=request.data)
    data.is_valid(raise_exception=True)
    code = data.validated_data["offering_code"]
    offering = CourseOffering.objects.filter(code=code).first()
    if offering is None:
        return Response({"code": "unknown_offering", "detail": "No offering with that code."}, status=404)
    if not attendance_required(offering):
        return Response(
            {
                "code": "attendance_not_required",
                "detail": "No programme of this offering's course makes attendance a condition of passing.",
            },
            status=409,
        )
    accepted, locked, unknown = [], [], []
    with transaction.atomic():
        enrolments = {
            e.student.student_no: e
            for e in Enrolment.objects.select_for_update(of=("self",))
            .filter(offering=offering)
            .exclude(status=Enrolment.Status.DROPPED)
            .select_related("student", "result")
        }
        for row in data.validated_data["totals"]:
            values = dict(row)
            student_no = values.pop("student_no")
            enrolment = enrolments.get(student_no)
            if enrolment is None:
                unknown.append(student_no)
                continue
            result = getattr(enrolment, "result", None)
            if result is not None and result.state != Result.State.DRAFT:
                locked.append(student_no)
                continue
            AttendanceTotal.objects.update_or_create(enrolment=enrolment, defaults=values)
            accepted.append(student_no)
        _audit(
            request,
            "attendance.write",
            {"offering": code, "accepted": len(accepted), "locked": len(locked), "unknown": len(unknown)},
        )
    return Response({"offering_code": code, "accepted": accepted, "locked": locked, "unknown": unknown})


@extend_schema(
    tags=INTEGRATION,
    summary="Learning outcomes of each course (scope academics:read)",
    description="Every active course with the outcomes of its course outline, in outline order.",
    parameters=[OpenApiParameter("course", str, description="Only this course code")],
    responses={
        200: _paged(
            "CourseOutcomes",
            {
                "course_code": serializers.CharField(),
                "outcomes": inline_serializer(
                    "CourseOutcomeRow",
                    {"code": serializers.CharField(), "text": serializers.CharField()},
                    many=True,
                ),
            },
        ),
        403: ERROR,
    },
)
@api_view(["GET"])
@authentication_classes([ServiceKeyAuthentication])
@permission_classes([scope("academics:read")])
def course_outcomes(request):
    qs = Course.objects.filter(is_active=True).prefetch_related("outcomes").order_by("code")
    if request.query_params.get("course"):
        qs = qs.filter(code=request.query_params["course"])
    pager = Pager()
    page = pager.paginate_queryset(qs, request)
    _audit(request, "course_outcomes.read", {"count": len(page)})
    return pager.get_paginated_response(
        [
            {"course_code": c.code, "outcomes": [{"code": o.code, "text": o.text} for o in c.outcomes.all()]}
            for c in page
        ]
    )


class CompetencyRowSerializer(serializers.Serializer):
    offering_code = serializers.CharField(max_length=40)
    student_no = serializers.CharField(max_length=20)
    unit_code = serializers.CharField(max_length=40)
    result = serializers.ChoiceField(choices=CompetencyResult.Outcome.choices)
    assessed_on = serializers.DateField()


ROW_REF = {
    "offering_code": serializers.CharField(),
    "student_no": serializers.CharField(),
    "unit_code": serializers.CharField(),
}


@extend_schema(
    tags=INTEGRATION,
    summary="Competency results from the LMS (scope marks:write)",
    description=(
        "A list of units of competency assessed in the LMS, each competent or not_yet_competent. Idempotent: "
        "a unit sent again for the same student and offering replaces the earlier result. A unit whose "
        "result is past draft is listed as locked; an unknown offering, or a student not enrolled in it, is "
        "listed as unknown with the reason (`unknown_offering`, `unknown_student`)."
    ),
    request=CompetencyRowSerializer(many=True),
    responses={
        200: inline_serializer(
            "CompetencyResultsAccepted",
            {
                "accepted": inline_serializer("CompetencyAccepted", ROW_REF, many=True),
                "locked": inline_serializer("CompetencyLocked", ROW_REF, many=True),
                "unknown": inline_serializer(
                    "CompetencyUnknown", {**ROW_REF, "code": serializers.CharField()}, many=True
                ),
            },
        ),
        400: ERROR,
        403: ERROR,
    },
)
@api_view(["POST"])
@authentication_classes([ServiceKeyAuthentication])
@permission_classes([scope("marks:write")])
def competency_results(request):
    data = CompetencyRowSerializer(data=request.data, many=True, allow_empty=False)
    data.is_valid(raise_exception=True)
    rows = data.validated_data
    accepted, locked, unknown = [], [], []
    with transaction.atomic():
        codes = {r["offering_code"] for r in rows}
        known = set(CourseOffering.objects.filter(code__in=codes).values_list("code", flat=True))
        enrolments = {
            (e.offering.code, e.student.student_no): e
            for e in Enrolment.objects.select_for_update(of=("self",))
            .filter(offering__code__in=known)
            .exclude(status=Enrolment.Status.DROPPED)
            .select_related("offering", "student", "result")
        }
        for row in rows:
            ref = {k: row[k] for k in ("offering_code", "student_no", "unit_code")}
            if row["offering_code"] not in known:
                unknown.append({**ref, "code": "unknown_offering"})
                continue
            enrolment = enrolments.get((row["offering_code"], row["student_no"]))
            if enrolment is None:
                unknown.append({**ref, "code": "unknown_student"})
                continue
            result = getattr(enrolment, "result", None)
            if result is not None and result.state != Result.State.DRAFT:
                locked.append(ref)
                continue
            CompetencyResult.objects.update_or_create(
                enrolment=enrolment,
                unit_code=row["unit_code"],
                defaults={"result": row["result"], "assessed_on": row["assessed_on"]},
            )
            accepted.append(ref)
        _audit(
            request,
            "competencies.write",
            {"accepted": len(accepted), "locked": len(locked), "unknown": len(unknown)},
        )
    return Response({"accepted": accepted, "locked": locked, "unknown": unknown})


@extend_schema(
    tags=INTEGRATION,
    summary="Academic terms with their dates (scope academics:read)",
    parameters=[OpenApiParameter("current", str, description="1 for the current term only")],
    responses={
        200: _paged(
            "Terms",
            {
                "code": serializers.CharField(),
                "name": serializers.CharField(),
                "year_code": serializers.CharField(),
                "starts": serializers.DateField(),
                "ends": serializers.DateField(),
                "is_current": serializers.BooleanField(),
            },
        ),
        403: ERROR,
    },
)
@api_view(["GET"])
@authentication_classes([ServiceKeyAuthentication])
@permission_classes([scope("academics:read")])
def terms(request):
    qs = Term.objects.select_related("year").order_by("starts")
    if request.query_params.get("current") == "1":
        qs = qs.filter(is_current=True)
    pager = Pager()
    page = pager.paginate_queryset(qs, request)
    _audit(request, "terms.read", {"count": len(page)})
    return pager.get_paginated_response(
        [
            {
                "code": t.code,
                "name": t.name,
                "year_code": t.year.code,
                "starts": t.starts.isoformat(),
                "ends": t.ends.isoformat(),
                "is_current": t.is_current,
            }
            for t in page
        ]
    )


@api_view(["GET"])
@permission_classes([RolePermission])
def campuses(request):
    return Response([{"id": c.id, "code": c.code, "name": c.name} for c in CampusRef.objects.all()])


@api_view(["GET"])
@permission_classes([RolePermission])
def staff(request):
    """Staff reference list (from the HRMS) for choosing lecturers. No personal identifiers."""
    qs = StaffRef.objects.filter(is_active=True)
    q = request.query_params.get("q")
    if q:
        qs = qs.filter(full_name__icontains=q) | qs.filter(employee_no__istartswith=q)
    return Response(
        [
            {
                "employee_no": s.employee_no,
                "full_name": s.full_name,
                "unit_code": s.unit_code,
                "unit_name": s.unit_name,
                "campus_code": s.campus_code,
                "position_title": s.position_title,
            }
            for s in qs.order_by("full_name")[:100]
        ]
    )


integration_urls = [
    path("offerings/", offerings, name="integration-offerings"),
    path("enrolments/", enrolments, name="integration-enrolments"),
    path("coursework-marks/", coursework_marks, name="integration-coursework"),
    path("attendance-totals/", attendance_totals, name="integration-attendance"),
    path("course-outcomes/", course_outcomes, name="integration-course-outcomes"),
    path("competency-results/", competency_results, name="integration-competencies"),
    path("terms/", terms, name="integration-terms"),
]
reference_urls = [
    path("campuses/", campuses, name="reference-campuses"),
    path("staff/", staff, name="reference-staff"),
]
