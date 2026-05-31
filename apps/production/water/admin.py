from django.contrib import admin

from .models import WaterLog


@admin.register(WaterLog)
class WaterLogAdmin(admin.ModelAdmin):
    list_display = ["batch", "record_date", "litres_consumed", "requirement_litres", "variance_litres", "anomaly_flagged"]
    list_filter = ["anomaly_flagged"]
    search_fields = ["batch__batch_name"]
    readonly_fields = ["requirement_litres", "variance_litres", "created_at", "updated_at"]
