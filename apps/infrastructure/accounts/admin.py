from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from unfold.admin import ModelAdmin

from .models import CustomUser


@admin.register(CustomUser)
class CustomUserAdmin(ModelAdmin, UserAdmin):
    list_display = ["email", "role", "org", "is_active", "date_joined"]
    list_filter = ["role", "is_active"]
    search_fields = ["email", "first_name", "last_name"]
    ordering = ["email"]

    fieldsets = UserAdmin.fieldsets + (
        ("FlockIQ", {"fields": ("org", "role", "phone")}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("FlockIQ", {"fields": ("org", "role", "phone")}),
    )
