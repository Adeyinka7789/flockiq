import datetime

from django.db import models

from apps.infrastructure.core.models import TenantAwareModel


class MarketPrice(TenantAwareModel):

    PRODUCT_TYPE_CHOICES = [
        ("eggs", "Eggs"),
        ("live_birds", "Live Birds"),
        ("spent_layers", "Spent Layers"),
        ("feed", "Feed"),
    ]

    date = models.DateField(default=datetime.date.today)
    product_type = models.CharField(max_length=20, choices=PRODUCT_TYPE_CHOICES)
    price_per_unit_kobo = models.IntegerField()
    unit = models.CharField(max_length=50)
    market_name = models.CharField(max_length=200)
    region = models.CharField(max_length=100, default="Lagos")
    recorded_by = models.ForeignKey(
        "accounts.CustomUser",
        null=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        db_table = "market_marketprice"
        indexes = [
            models.Index(fields=["org", "product_type", "date"], name="market_price_org_type_date_idx"),
        ]

    def __str__(self):
        return f"{self.date} — {self.get_product_type_display()} @ ₦{self.price_per_unit_kobo / 100:,.2f}/{self.unit}"

    @property
    def price_per_unit_naira(self):
        return self.price_per_unit_kobo / 100


class SeasonalDemandIndex(models.Model):
    """Global reference data — admin-managed, no RLS."""

    PRODUCT_TYPE_CHOICES = [
        ("eggs", "Eggs"),
        ("live_birds", "Live Birds"),
    ]

    month = models.IntegerField()
    product_type = models.CharField(max_length=20, choices=PRODUCT_TYPE_CHOICES)
    demand_index = models.IntegerField()
    notes = models.CharField(max_length=300, blank=True)

    class Meta:
        db_table = "market_seasonaldemandindex"
        unique_together = [("month", "product_type")]

    def __str__(self):
        return f"Month {self.month} — {self.get_product_type_display()} index={self.demand_index}"
