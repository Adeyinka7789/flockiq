from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0002_notificationlog_acknowledged_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='notificationlog',
            name='batch_reference',
            field=models.CharField(blank=True, default='', max_length=100),
        ),
    ]
