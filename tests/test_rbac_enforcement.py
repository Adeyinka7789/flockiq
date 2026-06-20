"""
RBAC enforcement tests.

Verifies server-side role enforcement added via RoleRequiredMixin (web views),
DRF permission classes (API views) and the financial-notification role floor.

Roles: owner, manager, supervisor, data_entry, vet_advisor.
``tenant_user`` (from conftest) is the org owner.
"""
import uuid
from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.infrastructure.core.rls import set_tenant_context

pytestmark = pytest.mark.django_db


def _other_org():
    from apps.infrastructure.tenants.models import Organization
    return Organization.objects.create(
        name="Other Org", subdomain=f"other-{uuid.uuid4().hex[:8]}"
    )


def _make_farm(test_org, name="Second Farm"):
    from apps.farm.farms.models import Farm
    with set_tenant_context(test_org):
        return Farm.objects.create(
            org=test_org, name=name, location="Kano",
            latitude=Decimal("8.0"), longitude=Decimal("8.0"), farm_type="mixed",
        )


# ── Role-user fixtures (all in the same org as tenant_user/test_org) ───────────

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
def vet_advisor_user(db, test_org):
    return _make_user(test_org, "vet_advisor", test_org.subdomain)


# ── CRITICAL: data export (owner only) ────────────────────────────────────────

class TestDataExportRBAC:
    URL = "accounts:export_data"

    def test_data_entry_cannot_export(self, client, data_entry_user):
        client.force_login(data_entry_user)
        assert client.get(reverse(self.URL)).status_code == 403

    def test_vet_advisor_cannot_export(self, client, vet_advisor_user):
        client.force_login(vet_advisor_user)
        assert client.get(reverse(self.URL)).status_code == 403

    def test_supervisor_cannot_export(self, client, supervisor_user):
        client.force_login(supervisor_user)
        assert client.get(reverse(self.URL)).status_code == 403

    def test_owner_can_export(self, client, tenant_user):
        client.force_login(tenant_user)
        assert client.get(reverse(self.URL)).status_code == 200


# ── CRITICAL: credit score (owner + manager only) ─────────────────────────────

class TestCreditScoreRBAC:
    URL = "/finance/credit-score/"

    def test_data_entry_cannot_view(self, client, data_entry_user):
        client.force_login(data_entry_user)
        assert client.get(self.URL).status_code == 403

    def test_vet_advisor_cannot_view(self, client, vet_advisor_user):
        client.force_login(vet_advisor_user)
        assert client.get(self.URL).status_code == 403

    def test_manager_can_view(self, client, manager_user):
        client.force_login(manager_user)
        assert client.get(self.URL).status_code == 200

    def test_owner_can_view(self, client, tenant_user):
        client.force_login(tenant_user)
        assert client.get(self.URL).status_code == 200


# ── HIGH: billing page (owner + manager read-only; owner-only mutations) ───────

class TestBillingRBAC:
    PAGE = "/billing/"
    UPGRADE = "/billing/upgrade/"

    def test_supervisor_cannot_view_billing(self, client, supervisor_user):
        client.force_login(supervisor_user)
        assert client.get(self.PAGE).status_code == 403

    def test_data_entry_cannot_view_billing(self, client, data_entry_user):
        client.force_login(data_entry_user)
        assert client.get(self.PAGE).status_code == 403

    def test_manager_can_view_billing(self, client, manager_user):
        client.force_login(manager_user)
        assert client.get(self.PAGE).status_code == 200

    def test_manager_cannot_upgrade(self, client, manager_user):
        client.force_login(manager_user)
        response = client.post(
            self.UPGRADE, {"plan_tier": "yearly", "timing": "immediate"}
        )
        assert response.status_code == 403

    def test_owner_can_view_billing(self, client, tenant_user):
        client.force_login(tenant_user)
        assert client.get(self.PAGE).status_code == 200


# ── MEDIUM: recording / structural views (vet_advisor blocked) ────────────────

class TestRecordingRBAC:

    def test_vet_advisor_cannot_post_mortality(self, client, vet_advisor_user, test_batch):
        client.force_login(vet_advisor_user)
        response = client.post(
            f"/batches/{test_batch.pk}/mortality/",
            {"count": 1, "cause": "disease", "date": date.today().isoformat()},
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 403

    def test_vet_advisor_cannot_post_feed_log(self, client, vet_advisor_user, test_batch):
        client.force_login(vet_advisor_user)
        response = client.post(
            f"/production/feed/{test_batch.pk}/log/",
            {
                "record_date": date.today().isoformat(),
                "feed_type": "layer_mash",
                "quantity_kg": "50",
            },
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 403

    def test_vet_advisor_cannot_create_batch(self, client, vet_advisor_user, test_farm):
        client.force_login(vet_advisor_user)
        response = client.post(
            f"/farms/{test_farm.pk}/batches/create/",
            {},
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 403

    def test_data_entry_cannot_view_pl_summary(self, client, data_entry_user, test_batch):
        client.force_login(data_entry_user)
        assert client.get(f"/finance/pl/{test_batch.pk}/").status_code == 403

    def test_data_entry_can_post_mortality(self, client, data_entry_user, test_batch):
        client.force_login(data_entry_user)
        response = client.post(
            f"/batches/{test_batch.pk}/mortality/",
            {"count": 2, "cause": "disease", "date": date.today().isoformat()},
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200


# ── DRF API permission wiring ─────────────────────────────────────────────────

class TestApiPermissionRBAC:

    def _api(self, user):
        from rest_framework.test import APIClient
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def test_vet_advisor_cannot_post_mortality_api(self, vet_advisor_user, test_batch):
        client = self._api(vet_advisor_user)
        response = client.post(
            f"/api/v1/flocks/batches/{test_batch.pk}/mortality/",
            {"count": 1, "cause": "disease", "date": date.today().isoformat()},
            format="json",
        )
        assert response.status_code == 403

    def test_vet_advisor_cannot_post_feed_log_api(self, vet_advisor_user, test_batch):
        client = self._api(vet_advisor_user)
        response = client.post(
            "/api/v1/feed/log/",
            {
                "batch_id": str(test_batch.pk),
                "record_date": date.today().isoformat(),
                "feed_type": "layer_mash",
                "quantity_kg": "50",
            },
            format="json",
        )
        assert response.status_code == 403

    def test_data_entry_can_list_batches_api(self, data_entry_user):
        # GET (read) is open to any authenticated tenant user.
        client = self._api(data_entry_user)
        assert client.get("/api/v1/flocks/batches/").status_code == 200

    def test_supervisor_can_list_batches_api(self, supervisor_user):
        client = self._api(supervisor_user)
        assert client.get("/api/v1/flocks/batches/").status_code == 200

    def test_data_entry_cannot_create_batch_api(self, data_entry_user):
        # Writes (POST) require supervisor or above.
        client = self._api(data_entry_user)
        assert client.post("/api/v1/flocks/batches/", {}, format="json").status_code == 403


# ── Market Intelligence & AI Analytics (supervisor and above) ─────────────────

class TestMarketAndAnalyticsRBAC:

    def test_data_entry_cannot_view_market_prices(self, client, data_entry_user):
        client.force_login(data_entry_user)
        assert client.get("/market/prices/").status_code == 403

    def test_vet_advisor_cannot_view_feed_prices(self, client, vet_advisor_user):
        client.force_login(vet_advisor_user)
        assert client.get("/market/feed-prices/").status_code == 403

    def test_data_entry_cannot_view_hatcheries(self, client, data_entry_user):
        client.force_login(data_entry_user)
        assert client.get("/market/hatcheries/").status_code == 403

    def test_supervisor_can_view_market_prices(self, client, supervisor_user):
        client.force_login(supervisor_user)
        assert client.get("/market/prices/").status_code == 200

    def test_data_entry_cannot_view_ai_analytics(self, client, data_entry_user):
        client.force_login(data_entry_user)
        assert client.get("/analytics/").status_code == 403

    def test_supervisor_can_view_ai_analytics(self, client, supervisor_user):
        client.force_login(supervisor_user)
        assert client.get("/analytics/").status_code == 200


# ── Bank transfer notify (owner only) ─────────────────────────────────────────

class TestBankTransferRBAC:
    URL = "/billing/bank-transfer/notify/"

    def test_manager_cannot_notify_bank_transfer(self, client, manager_user):
        client.force_login(manager_user)
        response = client.post(
            self.URL, {"plan_tier": "yearly", "amount": "50000"}
        )
        assert response.status_code == 403

    def test_data_entry_cannot_notify_bank_transfer(self, client, data_entry_user):
        client.force_login(data_entry_user)
        response = client.post(
            self.URL, {"plan_tier": "yearly", "amount": "50000"}
        )
        assert response.status_code == 403


# ── MEDIUM: production logging parity (vet_advisor blocked, data_entry allowed) ─

class TestProductionLoggingRBAC:
    """ProductionLogView / WaterLogView / WasteLogView gate writes the same way
    as FeedLogView / MortalityLogView: owner, manager, supervisor, data_entry may
    log; vet_advisor (read-only) is excluded.
    """

    def _egg_log(self, client, batch):
        return client.post(
            f"/production/eggs/{batch.pk}/log/",
            {"record_date": date.today().isoformat(), "total_eggs": "100"},
            HTTP_HX_REQUEST="true",
        )

    def _water_log(self, client, batch):
        return client.post(
            f"/production/water/{batch.pk}/log/",
            {"record_date": date.today().isoformat(), "litres_consumed": "50"},
            HTTP_HX_REQUEST="true",
        )

    def _waste_log(self, client, farm):
        return client.post(
            f"/production/waste/{farm.pk}/log/",
            {
                "record_date": date.today().isoformat(),
                "waste_type": "litter",
                "quantity_kg": "10",
                "disposal_method": "composting",
            },
            HTTP_HX_REQUEST="true",
        )

    # vet_advisor — blocked on all three
    def test_vet_advisor_cannot_post_production(self, client, vet_advisor_user, test_batch):
        client.force_login(vet_advisor_user)
        assert self._egg_log(client, test_batch).status_code == 403

    def test_vet_advisor_cannot_post_water(self, client, vet_advisor_user, test_batch):
        client.force_login(vet_advisor_user)
        assert self._water_log(client, test_batch).status_code == 403

    def test_vet_advisor_cannot_post_waste(self, client, vet_advisor_user, test_farm):
        client.force_login(vet_advisor_user)
        assert self._waste_log(client, test_farm).status_code == 403

    # data_entry — allowed on all three
    def test_data_entry_can_post_production(self, client, data_entry_user, test_batch):
        client.force_login(data_entry_user)
        assert self._egg_log(client, test_batch).status_code == 200

    def test_data_entry_can_post_water(self, client, data_entry_user, test_batch):
        client.force_login(data_entry_user)
        assert self._water_log(client, test_batch).status_code == 200

    def test_data_entry_can_post_waste(self, client, data_entry_user, test_farm):
        client.force_login(data_entry_user)
        assert self._waste_log(client, test_farm).status_code == 200

    # supervisor — allowed on all three
    def test_supervisor_can_post_production(self, client, supervisor_user, test_batch):
        client.force_login(supervisor_user)
        assert self._egg_log(client, test_batch).status_code == 200

    def test_supervisor_can_post_water(self, client, supervisor_user, test_batch):
        client.force_login(supervisor_user)
        assert self._water_log(client, test_batch).status_code == 200

    def test_supervisor_can_post_waste(self, client, supervisor_user, test_farm):
        client.force_login(supervisor_user)
        assert self._waste_log(client, test_farm).status_code == 200


# ── MEDIUM: task hard-delete (owner / manager / supervisor only) ──────────────

class TestTaskDeleteRBAC:
    """TaskDeleteView hard-deletes an ephemeral FarmTask — restricted to
    owner / manager / supervisor. data_entry and vet_advisor cannot delete.
    """

    def _make_task(self, org, user):
        from apps.farm.tasks.models import FarmTask
        from apps.infrastructure.core.rls import set_tenant_context

        with set_tenant_context(org):
            return FarmTask.objects.create(
                org=org,
                title="Vaccinate flock",
                status="pending",
                created_by=user,
            )

    def _delete(self, client, task):
        return client.post(
            f"/tasks/{task.pk}/delete/",
            HTTP_HX_REQUEST="true",
        )

    def test_vet_advisor_cannot_delete_task(self, client, vet_advisor_user, test_org, tenant_user):
        task = self._make_task(test_org, tenant_user)
        client.force_login(vet_advisor_user)
        assert self._delete(client, task).status_code == 403

    def test_data_entry_cannot_delete_task(self, client, data_entry_user, test_org, tenant_user):
        task = self._make_task(test_org, tenant_user)
        client.force_login(data_entry_user)
        assert self._delete(client, task).status_code == 403

    def test_supervisor_can_delete_task(self, client, supervisor_user, test_org, tenant_user):
        task = self._make_task(test_org, tenant_user)
        client.force_login(supervisor_user)
        assert self._delete(client, task).status_code == 204

    def test_owner_can_delete_task(self, client, tenant_user, test_org):
        task = self._make_task(test_org, tenant_user)
        client.force_login(tenant_user)
        assert self._delete(client, task).status_code == 204


# ── Farm edit (owner + manager only) ──────────────────────────────────────────

class TestFarmEditRBAC:
    def _url(self, farm):
        return f"/farms/{farm.pk}/edit/"

    def test_owner_can_get_edit_form(self, client, tenant_user, test_farm):
        client.force_login(tenant_user)
        assert client.get(self._url(test_farm), HTTP_HX_REQUEST="true").status_code == 200

    def test_manager_can_get_edit_form(self, client, manager_user, test_farm):
        client.force_login(manager_user)
        assert client.get(self._url(test_farm), HTTP_HX_REQUEST="true").status_code == 200

    def test_supervisor_cannot_edit_farm(self, client, supervisor_user, test_farm):
        client.force_login(supervisor_user)
        assert client.get(self._url(test_farm), HTTP_HX_REQUEST="true").status_code == 403

    def test_data_entry_cannot_edit_farm(self, client, data_entry_user, test_farm):
        client.force_login(data_entry_user)
        assert client.get(self._url(test_farm), HTTP_HX_REQUEST="true").status_code == 403

    def test_post_updates_editable_fields(self, client, tenant_user, test_org, test_farm):
        from apps.farm.farms.models import Farm
        client.force_login(tenant_user)
        r = client.post(
            self._url(test_farm),
            {"name": "Renamed Farm", "location": "Abuja",
             "farm_type": "broiler", "notes": "updated notes"},
            HTTP_HX_REQUEST="true",
        )
        assert r.status_code == 204
        with set_tenant_context(test_org):
            farm = Farm.objects.get(id=test_farm.pk)
        assert farm.name == "Renamed Farm"
        assert farm.location == "Abuja"
        assert farm.farm_type == "broiler"
        assert farm.notes == "updated notes"

    def test_post_cannot_change_org(self, client, tenant_user, test_org, test_farm):
        from apps.farm.farms.models import Farm
        client.force_login(tenant_user)
        other = _other_org()
        r = client.post(
            self._url(test_farm),
            {"name": test_farm.name, "location": test_farm.location,
             "farm_type": test_farm.farm_type, "org": str(other.id)},
            HTTP_HX_REQUEST="true",
        )
        assert r.status_code == 204
        with set_tenant_context(test_org):
            farm = Farm.objects.get(id=test_farm.pk)
        assert farm.org_id == test_org.id

    def test_htmx_post_returns_toast(self, client, tenant_user, test_farm):
        client.force_login(tenant_user)
        r = client.post(
            self._url(test_farm),
            {"name": "Toast Farm", "location": "Lagos", "farm_type": "mixed"},
            HTTP_HX_REQUEST="true",
        )
        assert r.status_code == 204
        assert "showToast" in r.headers["HX-Trigger"]


# ── House edit (owner + manager only) ─────────────────────────────────────────

class TestHouseEditRBAC:
    def _url(self, house):
        return f"/houses/{house.pk}/edit/"

    def test_owner_can_edit_house(self, client, tenant_user, test_house):
        client.force_login(tenant_user)
        assert client.get(self._url(test_house), HTTP_HX_REQUEST="true").status_code == 200

    def test_manager_can_edit_house(self, client, manager_user, test_house):
        client.force_login(manager_user)
        assert client.get(self._url(test_house), HTTP_HX_REQUEST="true").status_code == 200

    def test_supervisor_cannot_edit_house(self, client, supervisor_user, test_house):
        client.force_login(supervisor_user)
        assert client.get(self._url(test_house), HTTP_HX_REQUEST="true").status_code == 403

    def test_data_entry_cannot_edit_house(self, client, data_entry_user, test_house):
        client.force_login(data_entry_user)
        assert client.get(self._url(test_house), HTTP_HX_REQUEST="true").status_code == 403

    def test_post_updates_name_and_capacity(self, client, tenant_user, test_org, test_house):
        from apps.farm.farms.models import House
        client.force_login(tenant_user)
        r = client.post(
            self._url(test_house),
            {"name": "House Z", "capacity": "750", "house_type": "broiler"},
            HTTP_HX_REQUEST="true",
        )
        assert r.status_code == 204
        with set_tenant_context(test_org):
            house = House.objects.get(id=test_house.pk)
        assert house.name == "House Z"
        assert house.capacity == 750

    def test_post_cannot_change_farm(self, client, tenant_user, test_org, test_house):
        from apps.farm.farms.models import House
        client.force_login(tenant_user)
        original_farm_id = test_house.farm_id
        other_farm = _make_farm(test_org, name="Farm Two")
        r = client.post(
            self._url(test_house),
            {"name": test_house.name, "capacity": str(test_house.capacity),
             "house_type": test_house.house_type, "farm": str(other_farm.id)},
            HTTP_HX_REQUEST="true",
        )
        assert r.status_code == 204
        with set_tenant_context(test_org):
            house = House.objects.get(id=test_house.pk)
        assert house.farm_id == original_farm_id


# ── Batch edit (owner + manager only) ─────────────────────────────────────────

class TestBatchEditRBAC:
    def _url(self, batch):
        return f"/batches/{batch.pk}/edit/"

    def test_owner_can_get_edit_form(self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        assert client.get(self._url(test_batch), HTTP_HX_REQUEST="true").status_code == 200

    def test_manager_can_get_edit_form(self, client, manager_user, test_batch):
        client.force_login(manager_user)
        assert client.get(self._url(test_batch), HTTP_HX_REQUEST="true").status_code == 200

    def test_supervisor_cannot_edit_batch(self, client, supervisor_user, test_batch):
        client.force_login(supervisor_user)
        assert client.get(self._url(test_batch), HTTP_HX_REQUEST="true").status_code == 403

    def test_data_entry_cannot_edit_batch(self, client, data_entry_user, test_batch):
        client.force_login(data_entry_user)
        assert client.get(self._url(test_batch), HTTP_HX_REQUEST="true").status_code == 403

    def test_post_updates_descriptive_fields(self, client, tenant_user, test_org, test_batch):
        from apps.farm.flocks.models import Batch
        client.force_login(tenant_user)
        r = client.post(
            self._url(test_batch),
            {"batch_name": "Batch X", "breed_name": "ISA Brown",
             "bird_type": "layer", "notes": "note edit"},
            HTTP_HX_REQUEST="true",
        )
        assert r.status_code == 204
        with set_tenant_context(test_org):
            batch = Batch.objects.get(id=test_batch.pk)
        assert batch.batch_name == "Batch X"
        assert batch.breed_name == "ISA Brown"
        assert batch.notes == "note edit"

    def test_post_cannot_change_initial_count(self, client, tenant_user, test_org, test_batch):
        from apps.farm.flocks.models import Batch
        client.force_login(tenant_user)
        original = test_batch.initial_count
        r = client.post(
            self._url(test_batch),
            {"batch_name": test_batch.batch_name, "bird_type": test_batch.bird_type,
             "initial_count": "9999"},
            HTTP_HX_REQUEST="true",
        )
        assert r.status_code == 204
        with set_tenant_context(test_org):
            batch = Batch.objects.get(id=test_batch.pk)
        assert batch.initial_count == original

    def test_post_cannot_change_placement_date(self, client, tenant_user, test_org, test_batch):
        from apps.farm.flocks.models import Batch
        client.force_login(tenant_user)
        original = test_batch.placement_date
        r = client.post(
            self._url(test_batch),
            {"batch_name": test_batch.batch_name, "bird_type": test_batch.bird_type,
             "placement_date": "2020-01-01"},
            HTTP_HX_REQUEST="true",
        )
        assert r.status_code == 204
        with set_tenant_context(test_org):
            batch = Batch.objects.get(id=test_batch.pk)
        assert batch.placement_date == original

    def test_post_cannot_change_farm(self, client, tenant_user, test_org, test_batch):
        from apps.farm.flocks.models import Batch
        client.force_login(tenant_user)
        original_farm_id = test_batch.farm_id
        other_farm = _make_farm(test_org, name="Farm Three")
        r = client.post(
            self._url(test_batch),
            {"batch_name": test_batch.batch_name, "bird_type": test_batch.bird_type,
             "farm": str(other_farm.id)},
            HTTP_HX_REQUEST="true",
        )
        assert r.status_code == 204
        with set_tenant_context(test_org):
            batch = Batch.objects.get(id=test_batch.pk)
        assert batch.farm_id == original_farm_id


# ── NOTIFICATIONS: financial role floor ───────────────────────────────────────

class TestNotificationFinancialFloor:
    """Financial events must never reach data_entry / vet_advisor."""

    def _setup(self, test_org):
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.infrastructure.notifications.models import AlertRule

        roles = ["owner", "manager", "supervisor", "data_entry", "vet_advisor"]
        users = {r: _make_user(test_org, r, f"notif-{r}") for r in roles}
        # A default sale_timing AlertRule is seeded on org creation; widen its
        # notify_roles to every role so the code-level floor (not the rule) is
        # what excludes data_entry / vet_advisor.
        with set_tenant_context(test_org):
            AlertRule.objects.update_or_create(
                org=test_org,
                event_type="sale_timing",
                defaults={
                    "notify_roles": roles,
                    "channels": ["in_app"],
                    "is_active": True,
                    "cooldown_minutes": 0,
                },
            )
        return users

    def _send_and_collect(self, test_org):
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.infrastructure.notifications.models import OutboxEvent
        from apps.infrastructure.notifications.services import NotificationService

        with set_tenant_context(test_org):
            NotificationService(test_org).send(
                "sale_timing",
                {"farm_name": "F", "batch_name": "B", "value": "1500"},
            )
        return set(
            OutboxEvent.objects.filter(
                org_id=test_org.id, event_type="sale_timing"
            ).values_list("recipient_user_id", flat=True)
        )

    def test_floor_blocks_and_allows_correct_roles(self, db, test_org):
        users = self._setup(test_org)
        recipient_ids = self._send_and_collect(test_org)

        # Created for owner + manager (and supervisor — not a restricted role).
        assert users["owner"].id in recipient_ids
        assert users["manager"].id in recipient_ids
        assert users["supervisor"].id in recipient_ids

        # NOT created for the restricted roles.
        assert users["data_entry"].id not in recipient_ids
        assert users["vet_advisor"].id not in recipient_ids
