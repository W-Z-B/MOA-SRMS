"""Fee items (dated, per programme), a student's charges and payments, and the ledger views."""

from django.urls import path
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.routers import DefaultRouter

from core.serializers import TimeStampedSerializer
from core.views import AuditedModelViewSet
from fees.models import FeeCharge, FeeItem, Payment
from fees.services import ledger
from iam.models import Role
from iam.permissions import RolePermission
from iam.services import has_role, scope_queryset

FINANCE_WRITE = (Role.FINANCE, Role.REGISTRAR, Role.ADMINISTRATOR)
STAFF_READ = FINANCE_WRITE + (Role.PRINCIPAL, Role.AUDITOR, Role.ADMISSIONS_OFFICER)


class FeeItemSerializer(TimeStampedSerializer):
    programme_code = serializers.CharField(source="programme.code", read_only=True)

    class Meta(TimeStampedSerializer.Meta):
        model = FeeItem
        fields = ("id", "programme", "programme_code", "fee_type", "amount", "effective_from")


class FeeChargeSerializer(TimeStampedSerializer):
    student_no = serializers.CharField(source="student.student_no", read_only=True)
    term_code = serializers.CharField(source="term.code", read_only=True)

    class Meta(TimeStampedSerializer.Meta):
        model = FeeCharge
        fields = (
            "id",
            "student",
            "student_no",
            "term",
            "term_code",
            "fee_type",
            "amount",
            "due_date",
            "description",
        )


class PaymentSerializer(TimeStampedSerializer):
    student_no = serializers.CharField(source="student.student_no", read_only=True)
    recorded_by = serializers.CharField(source="created_by.username", read_only=True, default=None)

    class Meta(TimeStampedSerializer.Meta):
        model = Payment
        fields = (
            "id",
            "student",
            "student_no",
            "amount",
            "paid_on",
            "method",
            "reference",
            "note",
            "recorded_by",
        )


class FeeItemViewSet(AuditedModelViewSet):
    queryset = FeeItem.objects.select_related("programme")
    serializer_class = FeeItemSerializer
    read_roles = STAFF_READ
    write_roles = FINANCE_WRITE

    def get_queryset(self):
        qs = super().get_queryset()
        programme = self.request.query_params.get("programme")
        return qs.filter(programme_id=programme) if programme else qs


class FeeChargeViewSet(AuditedModelViewSet):
    """Charges are usually raised in bulk per term (see `manage.py apply_fee_schedule`); this
    endpoint also accepts an individual ad hoc charge, e.g. a lab breakage fee.
    """

    serializer_class = FeeChargeSerializer
    read_roles = STAFF_READ
    write_roles = FINANCE_WRITE
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        qs = scope_queryset(
            self.request.user,
            FeeCharge.objects.select_related("student", "term"),
            campus_field="student__campus_code",
        )
        student = self.request.query_params.get("student")
        return qs.filter(student_id=student) if student else qs


class PaymentViewSet(AuditedModelViewSet):
    serializer_class = PaymentSerializer
    read_roles = STAFF_READ
    write_roles = FINANCE_WRITE
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        qs = scope_queryset(
            self.request.user, Payment.objects.select_related("student"), campus_field="student__campus_code"
        )
        student = self.request.query_params.get("student")
        return qs.filter(student_id=student) if student else qs


@api_view(["GET"])
@permission_classes([RolePermission])
def student_ledger(request, student_id: int):
    """A finance officer's (or other records staff's) view of one student's ledger."""
    from students.models import Student

    if not has_role(request.user, *STAFF_READ):
        return Response({"code": "forbidden", "detail": "Your role cannot view student ledgers."}, status=403)
    student = scope_queryset(
        request.user, Student.objects.all(), campus_field="campus_code"
    ).filter(pk=student_id).first()
    if student is None:
        return Response({"code": "not_found", "detail": "Student not found."}, status=404)
    return Response(ledger(student))


@api_view(["GET"])
@permission_classes([RolePermission])
def my_balance(request):
    """A student's own ledger and running balance."""
    student = getattr(request.user, "student", None)
    if student is None:
        return Response(
            {"code": "not_a_student", "detail": "This account is not linked to a student."}, status=404
        )
    return Response(ledger(student))


router = DefaultRouter()
router.register("fee-items", FeeItemViewSet, basename="fee-item")
router.register("charges", FeeChargeViewSet, basename="fee-charge")
router.register("payments", PaymentViewSet, basename="payment")
urlpatterns = [
    path("my-balance/", my_balance, name="my-balance"),
    path("ledger/<int:student_id>/", student_ledger, name="student-ledger"),
    *router.urls,
]
