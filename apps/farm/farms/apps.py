from django.apps import AppConfig


class FarmsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.farm.farms"
    label = "farms"

    def ready(self):
        from auditlog.registry import auditlog

        from apps.farm.farms.models import Farm, House

        # Farm/House deletion is a high-impact destructive action — audit it.
        auditlog.register(Farm)
        auditlog.register(House)
