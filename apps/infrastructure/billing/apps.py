from django.apps import AppConfig


class BillingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.infrastructure.billing"
    label = "billing"

    def ready(self):
        from auditlog.registry import auditlog
        from apps.infrastructure.billing.models import PaymentRecord
        auditlog.register(PaymentRecord)
