from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("water", "0002_soft_delete"),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name="waterlog",
            unique_together=set(),
        ),
        migrations.AddConstraint(
            model_name="waterlog",
            constraint=models.UniqueConstraint(
                condition=models.Q(("is_deleted", False)),
                fields=("org", "batch", "record_date"),
                name="unique_waterlog_per_batch_date_active",
            ),
        ),
    ]
