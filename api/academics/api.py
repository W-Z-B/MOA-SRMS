"""Calendar, offerings, enrolments and results. Lecturers work only on their own offerings."""

from django.db import transaction
from django.db.models import Q
from django.urls import path
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.routers import DefaultRouter

from academics.models import (
    AcademicYear,
    CourseOffering,
    Enrolment,
    GradeBand,
    RegistrationHold,
    Result,
    Term,
)
from academics.services import (
    active_holds,
    compute,
    missing_prerequisites,
    next_enrolment_status,
    promote_next_waitlisted,
    transcript,
)
from academics.workflow import RESULT, owns_offering
from audit.services import record, snapshot
from core.serializers import TimeStampedSerializer
from core.views import AuditedModelViewSet
from core.workflow import WorkflowError
from iam.models import Role
from iam.permissions import RolePermission
from iam.services import has_role, scope_queryset, unit_codes

REGISTRY = (Role.REGISTRAR, Role.ADMINISTRATOR)
STAFF_READ = REGISTRY + (Role.HOD, Role.LECTURER, Role.PRINCIPAL, Role.AUDITOR, Role.ADMISSIONS_OFFICER)


class AcademicYearSerializer(TimeStampedSerializer):
    class Meta(TimeStampedSerializer.Meta):
        model = AcademicYear
        fields = ("id", "code", "starts", "ends")


class TermSerializer(TimeStampedSerializer):
    class Meta(TimeStampedSerializer.Meta):
        model = Term
        fields = ("id", "year", "code", "number", "name", "starts", "ends", "is_current")


class CourseOfferingSerializer(TimeStampedSerializer):
    course_code = serializers.CharField(source="course.code", read_only=True)
    course_title = serializers.CharField(source="course.title", read_only=True)
    term_code = serializers.CharField(source="term.code", read_only=True)
    enrolled = serializers.IntegerField(read_only=True, source="enrolments.count")

    class Meta(TimeStampedSerializer.Meta):
        model = CourseOffering
        fields = (
            "id",
            "code",
            "course",
            "course_code",
            "course_title",
            "term",
            "term_code",
            "campus_code",
            "lecturer_employee_no",
            "capacity",
            "coursework_weight",
            "exam_weight",
            "enrolled",
        )


class EnrolmentSerializer(TimeStampedSerializer):
    student_no = serializers.CharField(source="student.student_no", read_only=True)
    student_name = serializers.CharField(source="student.full_name", read_only=True)
    offering_code = serializers.CharField(source="offering.code", read_only=True)

    class Meta(TimeStampedSerializer.Meta):
        model = Enrolment
        fields = (
            "id",
            "student",
            "student_no",
            "student_name",
            "offering",
            "offering_code",
            "status",
            "waitlist_rank",
        )
        read_only_fields = TimeStampedSerializer.Meta.read_only_fields + ("status", "waitlist_rank")

    def validate(self, attrs):
        offering = attrs.get("offering")
        student = attrs.get("student")
        if offering and student and self.instance is None:
            if student.campus_code != offering.campus_code:
                raise serializers.ValidationError({"offering": "The offering is at a different campus."})
            holds = active_holds(student)
            if holds.exists():
                reasons = ", ".join(sorted({h.get_reason_display() for h in holds}))
                raise serializers.ValidationError({"student": f"Registration is on hold: {reasons}."})
            missing = missing_prerequisites(student, offering.course)
            if missing:
                raise serializers.ValidationError(
                    {"offering": f"Prerequisite not met: {', '.join(missing)}."}
                )
        return attrs


class RegistrationHoldSerializer(TimeStampedSerializer):
    student_no = serializers.CharField(source="student.student_no", read_only=True)
    reason_display = serializers.CharField(source="get_reason_display", read_only=True)

    class Meta(TimeStampedSerializer.Meta):
        model = RegistrationHold
        fields = (
            "id",
            "student",
            "student_no",
            "reason",
            "reason_display",
            "source",
            "detail",
            "is_active",
            "resolved_at",
            "created_at",
        )
        read_only_fields = TimeStampedSerializer.Meta.read_only_fields + ("resolved_at",)


class GradeBandSerializer(TimeStampedSerializer):
    class Meta(TimeStampedSerializer.Meta):
        model = GradeBand
        fields = ("id", "letter", "min_mark", "points", "is_pass", "effective_from")


class ResultSerializer(TimeStampedSerializer):
    student_no = serializers.CharField(source="enrolment.student.student_no", read_only=True)
    student_name = serializers.CharField(source="enrolment.student.full_name", read_only=True)
    offering_code = serializers.CharField(source="enrolment.offering.code", read_only=True)
    course_code = serializers.CharField(source="enrolment.offering.course.code", read_only=True)
    allowed_actions = serializers.SerializerMethodField()

    class Meta(TimeStampedSerializer.Meta):
        model = Result
        fields = (
            "id",
            "enrolment",
            "student_no",
            "student_name",
            "offering_code",
            "course_code",
            "coursework_mark",
            "exam_mark",
            "final_mark",
            "letter",
            "points",
            "is_pass",
            "state",
            "coursework_source",
            "decision_comment",
            "allowed_actions",
        )
        read_only_fields = TimeStampedSerializer.Meta.read_only_fields + (
            "enrolment",
            "final_mark",
            "letter",
            "points",
            "is_pass",
            "state",
            "coursework_source",
            "decision_comment",
        )

    def get_allowed_actions(self, obj):
        request = self.context.get("request")
        return RESULT.allowed_actions(obj, request.user) if request else []


class TransitionSerializer(serializers.Serializer):
    action = serializers.CharField()
    comment = serializers.CharField(required=False, allow_blank=True, max_length=300)


class AcademicYearViewSet(AuditedModelViewSet):
    queryset = AcademicYear.objects.all()
    serializer_class = AcademicYearSerializer
    write_roles = REGISTRY


class TermViewSet(AuditedModelViewSet):
    queryset = Term.objects.select_related("year")
    serializer_class = TermSerializer
    write_roles = REGISTRY


class GradeBandViewSet(AuditedModelViewSet):
    queryset = GradeBand.objects.all()
    serializer_class = GradeBandSerializer
    write_roles = REGISTRY


def _own_employee_no(user) -> str | None:
    staff = getattr(user, "staff_ref", None)
    return staff.employee_no if staff else None


class CourseOfferingViewSet(AuditedModelViewSet):
    serializer_class = CourseOfferingSerializer
    read_roles = STAFF_READ
    write_roles = REGISTRY

    def get_queryset(self):
        user = self.request.user
        qs = CourseOffering.objects.select_related("course", "term").prefetch_related("enrolments")
        if has_role(user, *REGISTRY, Role.PRINCIPAL, Role.AUDITOR, Role.ADMISSIONS_OFFICER):
            qs = scope_queryset(user, qs)
        else:
            mine = Q(lecturer_employee_no=_own_employee_no(user) or "__none__")
            department = (
                Q(course__department_code__in=unit_codes(user, Role.HOD)) if has_role(user, Role.HOD) else Q()
            )
            qs = qs.filter(mine | department) if department else qs.filter(mine)
        params = self.request.query_params
        if params.get("term"):
            qs = qs.filter(term__code=params["term"])
        if params.get("campus_code"):
            qs = qs.filter(campus_code=params["campus_code"])
        if params.get("mine") == "1":
            qs = qs.filter(lecturer_employee_no=_own_employee_no(user) or "__none__")
        return qs


class EnrolmentViewSet(AuditedModelViewSet):
    """Course add is capacity- and waitlist-aware; drop is its own action (see `drop`)."""

    serializer_class = EnrolmentSerializer
    read_roles = STAFF_READ
    write_roles = REGISTRY
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        user = self.request.user
        qs = Enrolment.objects.select_related("student", "offering")
        if has_role(user, *REGISTRY, Role.PRINCIPAL, Role.AUDITOR, Role.ADMISSIONS_OFFICER):
            qs = scope_queryset(user, qs, campus_field="offering__campus_code")
        else:
            qs = qs.filter(offering__in=CourseOfferingViewSet(request=self.request).get_queryset())
        params = self.request.query_params
        if params.get("offering"):
            qs = qs.filter(offering_id=params["offering"])
        if params.get("student"):
            qs = qs.filter(student_id=params["student"])
        if params.get("status"):
            qs = qs.filter(status=params["status"])
        return qs

    @transaction.atomic
    def perform_create(self, serializer):
        offering = serializer.validated_data["offering"]
        status_value, rank = next_enrolment_status(offering)
        serializer.validated_data["status"] = status_value
        serializer.validated_data["waitlist_rank"] = rank
        super().perform_create(serializer)
        if status_value == Enrolment.Status.ENROLLED:
            Result.objects.get_or_create(
                enrolment=serializer.instance,
                defaults={"created_by": self.request.user, "updated_by": self.request.user},
            )

    @action(detail=True, methods=["post"])
    def drop(self, request, pk=None):
        """Withdraw from an offering. Dropping an enrolled seat promotes the next waitlisted student."""
        instance = self.get_object()
        if instance.status not in (Enrolment.Status.ENROLLED, Enrolment.Status.WAITLISTED):
            return Response(
                {"code": "invalid_state", "detail": "Only an enrolled or waitlisted entry can be dropped."},
                status=status.HTTP_409_CONFLICT,
            )
        with transaction.atomic():
            before = snapshot(instance)
            was_enrolled = instance.status == Enrolment.Status.ENROLLED
            instance.status = Enrolment.Status.DROPPED
            instance.waitlist_rank = None
            instance.updated_by = request.user
            instance.save(update_fields=["status", "waitlist_rank", "updated_by", "updated_at"])
            record(request, "drop", instance, before=before, after=snapshot(instance))
            if was_enrolled:
                promote_next_waitlisted(instance.offering, actor=request.user)
        return Response(self.get_serializer(instance).data)


class ResultViewSet(AuditedModelViewSet):
    """Marks are edited only while a result is in draft, by the owning lecturer or the Registrar."""

    serializer_class = ResultSerializer
    read_roles = STAFF_READ
    # Heads of Department pass the role gate so the workflow can decide approve and return;
    # editing marks is still limited to the owning lecturer and the Registrar (perform_update).
    write_roles = REGISTRY + (Role.LECTURER, Role.HOD)
    http_method_names = ["get", "patch", "post", "head", "options"]

    def get_queryset(self):
        user = self.request.user
        qs = Result.objects.select_related(
            "enrolment__student", "enrolment__offering__course", "enrolment__offering__term"
        )
        if has_role(user, *REGISTRY, Role.PRINCIPAL, Role.AUDITOR):
            qs = scope_queryset(user, qs, campus_field="enrolment__offering__campus_code")
        else:
            mine = Q(enrolment__offering__lecturer_employee_no=_own_employee_no(user) or "__none__")
            units = unit_codes(user, Role.HOD) if has_role(user, Role.HOD) else set()
            qs = (
                qs.filter(mine | Q(enrolment__offering__course__department_code__in=units))
                if units
                else qs.filter(mine)
            )
        offering = self.request.query_params.get("offering")
        return qs.filter(enrolment__offering_id=offering) if offering else qs

    def create(self, request, *args, **kwargs):
        return Response(
            {"code": "not_allowed", "detail": "Results are created with the enrolment."}, status=405
        )

    def perform_update(self, serializer):
        result = serializer.instance
        user = self.request.user
        if result.state != Result.State.DRAFT:
            self.permission_denied(
                self.request, message="Marks can only be changed while the result is a draft."
            )
        if not has_role(user, *REGISTRY) and not owns_offering(result, user):
            self.permission_denied(self.request, message="You can only enter marks for your own offerings.")
        with transaction.atomic():
            super().perform_update(serializer)
            if "coursework_mark" in serializer.validated_data:
                serializer.instance.coursework_source = Result.Source.MANUAL
            compute(serializer.instance)

    @action(detail=True, methods=["post"])
    def transition(self, request, pk=None):
        data = TransitionSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        instance = self.get_object()
        name = data.validated_data["action"]
        if name == "submit" and (instance.coursework_mark is None or instance.exam_mark is None):
            return Response(
                {"code": "marks_missing", "detail": "Enter both coursework and examination marks first."},
                status=status.HTTP_409_CONFLICT,
            )
        try:
            RESULT.apply(instance, name, request=request, comment=data.validated_data.get("comment", ""))
        except WorkflowError as exc:
            code = status.HTTP_403_FORBIDDEN if exc.code == "forbidden_actor" else status.HTTP_409_CONFLICT
            return Response({"code": exc.code, "detail": str(exc)}, status=code)
        instance.refresh_from_db()
        return Response(self.get_serializer(instance).data)


class RegistrationHoldViewSet(AuditedModelViewSet):
    """Holds that block new course registration (never a drop). See `academics.models.RegistrationHold`."""

    serializer_class = RegistrationHoldSerializer
    read_roles = STAFF_READ
    write_roles = REGISTRY
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        qs = scope_queryset(
            self.request.user,
            RegistrationHold.objects.select_related("student"),
            campus_field="student__campus_code",
        )
        params = self.request.query_params
        if params.get("student"):
            qs = qs.filter(student_id=params["student"])
        if params.get("active") is not None:
            qs = qs.filter(is_active=params["active"] in ("1", "true", "True"))
        return qs

    @action(detail=True, methods=["post"])
    def resolve(self, request, pk=None):
        hold = self.get_object()
        before = snapshot(hold)
        hold.is_active = False
        hold.resolved_at = timezone.now()
        hold.resolved_by = request.user
        hold.updated_by = request.user
        hold.save(update_fields=["is_active", "resolved_at", "resolved_by", "updated_by", "updated_at"])
        record(request, "resolve", hold, before=before, after=snapshot(hold))
        return Response(self.get_serializer(hold).data)


@api_view(["GET"])
@permission_classes([RolePermission])
def my_results(request):
    """A student's own transcript: published results only."""
    student = getattr(request.user, "student", None)
    if student is None:
        return Response(
            {"code": "not_a_student", "detail": "This account is not linked to a student."}, status=404
        )
    return Response(transcript(student, published_only=True))


router = DefaultRouter()
router.register("years", AcademicYearViewSet)
router.register("terms", TermViewSet)
router.register("grade-bands", GradeBandViewSet)
router.register("offerings", CourseOfferingViewSet, basename="offering")
router.register("enrolments", EnrolmentViewSet, basename="enrolment")
router.register("registration-holds", RegistrationHoldViewSet, basename="registration-hold")
router.register("results", ResultViewSet, basename="result")
urlpatterns = [path("my-results/", my_results, name="my-results"), *router.urls]
