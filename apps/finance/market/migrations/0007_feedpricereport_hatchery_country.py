from django.db import migrations, models

from apps.infrastructure.accounts.constants import COUNTRY_CHOICES


class Migration(migrations.Migration):

    dependencies = [
        ("market", "0006_marketprice_country"),
    ]

    operations = [
        # default="Nigeria" backfills every existing row — all current
        # crowdsourced data is Nigeria-shaped (see codebase audit).
        migrations.AddField(
            model_name="feedpricereport",
            name="country",
            field=models.CharField(
                choices=COUNTRY_CHOICES,
                default="Nigeria",
                max_length=50,
            ),
        ),
        migrations.AddField(
            model_name="hatchery",
            name="country",
            field=models.CharField(
                choices=COUNTRY_CHOICES,
                default="Nigeria",
                max_length=50,
            ),
        ),
    ]
