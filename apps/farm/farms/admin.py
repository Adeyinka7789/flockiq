from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import Farm, House


@admin.register(Farm)
class FarmAdmin(ModelAdmin):
    list_display = ["name", "org", "farm_type", "is_active", "created_at"]
    list_filter = ["farm_type", "is_active"]
    search_fields = ["name", "location"]
    readonly_fields = ["id", "created_at", "updated_at"]
    fieldsets = (
        ("Identity", {"fields": ("id", "name", "org", "farm_type")}),
        ("Location", {"fields": ("location", "latitude", "longitude")}),
        ("Status", {"fields": ("is_active", "notes")}),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )


@admin.register(House)
class HouseAdmin(ModelAdmin):
    list_display = ["name", "farm", "capacity", "house_type", "is_active"]
    list_filter = ["house_type", "is_active"]
    search_fields = ["name"]
    readonly_fields = ["id", "created_at", "updated_at"]
    fieldsets = (
        ("Identity", {"fields": ("id", "name", "org", "farm", "house_type")}),
        ("Capacity", {"fields": ("capacity",)}),
        ("Status", {"fields": ("is_active", "notes")}),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )
