from django.db import migrations, models

from apps.infrastructure.accounts.constants import COUNTRY_CHOICES


def backfill_country_from_owner(apps, schema_editor):
    """Set each existing org's country from its owner's CustomUser.country.

    Falls back to any member, then to 'Nigeria' (the AddField default that
    every row already carries) when no user has a country set.
    """
    Organization = apps.get_model("tenants", "Organization")
    CustomUser = apps.get_model("accounts", "CustomUser")

    for org in Organization.objects.all():
        owner = CustomUser.objects.filter(org=org, role="owner").first()
        if owner is None:
            owner = CustomUser.objects.filter(org=org).first()
        country = (getattr(owner, "country", "") or "").strip() or "Nigeria"
        if org.country != country:
            org.country = country
            org.save(update_fields=["country"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0008_organization_paystack_subscription_code"),
        ("accounts", "0005_customuser_country_customuser_language_code_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="organization",
            name="country",
            field=models.CharField(
                choices=COUNTRY_CHOICES,
                default="Nigeria",
                max_length=50,
            ),
        ),
        migrations.RunPython(backfill_country_from_owner, noop_reverse),
    ]
