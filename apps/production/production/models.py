import datetime
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models

from apps.infrastructure.core.models import TenantAwareModel


class EggProductionLog(TenantAwareModel):
    batch = models.ForeignKey(
        "flocks.Batch",
        on_delete=models.PROTECT,
        related_name="egg_logs",
    )
    farm = models.ForeignKey("farms.Farm", on_delete=models.PROTECT, related_name="+")
    house = models.ForeignKey("farms.House", on_delete=models.PROTECT, related_name="+")
    record_date = models.DateField(default=datetime.date.today)

    total_eggs = models.IntegerField(validators=[MinValueValidator(0)])
    grade_a = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    grade_b = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    grade_c = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    broken = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    cracked = models.IntegerField(default=0, validators=[MinValueValidator(0)])

    hen_day_pct = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, editable=False
    )
    crates = models.DecimalField(
        max_digits=8, decimal_places=1, null=True, editable=False
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
        db_table = "production_eggproductionlog"
        unique_together = [("org", "batch", "record_date")]
        indexes = [
            models.Index(
                fields=["org", "batch", "record_date"],
                name="prod_egg_org_batch_date_idx",
            ),
            models.Index(
                fields=["org", "record_date"],
                name="prod_egg_org_date_idx",
            ),
        ]

    def clean(self):
        if self.batch_id:
            from apps.farm.flocks.models import Batch

            batch = (
                Batch.objects.unscoped().filter(id=self.batch_id, org_id=self.org_id).first()
            )
            if batch is None:
                raise ValidationError("EggProductionLog batch must belong to the same organisation.")
            if batch.bird_type != "layer":
                raise ValidationError(
                    "Egg production can only be logged for layer batches."
                )
            if batch.status != "active":
                raise ValidationError(
                    "Cannot log production on an inactive batch."
                )

        if self.total_eggs is not None:
            total_grades = (
                (self.grade_a or 0)
                + (self.grade_b or 0)
                + (self.grade_c or 0)
                + (self.broken or 0)
                + (self.cracked or 0)
            )
            if total_grades > 0 and total_grades != self.total_eggs:
                raise ValidationError(
                    f"Grade counts ({total_grades}) must equal total_eggs ({self.total_eggs})."
                )

        if self.record_date and self.record_date > datetime.date.today():
            raise ValidationError("Record date cannot be in the future.")

    def __str__(self):
        return f"{self.record_date} — {self.total_eggs} eggs"


class CrateInventory(TenantAwareModel):
    farm = models.ForeignKey("farms.Farm", on_delete=models.PROTECT, related_name="+")
    date = models.DateField(default=datetime.date.today)
    crates_produced = models.DecimalField(
        max_digits=8, decimal_places=1, default=Decimal("0.0")
    )
    crates_sold = models.DecimalField(
        max_digits=8, decimal_places=1, default=Decimal("0.0")
    )
    crates_balance = models.DecimalField(
        max_digits=8, decimal_places=1, default=Decimal("0.0")
    )

    class Meta:
        db_table = "production_crateinventory"
        unique_together = [("org", "farm", "date")]

    def __str__(self):
        return f"{self.date} — {self.crates_balance} crates balance"
