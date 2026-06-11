from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("feed", "0002_soft_delete"),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name="feedlog",
            unique_together=set(),
        ),
        migrations.AddConstraint(
            model_name="feedlog",
            constraint=models.UniqueConstraint(
                condition=models.Q(("is_deleted", False)),
                fields=("org", "batch", "record_date"),
                name="unique_feedlog_per_batch_date_active",
            ),
        ),
    ]
