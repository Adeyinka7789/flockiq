import django.db.models.deletion
import uuid
from django.db import migrations, models

from apps.infrastructure.core.migrations._rls_helpers import enable_rls


class Migration(migrations.Migration):

    dependencies = [
        ("analytics", "0002_aidailybrief"),
        ("tenants", "0003_organization_grace_period_ends_at_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="FarmBaseline",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("bird_type", models.CharField(max_length=20)),
                ("breed_name", models.CharField(blank=True, max_length=100)),
                ("avg_fcr", models.DecimalField(blank=True, decimal_places=3, max_digits=5, null=True)),
                ("avg_mortality_rate", models.DecimalField(blank=True, decimal_places=3, max_digits=5, null=True)),
                ("avg_daily_gain_g", models.DecimalField(blank=True, decimal_places=2, max_digits=6, null=True)),
                ("avg_feed_per_bird_kg", models.DecimalField(blank=True, decimal_places=3, max_digits=6, null=True)),
                ("avg_water_per_bird_l", models.DecimalField(blank=True, decimal_places=3, max_digits=6, null=True)),
                ("best_fcr", models.DecimalField(blank=True, decimal_places=3, max_digits=5, null=True)),
                ("worst_fcr", models.DecimalField(blank=True, decimal_places=3, max_digits=5, null=True)),
                ("best_mortality_rate", models.DecimalField(blank=True, decimal_places=3, max_digits=5, null=True)),
                ("worst_mortality_rate", models.DecimalField(blank=True, decimal_places=3, max_digits=5, null=True)),
                ("batch_count", models.PositiveIntegerField(default=0)),
                ("last_updated", models.DateTimeField(auto_now=True)),
                ("org", models.ForeignKey(
                    db_index=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="+",
                    to="tenants.organization",
                )),
            ],
            options={
                "db_table": "analytics_farmbaseline",
            },
        ),
        migrations.AddIndex(
            model_name="farmbaseline",
            index=models.Index(
                fields=["org", "bird_type", "breed_name"],
                name="analytics_fb_org_bt_brd_idx",
            ),
        ),
        migrations.AlterUniqueTogether(
            name="farmbaseline",
            unique_together={("org", "bird_type", "breed_name")},
        ),
        *enable_rls("analytics_farmbaseline"),
    ]
