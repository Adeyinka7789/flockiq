from django.contrib import admin

from .models import Batch, MortalityLog, StockReconciliation, WeightRecord


@admin.register(Batch)
class BatchAdmin(admin.ModelAdmin):
    list_display = ["batch_name", "bird_type", "status", "placement_date", "initial_count", "current_count"]
    list_filter = ["status", "bird_type"]
    search_fields = ["batch_name", "breed_name"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(MortalityLog)
class MortalityLogAdmin(admin.ModelAdmin):
    list_display = ["batch", "date", "count", "cause"]
    list_filter = ["cause"]
    search_fields = ["batch__batch_name"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(StockReconciliation)
class StockReconciliationAdmin(admin.ModelAdmin):
    list_display = ["batch", "date", "variance", "variance_pct", "is_flagged"]
    list_filter = ["is_flagged"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(WeightRecord)
class WeightRecordAdmin(admin.ModelAdmin):
    list_display = ["batch", "sample_date", "avg_weight_kg", "sample_size"]
    readonly_fields = ["created_at", "updated_at"]
