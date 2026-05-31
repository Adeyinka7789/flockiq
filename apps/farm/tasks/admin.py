from django.contrib import admin

from .models import FarmTask, TaskTemplate


@admin.register(TaskTemplate)
class TaskTemplateAdmin(admin.ModelAdmin):
    list_display = ["name", "breed_applicable", "frequency", "cycle_day", "is_active"]
    list_filter = ["breed_applicable", "frequency", "is_active"]
    search_fields = ["name"]


@admin.register(FarmTask)
class FarmTaskAdmin(admin.ModelAdmin):
    list_display = ["title", "farm", "status", "priority", "due_date", "assigned_to"]
    list_filter = ["status", "priority"]
    search_fields = ["title"]
    readonly_fields = ["completed_at", "completed_by"]
