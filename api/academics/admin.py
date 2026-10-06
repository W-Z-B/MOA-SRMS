from django.contrib import admin

from academics.models import (
    AcademicYear,
    AttendanceTotal,
    CompetencyResult,
    CourseOffering,
    Enrolment,
    GradeBand,
    Result,
    Term,
)

admin.site.register(AcademicYear)
admin.site.register(Term)
admin.site.register(GradeBand)


@admin.register(CourseOffering)
class CourseOfferingAdmin(admin.ModelAdmin):
    list_display = ("code", "course", "term", "campus_code", "lecturer_employee_no", "capacity")
    list_filter = ("term", "campus_code")


@admin.register(Enrolment)
class EnrolmentAdmin(admin.ModelAdmin):
    list_display = ("student", "offering", "status")
    list_filter = ("status",)


@admin.register(Result)
class ResultAdmin(admin.ModelAdmin):
    list_display = ("enrolment", "coursework_mark", "exam_mark", "final_mark", "letter", "state")
    list_filter = ("state",)


@admin.register(AttendanceTotal)
class AttendanceTotalAdmin(admin.ModelAdmin):
    """Received from the LMS; read here, changed only by the LMS sending again."""

    list_display = ("enrolment", "sessions", "present", "late", "excused", "absent", "percent", "received_at")
    readonly_fields = [f.name for f in AttendanceTotal._meta.fields]

    def has_add_permission(self, request):
        return False


@admin.register(CompetencyResult)
class CompetencyResultAdmin(admin.ModelAdmin):
    """Received from the LMS; read here, changed only by the LMS sending again."""

    list_display = ("enrolment", "unit_code", "result", "assessed_on")
    list_filter = ("result",)
    readonly_fields = [f.name for f in CompetencyResult._meta.fields]

    def has_add_permission(self, request):
        return False
