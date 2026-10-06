from rest_framework import serializers
from rest_framework.routers import DefaultRouter

from core.serializers import TimeStampedSerializer
from core.views import AuditedModelViewSet
from iam.models import Role
from programmes.models import Course, CourseOutcome, Programme, ProgrammeCourse

WRITE = (Role.REGISTRAR, Role.ADMINISTRATOR)


class ProgrammeSerializer(TimeStampedSerializer):
    class Meta(TimeStampedSerializer.Meta):
        model = Programme
        fields = (
            "id",
            "code",
            "name",
            "award",
            "duration_years",
            "campus_codes",
            "attendance_required",
            "is_active",
        )


class CourseOutcomeSerializer(TimeStampedSerializer):
    course_code = serializers.CharField(source="course.code", read_only=True)

    class Meta(TimeStampedSerializer.Meta):
        model = CourseOutcome
        fields = ("id", "course", "course_code", "code", "text", "position")


class CourseSerializer(TimeStampedSerializer):
    outcomes = serializers.SerializerMethodField()

    class Meta(TimeStampedSerializer.Meta):
        model = Course
        fields = ("id", "code", "title", "credits", "department_code", "description", "is_active", "outcomes")

    def get_outcomes(self, obj) -> list[dict]:
        """The course outline's learning outcomes, edited at /course-outcomes/."""
        return [{"id": o.id, "code": o.code, "text": o.text} for o in obj.outcomes.all()]


class ProgrammeCourseSerializer(TimeStampedSerializer):
    class Meta(TimeStampedSerializer.Meta):
        model = ProgrammeCourse
        fields = ("id", "programme", "course", "year", "semester", "is_core")


class ProgrammeViewSet(AuditedModelViewSet):
    queryset = Programme.objects.all()
    serializer_class = ProgrammeSerializer
    write_roles = WRITE


class CourseViewSet(AuditedModelViewSet):
    queryset = Course.objects.prefetch_related("outcomes")
    serializer_class = CourseSerializer
    write_roles = WRITE

    def get_queryset(self):
        qs = super().get_queryset()
        department = self.request.query_params.get("department")
        return qs.filter(department_code=department) if department else qs


class CourseOutcomeViewSet(AuditedModelViewSet):
    """Learning outcomes of a course outline. The Registrar and administrators keep them; the LMS reads them
    through /api/v1/integration/course-outcomes/."""

    queryset = CourseOutcome.objects.select_related("course")
    serializer_class = CourseOutcomeSerializer
    write_roles = WRITE

    def get_queryset(self):
        qs = super().get_queryset()
        course = self.request.query_params.get("course")
        return qs.filter(course_id=course) if course else qs


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
router.register("course-outcomes", CourseOutcomeViewSet)
router.register("curriculum", ProgrammeCourseViewSet)
urlpatterns = router.urls
