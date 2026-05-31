from rest_framework import serializers

from .models import AnomalyRecord, ForecastResult, SaleTimingRecommendation, TheftFlag


class AnomalyRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = AnomalyRecord
        fields = [
            "id",
            "batch",
            "detected_at",
            "anomaly_type",
            "severity",
            "z_score",
            "description",
            "resolved",
            "resolved_at",
        ]
        read_only_fields = fields


class ForecastResultSerializer(serializers.ModelSerializer):
    class Meta:
        model = ForecastResult
        fields = [
            "id",
            "batch",
            "forecast_type",
            "forecast_date",
            "predicted_value",
            "confidence_lower",
            "confidence_upper",
            "generated_at",
        ]
        read_only_fields = fields


class TheftFlagSerializer(serializers.ModelSerializer):
    class Meta:
        model = TheftFlag
        fields = [
            "id",
            "batch",
            "flagged_at",
            "unaccounted_birds",
            "variance_pct",
            "initial_count",
            "total_mortality",
            "total_sold",
            "current_count",
            "resolved",
            "resolved_note",
        ]
        read_only_fields = fields


class SaleTimingSerializer(serializers.ModelSerializer):
    class Meta:
        model = SaleTimingRecommendation
        fields = [
            "id",
            "batch",
            "recommended_sale_date",
            "urgency",
            "estimated_weight_kg",
            "estimated_profit_kobo",
            "daily_holding_cost_kobo",
            "message",
            "generated_at",
        ]
        read_only_fields = fields
