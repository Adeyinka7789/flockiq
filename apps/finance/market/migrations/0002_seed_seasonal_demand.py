from django.db import migrations


SEASONAL_DATA = [
    # (month, product_type, demand_index)
    (1,  "eggs",       7),
    (2,  "eggs",       6),
    (3,  "eggs",       6),
    (4,  "eggs",       7),
    (5,  "eggs",       6),
    (6,  "eggs",       5),
    (7,  "eggs",       7),
    (8,  "eggs",       8),
    (9,  "eggs",       7),
    (10, "eggs",       8),
    (11, "eggs",       9),
    (12, "eggs",      10),
    (1,  "live_birds", 7),
    (2,  "live_birds", 6),
    (3,  "live_birds", 7),
    (4,  "live_birds", 8),
    (5,  "live_birds", 6),
    (6,  "live_birds", 5),
    (7,  "live_birds", 6),
    (8,  "live_birds", 7),
    (9,  "live_birds", 7),
    (10, "live_birds", 8),
    (11, "live_birds", 9),
    (12, "live_birds",10),
]


def seed_seasonal_demand(apps, schema_editor):
    SeasonalDemandIndex = apps.get_model("market", "SeasonalDemandIndex")
    for month, product_type, demand_index in SEASONAL_DATA:
        SeasonalDemandIndex.objects.get_or_create(
            month=month,
            product_type=product_type,
            defaults={"demand_index": demand_index},
        )


def remove_seasonal_demand(apps, schema_editor):
    SeasonalDemandIndex = apps.get_model("market", "SeasonalDemandIndex")
    SeasonalDemandIndex.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("market", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_seasonal_demand, remove_seasonal_demand),
    ]
