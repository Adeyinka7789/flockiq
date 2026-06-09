import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("flocks", "0003_composite_fk_constraints"),
        ("market", "0004_feedpricereport_hatchery_hatcheryreview"),
    ]

    operations = [
        migrations.AddField(
            model_name="batch",
            name="hatchery",
            field=models.ForeignKey(
                blank=True,
                help_text="Hatchery where DOCs were purchased",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="batches",
                to="market.hatchery",
            ),
        ),
        migrations.AddField(
            model_name="batch",
            name="doc_price_per_chick",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text="Price paid per day-old chick in Naira",
                max_digits=8,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="batch",
            name="doc_supplier_name",
            field=models.CharField(
                blank=True,
                help_text="Hatchery name if not in directory",
                max_length=200,
            ),
        ),
    ]
