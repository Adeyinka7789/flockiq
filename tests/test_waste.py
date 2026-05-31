"""
Phase 3B — Waste app tests.
"""

import datetime
from decimal import Decimal

import pytest

pytestmark = pytest.mark.django_db


# ── Helpers ─────────────────────────────────────────────────────────────────────

def _make_org(subdomain):
    from apps.infrastructure.tenants.models import Organization
    return Organization.objects.create(name="Waste Org", subdomain=subdomain)


def _make_user(org, email, username):
    from apps.infrastructure.accounts.models import CustomUser
    return CustomUser.objects.create_user(
        email=email, password="testpass123", username=username, org=org,
    )


def _make_farm(org, name="Waste Farm"):
    from apps.farm.farms.models import Farm
    farm = Farm(
        org=org, name=name, location="Kano",
        latitude=Decimal("12.0022"), longitude=Decimal("8.5920"),
        farm_type="layer",
    )
    farm.clean()
    farm.save()
    return farm


def _make_house(org, farm):
    from apps.farm.farms.models import House
    return House.objects.create(
        org=org, farm=farm, name="House A", capacity=2000, house_type="layer",
    )


def _log_waste(org, farm, quantity_kg=10, waste_type="litter"):
    from apps.production.waste.services import WasteService
    from apps.infrastructure.core.rls import set_tenant_context

    with set_tenant_context(org):
        return WasteService(org).log_waste(
            farm_id=str(farm.id),
            record_date=datetime.date.today(),
            waste_type=waste_type,
            quantity_kg=quantity_kg,
        )


# ── 1. WasteLog model ─────────────────────────────────────────────────────────────

class TestWasteLogModel:

    def test_waste_log_created(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        org = _make_org("wastemodel1")
        farm = _make_farm(org)

        with set_tenant_context(org):
            log = _log_waste(org, farm, quantity_kg=10, waste_type="litter")

        assert log.pk is not None
        assert float(log.quantity_kg) == 10.0
        assert log.waste_type == "litter"
        assert log.org == org

    def test_waste_log_with_batch_link(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.production.waste.services import WasteService
        org = _make_org("wastewithbatch")
        farm = _make_farm(org)
        house = _make_house(org, farm)

        from apps.farm.flocks.models import Batch
        batch = Batch.objects.create(
            org=org, farm=farm, house=house,
            batch_name="Waste Batch",
            bird_type="layer",
            placement_date=datetime.date.today() - datetime.timedelta(days=5),
            initial_count=500,
            current_count=500,
            status="active",
        )

        with set_tenant_context(org):
            log = WasteService(org).log_waste(
                farm_id=str(farm.id),
                record_date=datetime.date.today(),
                waste_type="dead_birds",
                quantity_kg=5,
                batch_id=str(batch.id),
            )

        assert log.batch == batch

    def test_waste_log_default_disposal_method(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        org = _make_org("wastedefault")
        farm = _make_farm(org)

        with set_tenant_context(org):
            log = _log_waste(org, farm)

        assert log.disposal_method == "composting"

    def test_waste_log_with_cost(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.production.waste.services import WasteService
        org = _make_org("wastecost")
        farm = _make_farm(org)

        with set_tenant_context(org):
            log = WasteService(org).log_waste(
                farm_id=str(farm.id),
                record_date=datetime.date.today(),
                waste_type="packaging",
                quantity_kg=5,
                cost=500,
            )

        assert float(log.cost) == 500.0


# ── 2. WasteService ───────────────────────────────────────────────────────────────

class TestWasteService:

    def test_waste_summary_returns_totals(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.production.waste.services import WasteService
        org = _make_org("wastesummary")
        farm = _make_farm(org)

        with set_tenant_context(org):
            _log_waste(org, farm, quantity_kg=10)
            _log_waste(org, farm, quantity_kg=5)
            summary = WasteService(org).get_waste_summary(str(farm.id))

        # Note: two logs created but unique_together not enforced for waste, so both created
        assert summary["total_quantity_kg"] == pytest.approx(15.0, abs=0.01)


# ── 3. HTMX views ─────────────────────────────────────────────────────────────────

class TestWasteHTMXViews:

    def _setup(self, db, subdomain):
        org = _make_org(subdomain)
        user = _make_user(org, f"{subdomain}@example.com", subdomain)
        farm = _make_farm(org)
        return org, user, farm

    def test_log_view_requires_login(self, db, client):
        import uuid
        response = client.post(f"/production/waste/{uuid.uuid4()}/log/", {})
        assert response.status_code in (302, 301)

    def test_log_view_valid_post_returns_200(self, db, client):
        org, user, farm = self._setup(db, "wasteview1")
        client.force_login(user)
        response = client.post(
            f"/production/waste/{farm.id}/log/",
            {
                "record_date": datetime.date.today().isoformat(),
                "waste_type": "litter",
                "quantity_kg": "10",
                "disposal_method": "composting",
                "cost": "",
                "notes": "",
            },
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        assert b"waste-table" in response.content

    def test_table_view_returns_200(self, db, client):
        org, user, farm = self._setup(db, "wasteviewtable")
        client.force_login(user)
        response = client.get(f"/production/waste/{farm.id}/table/")
        assert response.status_code == 200
        assert b"waste-table" in response.content


# ── 4. RLS isolation ──────────────────────────────────────────────────────────────

class TestWasteRLSIsolation:

    def test_waste_log_rls_isolation(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.production.waste.models import WasteLog

        org_a = _make_org("wasterlsa")
        farm_a = _make_farm(org_a, "Farm A")

        org_b = _make_org("wasterlsb")
        farm_b = _make_farm(org_b, "Farm B")

        with set_tenant_context(org_a):
            _log_waste(org_a, farm_a, quantity_kg=10)

        with set_tenant_context(org_b):
            _log_waste(org_b, farm_b, quantity_kg=8)

        with set_tenant_context(org_a):
            count_a = WasteLog.objects.count()

        with set_tenant_context(org_b):
            count_b = WasteLog.objects.count()

        assert count_a == 1
        assert count_b == 1
