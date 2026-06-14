from django.db import migrations, models

from apps.infrastructure.accounts.constants import COUNTRY_CHOICES


class Migration(migrations.Migration):

    dependencies = [
        ("market", "0005_rename_mkt_feedprice_type_state_date_idx_market_feed_feed_ty_7f586a_idx"),
    ]

    operations = [
        # default="Nigeria" backfills every existing row — all current market
        # data is Nigeria-shaped (see codebase audit).
        migrations.AddField(
            model_name="marketprice",
            name="country",
            field=models.CharField(
                choices=COUNTRY_CHOICES,
                default="Nigeria",
                max_length=50,
            ),
        ),
    ]
