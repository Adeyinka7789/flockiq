from django.contrib import admin

from .models import FeedLog, FeedStock


@admin.register(FeedLog)
class FeedLogAdmin(admin.ModelAdmin):
    list_display = ["batch", "record_date", "feed_type", "quantity_kg", "requirement_kg", "variance_kg", "total_cost"]
    list_filter = ["feed_type"]
    search_fields = ["batch__batch_name"]
    readonly_fields = ["requirement_kg", "variance_kg", "total_cost", "created_at", "updated_at"]


@admin.register(FeedStock)
class FeedStockAdmin(admin.ModelAdmin):
    list_display = ["farm", "feed_type", "quantity_kg", "low_stock_threshold_kg", "updated_at"]
    list_filter = ["feed_type"]
    search_fields = ["farm__name"]
    readonly_fields = ["created_at", "updated_at"]
