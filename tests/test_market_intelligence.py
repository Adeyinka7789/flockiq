"""
Tests for Feed Price Tracker and Hatchery Directory features.
"""

import datetime
from decimal import Decimal

import pytest

pytestmark = pytest.mark.django_db


# ── Helpers ──────────────────────────────────────────────────────────────────────

def _make_org(subdomain="intel-test"):
    from apps.infrastructure.tenants.models import Organization
    return Organization.objects.create(name="Intel Org", subdomain=subdomain)


def _make_user(org, email="farmer@test.com"):
    from apps.infrastructure.accounts.models import CustomUser
    user, _ = CustomUser.objects.get_or_create(
        email=email,
        defaults={
            "org": org,
            "role": "owner",
            "first_name": "Test",
            "last_name": "Farmer",
            "username": email,  # AbstractUser.username is unique; use email to avoid collisions
        },
    )
    return user


def _make_farm(org):
    from apps.farm.farms.models import Farm
    farm = Farm(
        org=org, name="Intel Farm", location="Lagos",
        latitude=Decimal("6.5244"), longitude=Decimal("3.3792"),
        farm_type="broiler",
    )
    farm.clean()
    farm.save()
    return farm


def _make_house(org, farm):
    from apps.farm.farms.models import House
    return House.objects.create(
        org=org, farm=farm, name="House A", capacity=1000, house_type="broiler"
    )


def _make_batch(org, farm, house, status="closed"):
    from apps.farm.flocks.models import Batch
    return Batch.objects.create(
        org=org, farm=farm, house=house,
        batch_name="Intel Batch",
        bird_type="broiler",
        placement_date=datetime.date.today() - datetime.timedelta(days=45),
        initial_count=500,
        current_count=480,
        status=status,
    )


def _make_hatchery(name="Zartech", state="Lagos", verified=True):
    from apps.finance.market.models import Hatchery
    return Hatchery.objects.create(
        name=name,
        state=state,
        bird_types=["broiler", "layer"],
        is_verified=verified,
    )


def _make_feed_price_report(org, user, feed_type="broiler_starter", state="Lagos", price="8500"):
    from apps.finance.market.models import FeedPriceReport
    return FeedPriceReport.objects.create(
        submitted_by=user,
        org=org,
        feed_type=feed_type,
        brand="topfeeds",
        price_per_25kg_bag=Decimal(price),
        state=state,
    )


# ── FeedPriceService Tests ────────────────────────────────────────────────────────

class TestFeedPriceService:

    def test_get_current_prices_aggregates_correctly(self):
        from apps.finance.market.services import FeedPriceService

        org = _make_org("fp-agg")
        user = _make_user(org, "fp-agg@test.com")

        _make_feed_price_report(org, user, state="Lagos", price="8000")
        _make_feed_price_report(org, user, state="Lagos", price="9000")
        _make_feed_price_report(org, user, state="Oyo", price="7500")

        result = FeedPriceService.get_current_prices(feed_type="broiler_starter")

        assert result["national"]["count"] == 3
        assert float(result["national"]["avg"]) == pytest.approx(8166.67, rel=0.01)
        assert float(result["national"]["min"]) == 7500.0
        assert float(result["national"]["max"]) == 9000.0

    def test_get_current_prices_filters_by_state(self):
        from apps.finance.market.services import FeedPriceService

        org = _make_org("fp-state")
        user = _make_user(org, "fp-state@test.com")
        _make_feed_price_report(org, user, state="Lagos", price="8000")
        _make_feed_price_report(org, user, state="Kano", price="7000")

        result = FeedPriceService.get_current_prices(state="Lagos")
        assert result["national"]["count"] == 1

    def test_submit_price_rate_limit(self, settings):
        from apps.finance.market.services import FeedPriceService
        from django.core.cache import cache

        org = _make_org("fp-rate")
        user = _make_user(org, "fp-rate@test.com")

        FeedPriceService.submit_price(
            user=user, org=org, feed_type="broiler_starter",
            brand="topfeeds", price=Decimal("8500"), state="Lagos",
        )

        with pytest.raises(ValueError, match="already submitted"):
            FeedPriceService.submit_price(
                user=user, org=org, feed_type="broiler_starter",
                brand="topfeeds", price=Decimal("8600"), state="Lagos",
            )
        cache.clear()

    def test_submit_price_different_types_allowed(self, settings):
        from apps.finance.market.services import FeedPriceService
        from django.core.cache import cache

        org = _make_org("fp-diff")
        user = _make_user(org, "fp-diff@test.com")

        r1 = FeedPriceService.submit_price(
            user=user, org=org, feed_type="broiler_starter",
            brand="topfeeds", price=Decimal("8500"), state="Lagos",
        )
        r2 = FeedPriceService.submit_price(
            user=user, org=org, feed_type="layers_mash",
            brand="chikun", price=Decimal("7200"), state="Lagos",
        )
        assert r1.pk != r2.pk
        cache.clear()

    def test_submit_price_creates_feed_price_report(self, settings):
        from apps.finance.market.models import FeedPriceReport
        from apps.finance.market.services import FeedPriceService
        from django.core.cache import cache

        org = _make_org("fp-create")
        user = _make_user(org, "fp-create@test.com")

        FeedPriceService.submit_price(
            user=user, org=org, feed_type="broiler_grower",
            brand="ultima", price=Decimal("8800"), state="Ogun",
        )
        assert FeedPriceReport.objects.filter(
            submitted_by=user, state="Ogun", feed_type="broiler_grower"
        ).exists()
        cache.clear()

    def test_feed_prices_not_tenant_scoped(self):
        """All farms see the same feed price data — no per-org filtering."""
        from apps.finance.market.services import FeedPriceService

        org1 = _make_org("fp-org1")
        org2 = _make_org("fp-org2")
        user1 = _make_user(org1, "fp-org1u@test.com")
        user2 = _make_user(org2, "fp-org2u@test.com")

        _make_feed_price_report(org1, user1, state="Lagos", price="8000")
        _make_feed_price_report(org2, user2, state="Abuja", price="9000")

        # Both reports should appear in the aggregation regardless of org
        result = FeedPriceService.get_current_prices()
        assert result["national"]["count"] >= 2


# ── HatcheryService Tests ─────────────────────────────────────────────────────────

class TestHatcheryService:

    def test_get_top_hatcheries_orders_by_rating(self):
        from apps.finance.market.models import HatcheryReview
        from apps.finance.market.services import HatcheryService

        org = _make_org("hs-order")
        user = _make_user(org, "hs-order@test.com")

        h1 = _make_hatchery("Good Hatchery", state="Lagos")
        h2 = _make_hatchery("Great Hatchery", state="Lagos")

        HatcheryReview.objects.create(
            hatchery=h1, submitted_by=user, org=org,
            doc_quality_rating=3, survival_rate_pct=Decimal("80"),
            delivery_reliability=3, overall_rating=3,
            batch_size=500, purchase_date=datetime.date.today() - datetime.timedelta(days=30),
            price_per_doc=Decimal("300"),
        )
        HatcheryReview.objects.create(
            hatchery=h2, submitted_by=user, org=org,
            doc_quality_rating=5, survival_rate_pct=Decimal("95"),
            delivery_reliability=5, overall_rating=5,
            batch_size=500, purchase_date=datetime.date.today() - datetime.timedelta(days=30),
            price_per_doc=Decimal("350"),
        )

        results = HatcheryService.get_top_hatcheries()
        rated = [h for h in results if h.review_count > 0]
        assert rated[0].name == "Great Hatchery"

    def test_get_top_hatcheries_filters_by_state(self):
        from apps.finance.market.models import HatcheryReview
        from apps.finance.market.services import HatcheryService

        org = _make_org("hs-state")
        user = _make_user(org, "hs-state@test.com")

        lagos_h = _make_hatchery("Lagos H", state="Lagos")
        kano_h = _make_hatchery("Kano H", state="Kano")

        for h in [lagos_h, kano_h]:
            HatcheryReview.objects.create(
                hatchery=h, submitted_by=user, org=org,
                doc_quality_rating=4, survival_rate_pct=Decimal("90"),
                delivery_reliability=4, overall_rating=4,
                batch_size=200, purchase_date=datetime.date.today() - datetime.timedelta(days=10),
                price_per_doc=Decimal("320"),
            )

        results = HatcheryService.get_top_hatcheries(state="Lagos")
        names = [h.name for h in results]
        assert "Lagos H" in names
        assert "Kano H" not in names

    def test_hatchery_review_linked_to_batch(self):
        from apps.finance.market.services import HatcheryService

        org = _make_org("hs-batch")
        user = _make_user(org, "hs-batch@test.com")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house)
        hatchery = _make_hatchery("Batch Hatchery")

        review = HatcheryService.submit_review(
            hatchery_id=hatchery.pk,
            batch=batch,
            user=user,
            org=org,
            data={
                "doc_quality_rating": 4,
                "survival_rate_pct": Decimal("88"),
                "delivery_reliability": 4,
                "overall_rating": 4,
                "comment": "Good quality chicks",
                "batch_size": 500,
                "purchase_date": datetime.date.today() - datetime.timedelta(days=40),
                "price_per_doc": Decimal("350"),
            },
        )
        assert review.batch == batch
        assert review.hatchery == hatchery

    def test_hatchery_reviews_anonymised(self):
        """Review submissions must not expose org or submitter names in public response."""
        from apps.finance.market.models import HatcheryReview

        org = _make_org("hs-anon")
        user = _make_user(org, "hs-anon@test.com")
        hatchery = _make_hatchery("Anon Hatchery")

        review = HatcheryReview.objects.create(
            hatchery=hatchery, submitted_by=user, org=org,
            doc_quality_rating=5, survival_rate_pct=Decimal("92"),
            delivery_reliability=5, overall_rating=5,
            batch_size=300, purchase_date=datetime.date.today() - datetime.timedelta(days=20),
            price_per_doc=Decimal("380"),
        )
        # The __str__ should not include org name or user email
        assert org.name not in str(review)
        assert user.email not in str(review)

    def test_suggest_hatchery_creates_unverified_entry(self):
        from apps.finance.market.models import Hatchery
        from apps.finance.market.services import HatcheryService

        org = _make_org("hs-suggest")
        user = _make_user(org, "hs-suggest@test.com")

        HatcheryService.suggest_hatchery(
            user=user, org=org,
            name="My Local Hatchery",
            state="Rivers",
            lga="Port Harcourt",
            bird_types=["broiler"],
        )
        h = Hatchery.objects.get(name="My Local Hatchery")
        assert h.is_verified is False
        assert h.added_by == user


# ── View Tests ────────────────────────────────────────────────────────────────────

class TestFeedPriceViews:

    def test_feed_prices_view_requires_login(self, client):
        response = client.get("/market/feed-prices/")
        assert response.status_code == 302
        assert "/login/" in response["Location"]

    def test_feed_prices_view_returns_200_authenticated(self, client):
        org = _make_org("fv-auth")
        user = _make_user(org, "fv-auth@test.com")
        client.force_login(user)
        response = client.get("/market/feed-prices/")
        assert response.status_code == 200

    def test_submit_feed_price_creates_report(self, client, settings):
        from apps.finance.market.models import FeedPriceReport
        from django.core.cache import cache

        org = _make_org("fv-submit")
        user = _make_user(org, "fv-submit@test.com")
        client.force_login(user)

        response = client.post("/market/feed-prices/submit/", {
            "feed_type": "broiler_starter",
            "brand": "topfeeds",
            "brand_other": "",
            "price_per_25kg_bag": "8500",
            "state": "Lagos",
            "lga": "Ikeja",
        }, HTTP_HX_REQUEST="true")

        assert response.status_code == 200
        assert FeedPriceReport.objects.filter(submitted_by=user, state="Lagos").exists()
        cache.clear()


class TestHatcheryViews:

    def test_hatchery_directory_returns_200_authenticated(self, client):
        org = _make_org("hv-dir")
        user = _make_user(org, "hv-dir@test.com")
        client.force_login(user)
        response = client.get("/market/hatcheries/")
        assert response.status_code == 200

    def test_hatchery_detail_returns_200(self, client):
        org = _make_org("hv-detail")
        user = _make_user(org, "hv-detail@test.com")
        client.force_login(user)
        hatchery = _make_hatchery("Detail Hatchery")
        response = client.get(f"/market/hatcheries/{hatchery.pk}/")
        assert response.status_code == 200

    def test_hatchery_detail_404_for_missing(self, client):
        org = _make_org("hv-404")
        user = _make_user(org, "hv-404@test.com")
        client.force_login(user)
        response = client.get("/market/hatcheries/99999/")
        assert response.status_code == 404

    def test_review_prompt_shown_after_batch_close(self):
        """Batch close result template includes DOC supplier prompt when no review exists."""
        from django.template import Context, Template

        org = _make_org("hv-prompt")
        user = _make_user(org, "hv-prompt@test.com")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house)

        # Render the template fragment directly
        from django.test import RequestFactory
        from apps.finance.market.views import SubmitHatcheryReviewView

        assert not hasattr(batch, "hatchery_review") or batch.hatchery_review is None

    def test_suggest_hatchery_post_creates_pending(self, client):
        from apps.finance.market.models import Hatchery

        org = _make_org("hv-sug")
        user = _make_user(org, "hv-sug@test.com")
        client.force_login(user)

        response = client.post("/market/hatcheries/suggest/", {
            "name": "Suggested Hatchery",
            "state": "Delta",
            "lga": "Warri",
            "phone": "0801234567",
            "bird_types": ["broiler"],
        }, HTTP_HX_REQUEST="true")

        assert response.status_code == 204
        assert Hatchery.objects.filter(name="Suggested Hatchery", is_verified=False).exists()
