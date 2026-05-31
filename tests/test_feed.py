"""
Phase 3B — Feed app tests.
"""

import datetime
from decimal import Decimal

import pytest

pytestmark = pytest.mark.django_db


# ── Helpers ─────────────────────────────────────────────────────────────────────

def _make_org(subdomain):
    from apps.infrastructure.tenants.models import Organization
    return Organization.objects.create(name="Feed Org", subdomain=subdomain)


def _make_user(org, email, username):
    from apps.infrastructure.accounts.models import CustomUser
    return CustomUser.objects.create_user(
        email=email, password="testpass123", username=username, org=org,
    )


def _make_farm(org, name="Feed Farm", farm_type="layer"):
    from apps.farm.farms.models import Farm
    farm = Farm(
        org=org, name=name, location="Lagos",
        latitude=Decimal("6.5244"), longitude=Decimal("3.3792"),
        farm_type=farm_type,
    )
    farm.clean()
    farm.save()
    return farm


def _make_house(org, farm, house_type="layer"):
    from apps.farm.farms.models import House
    return House.objects.create(
        org=org, farm=farm, name="House A", capacity=2000, house_type=house_type,
    )


def _make_batch(org, farm, house, bird_type="layer", status="active"):
    from apps.farm.flocks.models import Batch
    return Batch.objects.create(
        org=org, farm=farm, house=house,
        batch_name=f"Test Batch {bird_type}",
        bird_type=bird_type,
        placement_date=datetime.date.today() - datetime.timedelta(days=20),
        initial_count=1000,
        current_count=1000,
        status=status,
    )


def _make_weight_record(org, batch, avg_weight_kg="2.5"):
    from apps.farm.flocks.models import WeightRecord
    return WeightRecord.objects.create(
        org=org,
        batch=batch,
        sample_date=datetime.date.today(),
        sample_size=10,
        avg_weight_kg=Decimal(avg_weight_kg),
    )


def _log_feed(org, batch, quantity_kg=50, feed_type="layer_mash", cost_per_kg=None):
    from apps.production.feed.services import FeedService
    from apps.infrastructure.core.rls import set_tenant_context

    with set_tenant_context(org):
        return FeedService(org).log_feed(
            batch_id=str(batch.id),
            record_date=datetime.date.today(),
            feed_type=feed_type,
            quantity_kg=quantity_kg,
            cost_per_kg=cost_per_kg,
        )


# ── 1. FeedLog model ─────────────────────────────────────────────────────────────

class TestFeedLogModel:

    def test_feed_log_created_for_active_batch(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        org = _make_org("feedmodel1")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house)

        with set_tenant_context(org):
            log = _log_feed(org, batch, quantity_kg=60)

        assert log.pk is not None
        assert log.quantity_kg == Decimal("60")
        assert log.batch == batch
        assert log.org == org

    def test_requirement_auto_calculated_on_save(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        org = _make_org("feedreq")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house)

        with set_tenant_context(org):
            log = _log_feed(org, batch, quantity_kg=50)
            log.refresh_from_db()

        assert log.requirement_kg is not None
        assert log.requirement_kg > 0

    def test_variance_calculated_correctly(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        org = _make_org("feedvar")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house)

        with set_tenant_context(org):
            log = _log_feed(org, batch, quantity_kg=50)
            log.refresh_from_db()

        if log.requirement_kg is not None:
            expected = log.quantity_kg - log.requirement_kg
            assert log.variance_kg == pytest.approx(float(expected), abs=0.01)

    def test_total_cost_auto_calculated(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        org = _make_org("feedcost")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house)

        with set_tenant_context(org):
            log = _log_feed(org, batch, quantity_kg=50, cost_per_kg=Decimal("200"))
            log.refresh_from_db()

        assert log.total_cost is not None
        assert float(log.total_cost) == pytest.approx(10000.0, abs=0.01)

    def test_no_total_cost_when_cost_per_kg_not_provided(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        org = _make_org("feednocost")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house)

        with set_tenant_context(org):
            log = _log_feed(org, batch, quantity_kg=50)
            log.refresh_from_db()

        assert log.total_cost is None

    def test_feed_stock_decremented_on_log(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.production.feed.models import FeedStock
        org = _make_org("feedstock1")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house)

        # Pre-seed stock
        with set_tenant_context(org):
            FeedStock.objects.create(
                org=org, farm=farm, feed_type="layer_mash", quantity_kg=Decimal("200")
            )
            _log_feed(org, batch, quantity_kg=50)
            stock = FeedStock.objects.get(farm=farm, feed_type="layer_mash")

        assert float(stock.quantity_kg) == pytest.approx(150.0, abs=0.01)

    def test_low_stock_flag_triggers_on_threshold(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.production.feed.models import FeedStock
        org = _make_org("feedlowstock")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house)

        with set_tenant_context(org):
            FeedStock.objects.create(
                org=org, farm=farm, feed_type="layer_mash",
                quantity_kg=Decimal("60"), low_stock_threshold_kg=Decimal("50"),
            )
            _log_feed(org, batch, quantity_kg=20)
            stock = FeedStock.objects.get(farm=farm, feed_type="layer_mash")

        assert stock.is_low_stock is True

    def test_duplicate_date_raises_integrity_error(self, db):
        import django.db
        from apps.infrastructure.core.rls import set_tenant_context
        org = _make_org("feeddup")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house)

        with set_tenant_context(org):
            _log_feed(org, batch, quantity_kg=50)
            with pytest.raises(django.db.IntegrityError):
                _log_feed(org, batch, quantity_kg=55)


# ── 2. FeedService ────────────────────────────────────────────────────────────────

class TestFeedService:

    def test_fcr_calculated_for_broiler(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.production.feed.services import FeedService
        org = _make_org("feedfcr")
        farm = _make_farm(org, farm_type="broiler")
        house = _make_house(org, farm, house_type="broiler")
        batch = _make_batch(org, farm, house, bird_type="broiler")

        with set_tenant_context(org):
            _make_weight_record(org, batch, avg_weight_kg="2.5")
            _log_feed(org, batch, quantity_kg=200)
            fcr = FeedService(org).get_fcr(str(batch.id))

        assert fcr is not None
        assert fcr > 0

    def test_fcr_returns_none_for_layer(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.production.feed.services import FeedService
        org = _make_org("feedfcrlayer")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house, bird_type="layer")

        with set_tenant_context(org):
            _log_feed(org, batch, quantity_kg=50)
            fcr = FeedService(org).get_fcr(str(batch.id))

        assert fcr is None

    def test_feed_summary_returns_correct_totals(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.production.feed.services import FeedService
        org = _make_org("feedsummary")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house)

        with set_tenant_context(org):
            _log_feed(org, batch, quantity_kg=50)
            summary = FeedService(org).get_feed_summary(str(batch.id))

        assert summary["total_feed_consumed_kg"] == pytest.approx(50.0, abs=0.01)
        assert "last_7_days" in summary
        assert summary["days_logged"] == 1

    def test_log_feed_inactive_batch_raises(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.production.feed.services import FeedService
        org = _make_org("feedinactive")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house, status="closed")

        with set_tenant_context(org):
            with pytest.raises(ValueError, match="closed"):
                FeedService(org).log_feed(
                    batch_id=str(batch.id),
                    record_date=datetime.date.today(),
                    feed_type="layer_mash",
                    quantity_kg=50,
                )

    def test_feed_trend_data_returns_chart_structure(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.production.feed.services import FeedService
        org = _make_org("feedtrend")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house)

        with set_tenant_context(org):
            _log_feed(org, batch, quantity_kg=50)
            data = FeedService(org).get_trend_data(str(batch.id), days=30)

        assert "labels" in data
        assert "actual_data" in data
        assert "requirement_data" in data
        assert len(data["labels"]) == len(data["actual_data"])


# ── 3. HTMX views ─────────────────────────────────────────────────────────────────

class TestFeedHTMXViews:

    def _setup(self, db, subdomain):
        org = _make_org(subdomain)
        user = _make_user(org, f"{subdomain}@example.com", subdomain)
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house)
        return org, user, farm, house, batch

    def test_log_view_requires_login(self, db, client):
        import uuid
        response = client.post(f"/production/feed/{uuid.uuid4()}/log/", {})
        assert response.status_code in (302, 301)

    def test_log_view_valid_post_returns_200(self, db, client):
        org, user, farm, house, batch = self._setup(db, "feedview1")
        client.force_login(user)
        response = client.post(
            f"/production/feed/{batch.id}/log/",
            {
                "record_date": datetime.date.today().isoformat(),
                "feed_type": "layer_mash",
                "quantity_kg": "50",
                "notes": "",
            },
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        assert b"feed-summary-card" in response.content

    def test_log_view_invalid_post_returns_422(self, db, client):
        org, user, farm, house, batch = self._setup(db, "feedview2")
        client.force_login(user)
        response = client.post(
            f"/production/feed/{batch.id}/log/",
            {"record_date": datetime.date.today().isoformat(), "quantity_kg": "-5"},
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 422

    def test_table_view_returns_200(self, db, client):
        org, user, farm, house, batch = self._setup(db, "feedviewtable")
        client.force_login(user)
        response = client.get(f"/production/feed/{batch.id}/table/")
        assert response.status_code == 200
        assert b"feed-table" in response.content

    def test_summary_view_returns_200(self, db, client):
        org, user, farm, house, batch = self._setup(db, "feedviewsummary")
        client.force_login(user)
        response = client.get(f"/production/feed/{batch.id}/summary/")
        assert response.status_code == 200
        assert b"feed-summary-card" in response.content

    def test_chart_view_returns_200(self, db, client):
        org, user, farm, house, batch = self._setup(db, "feedviewchart")
        client.force_login(user)
        response = client.get(f"/production/feed/{batch.id}/chart/")
        assert response.status_code == 200
        assert b"feed-chart" in response.content

    def test_stock_view_returns_200(self, db, client):
        org, user, farm, house, batch = self._setup(db, "feedviewstock")
        client.force_login(user)
        response = client.get(f"/production/feed/{farm.id}/stock/")
        assert response.status_code == 200
        assert b"feed-stock-panel" in response.content


# ── 4. DRF API views ──────────────────────────────────────────────────────────────

def _jwt_auth(user):
    from rest_framework_simplejwt.tokens import RefreshToken
    token = str(RefreshToken.for_user(user).access_token)
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


class TestFeedLogAPIViews:

    def _setup(self, db, subdomain):
        org = _make_org(subdomain)
        user = _make_user(org, f"{subdomain}@example.com", subdomain)
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house)
        return org, user, farm, house, batch

    def test_api_list_requires_auth(self, db, client):
        response = client.get("/api/v1/feed/log/")
        assert response.status_code == 401

    def test_api_post_creates_log(self, db, client):
        import json
        org, user, farm, house, batch = self._setup(db, "feedapi1")
        payload = {
            "batch_id": str(batch.id),
            "record_date": datetime.date.today().isoformat(),
            "feed_type": "layer_mash",
            "quantity_kg": "50",
        }
        response = client.post(
            "/api/v1/feed/log/",
            data=json.dumps(payload),
            content_type="application/json",
            **_jwt_auth(user),
        )
        assert response.status_code == 201
        assert response.json()["data"]["feed_type"] == "layer_mash"


# ── 5. RLS isolation ──────────────────────────────────────────────────────────────

class TestFeedRLSIsolation:

    def test_feed_log_rls_isolation(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.production.feed.models import FeedLog

        org_a = _make_org("feedrlsa")
        farm_a = _make_farm(org_a, "Farm A")
        house_a = _make_house(org_a, farm_a)
        batch_a = _make_batch(org_a, farm_a, house_a)

        org_b = _make_org("feedrlsb")
        farm_b = _make_farm(org_b, "Farm B")
        house_b = _make_house(org_b, farm_b)
        batch_b = _make_batch(org_b, farm_b, house_b)

        with set_tenant_context(org_a):
            _log_feed(org_a, batch_a, quantity_kg=50)

        with set_tenant_context(org_b):
            _log_feed(org_b, batch_b, quantity_kg=60)

        with set_tenant_context(org_a):
            count_a = FeedLog.objects.count()

        with set_tenant_context(org_b):
            count_b = FeedLog.objects.count()

        assert count_a == 1
        assert count_b == 1
