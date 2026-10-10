from django.contrib import admin

from students.models import Application, ApplicationDocument, Student, WaitlistEntry


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


@admin.register(ApplicationDocument)
class ApplicationDocumentAdmin(admin.ModelAdmin):
    list_display = ("application", "doc_type", "created_at")
    list_filter = ("doc_type",)


@admin.register(WaitlistEntry)
class WaitlistEntryAdmin(admin.ModelAdmin):
    list_display = ("application", "programme", "intake_year", "rank")
    list_filter = ("programme", "intake_year")
