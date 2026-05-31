from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import BillingPlan, CycleSubscription, PaymentRecord, PaystackWebhookLog


@admin.register(BillingPlan)
class BillingPlanAdmin(ModelAdmin):
    list_display = ["name", "plan_tier", "amount_kobo", "billing_interval", "is_active"]
    list_filter = ["plan_tier", "billing_interval", "is_active"]
    search_fields = ["name", "paystack_plan_code"]
    ordering = ["amount_kobo"]


@admin.register(CycleSubscription)
class CycleSubscriptionAdmin(ModelAdmin):
    list_display = ["org", "batch_id", "plan", "status", "activated_at", "deactivated_at"]
    list_filter = ["status"]
    search_fields = ["org__name", "paystack_subscription_code"]
    ordering = ["-created_at"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(PaymentRecord)
class PaymentRecordAdmin(ModelAdmin):
    list_display = ["org", "reference", "amount_kobo", "status", "channel", "paid_at"]
    list_filter = ["status", "channel"]
    search_fields = ["reference", "org__name", "paystack_transaction_id"]
    ordering = ["-created_at"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(PaystackWebhookLog)
class PaystackWebhookLogAdmin(ModelAdmin):
    list_display = ["event_type", "signature_valid", "processed", "received_at", "error"]
    list_filter = ["event_type", "signature_valid", "processed"]
    search_fields = ["event_type"]
    ordering = ["-received_at"]
    readonly_fields = ["event_type", "payload", "signature_valid", "processed", "error", "received_at"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
