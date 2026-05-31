from django.contrib import admin

from .models import WasteLog


@admin.register(WasteLog)
class WasteLogAdmin(admin.ModelAdmin):
    list_display = ["farm", "record_date", "waste_type", "quantity_kg", "disposal_method", "cost"]
    list_filter = ["waste_type", "disposal_method"]
    search_fields = ["farm__name"]
    readonly_fields = ["created_at", "updated_at"]
