import datetime
import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models

from apps.infrastructure.core.migrations._rls_helpers import enable_rls, disable_rls


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("tenants", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="MarketPrice",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("date", models.DateField(default=datetime.date.today)),
                ("product_type", models.CharField(
                    choices=[
                        ("eggs", "Eggs"),
                        ("live_birds", "Live Birds"),
                        ("spent_layers", "Spent Layers"),
                        ("feed", "Feed"),
                    ],
                    max_length=20,
                )),
                ("price_per_unit_kobo", models.IntegerField()),
                ("unit", models.CharField(max_length=50)),
                ("market_name", models.CharField(max_length=200)),
                ("region", models.CharField(default="Lagos", max_length=100)),
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
                "db_table": "market_marketprice",
                "indexes": [
                    models.Index(fields=["org", "product_type", "date"], name="market_price_org_type_date_idx"),
                ],
            },
        ),
        migrations.CreateModel(
            name="SeasonalDemandIndex",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("month", models.IntegerField()),
                ("product_type", models.CharField(
                    choices=[("eggs", "Eggs"), ("live_birds", "Live Birds")],
                    max_length=20,
                )),
                ("demand_index", models.IntegerField()),
                ("notes", models.CharField(blank=True, max_length=300)),
            ],
            options={
                "db_table": "market_seasonaldemandindex",
                "unique_together": {("month", "product_type")},
            },
        ),
        *enable_rls("market_marketprice"),
        *disable_rls("market_seasonaldemandindex"),
    ]
