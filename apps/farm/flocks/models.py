import datetime

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from apps.infrastructure.core.models import TenantAwareModel


class Batch(TenantAwareModel):
    """A single production cycle — the heartbeat of everything in FlockIQ."""

    class BirdType(models.TextChoices):
        LAYER = "layer", "Layer"
        BROILER = "broiler", "Broiler"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        CLOSED = "closed", "Closed"
        CULLED = "culled", "Culled"

    farm = models.ForeignKey(
        "farms.Farm",
        on_delete=models.PROTECT,
        related_name="batches",
    )
    house = models.ForeignKey(
        "farms.House",
        on_delete=models.PROTECT,
        related_name="batches",
    )
    batch_name = models.CharField(max_length=100)
    breed_name = models.CharField(max_length=100, blank=True)
    bird_type = models.CharField(
        max_length=10,
        choices=BirdType.choices,
        default=BirdType.BROILER,
    )
    placement_date = models.DateField()
    initial_count = models.IntegerField(validators=[MinValueValidator(1)])
    current_count = models.IntegerField(validators=[MinValueValidator(0)])
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    # ── DOC sourcing ──────────────────────────────────────────────────────────
    hatchery = models.ForeignKey(
        "market.Hatchery",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="batches",
        help_text="Hatchery where DOCs were purchased",
    )
    doc_price_per_chick = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Price paid per day-old chick in Naira",
    )
    doc_supplier_name = models.CharField(
        max_length=200,
        blank=True,
        help_text="Hatchery name if not in directory",
    )

    class Meta:
        db_table = "flocks_batch"
        unique_together = [("org", "farm", "id")]
        indexes = [
            models.Index(fields=["org", "status"]),
            models.Index(fields=["org", "farm", "status"]),
        ]

    def __str__(self):
        return f"{self.batch_name} ({self.get_bird_type_display()})"

    def save(self, *args, **kwargs):
        if self.house_id and self.org_id:
            from apps.farm.farms.models import House as _House
            house_org_id = (
                _House.objects.unscoped()
                .filter(id=self.house_id)
                .values_list("org_id", flat=True)
                .first()
            )
            if house_org_id != self.org_id:
                raise ValidationError("Batch house must belong to the same organisation.")

        if self.farm_id and self.org_id:
            from apps.farm.farms.models import Farm as _Farm
            farm_org_id = (
                _Farm.objects.unscoped()
                .filter(id=self.farm_id)
                .values_list("org_id", flat=True)
                .first()
            )
            if farm_org_id != self.org_id:
                raise ValidationError("Batch farm must belong to the same organisation.")

        if self.current_count is not None and self.initial_count is not None:
            if self.current_count > self.initial_count:
                raise ValueError("current_count cannot exceed initial_count.")
            if self.current_count < 0:
                raise ValueError("current_count cannot go below 0.")

        super().save(*args, **kwargs)

    # ── Computed properties ────────────────────────────────────────────────

    @property
    def cycle_day(self):
        return (datetime.date.today() - self.placement_date).days

    @property
    def age_weeks(self):
        return self.cycle_day // 7

    @property
    def is_active(self):
        return self.status == self.Status.ACTIVE

    @property
    def mortality_to_date(self):
        return self.initial_count - self.current_count

    @property
    def mortality_rate_pct(self):
        if not self.initial_count:
            return 0.0
        return round(self.mortality_to_date / self.initial_count * 100, 2)


class MortalityLog(TenantAwareModel):
    """A single mortality event for a batch."""

    class Cause(models.TextChoices):
        DISEASE = "disease", "Disease"
        ACCIDENT = "accident", "Accident"
        CULLING = "culling", "Culling"
        UNKNOWN = "unknown", "Unknown"
        THEFT = "theft", "Theft"

    batch = models.ForeignKey(
        Batch,
        on_delete=models.PROTECT,
        related_name="mortality_logs",
    )
    farm = models.ForeignKey(
        "farms.Farm",
        on_delete=models.PROTECT,
        related_name="+",
    )
    date = models.DateField(default=datetime.date.today)
    count = models.IntegerField(validators=[MinValueValidator(1)])
    cause = models.CharField(
        max_length=10,
        choices=Cause.choices,
        default=Cause.UNKNOWN,
    )
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "flocks_mortalitylog"
        indexes = [
            models.Index(fields=["org", "batch", "date"]),
            models.Index(fields=["org", "date"]),
        ]

    def __str__(self):
        return f"{self.date} — {self.count} ({self.get_cause_display()})"

    def save(self, *args, **kwargs):
        from apps.farm.flocks.exceptions import BatchClosedError

        if self.batch_id:
            batch_status = (
                Batch.objects.unscoped()
                .filter(id=self.batch_id, org_id=self.org_id)
                .values_list("status", flat=True)
                .first()
            )
            if batch_status is None:
                raise ValidationError("MortalityLog batch must belong to the same organisation.")
            if batch_status != "active":
                raise BatchClosedError(
                    f"Cannot log mortality on a {batch_status} batch."
                )

        if self.farm_id and self.org_id:
            from apps.farm.farms.models import Farm as _Farm
            farm_org_id = (
                _Farm.objects.unscoped()
                .filter(id=self.farm_id)
                .values_list("org_id", flat=True)
                .first()
            )
            if farm_org_id != self.org_id:
                raise ValidationError("MortalityLog farm must belong to the same organisation.")

        super().save(*args, **kwargs)


class StockReconciliation(TenantAwareModel):
    """Periodic stock count check — flags discrepancies that may indicate theft."""

    batch = models.ForeignKey(
        Batch,
        on_delete=models.PROTECT,
        related_name="reconciliations",
    )
    date = models.DateField()
    expected_count = models.IntegerField()
    actual_count = models.IntegerField()
    variance = models.IntegerField()
    variance_pct = models.DecimalField(max_digits=5, decimal_places=2)
    is_flagged = models.BooleanField(default=False)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "flocks_stockreconciliation"
        unique_together = [("org", "batch", "date")]

    def __str__(self):
        flag = " ⚠️" if self.is_flagged else ""
        return f"{self.date} — variance {self.variance}{flag}"


class WeightRecord(TenantAwareModel):
    """Sample weight measurement for a broiler batch."""

    batch = models.ForeignKey(
        Batch,
        on_delete=models.PROTECT,
        related_name="weight_records",
    )
    sample_date = models.DateField()
    sample_size = models.IntegerField(validators=[MinValueValidator(1)])
    avg_weight_kg = models.DecimalField(max_digits=6, decimal_places=3)
    min_weight_kg = models.DecimalField(
        max_digits=6, decimal_places=3, null=True, blank=True
    )
    max_weight_kg = models.DecimalField(
        max_digits=6, decimal_places=3, null=True, blank=True
    )
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "flocks_weightrecord"
        indexes = [
            models.Index(fields=["org", "batch", "sample_date"]),
        ]

    def __str__(self):
        return f"{self.sample_date} — {self.avg_weight_kg} kg avg"
