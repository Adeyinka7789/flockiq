import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

from apps.infrastructure.core.migrations._rls_helpers import disable_rls, enable_rls


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("accounts", "0001_initial"),
        ("farms", "0001_initial"),
        ("flocks", "0001_initial"),
        ("tenants", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="TaskTemplate",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=200)),
                ("description", models.TextField(blank=True)),
                ("breed_applicable", models.CharField(
                    choices=[("layer", "Layer"), ("broiler", "Broiler"), ("both", "Both")],
                    default="both",
                    max_length=10,
                )),
                ("frequency", models.CharField(
                    choices=[("daily", "Daily"), ("weekly", "Weekly"), ("one_time", "One-Time")],
                    max_length=10,
                )),
                ("cycle_day", models.IntegerField(blank=True, null=True)),
                ("is_active", models.BooleanField(default=True)),
            ],
            options={"db_table": "tasks_tasktemplate"},
        ),
        migrations.CreateModel(
            name="FarmTask",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("title", models.CharField(max_length=200)),
                ("description", models.TextField(blank=True)),
                ("due_date", models.DateField()),
                ("status", models.CharField(
                    choices=[("pending", "Pending"), ("complete", "Complete"), ("overdue", "Overdue")],
                    default="pending",
                    max_length=10,
                )),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("priority", models.CharField(
                    choices=[("low", "Low"), ("medium", "Medium"), ("high", "High")],
                    default="medium",
                    max_length=10,
                )),
                ("assigned_to", models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="assigned_tasks",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("batch", models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="tasks",
                    to="flocks.batch",
                )),
                ("completed_by", models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="completed_tasks",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("farm", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="tasks",
                    to="farms.farm",
                )),
                ("org", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="+",
                    to="tenants.organization",
                )),
                ("template", models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="generated_tasks",
                    to="tasks.tasktemplate",
                )),
            ],
            options={"db_table": "tasks_farmtask"},
        ),
        migrations.AddIndex(
            model_name="farmtask",
            index=models.Index(
                fields=["org", "status", "due_date"],
                name="tasks_ft_org_status_due",
            ),
        ),
        migrations.AddIndex(
            model_name="farmtask",
            index=models.Index(
                fields=["org", "assigned_to", "status"],
                name="tasks_ft_org_assigned",
            ),
        ),
        # TaskTemplate is global/shared — RLS disabled
        *disable_rls("tasks_tasktemplate"),
        # FarmTask is tenant-scoped — RLS enabled
        *enable_rls("tasks_farmtask"),
    ]
