from django.contrib import admin

from .models import AnomalyRecord, ForecastResult, SaleTimingRecommendation, TheftFlag


@admin.register(ForecastResult)
class ForecastResultAdmin(admin.ModelAdmin):
    list_display = ["batch", "forecast_type", "forecast_date", "predicted_value", "generated_at"]
    list_filter = ["forecast_type"]
    readonly_fields = ["generated_at"]


@admin.register(AnomalyRecord)
class AnomalyRecordAdmin(admin.ModelAdmin):
    list_display = ["batch", "anomaly_type", "severity", "z_score", "resolved", "detected_at"]
    list_filter = ["anomaly_type", "severity", "resolved"]
    readonly_fields = ["detected_at"]


@admin.register(SaleTimingRecommendation)
class SaleTimingRecommendationAdmin(admin.ModelAdmin):
    list_display = ["batch", "urgency", "recommended_sale_date", "generated_at"]
    list_filter = ["urgency"]
    readonly_fields = ["generated_at"]


@admin.register(TheftFlag)
class TheftFlagAdmin(admin.ModelAdmin):
    list_display = ["batch", "unaccounted_birds", "variance_pct", "resolved", "flagged_at"]
    list_filter = ["resolved"]
    readonly_fields = ["flagged_at"]
