"""
Tests for FlockValuationService and the batch-detail valuation card.

Covers:
  - broiler estimate (weight_based)
  - layer estimate (point_of_lay)
  - missing market data → fallback price, confidence='low'
  - real weight + market price → confidence='high'
  - batch detail shows the valuation card for active batches
  - batch detail hides the valuation card for closed batches
"""
import datetime
from decimal import Decimal

import pytest

pytestmark = pytest.mark.django_db


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_org(subdomain="val-test"):
    from apps.infrastructure.tenants.models import Organization
    return Organization.objects.create(
        name="Valuation Test Org",
        subdomain=subdomain,
        plan_tier="monthly",
        subscription_status="active",
        onboarding_complete=True,
        is_active=True,
    )


def _make_farm(org):
    from apps.farm.farms.models import Farm
    from apps.infrastructure.core.rls import set_tenant_context
    with set_tenant_context(org):
        farm = Farm(
            org=org, name="Val Farm", location="Lagos",
            latitude=Decimal("6.5244"), longitude=Decimal("3.3792"),
            farm_type="mixed",
        )
        farm.clean()
        farm.save()
    return farm


def _make_house(org, farm, house_type="broiler"):
    from apps.farm.farms.models import House
    from apps.infrastructure.core.rls import set_tenant_context
    with set_tenant_context(org):
        return House.objects.create(
            org=org, farm=farm, name="House A", capacity=1000, house_type=house_type,
        )


def _make_batch(org, farm, house, bird_type="broiler", breed_name="Cobb 500",
                days_old=35, initial=500, current=480, status="active"):
    from apps.farm.flocks.models import Batch
    from apps.infrastructure.core.rls import set_tenant_context
    with set_tenant_context(org):
        return Batch.objects.create(
            org=org, farm=farm, house=house,
            batch_name="ValBatch",
            bird_type=bird_type,
            breed_name=breed_name,
            placement_date=datetime.date.today() - datetime.timedelta(days=days_old),
            initial_count=initial,
            current_count=current,
            status=status,
        )


# ── Service: broiler ───────────────────────────────────────────────────────────

class TestBroilerValuation:

    def test_broiler_returns_weight_based_estimate(self):
        from apps.infrastructure.core.valuation import FlockValuationService
        org = _make_org("val-broiler-1")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house, bird_type="broiler")

        result = FlockValuationService(batch).estimate_value()

        assert result["valuation_method"] == "weight_based"
        assert result["unit"] == "kg"
        assert result["current_count"] == 480
        assert result["estimated_value_naira"] > 0
        # No weight records and no market price → both inputs estimated/fallback.
        assert result["confidence"] == "low"
        assert result["price_source"] == "fallback"

    def test_broiler_uses_actual_weight_and_market_price(self):
        from apps.farm.flocks.models import WeightRecord
        from apps.finance.market.models import MarketPrice
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.infrastructure.core.valuation import FlockValuationService

        org = _make_org("val-broiler-2")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house, bird_type="broiler")

        with set_tenant_context(org):
            WeightRecord.objects.create(
                org=org, batch=batch,
                sample_date=datetime.date.today(),
                sample_size=20,
                avg_weight_kg=Decimal("2.000"),
            )
            MarketPrice.objects.create(
                org=org,
                date=datetime.date.today(),
                product_type="live_birds",
                price_per_unit_kobo=200000,  # ₦2,000/kg
                unit="kg",
                market_name="Mile 12",
                region="Lagos",
            )

        result = FlockValuationService(batch).estimate_value()

        # 480 birds × 2.0 kg × ₦2,000/kg = ₦1,920,000
        assert result["estimated_value_naira"] == Decimal("1920000")
        assert result["price_per_unit"] == Decimal("2000")
        assert result["confidence"] == "high"
        assert result["price_source"] == "market"
        assert result["weight_source"] == "actual"

    def test_broiler_uses_per_bird_market_quote(self):
        from apps.finance.market.models import MarketPrice
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.infrastructure.core.valuation import FlockValuationService

        org = _make_org("val-broiler-bird")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house, bird_type="broiler", current=400)

        with set_tenant_context(org):
            MarketPrice.objects.create(
                org=org, date=datetime.date.today(),
                product_type="live_birds",
                price_per_unit_kobo=350000,  # ₦3,500 per bird
                unit="per bird",
                market_name="Mile 12", region="Lagos",
            )

        result = FlockValuationService(batch).estimate_value()
        # 400 birds × ₦3,500 = ₦1,400,000 — weight calc skipped.
        assert result["valuation_method"] == "per_bird_market"
        assert result["unit"] == "bird"
        assert result["price_per_unit"] == Decimal("3500")
        assert result["estimated_value_naira"] == Decimal("1400000")
        assert result["price_source"] == "market"
        assert result["confidence"] == "medium"

    def test_broiler_prefers_per_kg_over_per_bird(self):
        from apps.farm.flocks.models import WeightRecord
        from apps.finance.market.models import MarketPrice
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.infrastructure.core.valuation import FlockValuationService

        org = _make_org("val-broiler-pref")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house, bird_type="broiler", current=400)

        with set_tenant_context(org):
            MarketPrice.objects.create(
                org=org, date=datetime.date.today(),
                product_type="live_birds",
                price_per_unit_kobo=350000, unit="per bird",
                market_name="Mile 12", region="Lagos",
            )
            MarketPrice.objects.create(
                org=org, date=datetime.date.today(),
                product_type="live_birds",
                price_per_unit_kobo=200000, unit="kg",
                market_name="Mile 12", region="Lagos",
            )
            WeightRecord.objects.create(
                org=org, batch=batch, sample_date=datetime.date.today(),
                sample_size=20, avg_weight_kg=Decimal("2.000"),
            )

        result = FlockValuationService(batch).estimate_value()
        # Per-kg wins: 400 × 2.0 kg × ₦2,000 = ₦1,600,000.
        assert result["valuation_method"] == "weight_based"
        assert result["unit"] == "kg"
        assert result["estimated_value_naira"] == Decimal("1600000")
        assert result["confidence"] == "high"

    def test_broiler_fallback_price_when_no_market_data(self):
        from apps.infrastructure.core.valuation import (
            FALLBACK_BROILER_PRICE_PER_KG,
            FlockValuationService,
        )
        org = _make_org("val-broiler-3")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house, bird_type="broiler")

        result = FlockValuationService(batch).estimate_value()
        assert result["price_per_unit"] == FALLBACK_BROILER_PRICE_PER_KG
        assert result["price_source"] == "fallback"
        assert result["confidence"] == "low"


# ── Service: layer ─────────────────────────────────────────────────────────────

class TestLayerValuation:

    def test_layer_returns_point_of_lay_estimate(self):
        from apps.infrastructure.core.valuation import (
            FALLBACK_POINT_OF_LAY_PER_BIRD,
            FlockValuationService,
        )
        org = _make_org("val-layer-1")
        farm = _make_farm(org)
        house = _make_house(org, farm, house_type="layer")
        batch = _make_batch(
            org, farm, house, bird_type="layer",
            breed_name="ISA Brown", days_old=200, initial=300, current=290,
        )

        result = FlockValuationService(batch).estimate_value()
        assert result["valuation_method"] == "point_of_lay"
        assert result["unit"] == "bird"
        assert result["price_per_unit"] == FALLBACK_POINT_OF_LAY_PER_BIRD
        # 290 × ₦2,800 = ₦812,000
        assert result["estimated_value_naira"] == Decimal("812000")
        # Laying batch (200 days > point of lay) → note about higher value.
        assert result["is_laying"] is True
        assert result["confidence"] == "medium"

    def test_layer_unknown_breed_low_confidence(self):
        from apps.infrastructure.core.valuation import FlockValuationService
        org = _make_org("val-layer-2")
        farm = _make_farm(org)
        house = _make_house(org, farm, house_type="layer")
        batch = _make_batch(
            org, farm, house, bird_type="layer",
            breed_name="", days_old=60, initial=100, current=100,
        )
        result = FlockValuationService(batch).estimate_value()
        assert result["confidence"] == "low"
        assert result["is_laying"] is False


# ── Batch detail card ──────────────────────────────────────────────────────────

class TestValuationCardOnDetail:

    def _make_user(self, org, role="owner"):
        from apps.infrastructure.accounts.models import CustomUser
        return CustomUser.objects.create_user(
            username=f"{role}-{org.subdomain}",
            email=f"{role}@{org.subdomain}.com",
            password="testpass123",
            org=org, role=role, email_verified=True,
        )

    def test_active_batch_shows_valuation_card(self, client):
        org = _make_org("val-card-1")
        user = self._make_user(org)
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house, bird_type="broiler", status="active")

        client.force_login(user)
        resp = client.get(f"/batches/{batch.pk}/")
        assert resp.status_code == 200
        assert b"Estimated Flock Value" in resp.content

    def test_closed_batch_hides_valuation_card(self, client):
        org = _make_org("val-card-2")
        user = self._make_user(org)
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house, bird_type="broiler", status="closed")

        client.force_login(user)
        resp = client.get(f"/batches/{batch.pk}/")
        assert resp.status_code == 200
        assert b"Estimated Flock Value" not in resp.content
