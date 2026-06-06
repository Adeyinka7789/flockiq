from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0007_supportticketreply'),
    ]

    operations = [
        migrations.AddField(
            model_name='notificationlog',
            name='action_url',
            field=models.CharField(blank=True, default='', max_length=500),
        ),
        migrations.AddField(
            model_name='adminnotification',
            name='action_url',
            field=models.CharField(blank=True, default='', max_length=500),
        ),
    ]
