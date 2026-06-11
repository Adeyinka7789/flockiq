"""
Soft-delete system tests.

Covers the permission matrix, typed-confirmation flow, manager behaviour
(default excludes deleted, all_objects includes them), the superadmin restore
panel, the 90-day hard-delete sweep and audit-trail creation.

Roles: owner, manager, supervisor, data_entry, vet_advisor.
``tenant_user`` (conftest) is the org owner.
"""
from datetime import date, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.infrastructure.core.rls import set_tenant_context

pytestmark = pytest.mark.django_db


# ── Role-user fixtures (same org as test_org) ─────────────────────────────────

def _make_user(org, role, suffix):
    from apps.infrastructure.accounts.models import CustomUser
    return CustomUser.objects.create_user(
        username=f"{role}-{suffix}",
        email=f"{role}-{suffix}@{org.subdomain}.com",
        password="testpass123",
        org=org,
        role=role,
        first_name=role.title(),
        last_name="User",
        email_verified=True,
    )


@pytest.fixture
def manager_user(db, test_org):
    return _make_user(test_org, "manager", test_org.subdomain)


@pytest.fixture
def supervisor_user(db, test_org):
    return _make_user(test_org, "supervisor", test_org.subdomain)


@pytest.fixture
def data_entry_user(db, test_org):
    return _make_user(test_org, "data_entry", test_org.subdomain)


@pytest.fixture
def mortality_log(db, test_org, test_farm, test_batch):
    from apps.farm.flocks.models import MortalityLog
    with set_tenant_context(test_org):
        return MortalityLog.objects.create(
            org=test_org,
            batch=test_batch,
            farm=test_farm,
            date=date.today(),
            count=3,
            cause="disease",
        )


# ── Farm deletion (owner only, typed name + phrase) ───────────────────────────

class TestFarmDeleteRBAC:

    def test_manager_cannot_delete_farm(self, client, manager_user, test_farm):
        client.force_login(manager_user)
        url = reverse("farms:delete", args=[test_farm.pk])
        resp = client.post(
            url,
            {"confirmation": test_farm.name, "confirmation_phrase": "DELETE FARM"},
            HTTP_HX_REQUEST="true",
        )
        assert resp.status_code == 403

    def test_supervisor_cannot_delete_farm(self, client, supervisor_user, test_farm):
        client.force_login(supervisor_user)
        url = reverse("farms:delete", args=[test_farm.pk])
        resp = client.post(url, {}, HTTP_HX_REQUEST="true")
        assert resp.status_code == 403

    def test_owner_can_delete_farm(self, client, tenant_user, test_farm, test_org):
        from apps.farm.farms.models import Farm
        client.force_login(tenant_user)
        url = reverse("farms:delete", args=[test_farm.pk])
        resp = client.post(
            url,
            {"confirmation": test_farm.name, "confirmation_phrase": "DELETE FARM"},
            HTTP_HX_REQUEST="true",
        )
        assert resp.status_code == 204
        with set_tenant_context(test_org):
            assert Farm.all_objects.get(pk=test_farm.pk).is_deleted is True

    def test_wrong_confirmation_returns_422(self, client, tenant_user, test_farm, test_org):
        from apps.farm.farms.models import Farm
        client.force_login(tenant_user)
        url = reverse("farms:delete", args=[test_farm.pk])
        resp = client.post(
            url,
            {"confirmation": "Wrong Name", "confirmation_phrase": "DELETE FARM"},
            HTTP_HX_REQUEST="true",
        )
        assert resp.status_code == 422
        with set_tenant_context(test_org):
            assert Farm.all_objects.get(pk=test_farm.pk).is_deleted is False

    def test_missing_phrase_returns_422(self, client, tenant_user, test_farm, test_org):
        from apps.farm.farms.models import Farm
        client.force_login(tenant_user)
        url = reverse("farms:delete", args=[test_farm.pk])
        resp = client.post(
            url,
            {"confirmation": test_farm.name, "confirmation_phrase": ""},
            HTTP_HX_REQUEST="true",
        )
        assert resp.status_code == 422
        with set_tenant_context(test_org):
            assert Farm.all_objects.get(pk=test_farm.pk).is_deleted is False


# ── Batch deletion (owner + manager, typed batch name) ────────────────────────

class TestBatchDeleteRBAC:

    def _delete(self, client, batch):
        url = reverse("flocks:delete", args=[batch.pk])
        return client.post(
            url, {"confirmation": batch.batch_name}, HTTP_HX_REQUEST="true"
        )

    def test_owner_can_delete_batch(self, client, tenant_user, test_batch, test_org):
        from apps.farm.flocks.models import Batch
        client.force_login(tenant_user)
        assert self._delete(client, test_batch).status_code == 204
        with set_tenant_context(test_org):
            assert Batch.all_objects.get(pk=test_batch.pk).is_deleted is True

    def test_manager_can_delete_batch(self, client, manager_user, test_batch, test_org):
        from apps.farm.flocks.models import Batch
        client.force_login(manager_user)
        assert self._delete(client, test_batch).status_code == 204
        with set_tenant_context(test_org):
            assert Batch.all_objects.get(pk=test_batch.pk).is_deleted is True

    def test_supervisor_cannot_delete_batch(self, client, supervisor_user, test_batch):
        client.force_login(supervisor_user)
        assert self._delete(client, test_batch).status_code == 403

    def test_wrong_batch_name_returns_422(self, client, tenant_user, test_batch, test_org):
        from apps.farm.flocks.models import Batch
        client.force_login(tenant_user)
        url = reverse("flocks:delete", args=[test_batch.pk])
        resp = client.post(url, {"confirmation": "nope"}, HTTP_HX_REQUEST="true")
        assert resp.status_code == 422
        with set_tenant_context(test_org):
            assert Batch.all_objects.get(pk=test_batch.pk).is_deleted is False


# ── Log deletion (owner + manager + supervisor, simple confirm) ───────────────

class TestMortalityLogDeleteRBAC:

    def test_supervisor_can_delete_mortality_log(
        self, client, supervisor_user, mortality_log, test_org
    ):
        from apps.farm.flocks.models import MortalityLog
        client.force_login(supervisor_user)
        url = reverse("flocks:mortality_delete", args=[mortality_log.pk])
        resp = client.post(url, {}, HTTP_HX_REQUEST="true")
        assert resp.status_code == 204
        with set_tenant_context(test_org):
            assert MortalityLog.all_objects.get(pk=mortality_log.pk).is_deleted is True

    def test_data_entry_cannot_delete_mortality_log(
        self, client, data_entry_user, mortality_log
    ):
        client.force_login(data_entry_user)
        url = reverse("flocks:mortality_delete", args=[mortality_log.pk])
        resp = client.post(url, {}, HTTP_HX_REQUEST="true")
        assert resp.status_code == 403


# ── Manager behaviour ─────────────────────────────────────────────────────────

class TestSoftDeleteManagers:

    def test_default_manager_excludes_deleted(self, test_org, test_farm):
        from apps.farm.farms.models import Farm
        with set_tenant_context(test_org):
            test_farm.soft_delete()
            assert not Farm.objects.filter(pk=test_farm.pk).exists()

    def test_all_objects_includes_deleted(self, test_org, test_farm):
        from apps.farm.farms.models import Farm
        with set_tenant_context(test_org):
            test_farm.soft_delete()
            assert Farm.all_objects.filter(pk=test_farm.pk).exists()

    def test_soft_deleted_row_still_in_db(self, test_org, test_farm):
        """Soft delete must never remove the row — it's recoverable."""
        from apps.farm.farms.models import Farm
        with set_tenant_context(test_org):
            test_farm.soft_delete()
            # Hidden from the default manager but still physically present.
            assert not Farm.objects.filter(pk=test_farm.pk).exists()
            assert Farm.all_objects.filter(pk=test_farm.pk).exists()

    def test_restore_clears_flags(self, test_org, test_farm):
        from apps.farm.farms.models import Farm
        with set_tenant_context(test_org):
            test_farm.soft_delete()
            test_farm.restore()
            assert Farm.objects.filter(pk=test_farm.pk).exists()
            refreshed = Farm.all_objects.get(pk=test_farm.pk)
            assert refreshed.is_deleted is False
            assert refreshed.deleted_at is None


# ── Superadmin restore panel ──────────────────────────────────────────────────

class TestSuperadminRestore:

    def test_superadmin_can_restore_deleted_farm(
        self, client, super_admin_user, test_org, test_farm
    ):
        from apps.farm.farms.models import Farm
        with set_tenant_context(test_org):
            test_farm.soft_delete()

        client.force_login(super_admin_user)
        resp = client.post(
            reverse("superadmin:deleted_records"),
            {"model": "farm", "pk": str(test_farm.pk), "org_id": str(test_org.id)},
            HTTP_HX_REQUEST="true",
        )
        assert resp.status_code == 204
        with set_tenant_context(test_org):
            assert Farm.all_objects.get(pk=test_farm.pk).is_deleted is False

    def test_deleted_records_page_renders(self, client, super_admin_user):
        client.force_login(super_admin_user)
        resp = client.get(reverse("superadmin:deleted_records"))
        assert resp.status_code == 200


# ── 90-day hard delete sweep ──────────────────────────────────────────────────

class TestHardDeleteTask:

    def test_hard_delete_removes_old_records(self, test_org):
        """A childless farm soft-deleted >90 days ago is purged from the DB."""
        from apps.farm.farms.models import Farm
        from apps.infrastructure.core.tasks import hard_delete_expired_records
        from decimal import Decimal

        old = timezone.now() - timedelta(days=91)
        with set_tenant_context(test_org):
            farm = Farm.objects.create(
                org=test_org,
                name="Stale Farm",
                location="Kano",
                latitude=Decimal("8.5"),
                longitude=Decimal("8.5"),
                farm_type="mixed",
            )
            farm.soft_delete()
            # Backdate deleted_at beyond the 90-day cutoff.
            Farm.all_objects.filter(pk=farm.pk).update(deleted_at=old)

        hard_delete_expired_records()

        with set_tenant_context(test_org):
            assert not Farm.all_objects.filter(pk=farm.pk).exists()

    def test_hard_delete_keeps_recent_records(self, test_org, test_farm):
        """A farm soft-deleted today must survive the sweep."""
        from apps.farm.farms.models import Farm
        from apps.infrastructure.core.tasks import hard_delete_expired_records

        with set_tenant_context(test_org):
            test_farm.soft_delete()

        hard_delete_expired_records()

        with set_tenant_context(test_org):
            assert Farm.all_objects.filter(pk=test_farm.pk).exists()


# ── Audit trail ───────────────────────────────────────────────────────────────

class TestSoftDeleteAuditTrail:

    def test_audit_entry_created_on_batch_deletion(
        self, client, tenant_user, test_batch
    ):
        from auditlog.models import LogEntry

        before = LogEntry.objects.filter(object_pk=str(test_batch.pk)).count()

        client.force_login(tenant_user)
        client.post(
            reverse("flocks:delete", args=[test_batch.pk]),
            {"confirmation": test_batch.batch_name},
            HTTP_HX_REQUEST="true",
        )

        after = LogEntry.objects.filter(object_pk=str(test_batch.pk)).count()
        assert after == before + 1
