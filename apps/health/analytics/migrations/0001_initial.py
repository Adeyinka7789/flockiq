import django.db.models.deletion
import uuid
from django.db import migrations, models

from apps.infrastructure.core.migrations._rls_helpers import enable_rls


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("flocks", "0002_rename_flocks_batch_org_status_idx_flocks_batc_org_id_96386e_idx_and_more"),
        ("tenants", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="ForecastResult",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("forecast_type", models.CharField(
                    choices=[("egg", "Egg Production"), ("mortality", "Mortality"), ("feed", "Feed Consumption")],
                    max_length=20,
                )),
                ("forecast_date", models.DateField()),
                ("predicted_value", models.DecimalField(decimal_places=2, max_digits=10)),
                ("confidence_lower", models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True)),
                ("confidence_upper", models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True)),
                ("generated_at", models.DateTimeField(auto_now_add=True)),
                ("batch", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="forecasts",
                    to="flocks.batch",
                )),
                ("org", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="+",
                    to="tenants.organization",
                )),
            ],
            options={"db_table": "analytics_forecastresult"},
        ),
        migrations.AddIndex(
            model_name="forecastresult",
            index=models.Index(
                fields=["org", "batch", "forecast_type", "forecast_date"],
                name="analytics_fcst_idx",
            ),
        ),
        migrations.CreateModel(
            name="AnomalyRecord",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("detected_at", models.DateTimeField(auto_now_add=True)),
                ("anomaly_type", models.CharField(
                    choices=[
                        ("mortality_spike", "Mortality Spike"),
                        ("water_drop", "Water Drop"),
                        ("production_drop", "Production Drop"),
                        ("weight_deviation", "Weight Deviation"),
                    ],
                    max_length=30,
                )),
                ("severity", models.CharField(
                    choices=[("info", "Info"), ("warning", "Warning"), ("critical", "Critical")],
                    max_length=10,
                )),
                ("z_score", models.DecimalField(blank=True, decimal_places=3, max_digits=6, null=True)),
                ("description", models.CharField(max_length=300)),
                ("resolved", models.BooleanField(default=False)),
                ("resolved_at", models.DateTimeField(blank=True, null=True)),
                ("batch", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="anomalies",
                    to="flocks.batch",
                )),
                ("org", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="+",
                    to="tenants.organization",
                )),
            ],
            options={"db_table": "analytics_anomalyrecord"},
        ),
        migrations.AddIndex(
            model_name="anomalyrecord",
            index=models.Index(
                fields=["org", "batch", "resolved"],
                name="analytics_anom_org_bt_res_idx",
            ),
        ),
        migrations.CreateModel(
            name="SaleTimingRecommendation",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("recommended_sale_date", models.DateField(blank=True, null=True)),
                ("urgency", models.CharField(
                    choices=[("wait", "Wait"), ("now", "Now"), ("urgent", "Urgent")],
                    default="wait",
                    max_length=10,
                )),
                ("estimated_weight_kg", models.DecimalField(blank=True, decimal_places=3, max_digits=6, null=True)),
                ("estimated_profit_kobo", models.IntegerField(blank=True, null=True)),
                ("daily_holding_cost_kobo", models.IntegerField(blank=True, null=True)),
                ("message", models.TextField()),
                ("generated_at", models.DateTimeField(auto_now_add=True)),
                ("batch", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="sale_recommendations",
                    to="flocks.batch",
                )),
                ("org", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="+",
                    to="tenants.organization",
                )),
            ],
            options={"db_table": "analytics_saletimingresult"},
        ),
        migrations.CreateModel(
            name="TheftFlag",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("flagged_at", models.DateTimeField(auto_now_add=True)),
                ("unaccounted_birds", models.IntegerField()),
                ("variance_pct", models.DecimalField(decimal_places=2, max_digits=5)),
                ("initial_count", models.IntegerField()),
                ("total_mortality", models.IntegerField()),
                ("total_sold", models.IntegerField()),
                ("current_count", models.IntegerField()),
                ("resolved", models.BooleanField(default=False)),
                ("resolved_note", models.TextField(blank=True)),
                ("batch", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="theft_flags",
                    to="flocks.batch",
                )),
                ("org", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="+",
                    to="tenants.organization",
                )),
            ],
            options={"db_table": "analytics_theftflag"},
        ),
        *enable_rls("analytics_forecastresult"),
        *enable_rls("analytics_anomalyrecord"),
        *enable_rls("analytics_saletimingresult"),
        *enable_rls("analytics_theftflag"),
    ]
