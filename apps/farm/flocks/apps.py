from django.apps import AppConfig


class FlocksConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.farm.flocks"
    label = "flocks"

    def ready(self):
        import apps.farm.flocks.signals  # noqa: F401
        from auditlog.registry import auditlog
        from apps.farm.flocks.models import Batch, MortalityLog
        auditlog.register(Batch)
        auditlog.register(MortalityLog)
