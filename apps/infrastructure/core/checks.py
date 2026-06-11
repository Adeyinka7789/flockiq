from django.core.checks import Error, Warning, register
from django.db import connection


@register()
def check_database_role_security(app_configs, **kwargs):
    """
    Verify the runtime DB role is not superuser and does not bypass RLS.
    A wrong DATABASE_URL (e.g. pointing at flockiq_admin) fails loudly at
    startup rather than silently voiding all tenant isolation.
    """
    errors = []
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT usesuper, rolbypassrls
                FROM pg_user
                JOIN pg_roles ON pg_user.usename = pg_roles.rolname
                WHERE usename = current_user
                """
            )
            row = cursor.fetchone()
            if row:
                is_super, bypass_rls = row
                if is_super:
                    errors.append(
                        Error(
                            "Database runtime user is a superuser. "
                            "RLS policies are bypassed. "
                            "Use flockiq_app (NOSUPERUSER).",
                            id="core.E001",
                        )
                    )
                if bypass_rls:
                    errors.append(
                        Error(
                            "Database runtime user has BYPASSRLS. "
                            "All tenant isolation is disabled.",
                            id="core.E002",
                        )
                    )
    except Exception as e:
        errors.append(
            Warning(
                f"Could not verify DB role security: {e}",
                id="core.W001",
            )
        )
    return errors
