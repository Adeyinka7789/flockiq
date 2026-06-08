# Generated for suspended-org handling.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenants', '0003_organization_grace_period_ends_at_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='organization',
            name='suspension_reason',
            field=models.CharField(
                blank=True,
                help_text='Reason shown to the org owner when the account is suspended',
                max_length=500,
            ),
        ),
    ]
