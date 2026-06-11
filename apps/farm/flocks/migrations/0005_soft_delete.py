import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("flocks", "0004_batch_hatchery_doc_price"),
    ]

    operations = [
        # ── Batch ──────────────────────────────────────────────────────────
        migrations.AddField(
            model_name="batch",
            name="is_deleted",
            field=models.BooleanField(default=False, db_index=True),
        ),
        migrations.AddField(
            model_name="batch",
            name="deleted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="batch",
            name="deleted_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="deleted_batchs",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        # ── MortalityLog ───────────────────────────────────────────────────
        migrations.AddField(
            model_name="mortalitylog",
            name="is_deleted",
            field=models.BooleanField(default=False, db_index=True),
        ),
        migrations.AddField(
            model_name="mortalitylog",
            name="deleted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="mortalitylog",
            name="deleted_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="deleted_mortalitylogs",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        # ── WeightRecord ───────────────────────────────────────────────────
        migrations.AddField(
            model_name="weightrecord",
            name="is_deleted",
            field=models.BooleanField(default=False, db_index=True),
        ),
        migrations.AddField(
            model_name="weightrecord",
            name="deleted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="weightrecord",
            name="deleted_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="deleted_weightrecords",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
