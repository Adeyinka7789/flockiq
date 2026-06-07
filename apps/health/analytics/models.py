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


class AIDailyBrief(TenantAwareModel):
    """
    Persisted daily AI brief per org.
    Replaces cache-only storage so we can
    build farm memory from historical briefs.
    """
    org = models.ForeignKey(
        'tenants.Organization',
        on_delete=models.CASCADE,
        related_name='daily_briefs')
    generated_at = models.DateTimeField(auto_now_add=True)
    brief_date = models.DateField()

    overall_status = models.CharField(
        max_length=20,
        choices=[
            ('optimal', 'Optimal'),
            ('attention', 'Needs Attention'),
            ('critical', 'Critical'),
            ('warning', 'Warning'),
        ],
        default='optimal')
    headline = models.CharField(max_length=200)
    summary = models.TextField(blank=True)

    alerts = models.JSONField(default=list)
    recommendations = models.JSONField(default=list)
    patterns_detected = models.JSONField(default=list)
    metrics_snapshot = models.JSONField(default=dict)

    critical_count = models.IntegerField(default=0)
    warning_count = models.IntegerField(default=0)

    class Meta:
        ordering = ['-brief_date']
        unique_together = [['org', 'brief_date']]
        indexes = [
            models.Index(fields=['org', 'brief_date']),
        ]

    def __str__(self):
        return f'Brief {self.brief_date} — {self.overall_status}'


class FarmBaseline(TenantAwareModel):
    """
    Persisted, continuously-updated per-farm performance baseline.

    Computed from closed batches. Replaces the static breed benchmark
    as the comparison target once enough history exists. New farms with
    no history fall back to breed benchmarks (see FarmBaselineService).

    Units:
      - avg_mortality_rate / best_/worst_ are cumulative fractions per
        batch (total deaths / initial_count), e.g. 0.045 == 4.5%.
      - avg_fcr uses biomass = current_count * latest avg_weight_kg, the
        same definition as FeedEfficiencyService so the two compare cleanly.
    """

    bird_type = models.CharField(max_length=20)  # broiler / layer
    breed_name = models.CharField(max_length=100, blank=True)

    # Core performance metrics (farm's actual historical averages)
    avg_fcr = models.DecimalField(
        max_digits=5, decimal_places=3, null=True, blank=True
    )
    avg_mortality_rate = models.DecimalField(
        max_digits=5, decimal_places=3, null=True, blank=True
    )
    avg_daily_gain_g = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True
    )
    avg_feed_per_bird_kg = models.DecimalField(
        max_digits=6, decimal_places=3, null=True, blank=True
    )
    avg_water_per_bird_l = models.DecimalField(
        max_digits=6, decimal_places=3, null=True, blank=True
    )

    # Range awareness
    best_fcr = models.DecimalField(
        max_digits=5, decimal_places=3, null=True, blank=True
    )
    worst_fcr = models.DecimalField(
        max_digits=5, decimal_places=3, null=True, blank=True
    )
    best_mortality_rate = models.DecimalField(
        max_digits=5, decimal_places=3, null=True, blank=True
    )
    worst_mortality_rate = models.DecimalField(
        max_digits=5, decimal_places=3, null=True, blank=True
    )

    # Confidence
    batch_count = models.PositiveIntegerField(default=0)
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "analytics_farmbaseline"
        unique_together = [("org", "bird_type", "breed_name")]
        indexes = [
            models.Index(
                fields=["org", "bird_type", "breed_name"],
                name="analytics_fb_org_bt_brd_idx",
            ),
        ]

    def __str__(self):
        return f"Baseline {self.bird_type} {self.breed_name or 'any'} ({self.batch_count} batches)"

    @property
    def confidence_level(self):
        if self.batch_count >= 6:
            return "high"
        elif self.batch_count >= 3:
            return "medium"
        elif self.batch_count >= 1:
            return "low"
        return "none"

    @property
    def confidence_label(self):
        labels = {
            "high": f"Based on your last {self.batch_count} batches",
            "medium": f"Based on {self.batch_count} batches — improving",
            "low": "Early benchmark — based on 1 batch",
            "none": "No history yet — using breed benchmarks",
        }
        return labels[self.confidence_level]


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
