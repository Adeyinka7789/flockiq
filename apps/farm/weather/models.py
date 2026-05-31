import uuid

from django.db import models

from apps.infrastructure.core.models import TenantAwareModel


class WeatherCache(models.Model):
    """Cross-tenant weather data cache. RLS DISABLED — read by Celery workers globally."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    farm_id = models.UUIDField(db_index=True, unique=True)
    lat = models.DecimalField(max_digits=10, decimal_places=7)
    lng = models.DecimalField(max_digits=10, decimal_places=7)
    data = models.JSONField(default=dict)
    fetched_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "weather_cache"

    def __str__(self):
        return f"WeatherCache farm={self.farm_id}"


class WeatherAlert(TenantAwareModel):
    """A weather-driven alert for a specific farm. Tenant-scoped with RLS."""

    class AlertType(models.TextChoices):
        HEAT_STRESS = "heat_stress", "Heat Stress"
        HIGH_HUMIDITY = "high_humidity", "High Humidity"
        HEAVY_RAIN = "heavy_rain", "Heavy Rain"

    class Severity(models.TextChoices):
        INFO = "info", "Info"
        WARNING = "warning", "Warning"
        CRITICAL = "critical", "Critical"

    farm = models.ForeignKey(
        "farms.Farm",
        on_delete=models.CASCADE,
        related_name="weather_alerts",
    )
    alert_type = models.CharField(max_length=20, choices=AlertType.choices)
    severity = models.CharField(max_length=10, choices=Severity.choices)
    temperature = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    humidity = models.IntegerField(null=True, blank=True)
    description = models.CharField(max_length=300)
    acknowledged_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "weather_weatheralert"
        indexes = [
            models.Index(
                fields=["org", "acknowledged_at", "created_at"],
                name="weather_alert_org_ack_idx",
            ),
        ]

    def __str__(self):
        return f"{self.get_alert_type_display()} at {self.farm} ({self.severity})"
