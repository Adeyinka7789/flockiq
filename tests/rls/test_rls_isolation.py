"""
Cross-tenant RLS isolation suite — run after EVERY model change:

    pytest tests/rls/ -v

What this verifies, for every tenant-scoped model in the project:

  Layer 1 (ORM)  — TenantAwareManager scopes every queryset to the bound
                   org and fail-closes (qs.none()) without a context.
  Layer 2 (DB)   — PostgreSQL row-level security (tenant_isolation policy,
                   FORCE'd so even the table owner is subject to it) blocks
                   rows of other orgs even when the ORM filter is bypassed
                   via .unscoped() or raw SQL.

The two layers are asserted SEPARATELY: a passing Layer-1 test with a broken
RLS policy must still fail here (via the .unscoped() / raw SQL assertions),
and vice versa.

The model list below is guarded by test_model_inventory_is_complete, which
diffs it against the live app registry — adding a new TenantAwareModel
without updating this suite (and its fixture) fails immediately.

Layer-2 tests skip on SQLite (no RLS support — dev fallback only); the
suite is only meaningful against PostgreSQL, which is what CI and the dev
environment use.
"""
import pytest
from django.core.exceptions import ObjectDoesNotExist
from django.db import DatabaseError, connection, transaction

from apps.infrastructure.core.rls import no_tenant_context, set_tenant_context

pytestmark = pytest.mark.django_db

requires_postgres = pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason="DB-level RLS requires PostgreSQL (SQLite is a dev-only fallback)",
)

# Every concrete TenantAwareModel subclass. Guarded against the app registry
# by test_model_inventory_is_complete — keep in sync with the fixture in
# tests/rls/conftest.py.
TENANT_SCOPED_MODELS = [
    ("farms", "Farm"),
    ("farms", "House"),
    ("flocks", "Batch"),
    ("flocks", "MortalityLog"),
    ("flocks", "StockReconciliation"),
    ("flocks", "WeightRecord"),
    ("tasks", "FarmTask"),
    ("weather", "WeatherAlert"),
    ("feed", "FeedLog"),
    ("feed", "FeedStock"),
    ("production", "EggProductionLog"),
    ("production", "CrateInventory"),
    ("water", "WaterLog"),
    ("waste", "WasteLog"),
    ("health", "VaccinationSchedule"),
    ("health", "MedicationRecord"),
    ("health", "SymptomLog"),
    ("health", "OutbreakAlert"),
    ("analytics", "ForecastResult"),
    ("analytics", "AnomalyRecord"),
    ("analytics", "SaleTimingRecommendation"),
    ("analytics", "AIDailyBrief"),
    ("analytics", "FarmBaseline"),
    ("analytics", "TheftFlag"),
    ("finance", "SalesRecord"),
    ("finance", "BatchFinancialSummary"),
    ("finance", "FarmCreditScore"),
    ("expenses", "ExpenseRecord"),
    ("market", "MarketPrice"),
    ("billing", "CycleSubscription"),
    ("billing", "PaymentRecord"),
    ("notifications", "AlertRule"),
    ("notifications", "NotificationLog"),
]

# Subset using SoftDeleteMixin (objects = ActiveManager, all_objects =
# AllObjectsManager).
SOFT_DELETE_MODELS = [
    ("farms", "Farm"),
    ("farms", "House"),
    ("flocks", "Batch"),
    ("flocks", "MortalityLog"),
    ("flocks", "WeightRecord"),
    ("feed", "FeedLog"),
    ("production", "EggProductionLog"),
    ("water", "WaterLog"),
]


def _get_model(app_label, model_name):
    from django.apps import apps as django_apps

    return django_apps.get_model(app_label, model_name)


def test_model_inventory_is_complete():
    """
    The parametrize list above must exactly match the concrete
    TenantAwareModel subclasses in the app registry. If this fails you
    added (or removed) a tenant-scoped model: update TENANT_SCOPED_MODELS,
    SOFT_DELETE_MODELS if applicable, AND create an instance of it in
    tests/rls/conftest.py::org_a_full_dataset.
    """
    from django.apps import apps as django_apps

    from apps.infrastructure.core.models import TenantAwareModel

    discovered = {
        (m._meta.app_label, m.__name__)
        for m in django_apps.get_models()
        if issubclass(m, TenantAwareModel)
    }
    listed = set(TENANT_SCOPED_MODELS)
    missing = discovered - listed
    stale = listed - discovered
    assert not missing, (
        f"New TenantAwareModel(s) not covered by the RLS suite: {missing}. "
        f"Add to TENANT_SCOPED_MODELS and org_a_full_dataset."
    )
    assert not stale, (
        f"TENANT_SCOPED_MODELS lists models that no longer exist: {stale}."
    )


@requires_postgres
class TestRLSPolicyEnforcement:
    """RLS must be enforced at the DATABASE level, independent of the ORM."""

    @pytest.mark.parametrize("app_label,model_name", TENANT_SCOPED_MODELS)
    def test_table_has_forced_rls_policy(self, app_label, model_name):
        """
        Every TenantAwareModel table must have RLS enabled AND forced
        (FORCE makes the table owner subject to the policy too), plus the
        tenant_isolation policy itself. This is the check that catches a
        migration missing enable_rls() — CLAUDE.md non-negotiable #2.
        """
        table = _get_model(app_label, model_name)._meta.db_table
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE oid = %s::regclass",
                [table],
            )
            enabled, forced = cursor.fetchone()
            cursor.execute(
                "SELECT COUNT(*) FROM pg_policies "
                "WHERE tablename = %s AND policyname = 'tenant_isolation'",
                [table],
            )
            policy_count = cursor.fetchone()[0]

        assert enabled, (
            f"{table}: ROW LEVEL SECURITY is NOT enabled — the migration "
            f"for {model_name} must call enable_rls('{table}')"
        )
        assert forced, (
            f"{table}: RLS is enabled but not FORCEd — the table owner "
            f"bypasses the policy"
        )
        assert policy_count == 1, (
            f"{table}: tenant_isolation policy missing"
        )

    def test_runtime_role_cannot_bypass_rls(self):
        """
        If the connection role is superuser or has BYPASSRLS, every other
        assertion in this suite is meaningless — RLS would be silently
        skipped for the whole app.
        """
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT rolsuper, rolbypassrls FROM pg_roles "
                "WHERE rolname = current_user"
            )
            is_super, bypass_rls = cursor.fetchone()
        assert not is_super, (
            "DB role is superuser — RLS is bypassed for the entire app!"
        )
        assert not bypass_rls, (
            "DB role has BYPASSRLS — RLS is bypassed for the entire app!"
        )

    def test_raw_sql_respects_rls(self, two_orgs, org_a_full_dataset):
        """Raw SQL (no ORM manager involved) must still be row-filtered."""
        org_a, org_b = two_orgs

        with set_tenant_context(org_a):
            with connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM farms_farm")
                assert cursor.fetchone()[0] >= 1

        with set_tenant_context(org_b):
            with connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM farms_farm")
                count_b = cursor.fetchone()[0]
                assert count_b == 0, (
                    f"Raw SQL bypasses RLS — org_b sees {count_b} farms"
                )

    def test_cross_tenant_write_is_rejected(self, two_orgs):
        """
        WITH CHECK side of the policy: inserting a row tagged org_a while
        org_b's context is active must be rejected by the database.
        """
        from decimal import Decimal

        from apps.farm.farms.models import Farm

        org_a, org_b = two_orgs
        with set_tenant_context(org_b):
            with pytest.raises(DatabaseError):
                # Inner atomic so the expected error doesn't poison the
                # surrounding test transaction.
                with transaction.atomic():
                    Farm.objects.create(
                        org=org_a,
                        name="Smuggled farm",
                        location="Lagos",
                        latitude=Decimal("6.5"),
                        longitude=Decimal("3.4"),
                    )


class TestCrossTenantIsolation:
    """
    For every tenant-scoped model:
      1. org_a sees its own record.
      2. org_b sees NOTHING (ORM manager — Layer 1).
      3. org_b sees NOTHING via .unscoped() (DB RLS — Layer 2, PG only).
      4. No context → empty queryset (fail-closed manager).
      5. Direct PK fetch from org_b's context → DoesNotExist.
    """

    @pytest.mark.parametrize("app_label,model_name", TENANT_SCOPED_MODELS)
    def test_org_b_cannot_see_org_a_records(
        self, app_label, model_name, two_orgs, org_a_full_dataset
    ):
        # Assertions target org_a's specific row rather than "org_b sees
        # zero rows total" — some models (e.g. AlertRule) are legitimately
        # seeded for EVERY new org, so org_b owning rows of its own is not
        # a leak. Seeing org_a's row is.
        org_a, org_b = two_orgs
        Model = _get_model(app_label, model_name)
        record = org_a_full_dataset[(app_label, model_name)]

        with set_tenant_context(org_a):
            assert Model.objects.filter(pk=record.pk).exists(), (
                f"{model_name}: org_a should see its own record — "
                f"fixture gap in org_a_full_dataset?"
            )

        with set_tenant_context(org_b):
            leak_orm = Model.objects.filter(pk=record.pk).count()
            assert leak_orm == 0, (
                f"{model_name}: org_b sees org_a's record via the "
                f"default manager — CROSS-TENANT LEAK (Layer 1)"
            )
            cross_probe = Model.objects.filter(org=org_a).count()
            assert cross_probe == 0, (
                f"{model_name}: org_b can query org_a's rows by "
                f"explicitly filtering org=org_a — CROSS-TENANT LEAK"
            )
            if connection.vendor == "postgresql":
                # .unscoped() bypasses the ORM org filter entirely — only
                # the DB policy stands between org_b and org_a's rows.
                leak_db = Model.objects.unscoped().filter(pk=record.pk).count()
                assert leak_db == 0, (
                    f"{model_name}: org_b sees org_a's record via "
                    f".unscoped() — DB RLS NOT ENFORCING (Layer 2)"
                )

        with no_tenant_context():
            count_none = Model.objects.filter(pk=record.pk).count()
            assert count_none == 0, (
                f"{model_name}: contextless query returned org_a's "
                f"record — manager is not failing closed"
            )

    @pytest.mark.parametrize("app_label,model_name", TENANT_SCOPED_MODELS)
    def test_org_b_cannot_fetch_org_a_record_by_pk(
        self, app_label, model_name, two_orgs, org_a_full_dataset
    ):
        """Even with the exact PK, org_b's context must not retrieve it."""
        org_a, org_b = two_orgs
        Model = _get_model(app_label, model_name)
        record = org_a_full_dataset[(app_label, model_name)]

        with set_tenant_context(org_b):
            with pytest.raises(ObjectDoesNotExist):
                Model.objects.get(pk=record.pk)
            if connection.vendor == "postgresql":
                with pytest.raises(ObjectDoesNotExist):
                    Model.objects.unscoped().get(pk=record.pk)


class TestSoftDeleteIsolation:
    """
    Soft delete must compose with tenant isolation:
      1. soft_delete() hides the row from the default (Active) manager.
      2. all_objects still exposes it WITHIN the owning org.
      3. org_b cannot see org_a's soft-deleted rows through any manager.
    """

    @pytest.mark.parametrize("app_label,model_name", SOFT_DELETE_MODELS)
    def test_soft_deleted_excluded_from_default_manager(
        self, app_label, model_name, two_orgs, org_a_full_dataset
    ):
        org_a, _ = two_orgs
        Model = _get_model(app_label, model_name)
        record = org_a_full_dataset[(app_label, model_name)]

        with set_tenant_context(org_a):
            record.soft_delete()
            assert not Model.objects.filter(pk=record.pk).exists(), (
                f"{model_name}: soft-deleted record still visible via the "
                f"default manager"
            )
            assert Model.all_objects.filter(pk=record.pk).exists(), (
                f"{model_name}: soft-deleted record not reachable via "
                f"all_objects (restore panel would lose it)"
            )

    @pytest.mark.parametrize("app_label,model_name", SOFT_DELETE_MODELS)
    def test_org_b_cannot_see_org_a_soft_deleted_records(
        self, app_label, model_name, two_orgs, org_a_full_dataset
    ):
        org_a, org_b = two_orgs
        Model = _get_model(app_label, model_name)
        record = org_a_full_dataset[(app_label, model_name)]

        with set_tenant_context(org_a):
            record.soft_delete()

        with set_tenant_context(org_b):
            assert Model.all_objects.filter(pk=record.pk).count() == 0, (
                f"{model_name}: org_b's all_objects sees org_a's "
                f"soft-deleted record (Layer 1)"
            )
            if connection.vendor == "postgresql":
                leak = Model.all_objects.unscoped().filter(pk=record.pk).count()
                assert leak == 0, (
                    f"{model_name}: org_b reaches org_a's soft-deleted "
                    f"record via all_objects.unscoped() — DB RLS NOT "
                    f"ENFORCING (Layer 2)"
                )


class TestCustomUserIsolation:
    """
    CustomUser is the deliberate special case: its default manager is
    UNSCOPED (Django auth needs cross-tenant lookups at login), and
    tenant-scoped queries must use .tenant_objects. Verify the scoped
    manager actually scopes.
    """

    def test_tenant_objects_scopes_to_current_org(self, two_orgs, org_a_user):
        from apps.infrastructure.accounts.models import CustomUser

        org_a, org_b = two_orgs

        with set_tenant_context(org_a):
            assert CustomUser.tenant_objects.filter(
                pk=org_a_user.pk
            ).exists(), "org_a cannot see its own user via tenant_objects"

        with set_tenant_context(org_b):
            assert not CustomUser.tenant_objects.filter(
                pk=org_a_user.pk
            ).exists(), (
                "org_b sees org_a's user via tenant_objects — "
                "CROSS-TENANT LEAK"
            )
