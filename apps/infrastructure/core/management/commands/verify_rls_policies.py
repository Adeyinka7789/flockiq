from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = "Verify RLS policies are applied to all TenantAwareModel subclasses"

    EXEMPT_TABLES = {
        "notifications_outboxevent",
        "weather_weathercache",
        "tasks_tasktemplate",
        "billing_billingplan",
    }

    def handle(self, *args, **options):
        from apps.infrastructure.core.models import TenantAwareModel

        tenant_tables = {
            model._meta.db_table
            for model in apps.get_models()
            if issubclass(model, TenantAwareModel) and not model._meta.abstract
        }

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'public' AND rowsecurity = TRUE"
            )
            rls_enabled = {row[0] for row in cursor.fetchall()}

        missing = tenant_tables - rls_enabled - self.EXEMPT_TABLES
        if missing:
            self.stderr.write(f"RLS NOT ENABLED on {len(missing)} tables:")
            for table in sorted(missing):
                self.stderr.write(f"  - {table}")
            raise SystemExit(1)

        self.stdout.write(
            self.style.SUCCESS(f"RLS verified on {len(tenant_tables)} tenant tables.")
        )
