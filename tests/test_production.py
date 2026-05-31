"""
Phase 3A — Egg Production app tests.

Coverage:
- EggProductionLog model: creation, validation (bird_type, status, date, grades)
- CrateInventory model: basic creation
- EggProductionService: log_production, get_production_summary,
  check_against_benchmark, get_trend_data, get_production_table
- Exception guards: BatchNotLayerError, ProductionBatchClosedError
- Signal: hen_day_pct and crates computed on save
- HTMX views: POST log, GET table, GET chart, GET summary
- DRF API views: GET list, POST create, GET detail
- RLS isolation: org A cannot see org B's logs
"""

import datetime
from decimal import Decimal

import pytest

pytestmark = pytest.mark.django_db


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_org(subdomain="testprod"):
    from apps.infrastructure.tenants.models import Organization
    return Organization.objects.create(name="Prod Org", subdomain=subdomain)


def _make_user(org, email="prod@example.com", username="produser"):
    from apps.infrastructure.accounts.models import CustomUser
    return CustomUser.objects.create_user(
        email=email, password="testpass123", username=username, org=org,
    )


def _make_farm(org, name="Prod Farm"):
    from apps.farm.farms.models import Farm
    farm = Farm(
        org=org, name=name, location="Ibadan",
        latitude=Decimal("7.3775"), longitude=Decimal("3.9470"),
        farm_type="layer",
    )
    farm.clean()
    farm.save()
    return farm


def _make_house(org, farm, capacity=5000, name="Layer House A", house_type="layer"):
    from apps.farm.farms.models import House
    return House.objects.create(
        org=org, farm=farm, name=name, capacity=capacity, house_type=house_type,
    )


def _make_batch(org, farm, house, bird_type="layer", initial_count=1000, status="active"):
    from apps.farm.flocks.models import Batch
    return Batch.objects.create(
        org=org,
        farm=farm,
        house=house,
        batch_name=f"Test Batch {bird_type}",
        bird_type=bird_type,
        placement_date=datetime.date.today() - datetime.timedelta(days=30),
        initial_count=initial_count,
        current_count=initial_count,
        status=status,
    )


def _log_production(org, batch, total_eggs=300, record_date=None):
    from apps.production.production.services import EggProductionService
    from apps.infrastructure.core.rls import set_tenant_context

    with set_tenant_context(org):
        return EggProductionService(org).log_production(
            batch_id=str(batch.id),
            record_date=record_date or datetime.date.today(),
            total_eggs=total_eggs,
        )


# ── 1. EggProductionLog model ─────────────────────────────────────────────────

class TestEggProductionLogModel:

    def test_log_created_with_correct_fields(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        org = _make_org("modelprod1")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house)

        with set_tenant_context(org):
            log = _log_production(org, batch, total_eggs=270)

        assert log.total_eggs == 270
        assert log.batch == batch
        assert log.farm == farm
        assert log.org == org

    def test_log_computes_hen_day_pct_via_signal(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        org = _make_org("hdpsignal")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house, initial_count=1000)

        with set_tenant_context(org):
            log = _log_production(org, batch, total_eggs=800)
            log.refresh_from_db()

        assert log.hen_day_pct is not None
        assert float(log.hen_day_pct) == pytest.approx(80.0, abs=0.1)

    def test_log_computes_crates_via_signal(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        org = _make_org("cratessignal")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house)

        with set_tenant_context(org):
            log = _log_production(org, batch, total_eggs=300)
            log.refresh_from_db()

        assert log.crates is not None
        assert float(log.crates) == pytest.approx(10.0, abs=0.1)

    def test_duplicate_date_raises_integrity_error(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        import django.db
        org = _make_org("dupdate")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house)
        today = datetime.date.today()

        with set_tenant_context(org):
            _log_production(org, batch, total_eggs=300, record_date=today)
            with pytest.raises(django.db.IntegrityError):
                _log_production(org, batch, total_eggs=310, record_date=today)

    def test_model_str(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        org = _make_org("modelstr")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house)

        with set_tenant_context(org):
            log = _log_production(org, batch, total_eggs=150)

        assert "150 eggs" in str(log)


# ── 2. EggProductionService ───────────────────────────────────────────────────

class TestEggProductionService:

    def test_log_production_layer_batch_succeeds(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        org = _make_org("svclog1")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house, bird_type="layer")

        with set_tenant_context(org):
            log = _log_production(org, batch, total_eggs=400)

        assert log.pk is not None
        assert log.total_eggs == 400

    def test_log_production_broiler_raises_batch_not_layer(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.production.production.exceptions import BatchNotLayerError
        from apps.farm.farms.models import House
        org = _make_org("svcbroiler")
        farm = _make_farm(org)
        house = House.objects.create(
            org=org, farm=farm, name="Broiler House", capacity=5000, house_type="broiler"
        )
        batch = _make_batch(org, farm, house, bird_type="broiler")

        with set_tenant_context(org):
            from apps.production.production.services import EggProductionService
            with pytest.raises(BatchNotLayerError):
                EggProductionService(org).log_production(
                    batch_id=str(batch.id),
                    record_date=datetime.date.today(),
                    total_eggs=100,
                )

    def test_log_production_closed_batch_raises_error(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.production.production.exceptions import ProductionBatchClosedError
        org = _make_org("svcclosed")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house, bird_type="layer", status="closed")

        with set_tenant_context(org):
            from apps.production.production.services import EggProductionService
            with pytest.raises(ProductionBatchClosedError):
                EggProductionService(org).log_production(
                    batch_id=str(batch.id),
                    record_date=datetime.date.today(),
                    total_eggs=100,
                )

    def test_log_production_grade_mismatch_raises_value_error(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        org = _make_org("svcgrade")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house, bird_type="layer")

        with set_tenant_context(org):
            from apps.production.production.services import EggProductionService
            with pytest.raises(ValueError, match="Grade counts"):
                EggProductionService(org).log_production(
                    batch_id=str(batch.id),
                    record_date=datetime.date.today(),
                    total_eggs=300,
                    grade_a=100,
                    grade_b=100,
                    grade_c=50,
                    broken=10,  # total = 260 ≠ 300
                )

    def test_log_production_grades_sum_to_total_succeeds(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        org = _make_org("svcgradeok")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house, bird_type="layer")

        with set_tenant_context(org):
            from apps.production.production.services import EggProductionService
            log = EggProductionService(org).log_production(
                batch_id=str(batch.id),
                record_date=datetime.date.today(),
                total_eggs=300,
                grade_a=200,
                grade_b=70,
                grade_c=20,
                broken=10,
            )
        assert log.grade_a == 200

    def test_get_production_summary_returns_totals(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        org = _make_org("svcsummary")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house)

        with set_tenant_context(org):
            _log_production(org, batch, total_eggs=300)

        with set_tenant_context(org):
            from apps.production.production.services import EggProductionService
            summary = EggProductionService(org).get_production_summary(str(batch.id))

        assert summary["total_eggs_to_date"] == 300
        assert "best_day" in summary
        assert "last_7_days" in summary

    def test_check_against_benchmark_returns_status(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        org = _make_org("svcbench")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house, initial_count=1000)

        with set_tenant_context(org):
            _log_production(org, batch, total_eggs=800)

        with set_tenant_context(org):
            from apps.production.production.services import EggProductionService
            result = EggProductionService(org).check_against_benchmark(str(batch.id))

        assert result["status"] in ("on_track", "below_benchmark", "critical")
        assert "expected_range" in result
        assert "actual_avg_7day" in result

    def test_get_trend_data_returns_chart_structure(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        org = _make_org("svctrend")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house)

        with set_tenant_context(org):
            _log_production(org, batch, total_eggs=300)

        with set_tenant_context(org):
            from apps.production.production.services import EggProductionService
            data = EggProductionService(org).get_trend_data(str(batch.id), days=30)

        assert "labels" in data
        assert "actual_data" in data
        assert "benchmark_data" in data
        assert len(data["labels"]) == len(data["actual_data"])

    def test_get_production_table_paginates(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        org = _make_org("svctable")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house)

        with set_tenant_context(org):
            for i in range(3):
                _log_production(
                    org, batch,
                    total_eggs=300 + i,
                    record_date=datetime.date.today() - datetime.timedelta(days=i),
                )

        with set_tenant_context(org):
            from apps.production.production.services import EggProductionService
            page = EggProductionService(org).get_production_table(str(batch.id), page=1)

        assert page.paginator.count == 3

    def test_log_production_unknown_batch_raises_value_error(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        import uuid
        org = _make_org("svcnobatch")

        with set_tenant_context(org):
            from apps.production.production.services import EggProductionService
            with pytest.raises(ValueError, match="not found"):
                EggProductionService(org).log_production(
                    batch_id=str(uuid.uuid4()),
                    record_date=datetime.date.today(),
                    total_eggs=100,
                )


# ── 3. HTMX views ─────────────────────────────────────────────────────────────

class TestProductionHTMXViews:

    def _setup(self, db, subdomain="viewprod"):
        org = _make_org(subdomain)
        user = _make_user(org, email=f"{subdomain}@example.com", username=subdomain)
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house, bird_type="layer")
        return org, user, farm, house, batch

    def test_log_view_requires_login(self, db, client):
        import uuid
        response = client.post(f"/production/eggs/{uuid.uuid4()}/log/", {})
        assert response.status_code in (302, 301)

    def test_log_view_valid_post_returns_200(self, db, client):
        org, user, farm, house, batch = self._setup(db, "viewprod2")
        client.force_login(user)
        response = client.post(
            f"/production/eggs/{batch.id}/log/",
            {
                "record_date": datetime.date.today().isoformat(),
                "total_eggs": "270",
                "grade_a": "0",
                "grade_b": "0",
                "grade_c": "0",
                "broken": "0",
                "notes": "",
            },
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        assert b"production-summary-card" in response.content

    def test_log_view_invalid_post_returns_422(self, db, client):
        org, user, farm, house, batch = self._setup(db, "viewprod3")
        client.force_login(user)
        response = client.post(
            f"/production/eggs/{batch.id}/log/",
            {
                "record_date": datetime.date.today().isoformat(),
                "total_eggs": "-5",
            },
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 422

    def test_log_view_broiler_batch_returns_422(self, db, client):
        from apps.farm.farms.models import House as FarmHouse
        org = _make_org("viewbro")
        user = _make_user(org, email="viewbro@example.com", username="viewbro")
        farm = _make_farm(org)
        house = FarmHouse.objects.create(
            org=org, farm=farm, name="Broiler H", capacity=5000, house_type="broiler"
        )
        batch = _make_batch(org, farm, house, bird_type="broiler")
        client.force_login(user)
        response = client.post(
            f"/production/eggs/{batch.id}/log/",
            {
                "record_date": datetime.date.today().isoformat(),
                "total_eggs": "200",
            },
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 422

    def test_table_view_returns_200(self, db, client):
        org, user, farm, house, batch = self._setup(db, "viewtable")
        client.force_login(user)
        response = client.get(f"/production/eggs/{batch.id}/table/")
        assert response.status_code == 200
        assert b"production-table" in response.content

    def test_chart_view_returns_200(self, db, client):
        org, user, farm, house, batch = self._setup(db, "viewchart")
        client.force_login(user)
        response = client.get(f"/production/eggs/{batch.id}/chart/")
        assert response.status_code == 200
        assert b"production-chart" in response.content

    def test_summary_view_returns_200(self, db, client):
        org, user, farm, house, batch = self._setup(db, "viewsummary")
        client.force_login(user)
        response = client.get(f"/production/eggs/{batch.id}/summary/")
        assert response.status_code == 200
        assert b"production-summary-card" in response.content


# ── 4. DRF API views ──────────────────────────────────────────────────────────

def _jwt_auth(user):
    """Return HTTP_AUTHORIZATION header dict for JWT-authenticated requests."""
    from rest_framework_simplejwt.tokens import RefreshToken
    token = str(RefreshToken.for_user(user).access_token)
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


class TestEggProductionAPIViews:

    def _setup(self, db, subdomain="apiprod"):
        org = _make_org(subdomain)
        user = _make_user(org, email=f"{subdomain}@example.com", username=subdomain)
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house, bird_type="layer")
        return org, user, farm, house, batch

    def test_api_list_requires_auth(self, db, client):
        response = client.get("/api/v1/production/eggs/")
        assert response.status_code == 401

    def test_api_list_returns_empty_for_new_batch(self, db, client):
        org, user, farm, house, batch = self._setup(db, "apilist")
        response = client.get(
            f"/api/v1/production/eggs/?batch_id={batch.id}",
            **_jwt_auth(user),
        )
        assert response.status_code == 200
        assert response.json()["data"] == []

    def test_api_post_creates_log(self, db, client):
        import json
        org, user, farm, house, batch = self._setup(db, "apipost")
        payload = {
            "batch_id": str(batch.id),
            "record_date": datetime.date.today().isoformat(),
            "total_eggs": 350,
        }
        response = client.post(
            "/api/v1/production/eggs/",
            data=json.dumps(payload),
            content_type="application/json",
            **_jwt_auth(user),
        )
        assert response.status_code == 201
        data = response.json()["data"]
        assert data["total_eggs"] == 350

    def test_api_post_invalid_grades_returns_400(self, db, client):
        import json
        org, user, farm, house, batch = self._setup(db, "apibadgrade")
        payload = {
            "batch_id": str(batch.id),
            "record_date": datetime.date.today().isoformat(),
            "total_eggs": 300,
            "grade_a": 100,
            "grade_b": 100,
            "broken": 50,  # sum = 250 ≠ 300
        }
        response = client.post(
            "/api/v1/production/eggs/",
            data=json.dumps(payload),
            content_type="application/json",
            **_jwt_auth(user),
        )
        assert response.status_code == 400

    def test_api_post_broiler_returns_422(self, db, client):
        import json
        from apps.farm.farms.models import House as FarmHouse
        org = _make_org("apibroiler")
        user = _make_user(org, email="apibroiler@example.com", username="apibroiler")
        farm = _make_farm(org)
        house = FarmHouse.objects.create(
            org=org, farm=farm, name="Bro H", capacity=5000, house_type="broiler"
        )
        batch = _make_batch(org, farm, house, bird_type="broiler")
        payload = {
            "batch_id": str(batch.id),
            "record_date": datetime.date.today().isoformat(),
            "total_eggs": 100,
        }
        response = client.post(
            "/api/v1/production/eggs/",
            data=json.dumps(payload),
            content_type="application/json",
            **_jwt_auth(user),
        )
        assert response.status_code == 422

    def test_api_detail_returns_summary(self, db, client):
        org, user, farm, house, batch = self._setup(db, "apidetail")
        _log_production(org, batch, total_eggs=300)
        response = client.get(
            f"/api/v1/production/eggs/{batch.id}/",
            **_jwt_auth(user),
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert "total_eggs_to_date" in data
        assert "benchmark" in data


# ── 5. RLS isolation ──────────────────────────────────────────────────────────

class TestProductionRLSIsolation:

    def test_org_a_cannot_see_org_b_logs(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.production.production.models import EggProductionLog

        org_a = _make_org("rlsa")
        farm_a = _make_farm(org_a, "Farm A")
        house_a = _make_house(org_a, farm_a)
        batch_a = _make_batch(org_a, farm_a, house_a)

        org_b = _make_org("rlsb")
        farm_b = _make_farm(org_b, "Farm B")
        house_b = _make_house(org_b, farm_b)
        batch_b = _make_batch(org_b, farm_b, house_b)

        with set_tenant_context(org_a):
            _log_production(org_a, batch_a, total_eggs=300)

        with set_tenant_context(org_b):
            _log_production(org_b, batch_b, total_eggs=400)

        with set_tenant_context(org_a):
            count_a = EggProductionLog.objects.count()

        with set_tenant_context(org_b):
            count_b = EggProductionLog.objects.count()

        assert count_a == 1
        assert count_b == 1
