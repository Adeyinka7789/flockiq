from django.db import models

from apps.infrastructure.core.models import TenantAwareModel


class ForecastResult(TenantAwareModel):
    FORECAST_TYPE_CHOICES = [
        ("egg", "Egg Production"),
        ("mortality", "Mortality"),
        ("feed", "Feed Consumption"),
    ]

    batch = models.ForeignKey(
        "flocks.Batch", on_delete=models.CASCADE, related_name="forecasts"
    )
    forecast_type = models.CharField(max_length=20, choices=FORECAST_TYPE_CHOICES)
    forecast_date = models.DateField()
    predicted_value = models.DecimalField(max_digits=10, decimal_places=2)
    confidence_lower = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    confidence_upper = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "analytics_forecastresult"
        indexes = [
            models.Index(
                fields=["org", "batch", "forecast_type", "forecast_date"],
                name="analytics_fcst_idx",
            ),
        ]

    def __str__(self):
        return f"{self.forecast_type} forecast for {self.forecast_date}"


class AnomalyRecord(TenantAwareModel):
    ANOMALY_TYPE_CHOICES = [
        ("mortality_spike", "Mortality Spike"),
        ("water_drop", "Water Drop"),
        ("production_drop", "Production Drop"),
        ("weight_deviation", "Weight Deviation"),
    ]
    SEVERITY_CHOICES = [
        ("info", "Info"),
        ("warning", "Warning"),
        ("critical", "Critical"),
    ]

    batch = models.ForeignKey(
        "flocks.Batch", on_delete=models.CASCADE, related_name="anomalies"
    )
    detected_at = models.DateTimeField(auto_now_add=True)
    anomaly_type = models.CharField(max_length=30, choices=ANOMALY_TYPE_CHOICES)
    severity = models.CharField(max_length=10, choices=SEVERITY_CHOICES)
    z_score = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True)
    description = models.CharField(max_length=300)
    resolved = models.BooleanField(default=False)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "analytics_anomalyrecord"
        indexes = [
            models.Index(
                fields=["org", "batch", "resolved"],
                name="analytics_anom_org_bt_res_idx",
            ),
        ]

    def __str__(self):
        return f"{self.anomaly_type} ({self.severity})"


class SaleTimingRecommendation(TenantAwareModel):
    URGENCY_CHOICES = [
        ("wait", "Wait"),
        ("now", "Now"),
        ("urgent", "Urgent"),
    ]

    batch = models.ForeignKey(
        "flocks.Batch", on_delete=models.CASCADE, related_name="sale_recommendations"
    )
    recommended_sale_date = models.DateField(null=True, blank=True)
    urgency = models.CharField(max_length=10, choices=URGENCY_CHOICES, default="wait")
    estimated_weight_kg = models.DecimalField(
        max_digits=6, decimal_places=3, null=True, blank=True
    )
    estimated_profit_kobo = models.IntegerField(null=True, blank=True)
    daily_holding_cost_kobo = models.IntegerField(null=True, blank=True)
    message = models.TextField()
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "analytics_saletimingresult"

    def __str__(self):
        return f"{self.urgency} recommendation for batch"


class TheftFlag(TenantAwareModel):
    batch = models.ForeignKey(
        "flocks.Batch", on_delete=models.CASCADE, related_name="theft_flags"
    )
    flagged_at = models.DateTimeField(auto_now_add=True)
    unaccounted_birds = models.IntegerField()
    variance_pct = models.DecimalField(max_digits=5, decimal_places=2)
    initial_count = models.IntegerField()
    total_mortality = models.IntegerField()
    total_sold = models.IntegerField()
    current_count = models.IntegerField()
    resolved = models.BooleanField(default=False)
    resolved_note = models.TextField(blank=True)

    class Meta:
        db_table = "analytics_theftflag"

    def __str__(self):
        return f"TheftFlag — {self.unaccounted_birds} unaccounted birds"
