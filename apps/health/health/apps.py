from django.apps import AppConfig


class HealthConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.health.health"
    label = "health"

    def ready(self):
        import apps.health.health.signals  # noqa: F401
