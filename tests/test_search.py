"""
Global search coverage tests.

Exercises GlobalSearchView (apps/infrastructure/core/search.py) after the audit
expansion: new entity types (House, Team Member, Medication, Outbreak, Sale),
RBAC parity fixes (Expense, Vaccination), tenant-scoped team search, and the
per-type truncation indicator.

``tenant_user`` (from conftest) is the org owner; helper ``_role_user`` mints
same-org users with other roles.
"""
from datetime import date, timedelta

import pytest

from apps.infrastructure.core.rls import set_tenant_context

pytestmark = pytest.mark.django_db

SEARCH_URL = "/search/"


# ── Helpers ───────────────────────────────────────────────────────────────────


def _role_user(org, role, suffix="x"):
    from apps.infrastructure.accounts.models import CustomUser

    return CustomUser.objects.create_user(
        username=f"{role}-{suffix}-{org.subdomain}",
        email=f"{role}-{suffix}@{org.subdomain}.com",
        password="testpass123",
        org=org,
        role=role,
        first_name=role.title(),
        last_name="User",
        email_verified=True,
    )


def _search(client, q):
    return client.get(SEARCH_URL, {"q": q})


def _types(response):
    return [r["type"] for r in response.context["results"]]


def _titles(response):
    return [r["title"] for r in response.context["results"]]


# ── Entity factories (org context required for TenantAware inserts) ────────────


def _make_expense(org, farm, description):
    from apps.finance.expenses.models import ExpenseRecord

    with set_tenant_context(org):
        return ExpenseRecord.objects.create(
            org=org,
            farm=farm,
            category="feed",
            amount_kobo=500000,
            description=description,
            expense_date=date.today(),
        )


def _make_vaccination(org, farm, batch, vaccine_name):
    from apps.health.health.models import VaccinationSchedule

    with set_tenant_context(org):
        return VaccinationSchedule.objects.create(
            org=org,
            farm=farm,
            batch=batch,
            vaccine_name=vaccine_name,
            due_date=date.today() + timedelta(days=3),
        )


def _make_medication(org, farm, batch, drug_name):
    from apps.health.health.models import MedicationRecord

    with set_tenant_context(org):
        return MedicationRecord.objects.create(
            org=org,
            farm=farm,
            batch=batch,
            drug_name=drug_name,
            start_date=date.today(),
            duration_days=5,
            dosage="10ml/L",
            quantity_used=50,
        )


def _make_outbreak(org, farm, disease_name):
    from apps.health.health.models import OutbreakAlert

    with set_tenant_context(org):
        return OutbreakAlert.objects.create(
            org=org,
            farm=farm,
            disease_name=disease_name,
            severity="warning",
        )


def _make_sale(org, farm, batch, buyer_name):
    from apps.finance.finance.models import SalesRecord

    with set_tenant_context(org):
        return SalesRecord.objects.create(
            org=org,
            farm=farm,
            batch=batch,
            sale_date=date.today(),
            product_type="eggs",
            quantity=10,
            unit="crates",
            unit_price_kobo=120000,
            buyer_name=buyer_name,
        )


# ── House search ──────────────────────────────────────────────────────────────


class TestHouseSearch:
    def test_house_appears_for_matching_name(
        self, client, tenant_user, test_org, test_farm
    ):
        from apps.farm.farms.models import House

        with set_tenant_context(test_org):
            House.objects.create(
                org=test_org, farm=test_farm, name="Brooder Hut", capacity=300
            )
        client.force_login(tenant_user)
        resp = _search(client, "Brooder")
        assert "House" in _types(resp)
        assert "Brooder Hut" in _titles(resp)

    def test_house_visible_to_data_entry(
        self, client, test_org, test_farm
    ):
        from apps.farm.farms.models import House

        with set_tenant_context(test_org):
            House.objects.create(
                org=test_org, farm=test_farm, name="Layer Pen Z", capacity=400
            )
        user = _role_user(test_org, "data_entry")
        client.force_login(user)
        resp = _search(client, "Layer Pen Z")
        assert "Layer Pen Z" in _titles(resp)


# ── Team member (CustomUser) search ───────────────────────────────────────────


class TestTeamMemberSearch:
    def _add_member(self, org):
        from apps.infrastructure.accounts.models import CustomUser

        return CustomUser.objects.create_user(
            username=f"findme-{org.subdomain}",
            email=f"findme@{org.subdomain}.com",
            password="testpass123",
            org=org,
            role="supervisor",
            first_name="Findme",
            last_name="Person",
            email_verified=True,
        )

    def test_owner_sees_team_member(self, client, tenant_user, test_org):
        self._add_member(test_org)
        client.force_login(tenant_user)
        resp = _search(client, "Findme")
        assert "Team Member" in _types(resp)
        assert "Findme Person" in _titles(resp)

    def test_manager_sees_team_member(self, client, test_org):
        self._add_member(test_org)
        manager = _role_user(test_org, "manager")
        client.force_login(manager)
        resp = _search(client, "Findme")
        assert "Team Member" in _types(resp)

    @pytest.mark.parametrize("role", ["supervisor", "data_entry", "vet_advisor"])
    def test_lower_roles_do_not_see_team_member(self, client, test_org, role):
        self._add_member(test_org)
        user = _role_user(test_org, role, suffix="lookup")
        client.force_login(user)
        resp = _search(client, "Findme")
        assert "Team Member" not in _types(resp)

    def test_team_search_is_tenant_scoped(self, client, tenant_user, test_org):
        """An org_b member must never surface in org_a's search."""
        import uuid

        from apps.infrastructure.accounts.models import CustomUser
        from apps.infrastructure.tenants.models import Organization

        org_b = Organization.objects.create(
            name="Other Farm Ltd",
            subdomain=f"otherfarm-{uuid.uuid4().hex[:8]}",
            plan_tier="monthly",
            subscription_status="active",
            onboarding_complete=True,
            is_active=True,
        )
        CustomUser.objects.create_user(
            username=f"findme-{org_b.subdomain}",
            email=f"findme@{org_b.subdomain}.com",
            password="testpass123",
            org=org_b,
            role="manager",
            first_name="Findme",
            last_name="Stranger",
            email_verified=True,
        )
        client.force_login(tenant_user)
        resp = _search(client, "Findme")
        assert "Findme Stranger" not in _titles(resp)


# ── Expense RBAC parity (supervisor + data_entry now included) ─────────────────


class TestExpenseSearchRBAC:
    @pytest.mark.parametrize(
        "role", ["owner", "manager", "supervisor", "data_entry"]
    )
    def test_operational_roles_see_expense(
        self, client, test_org, test_farm, role
    ):
        _make_expense(test_org, test_farm, "Special Drum Purchase")
        user = _role_user(test_org, role, suffix="exp")
        client.force_login(user)
        resp = _search(client, "Special Drum")
        assert "Expense" in _types(resp)

    def test_vet_advisor_excluded_from_expense(
        self, client, test_org, test_farm
    ):
        _make_expense(test_org, test_farm, "Special Drum Purchase")
        user = _role_user(test_org, "vet_advisor", suffix="exp")
        client.force_login(user)
        resp = _search(client, "Special Drum")
        assert "Expense" not in _types(resp)


# ── Vaccination RBAC parity (data_entry now included) ─────────────────────────


class TestVaccinationSearchRBAC:
    def test_data_entry_sees_vaccination(
        self, client, test_org, test_farm, test_batch
    ):
        _make_vaccination(test_org, test_farm, test_batch, "Gumboro Vax")
        user = _role_user(test_org, "data_entry", suffix="vacc")
        client.force_login(user)
        resp = _search(client, "Gumboro")
        assert "Vaccination" in _types(resp)


# ── Medication / Outbreak search ──────────────────────────────────────────────


class TestHealthSearch:
    def test_vet_advisor_sees_medication_and_outbreak(
        self, client, test_org, test_farm, test_batch
    ):
        _make_medication(test_org, test_farm, test_batch, "Amoxiclav")
        _make_outbreak(test_org, test_farm, "Newcastle Outbreak")
        user = _role_user(test_org, "vet_advisor", suffix="health")
        client.force_login(user)
        resp = _search(client, "Amoxiclav")
        assert "Medication" in _types(resp)
        resp2 = _search(client, "Newcastle")
        assert "Outbreak Alert" in _types(resp2)

    def test_data_entry_excluded_from_medication(
        self, client, test_org, test_farm, test_batch
    ):
        _make_medication(test_org, test_farm, test_batch, "Amoxiclav")
        user = _role_user(test_org, "data_entry", suffix="health")
        client.force_login(user)
        resp = _search(client, "Amoxiclav")
        assert "Medication" not in _types(resp)


# ── Sales search ──────────────────────────────────────────────────────────────


class TestSalesSearch:
    @pytest.mark.parametrize("role", ["owner", "manager", "supervisor"])
    def test_finance_tier_sees_sale(
        self, client, test_org, test_farm, test_batch, role
    ):
        _make_sale(test_org, test_farm, test_batch, "Mama Ngozi")
        user = _role_user(test_org, role, suffix="sale")
        client.force_login(user)
        resp = _search(client, "Ngozi")
        assert "Sale" in _types(resp)
        assert "Sale to Mama Ngozi" in _titles(resp)

    @pytest.mark.parametrize("role", ["data_entry", "vet_advisor"])
    def test_lower_roles_excluded_from_sale(
        self, client, test_org, test_farm, test_batch, role
    ):
        _make_sale(test_org, test_farm, test_batch, "Mama Ngozi")
        user = _role_user(test_org, role, suffix="sale")
        client.force_login(user)
        resp = _search(client, "Ngozi")
        assert "Sale" not in _types(resp)


# ── Truncation indicator ──────────────────────────────────────────────────────


class TestTruncationIndicator:
    def test_truncated_types_populated_when_over_cap(
        self, client, tenant_user, test_org, test_farm
    ):
        from apps.farm.farms.models import House

        # House cap is 5 — create 6 matching to trip the indicator.
        with set_tenant_context(test_org):
            for i in range(6):
                House.objects.create(
                    org=test_org,
                    farm=test_farm,
                    name=f"Coopzz {i}",
                    capacity=100,
                )
        client.force_login(tenant_user)
        resp = _search(client, "Coopzz")
        assert "House" in resp.context["truncated_types"]
        # Only 5 of the 6 rendered.
        assert _types(resp).count("House") == 5

    def test_no_truncation_when_under_cap(
        self, client, tenant_user, test_org, test_farm
    ):
        from apps.farm.farms.models import House

        with set_tenant_context(test_org):
            House.objects.create(
                org=test_org, farm=test_farm, name="Solohouse", capacity=100
            )
        client.force_login(tenant_user)
        resp = _search(client, "Solohouse")
        assert "House" not in resp.context["truncated_types"]
