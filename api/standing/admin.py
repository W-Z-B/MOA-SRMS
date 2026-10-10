from django.contrib import admin

from standing.models import AcademicStanding, StandingAppeal, StandingDecision


@admin.register(AcademicStanding)
class AcademicStandingAdmin(admin.ModelAdmin):
    list_display = ("student", "tier", "cumulative_gpa", "as_of_term", "computed_at")
    list_filter = ("tier",)


@admin.register(StandingDecision)
class StandingDecisionAdmin(admin.ModelAdmin):
    list_display = ("standing", "term", "previous_tier", "tier", "is_automatic", "decided_by", "created_at")
    list_filter = ("tier", "is_automatic")


@admin.register(StandingAppeal)
class StandingAppealAdmin(admin.ModelAdmin):
    list_display = ("decision", "outcome", "heard_by", "heard_at", "created_at")
    list_filter = ("outcome",)
