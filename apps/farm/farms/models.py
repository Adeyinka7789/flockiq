from django.core.exceptions import ValidationError
from django.db import models

from apps.infrastructure.core.managers import ActiveManager, AllObjectsManager
from apps.infrastructure.core.models import SoftDeleteMixin, TenantAwareModel

# Nigeria bounding box
_LAT_MIN, _LAT_MAX = 4.0, 14.0
_LNG_MIN, _LNG_MAX = 2.7, 15.0


class Farm(SoftDeleteMixin, TenantAwareModel):
    """A physical poultry farm location owned by one tenant."""

    objects = ActiveManager()
    all_objects = AllObjectsManager()

    class FarmType(models.TextChoices):
        LAYER = "layer", "Layer"
        BROILER = "broiler", "Broiler"
        MIXED = "mixed", "Mixed"

    name = models.CharField(max_length=200)
    location = models.CharField(max_length=300)
    latitude = models.DecimalField(max_digits=10, decimal_places=7)
    longitude = models.DecimalField(max_digits=10, decimal_places=7)
    farm_type = models.CharField(
        max_length=10,
        choices=FarmType.choices,
        default=FarmType.MIXED,
    )
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "farms_farm"
        unique_together = [("org", "id")]
        indexes = [
            models.Index(fields=["org", "is_active"]),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        if self.latitude is not None and not (_LAT_MIN <= float(self.latitude) <= _LAT_MAX):
            raise ValidationError(
                {"latitude": f"Latitude must be between {_LAT_MIN} and {_LAT_MAX} (Nigeria bounding box)."}
            )
        if self.longitude is not None and not (_LNG_MIN <= float(self.longitude) <= _LNG_MAX):
            raise ValidationError(
                {"longitude": f"Longitude must be between {_LNG_MIN} and {_LNG_MAX} (Nigeria bounding box)."}
            )

    @property
    def active_batch_count(self):
        try:
            return (
                self.houses
                .filter(batches__status="active")
                .values("batches__id")
                .distinct()
                .count()
            )
        except Exception:
            return 0

    @property
    def total_live_birds(self):
        try:
            from django.db.models import Sum
            return (
                self.houses
                .filter(batches__status="active")
                .aggregate(total=Sum("batches__current_count"))["total"]
                or 0
            )
        except Exception:
            return 0


class House(SoftDeleteMixin, TenantAwareModel):
    """A poultry house within a farm."""

    objects = ActiveManager()
    all_objects = AllObjectsManager()

    class HouseType(models.TextChoices):
        LAYER = "layer", "Layer"
        BROILER = "broiler", "Broiler"
        MIXED = "mixed", "Mixed"

    farm = models.ForeignKey(Farm, on_delete=models.PROTECT, related_name="houses")
    name = models.CharField(max_length=100)
    capacity = models.IntegerField()
    house_type = models.CharField(
        max_length=10,
        choices=HouseType.choices,
        default=HouseType.MIXED,
    )
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "farms_house"
        unique_together = [("org", "farm", "id")]
        indexes = [
            models.Index(fields=["org", "farm", "is_active"]),
        ]

    def __str__(self):
        return f"{self.farm.name} — {self.name}"

    def save(self, *args, **kwargs):
        if self.farm_id and self.org_id:
            farm_org_id = (
                Farm.objects.unscoped()
                .filter(id=self.farm_id)
                .values_list("org_id", flat=True)
                .first()
            )
            if farm_org_id != self.org_id:
                raise ValueError(
                    "Cross-tenant assignment: house farm must belong to the same organisation."
                )
        super().save(*args, **kwargs)

    @property
    def current_occupancy(self):
        try:
            batch = self.batches.filter(status="active").first()
            return batch.current_count if batch else 0
        except Exception:
            return 0

    @property
    def occupancy_pct(self):
        if not self.capacity:
            return 0.0
        return round(self.current_occupancy / self.capacity * 100, 1)
