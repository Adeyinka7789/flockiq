from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.infrastructure.core"
    label = "core"

    def ready(self):
        import apps.infrastructure.core.checks  # noqa: F401
