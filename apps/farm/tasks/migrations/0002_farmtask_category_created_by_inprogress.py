import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tasks", "0001_initial"),
        ("accounts", "0001_initial"),
    ]

    operations = [
        # Widen status column so 'in_progress' (11 chars) fits
        migrations.AlterField(
            model_name="farmtask",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("in_progress", "In Progress"),
                    ("complete", "Complete"),
                    ("overdue", "Overdue"),
                ],
                default="pending",
                max_length=15,
            ),
        ),
        # Make farm optional for manually created tasks
        migrations.AlterField(
            model_name="farmtask",
            name="farm",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="tasks",
                to="farms.farm",
            ),
        ),
        # Make due_date optional for manually created tasks
        migrations.AlterField(
            model_name="farmtask",
            name="due_date",
            field=models.DateField(blank=True, null=True),
        ),
        # Add category
        migrations.AddField(
            model_name="farmtask",
            name="category",
            field=models.CharField(
                blank=True,
                choices=[
                    ("medication", "Medication"),
                    ("nutrition", "Nutrition"),
                    ("maintenance", "Maintenance"),
                    ("environmental", "Environmental"),
                    ("health", "Health"),
                    ("production", "Production"),
                    ("finance", "Finance"),
                    ("other", "Other"),
                ],
                default="other",
                max_length=30,
            ),
        ),
        # Add created_by
        migrations.AddField(
            model_name="farmtask",
            name="created_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="created_tasks",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
