import datetime
import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models

from apps.infrastructure.core.migrations._rls_helpers import enable_rls


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("farms", "0001_initial"),
        ("flocks", "0002_rename_flocks_batch_org_status_idx_flocks_batc_org_id_96386e_idx_and_more"),
        ("tenants", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ExpenseRecord",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("category", models.CharField(
                    choices=[
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
                    ],
                    max_length=20,
                )),
                ("amount_kobo", models.IntegerField()),
                ("description", models.CharField(max_length=300)),
                ("expense_date", models.DateField(default=datetime.date.today)),
                ("receipt_ref", models.CharField(blank=True, max_length=100)),
                ("notes", models.TextField(blank=True)),
                ("batch", models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="expenses",
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
                "db_table": "expenses_expenserecord",
                "indexes": [
                    models.Index(fields=["org", "farm", "expense_date"], name="expenses_rec_org_farm_date_idx"),
                    models.Index(fields=["org", "batch", "category"], name="expenses_rec_org_batch_cat_idx"),
                ],
            },
        ),
        *enable_rls("expenses_expenserecord"),
    ]
