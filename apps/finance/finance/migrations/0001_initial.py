import datetime
import django.db.models.deletion
import uuid
from decimal import Decimal
from django.conf import settings
from django.db import migrations, models

from apps.infrastructure.core.migrations._rls_helpers import enable_rls


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("expenses", "0001_initial"),
        ("farms", "0001_initial"),
        ("flocks", "0002_rename_flocks_batch_org_status_idx_flocks_batc_org_id_96386e_idx_and_more"),
        ("tenants", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SalesRecord",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("sale_date", models.DateField(default=datetime.date.today)),
                ("product_type", models.CharField(
                    choices=[
                        ("eggs", "Eggs"),
                        ("live_birds", "Live Birds"),
                        ("spent_layers", "Spent Layers"),
                        ("manure", "Manure"),
                        ("other", "Other"),
                    ],
                    max_length=20,
                )),
                ("quantity", models.DecimalField(decimal_places=2, max_digits=10)),
                ("unit", models.CharField(
                    choices=[
                        ("crates", "Crates"),
                        ("birds", "Birds"),
                        ("kg", "Kilograms"),
                        ("bags", "Bags"),
                    ],
                    default="crates",
                    max_length=10,
                )),
                ("unit_price_kobo", models.IntegerField()),
                ("total_revenue_kobo", models.IntegerField()),
                ("buyer_name", models.CharField(blank=True, max_length=200)),
                ("notes", models.TextField(blank=True)),
                ("batch", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="sales",
                    to="flocks.batch",
                )),
                ("farm", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="+",
                    to="farms.farm",
                )),
                ("org", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="+",
                    to="tenants.organization",
                )),
                ("recorded_by", models.ForeignKey(
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="+",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                "db_table": "finance_salesrecord",
                "indexes": [
                    models.Index(fields=["org", "batch", "sale_date"], name="finance_sales_org_bt_date_idx"),
                ],
            },
        ),
        migrations.CreateModel(
            name="BatchFinancialSummary",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("total_revenue_kobo", models.IntegerField(default=0)),
                ("total_expenses_kobo", models.IntegerField(default=0)),
                ("gross_profit_kobo", models.IntegerField(default=0)),
                ("profit_margin_pct", models.DecimalField(decimal_places=2, default=Decimal("0"), max_digits=6)),
                ("cost_per_bird_kobo", models.IntegerField(default=0)),
                ("revenue_per_bird_kobo", models.IntegerField(default=0)),
                ("break_even_quantity", models.IntegerField(default=0)),
                ("roi_pct", models.DecimalField(decimal_places=2, default=Decimal("0"), max_digits=8)),
                ("last_updated", models.DateTimeField(auto_now=True)),
                ("batch", models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="financial_summary",
                    to="flocks.batch",
                )),
                ("org", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="+",
                    to="tenants.organization",
                )),
            ],
            options={
                "db_table": "finance_batchfinancialsummary",
            },
        ),
        *enable_rls("finance_salesrecord"),
        *enable_rls("finance_batchfinancialsummary"),
    ]
