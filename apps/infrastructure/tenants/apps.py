from django.apps import AppConfig


class TenantsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.infrastructure.tenants"
    label = "tenants"

    def ready(self):
        import apps.infrastructure.tenants.signals  # noqa: F401
        from auditlog.registry import auditlog
        from apps.infrastructure.tenants.models import Organization
        auditlog.register(Organization)
