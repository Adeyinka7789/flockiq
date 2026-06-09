import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

from apps.infrastructure.core.migrations._rls_helpers import disable_rls


class Migration(migrations.Migration):

    dependencies = [
        ("market", "0003_alter_seasonaldemandindex_id"),
        ("tenants", "0001_initial"),
        ("flocks", "0003_composite_fk_constraints"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="FeedPriceReport",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("feed_type", models.CharField(
                    choices=[
                        ("broiler_starter", "Broiler Starter"),
                        ("broiler_grower", "Broiler Grower"),
                        ("broiler_finisher", "Broiler Finisher"),
                        ("layers_mash", "Layer's Mash"),
                        ("layers_chick_mash", "Layer Chick Mash"),
                    ],
                    max_length=30,
                )),
                ("brand", models.CharField(
                    choices=[
                        ("topfeeds", "TopFeeds"),
                        ("chikun", "Chikun"),
                        ("ultima", "Ultima"),
                        ("animal_care", "Animal Care"),
                        ("hybrid", "Hybrid"),
                        ("other", "Other"),
                    ],
                    default="other",
                    max_length=30,
                )),
                ("brand_other", models.CharField(blank=True, max_length=100)),
                ("price_per_25kg_bag", models.DecimalField(
                    decimal_places=2, max_digits=10,
                    help_text="Price in Naira for a 25kg bag",
                )),
                ("state", models.CharField(max_length=100)),
                ("lga", models.CharField(blank=True, help_text="Local Government Area", max_length=100)),
                ("reported_date", models.DateField(auto_now_add=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("submitted_by", models.ForeignKey(
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="feed_price_reports",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("org", models.ForeignKey(
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    to="tenants.organization",
                )),
            ],
            options={
                "ordering": ["-reported_date"],
                "indexes": [
                    models.Index(fields=["feed_type", "state", "reported_date"], name="mkt_feedprice_type_state_date_idx"),
                ],
            },
        ),
        migrations.CreateModel(
            name="Hatchery",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=200)),
                ("state", models.CharField(max_length=100)),
                ("lga", models.CharField(blank=True, max_length=100)),
                ("address", models.TextField(blank=True)),
                ("phone", models.CharField(blank=True, max_length=20)),
                ("website", models.URLField(blank=True)),
                ("bird_types", models.JSONField(
                    default=list,
                    help_text='["broiler", "layer", "noiler"]',
                )),
                ("is_verified", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("added_by", models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                "ordering": ["state", "name"],
                "verbose_name_plural": "hatcheries",
            },
        ),
        migrations.CreateModel(
            name="HatcheryReview",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("doc_quality_rating", models.PositiveSmallIntegerField(help_text="1-5: Quality of day-old chicks")),
                ("survival_rate_pct", models.DecimalField(
                    decimal_places=2, max_digits=5,
                    help_text="% of DOCs that survived to harvest",
                )),
                ("delivery_reliability", models.PositiveSmallIntegerField(
                    help_text="1-5: On-time delivery reliability",
                )),
                ("overall_rating", models.PositiveSmallIntegerField(help_text="1-5: Overall satisfaction")),
                ("comment", models.TextField(blank=True)),
                ("batch_size", models.PositiveIntegerField(help_text="Number of DOCs purchased")),
                ("purchase_date", models.DateField()),
                ("price_per_doc", models.DecimalField(
                    decimal_places=2, max_digits=8,
                    help_text="Price paid per DOC in Naira",
                )),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("hatchery", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="reviews",
                    to="market.hatchery",
                )),
                ("batch", models.OneToOneField(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="hatchery_review",
                    to="flocks.batch",
                )),
                ("submitted_by", models.ForeignKey(
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    to=settings.AUTH_USER_MODEL,
                )),
                ("org", models.ForeignKey(
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    to="tenants.organization",
                )),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        *disable_rls("market_feedpricereport"),
        *disable_rls("market_hatchery"),
        *disable_rls("market_hatcheryreview"),
    ]
