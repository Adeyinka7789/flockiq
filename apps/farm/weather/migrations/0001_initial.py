import uuid

import django.db.models.deletion
from django.db import migrations, models

from apps.infrastructure.core.migrations._rls_helpers import disable_rls, enable_rls


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("farms", "0001_initial"),
        ("tenants", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="WeatherCache",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("farm_id", models.UUIDField(db_index=True, unique=True)),
                ("lat", models.DecimalField(decimal_places=7, max_digits=10)),
                ("lng", models.DecimalField(decimal_places=7, max_digits=10)),
                ("data", models.JSONField(default=dict)),
                ("fetched_at", models.DateTimeField(auto_now=True)),
            ],
            options={"db_table": "weather_cache"},
        ),
        migrations.CreateModel(
            name="WeatherAlert",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("alert_type", models.CharField(
                    choices=[
                        ("heat_stress", "Heat Stress"),
                        ("high_humidity", "High Humidity"),
                        ("heavy_rain", "Heavy Rain"),
                    ],
                    max_length=20,
                )),
                ("severity", models.CharField(
                    choices=[("info", "Info"), ("warning", "Warning"), ("critical", "Critical")],
                    max_length=10,
                )),
                ("temperature", models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True)),
                ("humidity", models.IntegerField(blank=True, null=True)),
                ("description", models.CharField(max_length=300)),
                ("acknowledged_at", models.DateTimeField(blank=True, null=True)),
                ("farm", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="weather_alerts",
                    to="farms.farm",
                )),
                ("org", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="+",
                    to="tenants.organization",
                )),
            ],
            options={"db_table": "weather_weatheralert"},
        ),
        migrations.AddIndex(
            model_name="weatheralert",
            index=models.Index(
                fields=["org", "acknowledged_at", "created_at"],
                name="weather_alert_org_ack_idx",
            ),
        ),
        # WeatherCache is cross-tenant infrastructure — RLS disabled
        *disable_rls("weather_cache"),
        # WeatherAlert is tenant-scoped — RLS enabled
        *enable_rls("weather_weatheralert"),
    ]
