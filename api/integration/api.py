"""Integration API of the SRMS: the system of record for students, offerings, enrolments and results.

Consumed by the LMS. Reference endpoints for the SRMS web app are here too.
"""

from django.db import transaction
from django.urls import path
from rest_framework import serializers
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from academics.models import CourseOffering, Enrolment, Result
from academics.services import compute
from audit.models import AuditLog
from iam.permissions import RolePermission
from integration.auth import ServiceKeyAuthentication, scope
from integration.models import CampusRef, StaffRef


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
]
reference_urls = [
    path("campuses/", campuses, name="reference-campuses"),
    path("staff/", staff, name="reference-staff"),
]
