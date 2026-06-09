# Generated for custom domain mapping (Phase 3, Item 7).
# Organization has RLS DISABLED (it IS the tenant), so no enable_rls() call.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenants', '0005_organization_plan_expiry_and_upgrade'),
    ]

    operations = [
        migrations.AddField(
            model_name='organization',
            name='custom_domain',
            field=models.CharField(
                blank=True,
                null=True,
                unique=True,
                db_index=True,
                max_length=255,
                help_text='e.g. app.obasanjofarm.com',
            ),
        ),
        migrations.AddField(
            model_name='organization',
            name='custom_domain_verified',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='organization',
            name='custom_domain_verification_token',
            field=models.CharField(
                blank=True,
                default='',
                max_length=64,
                help_text='TXT record value for DNS verification',
            ),
        ),
        migrations.AddField(
            model_name='organization',
            name='custom_domain_verified_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
