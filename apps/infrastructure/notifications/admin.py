from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import AlertRule, NotificationLog, OutboxEvent


@admin.register(AlertRule)
class AlertRuleAdmin(ModelAdmin):
    list_display = ["org", "event_type", "channels", "notify_roles", "min_severity", "is_active", "cooldown_minutes"]
    list_filter = ["event_type", "min_severity", "is_active"]
    search_fields = ["org__name", "event_type"]
    ordering = ["org", "event_type"]


@admin.register(OutboxEvent)
class OutboxEventAdmin(ModelAdmin):
    list_display = ["event_type", "channel", "status", "attempts", "org_id", "created_at", "last_attempted_at"]
    list_filter = ["status", "channel", "event_type"]
    search_fields = ["event_type", "recipient_email", "idempotency_key"]
    ordering = ["-created_at"]
    readonly_fields = [
        "id", "org_id", "recipient_user_id", "idempotency_key",
        "created_at", "delivered_at", "last_attempted_at",
    ]


@admin.register(NotificationLog)
class NotificationLogAdmin(ModelAdmin):
    list_display = ["title", "event_type", "severity", "channel", "recipient", "is_read", "created_at"]
    list_filter = ["event_type", "severity", "channel", "is_read"]
    search_fields = ["title", "recipient__email"]
    ordering = ["-created_at"]
    readonly_fields = ["id", "created_at", "read_at", "outbox_event_id"]
