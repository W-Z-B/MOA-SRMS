from django.contrib import admin

from fees.models import FeeCharge, FeeItem, Payment


@admin.register(FeeItem)
class FeeItemAdmin(admin.ModelAdmin):
    list_display = ("programme", "fee_type", "amount", "effective_from")
    list_filter = ("programme", "fee_type")


@admin.register(FeeCharge)
class FeeChargeAdmin(admin.ModelAdmin):
    list_display = ("student", "term", "fee_type", "amount", "due_date")
    list_filter = ("term", "fee_type")


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("student", "amount", "paid_on", "method", "reference")
    list_filter = ("method",)
