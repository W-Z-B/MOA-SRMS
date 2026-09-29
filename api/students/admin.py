from django.contrib import admin

from students.models import Application, Student


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = (
        "student_no",
        "last_name",
        "first_name",
        "programme",
        "campus_code",
        "intake_year",
        "status",
    )
    list_filter = ("campus_code", "status", "programme", "intake_year")
    search_fields = ("student_no", "first_name", "last_name")
    exclude = ("national_id",)  # managed through the audited API only


@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = (
        "reference",
        "last_name",
        "first_name",
        "programme",
        "campus_code",
        "intake_year",
        "state",
    )
    list_filter = ("state", "campus_code", "intake_year")
