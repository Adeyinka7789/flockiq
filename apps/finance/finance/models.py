import datetime
from decimal import Decimal

from django.db import models

from apps.infrastructure.core.models import TenantAwareModel


class SalesRecord(TenantAwareModel):

    PRODUCT_TYPE_CHOICES = [
        ("eggs", "Eggs"),
        ("live_birds", "Live Birds"),
        ("spent_layers", "Spent Layers"),
        ("manure", "Manure"),
        ("other", "Other"),
    ]
    UNIT_CHOICES = [
        ("crates", "Crates"),
        ("birds", "Birds"),
        ("kg", "Kilograms"),
        ("bags", "Bags"),
    ]

    batch = models.ForeignKey(
        "flocks.Batch",
        on_delete=models.PROTECT,
        related_name="sales",
    )
    farm = models.ForeignKey(
        "farms.Farm",
        on_delete=models.PROTECT,
        related_name="+",
    )
    sale_date = models.DateField(default=datetime.date.today)
    product_type = models.CharField(max_length=20, choices=PRODUCT_TYPE_CHOICES)
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    unit = models.CharField(max_length=10, choices=UNIT_CHOICES, default="crates")
    unit_price_kobo = models.IntegerField()
    total_revenue_kobo = models.IntegerField()
    buyer_name = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)
    recorded_by = models.ForeignKey(
        "accounts.CustomUser",
        null=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        db_table = "finance_salesrecord"
        indexes = [
            models.Index(fields=["org", "batch", "sale_date"], name="finance_sales_org_bt_date_idx"),
        ]

    def __str__(self):
        return f"{self.sale_date} — {self.get_product_type_display()} ₦{self.total_revenue_naira:,.2f}"

    def save(self, *args, **kwargs):
        self.total_revenue_kobo = int(self.quantity * self.unit_price_kobo)
        super().save(*args, **kwargs)

    @property
    def total_revenue_naira(self):
        return self.total_revenue_kobo / 100

    @property
    def unit_price_naira(self):
        return self.unit_price_kobo / 100


class BatchFinancialSummary(TenantAwareModel):

    batch = models.OneToOneField(
        "flocks.Batch",
        on_delete=models.CASCADE,
        related_name="financial_summary",
    )
    total_revenue_kobo = models.IntegerField(default=0)
    total_expenses_kobo = models.IntegerField(default=0)
    gross_profit_kobo = models.IntegerField(default=0)
    profit_margin_pct = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    cost_per_bird_kobo = models.IntegerField(default=0)
    revenue_per_bird_kobo = models.IntegerField(default=0)
    break_even_quantity = models.IntegerField(default=0)
    roi_pct = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "finance_batchfinancialsummary"

    def __str__(self):
        return f"FinancialSummary — {self.batch}"

    @property
    def gross_profit_naira(self):
        return self.gross_profit_kobo / 100

    @property
    def total_revenue_naira(self):
        return self.total_revenue_kobo / 100

    @property
    def total_expenses_naira(self):
        return self.total_expenses_kobo / 100
