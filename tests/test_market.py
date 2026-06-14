"""
Phase 5 — Market app tests.
"""

import datetime
from decimal import Decimal

import pytest

pytestmark = pytest.mark.django_db


# ── Helpers ──────────────────────────────────────────────────────────────────────

def _make_org(subdomain, country="Nigeria"):
    from apps.infrastructure.tenants.models import Organization
    return Organization.objects.create(
        name="Market Org", subdomain=subdomain, country=country,
    )


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


class TestMarketPriceCountryScoping:
    """MarketPrice is tenant-scoped AND country-scoped: an org only sees price
    rows recorded for its own country."""

    def test_record_market_price_stamps_org_country(self):
        org = _make_org("mkt_ctry_stamp", country="Ghana")
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.finance.market.services import MarketService
        with set_tenant_context(org):
            price = MarketService(org).record_market_price(
                product_type="eggs",
                price_per_unit_kobo=120000,
                unit="per crate",
                market_name="Accra Market",
            )
        assert price.country == "Ghana"

    def test_org_only_sees_own_country_prices(self):
        """A row recorded under a different country is filtered out."""
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.finance.market.models import MarketPrice
        from apps.finance.market.services import MarketService

        org = _make_org("mkt_ctry_filter", country="Nigeria")
        with set_tenant_context(org):
            # One Nigerian row (matches org) + one stray Ghana row (same org).
            MarketService(org).record_market_price(
                product_type="eggs", price_per_unit_kobo=120000,
                unit="per crate", market_name="Lagos Market",
            )
            MarketPrice.objects.create(
                org=org, product_type="eggs", price_per_unit_kobo=99000,
                unit="per crate", market_name="Accra Market", country="Ghana",
            )
            prices = list(MarketService(org).get_current_prices())

        assert len(prices) == 1
        assert all(p.country == "Nigeria" for p in prices)

    def test_non_nigerian_org_with_no_data_sees_empty(self):
        org = _make_org("mkt_empty_gh", country="Ghana")
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.finance.market.services import MarketService
        with set_tenant_context(org):
            prices = list(MarketService(org).get_current_prices())
        assert prices == []


class TestFeedPriceCountryScoping:

    def _submit(self, org, state, price=8500, country=None):
        from apps.finance.market.services import FeedPriceService
        from apps.infrastructure.accounts.models import CustomUser
        user = CustomUser.objects.create_user(
            username=f"u-{org.subdomain}-{state}",
            email=f"{org.subdomain}-{state}@x.com",
            password="x", org=org, role="owner",
        )
        # Clear the per-feed-type/day rate-limit cache between submissions.
        from django.core.cache import cache
        cache.clear()
        return FeedPriceService.submit_price(
            user=user, org=org, feed_type="broiler_starter",
            brand="topfeeds", price=price, state=state,
        )

    def test_submit_stamps_org_country(self):
        org = _make_org("feed_stamp_gh", country="Ghana")
        report = self._submit(org, state="Greater Accra")
        assert report.country == "Ghana"

    def test_feed_prices_scoped_by_country(self):
        from apps.finance.market.services import FeedPriceService

        ng_org = _make_org("feed_ng", country="Nigeria")
        gh_org = _make_org("feed_gh", country="Ghana")
        self._submit(ng_org, state="Lagos", price=8000)
        self._submit(gh_org, state="Greater Accra", price=9000)

        ng_data = FeedPriceService.get_current_prices(country="Nigeria")
        gh_data = FeedPriceService.get_current_prices(country="Ghana")

        assert ng_data["national"]["count"] == 1
        assert gh_data["national"]["count"] == 1
        ng_states = {r["state"] for r in ng_data["by_state"]}
        gh_states = {r["state"] for r in gh_data["by_state"]}
        assert ng_states == {"Lagos"}
        assert gh_states == {"Greater Accra"}

    def test_non_nigerian_org_no_data_empty(self):
        from apps.finance.market.services import FeedPriceService

        ng_org = _make_org("feed_ng_only", country="Nigeria")
        self._submit(ng_org, state="Lagos")

        gh_data = FeedPriceService.get_current_prices(country="Ghana")
        assert gh_data["national"]["count"] == 0
        assert gh_data["by_state"] == []


class TestHatcheryCountryScoping:

    def _make_hatchery(self, name, state, country):
        from apps.finance.market.models import Hatchery
        return Hatchery.objects.create(
            name=name, state=state, country=country, is_verified=True,
            bird_types=["broiler"],
        )

    def test_get_top_hatcheries_scoped_by_country(self):
        from apps.finance.market.services import HatcheryService

        self._make_hatchery("Lagos Hatchery", "Lagos", "Nigeria")
        self._make_hatchery("Accra Hatchery", "Greater Accra", "Ghana")

        ng = HatcheryService.get_top_hatcheries(country="Nigeria")
        gh = HatcheryService.get_top_hatcheries(country="Ghana")

        assert {h.name for h in ng} == {"Lagos Hatchery"}
        assert {h.name for h in gh} == {"Accra Hatchery"}

    def test_suggest_hatchery_stamps_org_country(self):
        from apps.finance.market.services import HatcheryService
        org = _make_org("hatch_suggest_gh", country="Ghana")
        h = HatcheryService.suggest_hatchery(
            user=None, org=org, name="New GH Hatchery", state="Ashanti",
        )
        assert h.country == "Ghana"


class TestStateFieldValidation:
    """Nigerian orgs validate state against NIGERIAN_STATES; other countries
    accept free text."""

    def test_nigeria_rejects_unknown_state(self):
        from apps.finance.market.forms import FeedPriceSubmitForm
        form = FeedPriceSubmitForm(
            data={
                "feed_type": "broiler_starter", "brand": "topfeeds",
                "price_per_25kg_bag": "8500", "state": "Greater Accra",
            },
            country="Nigeria",
        )
        assert not form.is_valid()
        assert "state" in form.errors

    def test_nigeria_accepts_valid_state(self):
        from apps.finance.market.forms import FeedPriceSubmitForm
        form = FeedPriceSubmitForm(
            data={
                "feed_type": "broiler_starter", "brand": "topfeeds",
                "price_per_25kg_bag": "8500", "state": "Lagos",
            },
            country="Nigeria",
        )
        assert form.is_valid(), form.errors

    def test_non_nigeria_accepts_free_text_state(self):
        from apps.finance.market.forms import FeedPriceSubmitForm
        form = FeedPriceSubmitForm(
            data={
                "feed_type": "broiler_starter", "brand": "topfeeds",
                "price_per_25kg_bag": "8500", "state": "Greater Accra",
            },
            country="Ghana",
        )
        assert form.is_valid(), form.errors
        assert form.cleaned_data["state"] == "Greater Accra"


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
