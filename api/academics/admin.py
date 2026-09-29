from django.contrib import admin

from academics.models import AcademicYear, CourseOffering, Enrolment, GradeBand, Result, Term

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
