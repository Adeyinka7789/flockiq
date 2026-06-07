import uuid
import pytest
from decimal import Decimal
from django.core.exceptions import ValidationError

pytestmark = pytest.mark.django_db


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_org(subdomain=None):
    from apps.infrastructure.tenants.models import Organization
    if subdomain is None:
        subdomain = f"testfarm-{uuid.uuid4().hex[:8]}"
    return Organization.objects.create(name="Test Org", subdomain=subdomain)


def _make_org2(subdomain=None):
    from apps.infrastructure.tenants.models import Organization
    if subdomain is None:
        subdomain = f"otherfarm-{uuid.uuid4().hex[:8]}"
    return Organization.objects.create(name="Other Org", subdomain=subdomain)


# ── Farm model tests ──────────────────────────────────────────────────────────

class TestFarmModel:

    def test_str_representation(self, db):
        from apps.farm.farms.models import Farm
        org = _make_org()
        farm = Farm(org=org, name="Sunrise Farm", location="Ibadan",
                    latitude=Decimal("7.3775"), longitude=Decimal("3.9470"),
                    farm_type="layer")
        farm.clean()
        farm.save()
        assert str(farm) == "Sunrise Farm"

    def test_valid_nigeria_coordinates_pass_clean(self, db):
        from apps.farm.farms.models import Farm
        org = _make_org()
        farm = Farm(org=org, name="Valid Farm", location="Lagos",
                    latitude=Decimal("6.5244"), longitude=Decimal("3.3792"),
                    farm_type="broiler")
        farm.clean()  # Should not raise

    def test_latitude_below_min_raises(self, db):
        from apps.farm.farms.models import Farm
        org = _make_org()
        farm = Farm(org=org, name="OOB Farm", location="Out of bounds",
                    latitude=Decimal("3.0"), longitude=Decimal("5.0"),
                    farm_type="layer")
        with pytest.raises(ValidationError, match="Latitude"):
            farm.clean()

    def test_latitude_above_max_raises(self, db):
        from apps.farm.farms.models import Farm
        org = _make_org()
        farm = Farm(org=org, name="OOB Farm", location="Out of bounds",
                    latitude=Decimal("15.0"), longitude=Decimal("5.0"),
                    farm_type="layer")
        with pytest.raises(ValidationError, match="Latitude"):
            farm.clean()

    def test_longitude_below_min_raises(self, db):
        from apps.farm.farms.models import Farm
        org = _make_org()
        farm = Farm(org=org, name="OOB Farm", location="Out of bounds",
                    latitude=Decimal("7.0"), longitude=Decimal("2.0"),
                    farm_type="layer")
        with pytest.raises(ValidationError, match="Longitude"):
            farm.clean()

    def test_longitude_above_max_raises(self, db):
        from apps.farm.farms.models import Farm
        org = _make_org()
        farm = Farm(org=org, name="OOB Farm", location="Out of bounds",
                    latitude=Decimal("7.0"), longitude=Decimal("16.0"),
                    farm_type="layer")
        with pytest.raises(ValidationError, match="Longitude"):
            farm.clean()

    def test_farm_type_choices(self, db):
        from apps.farm.farms.models import Farm
        org = _make_org()
        for ft in ("layer", "broiler", "mixed"):
            farm = Farm(org=org, name=f"Farm {ft}", location="Abuja",
                        latitude=Decimal("9.0"), longitude=Decimal("7.5"),
                        farm_type=ft)
            farm.clean()
            farm.save()

    def test_is_active_default_true(self, db):
        from apps.farm.farms.models import Farm
        org = _make_org()
        farm = Farm(org=org, name="Active Farm", location="Kano",
                    latitude=Decimal("12.0"), longitude=Decimal("8.5"),
                    farm_type="mixed")
        farm.clean()
        farm.save()
        assert farm.is_active is True


# ── House model tests ─────────────────────────────────────────────────────────

class TestHouseModel:

    def _create_farm(self, org, name="Test Farm"):
        from apps.farm.farms.models import Farm
        from apps.infrastructure.core.rls import set_tenant_context
        farm = Farm(org=org, name=name, location="Lagos",
                    latitude=Decimal("6.5244"), longitude=Decimal("3.3792"),
                    farm_type="layer")
        farm.clean()
        with set_tenant_context(org):
            farm.save()
        return farm

    def test_house_str(self, db):
        from apps.farm.farms.models import House
        org = _make_org()
        farm = self._create_farm(org)
        house = House.objects.create(org=org, farm=farm, name="House A",
                                     capacity=5000, house_type="layer")
        assert str(house) == "Test Farm — House A"

    def test_cross_tenant_assignment_raises(self, db):
        from apps.farm.farms.models import House
        org1 = _make_org("org1farm")
        org2 = _make_org2("org2farm")
        farm1 = self._create_farm(org1, "Farm 1")
        with pytest.raises(ValueError, match="Cross-tenant"):
            House.objects.create(org=org2, farm=farm1, name="Bad House",
                                 capacity=1000, house_type="mixed")

    def test_house_capacity_stored(self, db):
        from apps.farm.farms.models import House
        org = _make_org()
        farm = self._create_farm(org)
        house = House.objects.create(org=org, farm=farm, name="House B",
                                     capacity=2500, house_type="broiler")
        assert house.capacity == 2500

    def test_is_active_default_true(self, db):
        from apps.farm.farms.models import House
        org = _make_org()
        farm = self._create_farm(org)
        house = House.objects.create(org=org, farm=farm, name="House C",
                                     capacity=1000, house_type="mixed")
        assert house.is_active is True

    def test_occupancy_pct_zero_when_empty(self, db):
        from apps.farm.farms.models import House
        org = _make_org()
        farm = self._create_farm(org)
        house = House.objects.create(org=org, farm=farm, name="Empty House",
                                     capacity=1000, house_type="layer")
        assert house.current_occupancy == 0
        assert house.occupancy_pct == 0.0


# ── FarmService tests ─────────────────────────────────────────────────────────

class TestFarmService:

    def test_create_farm_returns_farm(self, db):
        from apps.farm.farms.services import FarmService
        from apps.infrastructure.core.rls import set_tenant_context
        org = _make_org()
        with set_tenant_context(org):
            farm = FarmService(org).create_farm(
                name="Service Farm",
                location="Abuja",
                lat=Decimal("9.0576"),
                lng=Decimal("7.4951"),
                farm_type="layer",
            )
        assert farm.pk is not None
        assert farm.name == "Service Farm"
        assert farm.org == org

    def test_create_farm_invalid_coords_raises(self, db):
        from apps.farm.farms.services import FarmService
        from apps.infrastructure.core.rls import set_tenant_context
        org = _make_org()
        with set_tenant_context(org):
            with pytest.raises(ValidationError):
                FarmService(org).create_farm(
                    name="Bad Farm",
                    location="Nowhere",
                    lat=Decimal("3.0"),
                    lng=Decimal("5.0"),
                    farm_type="mixed",
                )

    def test_list_farms_active_only(self, db):
        from apps.farm.farms.services import FarmService
        from apps.infrastructure.core.rls import set_tenant_context
        org = _make_org()
        with set_tenant_context(org):
            svc = FarmService(org)
            svc.create_farm("Active Farm", "Lagos", Decimal("6.5244"), Decimal("3.3792"), "layer")
            farm2 = svc.create_farm("To Deactivate", "Abuja", Decimal("9.0"), Decimal("7.5"), "mixed")
            farm2.is_active = False
            farm2.save(update_fields=["is_active", "updated_at"])

            active = list(svc.list_farms(active_only=True))
            all_farms = list(svc.list_farms(active_only=False))

        assert len(active) == 1
        assert len(all_farms) == 2

    def test_create_house_via_service(self, db):
        from apps.farm.farms.services import FarmService
        from apps.infrastructure.core.rls import set_tenant_context
        org = _make_org()
        with set_tenant_context(org):
            svc = FarmService(org)
            farm = svc.create_farm("House Test Farm", "Kano", Decimal("12.0"), Decimal("8.5"), "broiler")
            house = svc.create_house(
                farm_id=str(farm.id),
                name="House X",
                capacity=3000,
                house_type="broiler",
            )
        assert house.pk is not None
        assert house.farm == farm
        assert house.capacity == 3000

    def test_create_house_zero_capacity_raises(self, db):
        from apps.farm.farms.services import FarmService
        from apps.infrastructure.core.rls import set_tenant_context
        org = _make_org()
        with set_tenant_context(org):
            svc = FarmService(org)
            farm = svc.create_farm("Capacity Farm", "Enugu", Decimal("6.4698"), Decimal("7.5200"), "layer")
            with pytest.raises(ValueError, match="capacity"):
                svc.create_house(str(farm.id), "Bad House", 0, "layer")

    def test_get_farm_summary_empty(self, db):
        from apps.farm.farms.services import FarmService
        from apps.infrastructure.core.rls import set_tenant_context
        org = _make_org()
        with set_tenant_context(org):
            svc = FarmService(org)
            farm = svc.create_farm("Summary Farm", "Ibadan", Decimal("7.3775"), Decimal("3.9470"), "mixed")
            summary = svc.get_farm_summary(str(farm.id))

        assert summary["farm"] == farm
        assert summary["total_live_birds"] == 0
        assert summary["total_capacity"] == 0
        assert summary["occupancy_pct"] == 0.0
        assert summary["houses"] == []

    def test_get_dashboard_data(self, db):
        from apps.farm.farms.services import FarmService
        from apps.infrastructure.core.rls import set_tenant_context
        org = _make_org()
        with set_tenant_context(org):
            svc = FarmService(org)
            svc.create_farm("Farm A", "Lagos", Decimal("6.5244"), Decimal("3.3792"), "layer")
            svc.create_farm("Farm B", "Abuja", Decimal("9.0"), Decimal("7.5"), "broiler")
            dashboard = svc.get_dashboard_data()

        assert dashboard["total_farms"] == 2
        assert "farms_list" in dashboard

    def test_update_farm(self, db):
        from apps.farm.farms.services import FarmService
        from apps.infrastructure.core.rls import set_tenant_context
        org = _make_org()
        with set_tenant_context(org):
            svc = FarmService(org)
            farm = svc.create_farm("Old Name", "Abuja", Decimal("9.0"), Decimal("7.5"), "mixed")
            updated = svc.update_farm(str(farm.id), name="New Name")

        assert updated.name == "New Name"


# ── Form validation tests ─────────────────────────────────────────────────────

class TestFarmCreateForm:

    def test_valid_form(self):
        from apps.farm.farms.forms import FarmCreateForm
        form = FarmCreateForm(data={
            "name": "Test Farm",
            "location": "Lagos",
            "latitude": "6.5244",
            "longitude": "3.3792",
            "farm_type": "layer",
        })
        assert form.is_valid(), form.errors

    def test_invalid_latitude(self):
        from apps.farm.farms.forms import FarmCreateForm
        form = FarmCreateForm(data={
            "name": "Bad Farm",
            "location": "Nowhere",
            "latitude": "2.0",
            "longitude": "5.0",
            "farm_type": "mixed",
        })
        assert not form.is_valid()
        assert "latitude" in form.errors

    def test_invalid_longitude(self):
        from apps.farm.farms.forms import FarmCreateForm
        form = FarmCreateForm(data={
            "name": "Bad Farm",
            "location": "Nowhere",
            "latitude": "7.0",
            "longitude": "1.0",
            "farm_type": "mixed",
        })
        assert not form.is_valid()
        assert "longitude" in form.errors


# ── farms/tasks.py — Celery task functions ────────────────────────────────────

class TestFarmCeleryTasks:

    def test_create_farm_async_creates_farm(self, db):
        from apps.farm.farms.tasks import create_farm_async
        from apps.farm.farms.models import Farm
        from apps.infrastructure.core.rls import set_tenant_context

        org = _make_org()
        create_farm_async(
            org_id=str(org.id),
            name="Async Farm",
            location="Kano",
            lat=12.0022,
            lng=8.5920,
            farm_type="broiler",
        )
        with set_tenant_context(org):
            assert Farm.objects.filter(name="Async Farm").exists()

    def test_create_house_async_creates_house(self, db):
        from apps.farm.farms.tasks import create_house_async
        from apps.farm.farms.models import Farm, House
        from apps.infrastructure.core.rls import set_tenant_context

        org = _make_org()
        farm = Farm(
            org=org, name="Task Farm", location="Lagos",
            latitude=Decimal("6.5244"), longitude=Decimal("3.3792"),
            farm_type="layer",
        )
        farm.clean()
        farm.save()

        create_house_async(
            org_id=str(org.id),
            farm_id=str(farm.id),
            name="Async House",
            capacity=1000,
            house_type="layer",
        )
        with set_tenant_context(org):
            assert House.objects.filter(name="Async House").exists()

    def test_create_farm_async_reraises_on_invalid_org(self, db):
        import uuid as _uuid
        from apps.farm.farms.tasks import create_farm_async

        with pytest.raises(Exception):
            create_farm_async(
                org_id=str(_uuid.uuid4()),
                name="Ghost Farm",
                location="Nowhere",
                lat=7.0,
                lng=5.0,
                farm_type="broiler",
            )


# ── View tests ────────────────────────────────────────────────────────────────

class TestFarmViews:

    def _setup(self, db):
        from apps.infrastructure.tenants.models import Organization
        from apps.infrastructure.accounts.models import CustomUser
        org = Organization.objects.create(name="View Org", subdomain="vieworg")
        user = CustomUser.objects.create_user(
            email="viewuser@example.com", password="testpass123",
            username="viewuser", org=org,
        )
        return org, user

    def test_farm_list_requires_login(self, db, client):
        response = client.get("/farms/")
        # LoginRequiredMixin redirects to login
        assert response.status_code in (302, 301)

    def test_farm_list_authenticated(self, db, client):
        org, user = self._setup(db)
        client.force_login(user)
        from apps.infrastructure.core.rls import set_tenant_context
        with set_tenant_context(org):
            pass  # ensure context is set up
        response = client.get("/farms/")
        assert response.status_code == 200

    def test_farm_create_get_returns_modal(self, db, client):
        org, user = self._setup(db)
        client.force_login(user)
        response = client.get("/farms/create/")
        assert response.status_code == 200
        assert b"form" in response.content.lower()

    def test_farm_create_post_valid(self, db, client):
        org, user = self._setup(db)
        client.force_login(user)
        # Non-HTMX success → redirect to list; HTMX success → 200 card fragment
        response = client.post("/farms/create/", {
            "name": "Created Farm",
            "location": "Lagos",
            "latitude": "6.5244",
            "longitude": "3.3792",
            "farm_type": "layer",
        })
        assert response.status_code == 302
        from apps.farm.farms.models import Farm
        from apps.infrastructure.core.rls import set_tenant_context
        with set_tenant_context(org):
            assert Farm.objects.filter(name="Created Farm").exists()

    def test_farm_create_post_invalid_returns_422(self, db, client):
        org, user = self._setup(db)
        client.force_login(user)
        response = client.post("/farms/create/", {
            "name": "Bad Farm",
            "location": "Nowhere",
            "latitude": "2.0",  # out of bounds
            "longitude": "5.0",
            "farm_type": "mixed",
        }, HTTP_HX_REQUEST="true")
        assert response.status_code == 422
