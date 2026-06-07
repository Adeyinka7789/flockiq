"""
Make every tenant_isolation RLS policy null/empty-safe on already-migrated
databases (dev / staging / production).

Fresh databases are already correct: pytest and `migrate` rebuild the schema by
re-running each app's enable_rls() call, which now emits the NULLIF(...) form.
This migration repairs databases whose policies were created with the original
bare `current_setting('app.current_org_id', TRUE)::uuid` expression, which raises
`invalid input syntax for type uuid: ""` whenever a connection is reused after a
SET LOCAL has reverted the GUC to the empty string (PgBouncer transaction mode,
super-admin .unscoped() reads, etc.).

Idempotent: loops over whatever tenant_isolation policies currently exist and
recreates each one with the NULLIF guard.
"""

from django.db import migrations

from apps.infrastructure.core.migrations._rls_helpers import _PostgreSQLRunSQL


RECREATE_NULL_SAFE = r"""
DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN
        SELECT schemaname, tablename
        FROM pg_policies
        WHERE policyname = 'tenant_isolation'
    LOOP
        EXECUTE format('DROP POLICY tenant_isolation ON %I.%I', r.schemaname, r.tablename);
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON %I.%I '
            'USING (org_id = NULLIF(current_setting(''app.current_org_id'', TRUE), '''')::uuid)',
            r.schemaname, r.tablename
        );
    END LOOP;
END $$;
"""


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0001_initial"),
    ]

    operations = [
        _PostgreSQLRunSQL(
            sql=RECREATE_NULL_SAFE,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
