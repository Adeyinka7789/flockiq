from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0007_alter_organization_subscription_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="organization",
            name="paystack_subscription_code",
            field=models.CharField(
                blank=True,
                default="",
                help_text=(
                    "Parking slot for a subscription.create webhook that arrives "
                    "before the create_subscription API response is processed; "
                    "consumed by BillingService.activate_cycle_subscription."
                ),
                max_length=100,
            ),
        ),
    ]
