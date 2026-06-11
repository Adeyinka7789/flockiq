from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("production", "0003_soft_delete"),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name="eggproductionlog",
            unique_together=set(),
        ),
        migrations.AddConstraint(
            model_name="eggproductionlog",
            constraint=models.UniqueConstraint(
                condition=models.Q(("is_deleted", False)),
                fields=("org", "batch", "record_date"),
                name="unique_egglog_per_batch_date_active",
            ),
        ),
    ]
