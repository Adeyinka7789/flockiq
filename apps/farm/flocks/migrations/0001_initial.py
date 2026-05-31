import datetime
import uuid

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models

from apps.infrastructure.core.migrations._rls_helpers import enable_rls


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("farms", "0001_initial"),
        ("tenants", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Batch",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("batch_name", models.CharField(max_length=100)),
                ("breed_name", models.CharField(blank=True, max_length=100)),
                ("bird_type", models.CharField(
                    choices=[("layer", "Layer"), ("broiler", "Broiler")],
                    default="broiler",
                    max_length=10,
                )),
                ("placement_date", models.DateField()),
                ("initial_count", models.IntegerField(validators=[django.core.validators.MinValueValidator(1)])),
                ("current_count", models.IntegerField(validators=[django.core.validators.MinValueValidator(0)])),
                ("status", models.CharField(
                    choices=[("active", "Active"), ("closed", "Closed"), ("culled", "Culled")],
                    default="active",
                    max_length=10,
                )),
                ("closed_at", models.DateTimeField(blank=True, null=True)),
                ("notes", models.TextField(blank=True)),
                ("farm", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="batches",
                    to="farms.farm",
                )),
                ("house", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="batches",
                    to="farms.house",
                )),
                ("org", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="+",
                    to="tenants.organization",
                )),
            ],
            options={"db_table": "flocks_batch"},
        ),
        migrations.CreateModel(
            name="MortalityLog",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("date", models.DateField(default=datetime.date.today)),
                ("count", models.IntegerField(validators=[django.core.validators.MinValueValidator(1)])),
                ("cause", models.CharField(
                    choices=[
                        ("disease", "Disease"), ("accident", "Accident"),
                        ("culling", "Culling"), ("unknown", "Unknown"), ("theft", "Theft"),
                    ],
                    default="unknown",
                    max_length=10,
                )),
                ("notes", models.TextField(blank=True)),
                ("batch", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="mortality_logs",
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
            ],
            options={"db_table": "flocks_mortalitylog"},
        ),
        migrations.CreateModel(
            name="StockReconciliation",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("date", models.DateField()),
                ("expected_count", models.IntegerField()),
                ("actual_count", models.IntegerField()),
                ("variance", models.IntegerField()),
                ("variance_pct", models.DecimalField(decimal_places=2, max_digits=5)),
                ("is_flagged", models.BooleanField(default=False)),
                ("notes", models.TextField(blank=True)),
                ("batch", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="reconciliations",
                    to="flocks.batch",
                )),
                ("org", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="+",
                    to="tenants.organization",
                )),
            ],
            options={"db_table": "flocks_stockreconciliation"},
        ),
        migrations.CreateModel(
            name="WeightRecord",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("sample_date", models.DateField()),
                ("sample_size", models.IntegerField(validators=[django.core.validators.MinValueValidator(1)])),
                ("avg_weight_kg", models.DecimalField(decimal_places=3, max_digits=6)),
                ("min_weight_kg", models.DecimalField(blank=True, decimal_places=3, max_digits=6, null=True)),
                ("max_weight_kg", models.DecimalField(blank=True, decimal_places=3, max_digits=6, null=True)),
                ("notes", models.TextField(blank=True)),
                ("batch", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="weight_records",
                    to="flocks.batch",
                )),
                ("org", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="+",
                    to="tenants.organization",
                )),
            ],
            options={"db_table": "flocks_weightrecord"},
        ),
        # Indexes
        migrations.AddIndex(
            model_name="batch",
            index=models.Index(fields=["org", "status"], name="flocks_batch_org_status_idx"),
        ),
        migrations.AddIndex(
            model_name="batch",
            index=models.Index(fields=["org", "farm", "status"], name="flocks_batch_org_farm_status_idx"),
        ),
        migrations.AlterUniqueTogether(
            name="batch",
            unique_together={("org", "farm", "id")},
        ),
        migrations.AddIndex(
            model_name="mortalitylog",
            index=models.Index(fields=["org", "batch", "date"], name="flocks_mortalitylog_org_batch_date_idx"),
        ),
        migrations.AddIndex(
            model_name="mortalitylog",
            index=models.Index(fields=["org", "date"], name="flocks_mortalitylog_org_date_idx"),
        ),
        migrations.AlterUniqueTogether(
            name="stockreconciliation",
            unique_together={("org", "batch", "date")},
        ),
        migrations.AddIndex(
            model_name="weightrecord",
            index=models.Index(fields=["org", "batch", "sample_date"], name="flocks_weightrecord_org_batch_idx"),
        ),
        # RLS
        *enable_rls("flocks_batch"),
        *enable_rls("flocks_mortalitylog"),
        *enable_rls("flocks_stockreconciliation"),
        *enable_rls("flocks_weightrecord"),
    ]
