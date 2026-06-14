# Seed the singleton ValuationSettings row so FlockValuationService has its
# admin-configurable fallback prices from first deploy. The field defaults
# (₦1850/kg broiler, ₦2800 POL pullet, ₦2000 generic per-bird) match the
# constants the service used before this feature, so behaviour is unchanged.
from django.db import migrations


def seed_valuation_settings(apps, schema_editor):
    ValuationSettings = apps.get_model("billing", "ValuationSettings")
    # get_or_create applies the model field defaults; pk=1 is the singleton row.
    ValuationSettings.objects.get_or_create(pk=1)


def unseed_valuation_settings(apps, schema_editor):
    ValuationSettings = apps.get_model("billing", "ValuationSettings")
    ValuationSettings.objects.filter(pk=1).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("billing", "0003_valuationsettings"),
    ]

    operations = [
        migrations.RunPython(seed_valuation_settings, unseed_valuation_settings),
    ]
