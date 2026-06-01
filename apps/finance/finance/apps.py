from django.apps import AppConfig


class FinanceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.finance.finance"
    label = "finance"

    def ready(self):
        from apps.finance.finance.signals import connect_signals
        connect_signals()
