import uuid

import django.db.models.deletion
from django.db import migrations, models

from apps.infrastructure.core.migrations._rls_helpers import enable_rls


class Migration(migrations.Migration):

    dependencies = [
        ("finance", "0002_alter_profit_margin_pct_max_digits"),
        ("tenants", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="FarmCreditScore",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "org",
                    models.ForeignKey(
                        db_index=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="tenants.organization",
                    ),
                ),
                ("score", models.PositiveSmallIntegerField(help_text="0-100 credit score")),
                ("grade", models.CharField(max_length=2, help_text="A+/A/B/C/D/F")),
                (
                    "confidence",
                    models.CharField(
                        choices=[
                            ("early", "Early Profile"),
                            ("growing", "Growing Profile"),
                            ("established", "Established Profile"),
                        ],
                        max_length=20,
                    ),
                ),
                ("financial_health_score", models.PositiveSmallIntegerField()),
                ("operational_consistency_score", models.PositiveSmallIntegerField()),
                ("mortality_management_score", models.PositiveSmallIntegerField()),
                ("feed_efficiency_score", models.PositiveSmallIntegerField()),
                ("platform_engagement_score", models.PositiveSmallIntegerField()),
                ("payment_history_score", models.PositiveSmallIntegerField()),
                ("batches_analysed", models.PositiveSmallIntegerField()),
                ("avg_profit_margin_pct", models.DecimalField(blank=True, decimal_places=2, max_digits=6, null=True)),
                ("avg_mortality_rate_pct", models.DecimalField(blank=True, decimal_places=2, max_digits=6, null=True)),
                ("avg_fcr", models.DecimalField(blank=True, decimal_places=3, max_digits=5, null=True)),
                ("total_birds_managed", models.PositiveIntegerField(default=0)),
                ("months_on_platform", models.PositiveSmallIntegerField(default=0)),
                ("computed_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "finance_farmcreditscore",
                "ordering": ["-computed_at"],
            },
        ),
        *enable_rls("finance_farmcreditscore"),
    ]
