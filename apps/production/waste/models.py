import datetime
from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models

from apps.infrastructure.core.models import TenantAwareModel


WASTE_TYPE_CHOICES = [
    ("litter", "Litter"),
    ("dead_birds", "Dead Birds"),
    ("packaging", "Packaging"),
    ("feed_waste", "Feed Waste"),
    ("other", "Other"),
]

DISPOSAL_METHOD_CHOICES = [
    ("composting", "Composting"),
    ("burning", "Burning"),
    ("burial", "Burial"),
    ("collection", "Collection"),
]


class WasteLog(TenantAwareModel):
    batch = models.ForeignKey(
        "flocks.Batch",
        on_delete=models.PROTECT,
        related_name="waste_logs",
        null=True,
        blank=True,
    )
    farm = models.ForeignKey("farms.Farm", on_delete=models.PROTECT, related_name="+")
    record_date = models.DateField(default=datetime.date.today)
    waste_type = models.CharField(max_length=20, choices=WASTE_TYPE_CHOICES)
    quantity_kg = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    disposal_method = models.CharField(
        max_length=20,
        choices=DISPOSAL_METHOD_CHOICES,
        default="composting",
    )
    cost = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0")
    )
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "waste_wastelog"
        indexes = [
            models.Index(
                fields=["org", "farm", "record_date"],
                name="waste_log_org_farm_date_idx",
            )
        ]

    def __str__(self):
        return f"{self.record_date} — {self.get_waste_type_display()}: {self.quantity_kg} kg"
