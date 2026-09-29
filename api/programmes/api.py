from rest_framework.routers import DefaultRouter

from core.serializers import TimeStampedSerializer
from core.views import AuditedModelViewSet
from iam.models import Role
from programmes.models import Course, Programme, ProgrammeCourse

WRITE = (Role.REGISTRAR, Role.ADMINISTRATOR)


class ProgrammeSerializer(TimeStampedSerializer):
    class Meta(TimeStampedSerializer.Meta):
        model = Programme
        fields = ("id", "code", "name", "award", "duration_years", "campus_codes", "is_active")


class CourseSerializer(TimeStampedSerializer):
    class Meta(TimeStampedSerializer.Meta):
        model = Course
        fields = ("id", "code", "title", "credits", "department_code", "description", "is_active")


class ProgrammeCourseSerializer(TimeStampedSerializer):
    class Meta(TimeStampedSerializer.Meta):
        model = ProgrammeCourse
        fields = ("id", "programme", "course", "year", "semester", "is_core")


class ProgrammeViewSet(AuditedModelViewSet):
    queryset = Programme.objects.all()
    serializer_class = ProgrammeSerializer
    write_roles = WRITE


class CourseViewSet(AuditedModelViewSet):
    queryset = Course.objects.all()
    serializer_class = CourseSerializer
    write_roles = WRITE

    def get_queryset(self):
        qs = super().get_queryset()
        department = self.request.query_params.get("department")
        return qs.filter(department_code=department) if department else qs


class ProgrammeCourseViewSet(AuditedModelViewSet):
    queryset = ProgrammeCourse.objects.select_related("programme", "course")
    serializer_class = ProgrammeCourseSerializer
    write_roles = WRITE

    def get_queryset(self):
        qs = super().get_queryset()
        programme = self.request.query_params.get("programme")
        return qs.filter(programme_id=programme) if programme else qs


router = DefaultRouter()
router.register("programmes", ProgrammeViewSet)
router.register("courses", CourseViewSet)
router.register("curriculum", ProgrammeCourseViewSet)
urlpatterns = router.urls
