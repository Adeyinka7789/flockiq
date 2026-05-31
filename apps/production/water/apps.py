from django.apps import AppConfig


class WaterConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.production.water"
    label = "water"

    def ready(self):
        import apps.production.water.signals  # noqa: F401
