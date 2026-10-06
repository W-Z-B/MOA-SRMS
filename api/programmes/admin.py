from django.contrib import admin

from programmes.models import Course, CourseOutcome, Programme, ProgrammeCourse


@admin.register(Programme)
class ProgrammeAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "award", "duration_years", "attendance_required", "is_active")


class CourseOutcomeInline(admin.TabularInline):
    model = CourseOutcome
    extra = 1
    fields = ("position", "code", "text")


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("code", "title", "credits", "department_code", "is_active")
    search_fields = ("code", "title")
    inlines = [CourseOutcomeInline]


admin.site.register(ProgrammeCourse)
