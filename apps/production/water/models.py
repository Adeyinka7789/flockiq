import datetime

from django.core.validators import MinValueValidator
from django.db import models

from apps.infrastructure.core.models import TenantAwareModel


class WaterLog(TenantAwareModel):
    batch = models.ForeignKey(
        "flocks.Batch",
        on_delete=models.PROTECT,
        related_name="water_logs",
    )
    farm = models.ForeignKey("farms.Farm", on_delete=models.PROTECT, related_name="+")
    record_date = models.DateField(default=datetime.date.today)
    litres_consumed = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        validators=[MinValueValidator(0)],
    )
    requirement_litres = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True, editable=False
    )
    variance_litres = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True, editable=False
    )
    anomaly_flagged = models.BooleanField(default=False)
    recorded_by = models.ForeignKey(
        "accounts.CustomUser",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "water_waterlog"
        unique_together = [("org", "batch", "record_date")]
        indexes = [
            models.Index(
                fields=["org", "batch", "record_date"],
                name="water_log_org_batch_date_idx",
            )
        ]

    def __str__(self):
        flag = " ⚠" if self.anomaly_flagged else ""
        return f"{self.record_date} — {self.litres_consumed} L{flag}"
