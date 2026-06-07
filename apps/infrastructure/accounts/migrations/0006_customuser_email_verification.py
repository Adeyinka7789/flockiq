import uuid
from django.db import migrations, models


def backfill_existing_users_verified(apps, schema_editor):
    """All users created before email verification was introduced are considered verified."""
    CustomUser = apps.get_model('accounts', 'CustomUser')
    CustomUser.objects.all().update(email_verified=True)


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0005_customuser_country_customuser_language_code_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='customuser',
            name='email_verified',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='customuser',
            name='email_verification_token',
            field=models.UUIDField(default=uuid.uuid4, editable=False),
        ),
        migrations.RunPython(
            backfill_existing_users_verified,
            migrations.RunPython.noop,
        ),
    ]
