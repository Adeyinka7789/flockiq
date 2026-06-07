from django.db import migrations
from django.db.migrations.operations.special import RunSQL


class _PgOnlySQL(RunSQL):
    """RunSQL that no-ops on non-PostgreSQL backends (e.g. SQLite in dev)."""

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        if schema_editor.connection.vendor != "postgresql":
            return
        super().database_forwards(app_label, schema_editor, from_state, to_state)

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        if schema_editor.connection.vendor != "postgresql":
            return
        super().database_backwards(app_label, schema_editor, from_state, to_state)


class Migration(migrations.Migration):
    """
    Add composite FK constraints that enforce cross-org reference integrity at
    the database level.

    The existing unique_together constraints provide the unique keys these FKs
    reference:
        farms_farm  UNIQUE(org_id, id)           — from farms/migrations/0001
        farms_house UNIQUE(org_id, farm_id, id)  — from farms/migrations/0001

    farms_house needs an additional UNIQUE(org_id, id) index before
    flocks_batch can reference it with a two-column composite FK.

    Django model save() already validates cross-org references in Python; these
    constraints close the gap for bulk_create, update(), and direct DB writes
    that bypass clean()/save().

    DEFERRABLE INITIALLY DEFERRED: constraints are checked at transaction commit,
    not per-statement. This allows batch creation within a single transaction
    without ordering constraints.

    ON DELETE CASCADE is declared on the composite FKs. In practice it never
    fires because the simple Django-managed FKs use PROTECT (NO ACTION), which
    blocks parent deletion before CASCADE could run.
    """

    dependencies = [
        (
            "flocks",
            "0002_rename_flocks_batch_org_status_idx_flocks_batc_org_id_96386e_idx_and_more",
        ),
        ("farms", "0001_initial"),
    ]

    operations = [
        # farms_house.unique_together covers (org, farm, id) but not (org, id).
        # The batch→house FK below references (org_id, id), so we add the index.
        _PgOnlySQL(
            sql="CREATE UNIQUE INDEX IF NOT EXISTS farms_house_org_id_uidx ON farms_house (org_id, id);",
            reverse_sql="DROP INDEX IF EXISTS farms_house_org_id_uidx;",
        ),
        # House → Farm: prevents a house from referencing a farm in another org
        _PgOnlySQL(
            sql="""
                ALTER TABLE farms_house
                ADD CONSTRAINT house_farm_org_fk
                FOREIGN KEY (org_id, farm_id)
                REFERENCES farms_farm (org_id, id)
                ON DELETE CASCADE
                DEFERRABLE INITIALLY DEFERRED;
            """,
            reverse_sql="ALTER TABLE farms_house DROP CONSTRAINT IF EXISTS house_farm_org_fk;",
        ),
        # Batch → Farm: prevents a batch from referencing a farm in another org
        _PgOnlySQL(
            sql="""
                ALTER TABLE flocks_batch
                ADD CONSTRAINT batch_farm_org_fk
                FOREIGN KEY (org_id, farm_id)
                REFERENCES farms_farm (org_id, id)
                ON DELETE CASCADE
                DEFERRABLE INITIALLY DEFERRED;
            """,
            reverse_sql="ALTER TABLE flocks_batch DROP CONSTRAINT IF EXISTS batch_farm_org_fk;",
        ),
        # Batch → House: prevents a batch from referencing a house in another org
        _PgOnlySQL(
            sql="""
                ALTER TABLE flocks_batch
                ADD CONSTRAINT batch_house_org_fk
                FOREIGN KEY (org_id, house_id)
                REFERENCES farms_house (org_id, id)
                ON DELETE CASCADE
                DEFERRABLE INITIALLY DEFERRED;
            """,
            reverse_sql="ALTER TABLE flocks_batch DROP CONSTRAINT IF EXISTS batch_house_org_fk;",
        ),
    ]
