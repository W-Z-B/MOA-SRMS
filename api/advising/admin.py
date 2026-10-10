from django.contrib import admin

from advising.models import AdvisingNote, AdvisorAssignment


@admin.register(AdvisorAssignment)
class AdvisorAssignmentAdmin(admin.ModelAdmin):
    list_display = ("student", "advisor_employee_no", "started_at", "ended_at")
    list_filter = ("ended_at",)
    search_fields = ("student__student_no", "student__last_name", "advisor_employee_no")


@admin.register(AdvisingNote)
class AdvisingNoteAdmin(admin.ModelAdmin):
    list_display = ("student", "advisor_employee_no", "met_on", "concern", "flagged_for_registrar")
    list_filter = ("concern", "flagged_for_registrar")
    search_fields = ("student__student_no", "student__last_name", "advisor_employee_no")
