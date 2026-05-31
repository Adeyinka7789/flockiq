from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import Organization


@admin.register(Organization)
class OrganizationAdmin(ModelAdmin):
    list_display = [
        "name", "subdomain", "plan_tier",
        "subscription_status", "is_active", "created_at",
    ]
    list_filter = ["plan_tier", "subscription_status", "is_active"]
    search_fields = ["name", "subdomain", "owner_email"]
    readonly_fields = ["id", "created_at", "updated_at"]
    fieldsets = (
        ("Identity", {"fields": ("id", "name", "subdomain", "logo", "primary_colour")}),
        ("Subscription", {"fields": ("plan_tier", "subscription_status", "trial_ends_at")}),
        ("Contact", {"fields": ("owner_name", "owner_phone", "owner_email")}),
        ("Settings", {"fields": ("settings", "is_active")}),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )
