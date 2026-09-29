"""Students (campus-scoped, masked identifiers, audited reveal) and admissions applications."""

from django.db.models import Q
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.routers import DefaultRouter

from audit.services import record
from core.crypto import mask
from core.serializers import TimeStampedSerializer
from core.views import AuditedModelViewSet
from core.workflow import WorkflowError
from iam.models import Role
from iam.services import has_role, scope_queryset
from students.models import Application, Student
from students.services import next_reference
from students.workflow import APPLICATION

RECORDS_WRITE = (Role.REGISTRAR, Role.ADMISSIONS_OFFICER, Role.ADMINISTRATOR)
STAFF_READ = RECORDS_WRITE + (Role.HOD, Role.LECTURER, Role.PRINCIPAL, Role.FINANCE, Role.AUDITOR)


class StudentSerializer(TimeStampedSerializer):
    national_id = serializers.CharField(write_only=True, required=False, allow_null=True, allow_blank=True)
    national_id_masked = serializers.SerializerMethodField()
    full_name = serializers.CharField(read_only=True)
    programme_code = serializers.CharField(source="programme.code", read_only=True)
    programme_name = serializers.CharField(source="programme.name", read_only=True)

    class Meta(TimeStampedSerializer.Meta):
        model = Student
        fields = (
            "id",
            "student_no",
            "user",
            "first_name",
            "last_name",
            "other_names",
            "full_name",
            "date_of_birth",
            "gender",
            "national_id",
            "national_id_masked",
            "email",
            "phone",
            "address",
            "region",
            "nationality",
            "campus_code",
            "programme",
            "programme_code",
            "programme_name",
            "intake_year",
            "status",
            "is_residential",
            "sponsor",
            "next_of_kin_name",
            "next_of_kin_phone",
            "created_at",
            "updated_at",
        )

    def get_national_id_masked(self, obj):
        return mask(obj.national_id)


class ApplicationSerializer(TimeStampedSerializer):
    reference = serializers.CharField(read_only=True)
    state = serializers.CharField(read_only=True)
    full_name = serializers.CharField(read_only=True)
    allowed_actions = serializers.SerializerMethodField()
    student_no = serializers.CharField(source="student.student_no", read_only=True, default=None)

    class Meta(TimeStampedSerializer.Meta):
        model = Application
        fields = (
            "id",
            "reference",
            "first_name",
            "last_name",
            "other_names",
            "full_name",
            "date_of_birth",
            "gender",
            "email",
            "phone",
            "address",
            "region",
            "nationality",
            "qualifications",
            "programme",
            "campus_code",
            "intake_year",
            "state",
            "decision_comment",
            "allowed_actions",
            "student",
            "student_no",
            "created_at",
            "updated_at",
        )
        read_only_fields = TimeStampedSerializer.Meta.read_only_fields + ("decision_comment", "student")

    def get_allowed_actions(self, obj):
        request = self.context.get("request")
        return APPLICATION.allowed_actions(obj, request.user) if request else []


class TransitionSerializer(serializers.Serializer):
    action = serializers.CharField()
    comment = serializers.CharField(required=False, allow_blank=True, max_length=300)


class StudentViewSet(AuditedModelViewSet):
    serializer_class = StudentSerializer
    read_roles = STAFF_READ
    write_roles = RECORDS_WRITE

    def get_queryset(self):
        qs = scope_queryset(self.request.user, Student.objects.select_related("programme"))
        params = self.request.query_params
        if params.get("q"):
            q = params["q"]
            qs = qs.filter(
                Q(first_name__istartswith=q) | Q(last_name__istartswith=q) | Q(student_no__istartswith=q)
            )
        for key in ("campus_code", "status", "intake_year"):
            if params.get(key):
                qs = qs.filter(**{key: params[key]})
        if params.get("programme"):
            qs = qs.filter(programme_id=params["programme"])
        return qs

    @action(detail=True, methods=["post"])
    def reveal(self, request, pk=None):
        if not has_role(request.user, *RECORDS_WRITE):
            return Response(
                {"code": "forbidden", "detail": "Only records staff may reveal identifiers."}, status=403
            )
        student = self.get_object()
        record(request, "reveal", student, after={"fields": ["national_id"]})
        return Response(
            {"id": student.id, "student_no": student.student_no, "national_id": student.national_id}
        )

    @action(detail=True, methods=["get"])
    def transcript(self, request, pk=None):
        from academics.services import transcript

        student = self.get_object()
        record(request, "transcript", student)
        return Response(transcript(student, published_only=not has_role(request.user, Role.REGISTRAR)))


class ApplicationViewSet(AuditedModelViewSet):
    serializer_class = ApplicationSerializer
    read_roles = RECORDS_WRITE + (Role.PRINCIPAL, Role.AUDITOR)
    write_roles = RECORDS_WRITE

    def get_queryset(self):
        qs = scope_queryset(self.request.user, Application.objects.select_related("programme", "student"))
        params = self.request.query_params
        for key in ("state", "campus_code", "intake_year"):
            if params.get(key):
                qs = qs.filter(**{key: params[key]})
        return qs

    def perform_create(self, serializer):
        serializer.validated_data["reference"] = next_reference(serializer.validated_data["intake_year"])
        super().perform_create(serializer)

    @action(detail=True, methods=["post"])
    def transition(self, request, pk=None):
        data = TransitionSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        instance = self.get_object()
        try:
            APPLICATION.apply(
                instance,
                data.validated_data["action"],
                request=request,
                comment=data.validated_data.get("comment", ""),
            )
        except WorkflowError as exc:
            code = status.HTTP_403_FORBIDDEN if exc.code == "forbidden_actor" else status.HTTP_409_CONFLICT
            return Response({"code": exc.code, "detail": str(exc)}, status=code)
        instance.refresh_from_db()
        return Response(self.get_serializer(instance).data)


router = DefaultRouter()
router.register("students", StudentViewSet, basename="student")
router.register("applications", ApplicationViewSet, basename="application")
urlpatterns = router.urls
