"""
Migration helpers for enabling/disabling PostgreSQL Row-Level Security.

Usage in a migration file:
    from apps.infrastructure.core.migrations._rls_helpers import enable_rls

    class Migration(migrations.Migration):
        operations = [
            migrations.CreateModel(...),
            *enable_rls("flocks_batch"),
        ]

Call enable_rls() in EVERY migration that creates a TenantAwareModel table.
Omitting it means that table's data is visible to all tenants — a data leak.
"""

from django.db.migrations.operations.special import RunSQL


class _PostgreSQLRunSQL(RunSQL):
    """RunSQL subclass that no-ops on non-PostgreSQL backends (e.g. SQLite in dev)."""

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        if schema_editor.connection.vendor != "postgresql":
            return
        super().database_forwards(app_label, schema_editor, from_state, to_state)

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        if schema_editor.connection.vendor != "postgresql":
            return
        super().database_backwards(app_label, schema_editor, from_state, to_state)


def enable_rls(table_name: str) -> list:
    """
    Returns three RunSQL operations:
      1. Enable RLS on the table.
      2. Create the tenant isolation policy using app.current_org_id.
      3. Force RLS even for the table owner (prevents owner-bypass).

    The policy uses current_setting(..., TRUE) wrapped in NULLIF(..., ''):
    PostgreSQL reverts a transaction-scoped SET LOCAL to the EMPTY STRING (not NULL)
    once the transaction ends, so a bare current_setting(..., TRUE)::uuid raises
    'invalid input syntax for type uuid: ""' on the next context-less query that
    reuses the connection (e.g. via PgBouncer, or super-admin .unscoped() reads).
    NULLIF(current_setting('app.current_org_id', TRUE), '') maps both the unset and
    the reverted-empty states to NULL, so org_id = NULL is always false and zero
    rows are returned — the correct fail-closed behaviour, with no error.
    Never use current_setting(..., FALSE) — it raises an error when unset.
    """
    return [
        _PostgreSQLRunSQL(
            sql=f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY;",
            reverse_sql=f"ALTER TABLE {table_name} DISABLE ROW LEVEL SECURITY;",
        ),
        _PostgreSQLRunSQL(
            sql=f"""
                CREATE POLICY tenant_isolation ON {table_name}
                    USING (
                        org_id = NULLIF(current_setting('app.current_org_id', TRUE), '')::uuid
                    );
            """,
            reverse_sql=f"DROP POLICY IF EXISTS tenant_isolation ON {table_name};",
        ),
        _PostgreSQLRunSQL(
            sql=f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY;",
            reverse_sql=f"ALTER TABLE {table_name} NO FORCE ROW LEVEL SECURITY;",
        ),
    ]


def disable_rls(table_name: str) -> list:
    """
    Explicitly disables RLS for cross-tenant infrastructure tables.

    Tables that MAY disable RLS (exhaustive list — add here when creating new ones):
        - weather_weathercache       (shared weather data, read by all orgs)
        - notifications_outboxevent  (read by Celery processor worker cross-tenant)
        - tasks_tasktemplate         (shared task definitions)
        - billing_billingplan        (global subscription plans)
        - tenants_organization       (IS the tenant root — no RLS needed)

    Every other table: RLS ON, no exceptions.
    """
    return [
        _PostgreSQLRunSQL(
            sql=f"ALTER TABLE {table_name} DISABLE ROW LEVEL SECURITY;",
            reverse_sql=f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY;",
        ),
    ]
