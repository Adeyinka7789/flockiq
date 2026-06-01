"""
Phase 5 — Market app tests.
"""

import datetime
from decimal import Decimal

import pytest

pytestmark = pytest.mark.django_db


# ── Helpers ──────────────────────────────────────────────────────────────────────

def _make_org(subdomain):
    from apps.infrastructure.tenants.models import Organization
    return Organization.objects.create(name="Market Org", subdomain=subdomain)


def _make_farm(org):
    from apps.farm.farms.models import Farm
    farm = Farm(
        org=org, name="Market Farm", location="Lagos",
        latitude=Decimal("6.5244"), longitude=Decimal("3.3792"),
        farm_type="broiler",
    )
    farm.clean()
    farm.save()
    return farm


def _make_house(org, farm):
    from apps.farm.farms.models import House
    return House.objects.create(org=org, farm=farm, name="House A", capacity=5000, house_type="broiler")


def _make_batch(org, farm, house, count=5000):
    from apps.farm.flocks.models import Batch
    return Batch.objects.create(
        org=org, farm=farm, house=house,
        batch_name="Market Batch",
        bird_type="broiler",
        placement_date=datetime.date.today() - datetime.timedelta(days=40),
        initial_count=count,
        current_count=count,
        status="active",
    )


# ── Tests ─────────────────────────────────────────────────────────────────────────

class TestSeasonalDemandIndex:

    def test_seasonal_demand_seeded(self):
        from apps.finance.market.models import SeasonalDemandIndex
        count = SeasonalDemandIndex.objects.count()
        assert count == 24, f"Expected 24 seed records (12 months × 2 types), got {count}"

    def test_december_is_peak_demand(self):
        from apps.finance.market.models import SeasonalDemandIndex
        december_eggs = SeasonalDemandIndex.objects.get(month=12, product_type="eggs")
        december_birds = SeasonalDemandIndex.objects.get(month=12, product_type="live_birds")
        assert december_eggs.demand_index == 10
        assert december_birds.demand_index == 10

    def test_june_is_low_demand(self):
        from apps.finance.market.models import SeasonalDemandIndex
        june_eggs = SeasonalDemandIndex.objects.get(month=6, product_type="eggs")
        assert june_eggs.demand_index == 5

    def test_all_months_have_both_product_types(self):
        from apps.finance.market.models import SeasonalDemandIndex
        for month in range(1, 13):
            assert SeasonalDemandIndex.objects.filter(month=month, product_type="eggs").exists()
            assert SeasonalDemandIndex.objects.filter(month=month, product_type="live_birds").exists()


class TestMarketPrice:

    def test_market_price_recorded(self):
        org = _make_org("mkt_price")
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.finance.market.services import MarketService
        with set_tenant_context(org):
            price = MarketService(org).record_market_price(
                product_type="eggs",
                price_per_unit_kobo=120000,
                unit="per crate",
                market_name="Lagos Mile 12",
                region="Lagos",
            )

        assert price.price_per_unit_kobo == 120000
        assert price.market_name == "Lagos Mile 12"

    def test_market_price_naira_property(self):
        org = _make_org("mkt_naira")
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.finance.market.services import MarketService
        with set_tenant_context(org):
            price = MarketService(org).record_market_price(
                product_type="live_birds",
                price_per_unit_kobo=350000,
                unit="per bird",
                market_name="Test Market",
            )
        assert price.price_per_unit_naira == 3500.0


class TestMinimumViablePrice:

    def test_minimum_viable_price_above_cost(self):
        org = _make_org("mkt_mvp")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house, count=5000)
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.finance.expenses.services import ExpenseService
        from apps.finance.market.services import MarketService
        with set_tenant_context(org):
            ExpenseService(org).record_expense(
                farm_id=str(farm.id),
                category="feed",
                amount_kobo=100000000,
                description="Feed",
                batch_id=str(batch.id),
            )
            result = MarketService(org).get_minimum_viable_price(str(batch.id))

        assert result["min_price_kobo"] > 0
        assert result["recommended_price_kobo"] > result["min_price_kobo"]

    def test_recommended_price_is_20_percent_above_min(self):
        org = _make_org("mkt_mvp_20pct")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house, count=5000)
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.finance.expenses.services import ExpenseService
        from apps.finance.market.services import MarketService
        with set_tenant_context(org):
            ExpenseService(org).record_expense(
                farm_id=str(farm.id),
                category="chicks",
                amount_kobo=100000000,
                description="Chicks",
                batch_id=str(batch.id),
            )
            result = MarketService(org).get_minimum_viable_price(str(batch.id))

        expected_recommended = int(result["min_price_kobo"] * 1.2)
        assert result["recommended_price_kobo"] == expected_recommended


class TestSeasonalForecast:

    def test_seasonal_forecast_returns_eggs_data(self):
        org = _make_org("mkt_season")
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.finance.market.services import MarketService
        with set_tenant_context(org):
            result = MarketService(org).get_seasonal_forecast("eggs")

        assert result["available"] is True
        assert "current_index" in result
        assert result["trend"] in ("up", "down", "stable")
        assert "recommendation" in result

    def test_seasonal_forecast_unknown_type_returns_unavailable(self):
        org = _make_org("mkt_season_unk")
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.finance.market.services import MarketService
        with set_tenant_context(org):
            result = MarketService(org).get_seasonal_forecast("unknown_type")

        assert result.get("available") is False or "available" not in result or not result.get("available")
