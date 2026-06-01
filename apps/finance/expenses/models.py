import datetime

from django.db import models

from apps.infrastructure.core.models import TenantAwareModel


class ExpenseRecord(TenantAwareModel):

    CATEGORY_CHOICES = [
        ("feed", "Feed"),
        ("medication", "Medication"),
        ("labour", "Labour"),
        ("utilities", "Utilities"),
        ("equipment", "Equipment"),
        ("chicks", "Chicks / Day-Old Birds"),
        ("transport", "Transport"),
        ("veterinary", "Veterinary"),
        ("packaging", "Packaging"),
        ("other", "Other"),
    ]

    batch = models.ForeignKey(
        "flocks.Batch",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="expenses",
    )
    farm = models.ForeignKey(
        "farms.Farm",
        on_delete=models.PROTECT,
        related_name="+",
    )
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    amount_kobo = models.IntegerField()
    description = models.CharField(max_length=300)
    expense_date = models.DateField(default=datetime.date.today)
    receipt_ref = models.CharField(max_length=100, blank=True)
    recorded_by = models.ForeignKey(
        "accounts.CustomUser",
        null=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "expenses_expenserecord"
        indexes = [
            models.Index(fields=["org", "farm", "expense_date"], name="expenses_rec_org_farm_date_idx"),
            models.Index(fields=["org", "batch", "category"], name="expenses_rec_org_batch_cat_idx"),
        ]

    def __str__(self):
        return f"{self.expense_date} — {self.get_category_display()} ₦{self.amount_naira:,.2f}"

    @property
    def amount_naira(self):
        return self.amount_kobo / 100
