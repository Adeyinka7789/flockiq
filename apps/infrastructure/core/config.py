from django.db import models


class PlatformConfig(models.Model):
    """
    Singleton model for FlockIQ admin-configurable settings.
    Only one row should ever exist (pk=1).
    Edit via Django admin.
    """
    admin_whatsapp = models.CharField(
        max_length=20, default='2348000000000',
        help_text='WhatsApp number with country code, no + or spaces. '
                  'e.g. 2348012345678')
    admin_email = models.EmailField(default='admin@flockiq.com')
    admin_phone = models.CharField(max_length=20, blank=True, default='')

    bank_name = models.CharField(
        max_length=100, default='', blank=True,
        help_text='e.g. GTBank, Zenith Bank')
    bank_account_number = models.CharField(max_length=20, default='', blank=True)
    bank_account_name = models.CharField(
        max_length=200, default='', blank=True,
        help_text='e.g. ADM Tech Hub Limited')

    company_name = models.CharField(max_length=200, default='FlockIQ / ADM Tech Hub')
    support_hours = models.CharField(
        max_length=100, default='Mon–Fri, 8AM–6PM WAT', blank=True)

    class Meta:
        verbose_name = 'Platform Configuration'
        verbose_name_plural = 'Platform Configuration'

    def __str__(self):
        return 'Platform Configuration'

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)
