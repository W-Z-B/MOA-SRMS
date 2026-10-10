"""Academic standing: a registrar-facing standing/appeals screen, and a student's own standing
and right to appeal (S-W04). Visibility is kept narrower than ordinary academic data (REGISTRAR,
PRINCIPAL, AUDITOR, ADMINISTRATOR only) — standing is comparable in sensitivity to the HRMS
`cases` register, not an ordinary grade.
"""

from django.urls import path
from rest_framework import serializers, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.routers import DefaultRouter
from rest_framework.viewsets import ReadOnlyModelViewSet

from academics.models import Term
from core.serializers import TimeStampedSerializer
from iam.models import Role
from iam.permissions import RolePermission
from iam.services import has_role, scope_queryset
from standing.models import AcademicStanding, StandingAppeal, StandingDecision
from standing.services import StandingError, apply_override, hear_appeal, lodge_appeal

STAFF_READ = (Role.REGISTRAR, Role.ADMINISTRATOR, Role.PRINCIPAL, Role.AUDITOR)
OVERRIDE_ROLES = (Role.REGISTRAR, Role.ADMINISTRATOR)
HEAR_APPEAL_ROLES = (Role.REGISTRAR, Role.PRINCIPAL, Role.ADMINISTRATOR)


class StandingDecisionSerializer(TimeStampedSerializer):
    term_code = serializers.CharField(source="term.code", read_only=True)
    decided_by_name = serializers.SerializerMethodField()
    has_appeal = serializers.SerializerMethodField()

    class Meta(TimeStampedSerializer.Meta):
        model = StandingDecision
        fields = (
            "id",
            "term",
            "term_code",
            "previous_tier",
            "tier",
            "cumulative_gpa",
            "is_automatic",
            "reason",
            "decided_by_name",
            "has_appeal",
            "created_at",
        )

    def get_decided_by_name(self, obj) -> str | None:
        return obj.decided_by.get_full_name() or obj.decided_by.username if obj.decided_by else None

    def get_has_appeal(self, obj) -> bool:
        return hasattr(obj, "appeal")


class AcademicStandingSerializer(TimeStampedSerializer):
    student_no = serializers.CharField(source="student.student_no", read_only=True)
    student_name = serializers.CharField(source="student.full_name", read_only=True)
    campus_code = serializers.CharField(source="student.campus_code", read_only=True)
    programme_code = serializers.CharField(source="student.programme.code", read_only=True)
    as_of_term_code = serializers.CharField(source="as_of_term.code", read_only=True, default="")
    decisions = StandingDecisionSerializer(many=True, read_only=True)

    class Meta(TimeStampedSerializer.Meta):
        model = AcademicStanding
        fields = (
            "id",
            "student",
            "student_no",
            "student_name",
            "campus_code",
            "programme_code",
            "tier",
            "cumulative_gpa",
            "as_of_term_code",
            "computed_at",
            "decisions",
        )


class OverrideSerializer(serializers.Serializer):
    term = serializers.PrimaryKeyRelatedField(queryset=Term.objects.all())
    tier = serializers.ChoiceField(choices=AcademicStanding.Tier.choices)
    reason = serializers.CharField(max_length=300)


class AppealSerializer(serializers.Serializer):
    grounds = serializers.CharField()


class HearAppealSerializer(serializers.Serializer):
    outcome = serializers.ChoiceField(choices=StandingAppeal.Outcome.choices)
    reason = serializers.CharField()


class StandingAppealSerializer(TimeStampedSerializer):
    student_no = serializers.CharField(source="decision.standing.student.student_no", read_only=True)
    student_name = serializers.CharField(source="decision.standing.student.full_name", read_only=True)
    decision_tier = serializers.CharField(source="decision.tier", read_only=True)
    heard_by_name = serializers.SerializerMethodField()

    class Meta(TimeStampedSerializer.Meta):
        model = StandingAppeal
        fields = (
            "id",
            "decision",
            "student_no",
            "student_name",
            "decision_tier",
            "grounds",
            "outcome",
            "outcome_reason",
            "heard_by_name",
            "heard_at",
            "created_at",
        )

    def get_heard_by_name(self, obj) -> str | None:
        return obj.heard_by.get_full_name() or obj.heard_by.username if obj.heard_by else None


class StandingViewSet(ReadOnlyModelViewSet):
    """The registrar-facing standing register: every student's current tier and decision
    history. Read-only here; changes go through `override` (manual) or the nightly job.
    """

    serializer_class = AcademicStandingSerializer
    read_roles = STAFF_READ
    write_roles = OVERRIDE_ROLES
    permission_classes = [RolePermission]

    def get_queryset(self):
        qs = scope_queryset(
            self.request.user,
            AcademicStanding.objects.select_related("student", "student__programme", "as_of_term")
            .prefetch_related("decisions")
            .order_by("student__last_name", "student__first_name"),
            campus_field="student__campus_code",
        )
        params = self.request.query_params
        if params.get("tier"):
            qs = qs.filter(tier=params["tier"])
        if params.get("campus_code"):
            qs = qs.filter(student__campus_code=params["campus_code"])
        return qs

    @action(detail=True, methods=["post"])
    def override(self, request, pk=None):
        if not has_role(request.user, *OVERRIDE_ROLES):
            self.permission_denied(request, message="Only the Registrar may override a standing decision.")
        standing = self.get_object()
        data = OverrideSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            apply_override(standing.student, actor=request.user, **data.validated_data)
        except StandingError as exc:
            return Response({"code": exc.code, "detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        standing.refresh_from_db()
        return Response(self.get_serializer(standing).data)


class StandingAppealViewSet(ReadOnlyModelViewSet):
    """The registrar-facing appeals queue."""

    serializer_class = StandingAppealSerializer
    read_roles = STAFF_READ
    write_roles = HEAR_APPEAL_ROLES
    permission_classes = [RolePermission]

    def get_queryset(self):
        qs = scope_queryset(
            self.request.user,
            StandingAppeal.objects.select_related("decision__standing__student", "heard_by"),
            campus_field="decision__standing__student__campus_code",
        )
        if self.request.query_params.get("pending") == "1":
            qs = qs.filter(outcome="")
        return qs

    @action(detail=True, methods=["post"])
    def hear(self, request, pk=None):
        if not has_role(request.user, *HEAR_APPEAL_ROLES):
            self.permission_denied(request, message="Only the Registrar or Principal may decide an appeal.")
        appeal = self.get_object()
        data = HearAppealSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            hear_appeal(appeal, heard_by=request.user, **data.validated_data)
        except StandingError as exc:
            code = status.HTTP_403_FORBIDDEN if exc.code == "not_independent" else status.HTTP_400_BAD_REQUEST
            return Response({"code": exc.code, "detail": str(exc)}, status=code)
        appeal.refresh_from_db()
        return Response(self.get_serializer(appeal).data)


@api_view(["GET"])
@permission_classes([RolePermission])
def my_standing(request):
    """A student's own standing, decision history and whether each decision can still be
    appealed."""
    student = getattr(request.user, "student", None)
    if student is None:
        return Response(
            {"code": "not_a_student", "detail": "This account is not linked to a student."}, status=404
        )
    standing, _ = AcademicStanding.objects.get_or_create(student=student)
    data = AcademicStandingSerializer(standing, context={"request": request}).data
    return Response(data)


@api_view(["POST"])
@permission_classes([RolePermission])
def appeal_decision(request, decision_id: int):
    student = getattr(request.user, "student", None)
    if student is None:
        return Response(
            {"code": "not_a_student", "detail": "This account is not linked to a student."}, status=404
        )
    decision = StandingDecision.objects.select_related("standing").filter(pk=decision_id).first()
    if decision is None:
        return Response({"code": "not_found", "detail": "Decision not found."}, status=404)
    data = AppealSerializer(data=request.data)
    data.is_valid(raise_exception=True)
    try:
        appeal = lodge_appeal(decision, student_user=request.user, **data.validated_data)
    except StandingError as exc:
        code = status.HTTP_403_FORBIDDEN if exc.code == "forbidden" else status.HTTP_400_BAD_REQUEST
        return Response({"code": exc.code, "detail": str(exc)}, status=code)
    return Response(StandingAppealSerializer(appeal).data, status=status.HTTP_201_CREATED)


router = DefaultRouter()
router.register("students", StandingViewSet, basename="standing")
router.register("appeals", StandingAppealViewSet, basename="standing-appeal")
urlpatterns = [
    path("my-standing/", my_standing, name="my-standing"),
    path("decisions/<int:decision_id>/appeal/", appeal_decision, name="standing-decision-appeal"),
    *router.urls,
]
