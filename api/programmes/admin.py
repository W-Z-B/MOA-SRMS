from django.contrib import admin

from programmes.models import Course, Programme, ProgrammeCourse


@admin.register(Programme)
class ProgrammeAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "award", "duration_years", "is_active")


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("code", "title", "credits", "department_code", "is_active")
    search_fields = ("code", "title")


admin.site.register(ProgrammeCourse)
