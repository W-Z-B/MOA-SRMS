"""Academic advising (S-M04): the Registrar's advisor register and bulk-assignment tool, an
advisor's own advising notes, and the two personal views — a student's own advisor, and an
advisor's own advisees with the same standing/hold/enrolment facts the Registrar already sees.
"""

from django.db import transaction
from django.urls import path
from rest_framework import serializers, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.routers import DefaultRouter
from rest_framework.viewsets import ReadOnlyModelViewSet

from academics.models import Enrolment
from advising.models import AdvisingNote, AdvisorAssignment
from advising.services import AdvisingError
from advising.services import assign as assign_service
from advising.services import bulk_assign as bulk_assign_service
from advising.services import unassign as unassign_service
from audit.services import record, snapshot
from core.serializers import TimeStampedSerializer
from core.views import AuditedModelViewSet
from iam.models import Role
from iam.permissions import RolePermission
from iam.services import has_role, scope_queryset
from programmes.models import Programme
from students.models import Student

# Reassignment is a registrar-equivalent action, same bar as a standing override (see
# standing.api.OVERRIDE_ROLES) and the HRMS leave-approval convention this ecosystem reuses.
ADVISING_WRITE = (Role.REGISTRAR, Role.ADMINISTRATOR)
# Broader staff visibility of the advisor register itself (not of any one advisor's own notes,
# which stay scoped to that advisor — see AdvisingNoteViewSet.get_queryset).
ADVISING_READ = ADVISING_WRITE + (Role.PRINCIPAL, Role.AUDITOR, Role.HOD)


def _own_employee_no(user) -> str | None:
    staff = getattr(user, "staff_ref", None)
    return staff.employee_no if staff else None


def _advisor_name(employee_no: str) -> str | None:
    from integration.models import StaffRef

    ref = StaffRef.objects.filter(employee_no=employee_no).first()
    return ref.full_name if ref else None


class AdvisorAssignmentSerializer(TimeStampedSerializer):
    student_no = serializers.CharField(source="student.student_no", read_only=True)
    student_name = serializers.CharField(source="student.full_name", read_only=True)
    campus_code = serializers.CharField(source="student.campus_code", read_only=True)
    programme_code = serializers.CharField(source="student.programme.code", read_only=True)
    advisor_name = serializers.SerializerMethodField()

    class Meta(TimeStampedSerializer.Meta):
        model = AdvisorAssignment
        fields = (
            "id",
            "student",
            "student_no",
            "student_name",
            "campus_code",
            "programme_code",
            "advisor_employee_no",
            "advisor_name",
            "started_at",
            "ended_at",
            "ended_reason",
            "created_at",
        )
        read_only_fields = TimeStampedSerializer.Meta.read_only_fields + ("started_at", "ended_at")

    def get_advisor_name(self, obj) -> str | None:
        return _advisor_name(obj.advisor_employee_no)


class AssignSerializer(serializers.Serializer):
    student = serializers.PrimaryKeyRelatedField(queryset=Student.objects.all())
    advisor_employee_no = serializers.CharField(max_length=20)
    reason = serializers.CharField(max_length=300, required=False, allow_blank=True)


class BulkAssignSerializer(serializers.Serializer):
    """At least one filter is required so a slip of the finger can't assign the entire cohort."""

    advisor_employee_no = serializers.CharField(max_length=20)
    programme = serializers.PrimaryKeyRelatedField(queryset=Programme.objects.all(), required=False)
    intake_year = serializers.IntegerField(required=False)
    campus_code = serializers.CharField(max_length=10, required=False, allow_blank=True)

    def validate(self, attrs):
        if not (attrs.get("programme") or attrs.get("intake_year") or attrs.get("campus_code")):
            raise serializers.ValidationError(
                "Filter by programme, intake year or campus before bulk-assigning."
            )
        return attrs


class EndSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=300, required=False, allow_blank=True)


class AdvisingNoteSerializer(TimeStampedSerializer):
    student_no = serializers.CharField(source="student.student_no", read_only=True)
    student_name = serializers.CharField(source="student.full_name", read_only=True)
    concern_display = serializers.CharField(source="get_concern_display", read_only=True)

    class Meta(TimeStampedSerializer.Meta):
        model = AdvisingNote
        fields = (
            "id",
            "student",
            "student_no",
            "student_name",
            "advisor_employee_no",
            "met_on",
            "summary",
            "concern",
            "concern_display",
            "flagged_for_registrar",
            "created_at",
        )
        read_only_fields = TimeStampedSerializer.Meta.read_only_fields + ("advisor_employee_no",)


class AdviseeSerializer(serializers.Serializer):
    """A student as their advisor sees them: the same standing, hold and enrolment facts a
    registrar already has, via `academics` (S-W02) and `standing` (S-W04), surfaced read-only."""

    id = serializers.IntegerField()
    student_no = serializers.CharField()
    full_name = serializers.CharField()
    campus_code = serializers.CharField()
    status = serializers.CharField()
    programme_code = serializers.CharField(source="programme.code")
    programme_name = serializers.CharField(source="programme.name")
    standing_tier = serializers.SerializerMethodField()
    cumulative_gpa = serializers.SerializerMethodField()
    active_holds = serializers.SerializerMethodField()
    current_offerings = serializers.SerializerMethodField()

    def get_standing_tier(self, obj) -> str | None:
        standing = getattr(obj, "standing", None)
        return standing.tier if standing else None

    def get_cumulative_gpa(self, obj):
        standing = getattr(obj, "standing", None)
        return standing.cumulative_gpa if standing else None

    def get_active_holds(self, obj) -> list[str]:
        return [h.get_reason_display() for h in obj.registration_holds.all() if h.is_active]

    def get_current_offerings(self, obj) -> list[str]:
        return [e.offering.code for e in obj.enrolments.all() if e.status == Enrolment.Status.ENROLLED]


class AdvisorAssignmentViewSet(ReadOnlyModelViewSet):
    """The Registrar-facing advisor register: read-only here, changes go through `assign`, `end`
    or `bulk_assign` so that history is always kept (see `advising.services`).
    """

    serializer_class = AdvisorAssignmentSerializer
    read_roles = ADVISING_READ
    write_roles = ADVISING_WRITE
    permission_classes = [RolePermission]

    def get_queryset(self):
        qs = scope_queryset(
            self.request.user,
            AdvisorAssignment.objects.select_related("student", "student__programme"),
            campus_field="student__campus_code",
        )
        params = self.request.query_params
        if params.get("student"):
            qs = qs.filter(student_id=params["student"])
        if params.get("advisor_employee_no"):
            qs = qs.filter(advisor_employee_no=params["advisor_employee_no"])
        if params.get("current") == "1":
            qs = qs.filter(ended_at__isnull=True)
        return qs

    @action(detail=False, methods=["post"])
    def assign(self, request):
        if not has_role(request.user, *ADVISING_WRITE):
            self.permission_denied(request, message="Only the Registrar may assign an advisor.")
        data = AssignSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        try:
            assignment = assign_service(
                v["student"], v["advisor_employee_no"], actor=request.user, reason=v.get("reason", "")
            )
        except AdvisingError as exc:
            return Response({"code": exc.code, "detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        record(request, "assign", assignment, before=None, after=snapshot(assignment))
        return Response(self.get_serializer(assignment).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def end(self, request, pk=None):
        if not has_role(request.user, *ADVISING_WRITE):
            self.permission_denied(request, message="Only the Registrar may end an advising assignment.")
        assignment = self.get_object()
        if assignment.ended_at is not None:
            return Response(
                {"code": "already_ended", "detail": "This assignment has already ended."},
                status=status.HTTP_409_CONFLICT,
            )
        data = EndSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        before = snapshot(assignment)
        unassign_service(assignment.student, actor=request.user, reason=data.validated_data.get("reason", ""))
        assignment.refresh_from_db()
        record(request, "end", assignment, before=before, after=snapshot(assignment))
        return Response(self.get_serializer(assignment).data)

    @action(detail=False, methods=["post"])
    def bulk_assign(self, request):
        """Assign every student matching the given programme/intake-year/campus filter to one
        advisor — the "simple assignment mechanism" (programme/cohort), not an auto-matching
        algorithm."""
        if not has_role(request.user, *ADVISING_WRITE):
            self.permission_denied(request, message="Only the Registrar may bulk-assign advisees.")
        data = BulkAssignSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        qs = scope_queryset(request.user, Student.objects.all())
        if v.get("programme"):
            qs = qs.filter(programme=v["programme"])
        if v.get("intake_year"):
            qs = qs.filter(intake_year=v["intake_year"])
        if v.get("campus_code"):
            qs = qs.filter(campus_code=v["campus_code"])
        matched = qs.count()
        with transaction.atomic():
            changed = bulk_assign_service(qs, v["advisor_employee_no"], actor=request.user)
        return Response({"matched": matched, "assigned": changed})


class AdvisingNoteViewSet(AuditedModelViewSet):
    """An advisor's log of advising conversations. Notes are never edited or deleted once logged
    (`http_method_names` below) — a correction is a further note, same convention as a published
    `academics.Result`.
    """

    serializer_class = AdvisingNoteSerializer
    read_roles = ADVISING_READ + (Role.LECTURER,)
    write_roles = ADVISING_READ + (Role.LECTURER,)
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        user = self.request.user
        qs = AdvisingNote.objects.select_related("student")
        if has_role(user, *ADVISING_READ):
            qs = scope_queryset(user, qs, campus_field="student__campus_code")
        else:
            qs = qs.filter(advisor_employee_no=_own_employee_no(user) or "__none__")
        params = self.request.query_params
        if params.get("student"):
            qs = qs.filter(student_id=params["student"])
        if params.get("flagged") == "1":
            qs = qs.filter(flagged_for_registrar=True)
        return qs

    @transaction.atomic
    def perform_create(self, serializer):
        user = self.request.user
        own = _own_employee_no(user)
        if has_role(user, *ADVISING_WRITE):
            advisor_no = self.request.data.get("advisor_employee_no") or own
        else:
            advisor_no = own
        if not advisor_no:
            self.permission_denied(self.request, message="Only a linked advisor may log an advising note.")
        student = serializer.validated_data["student"]
        if not has_role(user, *ADVISING_WRITE):
            from advising.services import current_assignment

            current = current_assignment(student)
            if current is None or current.advisor_employee_no != advisor_no:
                self.permission_denied(
                    self.request, message="You can only log a note for your own current advisees."
                )
        instance = serializer.save(
            created_by=user, updated_by=user, advisor_employee_no=advisor_no
        )
        record(self.request, "create", instance, before=None, after=snapshot(instance))
        if instance.flagged_for_registrar:
            _notify_registrar(instance)


def _notify_registrar(note: AdvisingNote) -> None:
    from django.contrib.auth import get_user_model

    from notifications.models import Notification
    from notifications.services import notify

    recipients = get_user_model().objects.filter(role_scopes__role__code=Role.REGISTRAR).distinct()
    notify(
        recipients,
        title=f"Advising concern flagged: {note.student.student_no}",
        body=note.summary[:200],
        link="/advising",
        kind=Notification.Kind.ALERT,
        dedupe_key=f"advising-note:{note.id}",
    )


@api_view(["GET"])
@permission_classes([RolePermission])
def my_advisor(request):
    """A student's own current and past advisors (S-M04)."""
    student = getattr(request.user, "student", None)
    if student is None:
        return Response(
            {"code": "not_a_student", "detail": "This account is not linked to a student."}, status=404
        )
    assignments = AdvisorAssignment.objects.filter(student=student).select_related("student")
    return Response(AdvisorAssignmentSerializer(assignments, many=True, context={"request": request}).data)


@api_view(["GET"])
@permission_classes([RolePermission])
def my_advisees(request):
    """An advisor's own current advisees, with the standing, hold and enrolment facts a registrar
    already sees elsewhere — scoped to this advisor's own employee number only, resolved the same
    way `academics` resolves "my own offerings" (via `integration.StaffRef.user`)."""
    employee_no = _own_employee_no(request.user)
    if not employee_no:
        return Response(
            {"code": "not_staff", "detail": "This account is not linked to a staff record."}, status=404
        )
    student_ids = AdvisorAssignment.objects.filter(
        advisor_employee_no=employee_no, ended_at__isnull=True
    ).values_list("student_id", flat=True)
    students = (
        Student.objects.filter(id__in=student_ids)
        .select_related("programme", "standing")
        .prefetch_related("registration_holds", "enrolments__offering")
    )
    return Response(AdviseeSerializer(students, many=True, context={"request": request}).data)


router = DefaultRouter()
router.register("assignments", AdvisorAssignmentViewSet, basename="advisor-assignment")
router.register("notes", AdvisingNoteViewSet, basename="advising-note")
urlpatterns = [
    path("my-advisor/", my_advisor, name="my-advisor"),
    path("my-advisees/", my_advisees, name="my-advisees"),
    *router.urls,
]
