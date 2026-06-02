import datetime
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models

from apps.infrastructure.core.models import TenantAwareModel


FEED_TYPE_CHOICES = [
    ("starter", "Starter"),
    ("grower", "Grower"),
    ("finisher", "Finisher"),
    ("layer_mash", "Layer Mash"),
    ("chick_mash", "Chick Mash"),
]


class FeedLog(TenantAwareModel):
    batch = models.ForeignKey(
        "flocks.Batch",
        on_delete=models.PROTECT,
        related_name="feed_logs",
    )
    farm = models.ForeignKey("farms.Farm", on_delete=models.PROTECT, related_name="+")
    record_date = models.DateField(default=datetime.date.today)
    feed_type = models.CharField(
        max_length=20,
        choices=FEED_TYPE_CHOICES,
        default="layer_mash",
    )
    quantity_kg = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    cost_per_kg = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    total_cost = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, editable=False
    )
    requirement_kg = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True, editable=False
    )
    variance_kg = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True, editable=False
    )
    recorded_by = models.ForeignKey(
        "accounts.CustomUser",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "feed_feedlog"
        unique_together = [("org", "batch", "record_date")]
        indexes = [
            models.Index(
                fields=["org", "batch", "record_date"],
                name="feed_log_org_batch_date_idx",
            )
        ]

    def clean(self):
        if self.batch_id:
            from apps.farm.flocks.models import Batch

            batch = Batch.objects.unscoped().filter(id=self.batch_id, org_id=self.org_id).first()
            if batch is None:
                raise ValidationError("FeedLog batch must belong to the same organisation.")
            if batch.status != "active":
                raise ValidationError("Cannot log feed for an inactive batch.")

        if self.quantity_kg is not None and self.quantity_kg <= 0:
            raise ValidationError("quantity_kg must be greater than 0.")

    def __str__(self):
        return f"{self.record_date} — {self.quantity_kg} kg {self.get_feed_type_display()}"


class FeedStock(TenantAwareModel):
    farm = models.ForeignKey("farms.Farm", on_delete=models.PROTECT, related_name="+")
    feed_type = models.CharField(max_length=20, choices=FEED_TYPE_CHOICES)
    quantity_kg = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0")
    )
    low_stock_threshold_kg = models.DecimalField(
        max_digits=8, decimal_places=2, default=Decimal("50")
    )

    class Meta:
        db_table = "feed_feedstock"
        unique_together = [("org", "farm", "feed_type")]

    @property
    def is_low_stock(self):
        return self.quantity_kg <= self.low_stock_threshold_kg

    def __str__(self):
        return f"{self.farm} — {self.get_feed_type_display()}: {self.quantity_kg} kg"
