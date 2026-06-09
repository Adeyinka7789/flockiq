# Generated for subscription expiry tracking and pending upgrades.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenants', '0004_organization_suspension_reason'),
    ]

    operations = [
        migrations.AddField(
            model_name='organization',
            name='plan_expires_at',
            field=models.DateTimeField(
                blank=True,
                null=True,
                help_text='When the current paid plan lapses. Set on activation/renewal.',
            ),
        ),
        migrations.AddField(
            model_name='organization',
            name='plan_renewal_preference',
            field=models.CharField(
                choices=[('auto', 'Auto-renew'), ('manual', 'Manual renewal')],
                default='manual',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='organization',
            name='upgrade_pending',
            field=models.CharField(
                blank=True,
                choices=[
                    ('', 'No pending upgrade'),
                    ('monthly', 'Monthly'),
                    ('yearly', 'Yearly'),
                    ('cycle', 'Cycle'),
                ],
                default='',
                help_text='Plan the org has scheduled to switch to at next renewal.',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='organization',
            name='upgrade_timing',
            field=models.CharField(
                blank=True,
                choices=[('immediate', 'Immediate'), ('on_renewal', 'At next renewal')],
                default='',
                max_length=20,
            ),
        ),
    ]
