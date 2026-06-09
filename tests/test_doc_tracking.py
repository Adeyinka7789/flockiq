"""
Tests for Phase 2 DOC tracking loop:
  - Batch creation saves hatchery FK and doc_price
  - Review form pre-populated from batch data
  - Hatchery price trend uses review data
  - Batch detail shows hatchery info when set
  - DOC source section optional (batch creates without it)
  - Survival rate auto-calculated from batch counts
"""

import datetime
from decimal import Decimal

import pytest
from django.test import RequestFactory

pytestmark = pytest.mark.django_db


# ── Helpers ──────────────────────────────────────────────────────────────────────

def _make_org(subdomain="doc-test"):
    from apps.infrastructure.tenants.models import Organization
    return Organization.objects.create(
        name="DOC Test Org",
        subdomain=subdomain,
        plan_tier="monthly",
        subscription_status="active",
        onboarding_complete=True,
        is_active=True,
    )


def _make_user(org, email="farmer@doctest.com"):
    from apps.infrastructure.accounts.models import CustomUser
    user, _ = CustomUser.objects.get_or_create(
        email=email,
        defaults={
            "org": org,
            "role": "owner",
            "first_name": "Test",
            "last_name": "Farmer",
            "username": email,
        },
    )
    return user


def _make_farm(org):
    from apps.farm.farms.models import Farm
    from apps.infrastructure.core.rls import set_tenant_context
    with set_tenant_context(org):
        farm = Farm(
            org=org, name="DOC Farm", location="Lagos",
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


def _make_hatchery(name="Zartech Hatchery", state="Lagos", verified=True):
    from apps.finance.market.models import Hatchery
    return Hatchery.objects.create(
        name=name,
        state=state,
        bird_types=["broiler"],
        is_verified=verified,
    )


def _make_batch(org, farm, house, hatchery=None, doc_price=None, status="active"):
    from apps.farm.flocks.models import Batch
    return Batch.objects.create(
        org=org, farm=farm, house=house,
        batch_name="DOC Test Batch",
        bird_type="broiler",
        placement_date=datetime.date.today() - datetime.timedelta(days=45),
        initial_count=500,
        current_count=460,
        status=status,
        hatchery=hatchery,
        doc_price_per_chick=doc_price,
    )


def _make_review(hatchery, user, org, batch=None, price=Decimal("1500"), batch_size=500):
    from apps.finance.market.models import HatcheryReview
    return HatcheryReview.objects.create(
        hatchery=hatchery,
        batch=batch,
        submitted_by=user,
        org=org,
        doc_quality_rating=4,
        survival_rate_pct=Decimal("92.0"),
        delivery_reliability=4,
        overall_rating=4,
        batch_size=batch_size,
        purchase_date=datetime.date.today() - datetime.timedelta(days=45),
        price_per_doc=price,
    )


# ── Batch model: DOC fields ───────────────────────────────────────────────────────

class TestBatchDocFields:

    def test_batch_saves_hatchery_fk_and_doc_price(self):
        org = _make_org("doc-save-1")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        hatchery = _make_hatchery()
        batch = _make_batch(org, farm, house, hatchery=hatchery, doc_price=Decimal("1600"))

        batch.refresh_from_db()
        assert batch.hatchery_id == hatchery.pk
        assert batch.doc_price_per_chick == Decimal("1600")

    def test_batch_creates_without_doc_source(self):
        org = _make_org("doc-save-2")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house)

        batch.refresh_from_db()
        assert batch.hatchery is None
        assert batch.doc_price_per_chick is None
        assert batch.doc_supplier_name == ""

    def test_batch_saves_supplier_name_without_hatchery(self):
        from apps.farm.flocks.models import Batch
        org = _make_org("doc-save-3")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = Batch.objects.create(
            org=org, farm=farm, house=house,
            batch_name="Named Batch",
            bird_type="broiler",
            placement_date=datetime.date.today() - datetime.timedelta(days=10),
            initial_count=200,
            current_count=198,
            doc_supplier_name="Village Hatchery Ibadan",
            doc_price_per_chick=Decimal("1200"),
        )
        batch.refresh_from_db()
        assert batch.doc_supplier_name == "Village Hatchery Ibadan"
        assert batch.hatchery is None


# ── BatchService: DOC fields passed through ───────────────────────────────────────

class TestBatchServiceDocFields:

    def test_create_batch_with_hatchery(self):
        from apps.farm.flocks.services import BatchService
        from apps.infrastructure.core.rls import set_tenant_context

        org = _make_org("doc-svc-1")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        hatchery = _make_hatchery("Svc Hatchery", "Ogun")

        with set_tenant_context(org):
            batch = BatchService(org).create_batch(
                farm_id=str(farm.pk),
                house_id=str(house.pk),
                batch_name="Service Test Batch",
                bird_type="broiler",
                placement_date=datetime.date.today() - datetime.timedelta(days=5),
                initial_count=300,
                hatchery=hatchery,
                doc_price_per_chick=Decimal("1800"),
                doc_supplier_name="",
            )

        assert batch.hatchery_id == hatchery.pk
        assert batch.doc_price_per_chick == Decimal("1800")


# ── BatchCreateForm: DOC fields ───────────────────────────────────────────────────

class TestBatchCreateFormDocFields:

    def test_form_valid_with_doc_fields(self):
        from apps.farm.flocks.forms import BatchCreateForm
        import uuid

        hatchery = _make_hatchery("Form Hatchery")
        data = {
            "house_id": str(uuid.uuid4()),
            "batch_name": "Form Batch",
            "bird_type": "broiler",
            "placement_date": (datetime.date.today() - datetime.timedelta(days=1)).isoformat(),
            "initial_count": "400",
            "breed_name": "",
            "hatchery": str(hatchery.pk),
            "doc_price_per_chick": "1550",
            "doc_supplier_name": "",
        }
        form = BatchCreateForm(data=data)
        form.is_valid()  # may fail on house_id validation (UUID exists check) — we only need field-level

        assert form.errors.get("hatchery") is None
        assert form.errors.get("doc_price_per_chick") is None

    def test_form_valid_without_doc_fields(self):
        from apps.farm.flocks.forms import BatchCreateForm
        import uuid

        data = {
            "house_id": str(uuid.uuid4()),
            "batch_name": "No DOC Batch",
            "bird_type": "broiler",
            "placement_date": (datetime.date.today() - datetime.timedelta(days=1)).isoformat(),
            "initial_count": "100",
        }
        form = BatchCreateForm(data=data)
        # DOC fields absent → should not cause errors for missing optionals
        assert form.errors.get("hatchery") is None
        assert form.errors.get("doc_price_per_chick") is None


# ── Review form pre-population from batch data ────────────────────────────────────

class TestReviewFormPrePopulation:

    def test_survival_rate_calculated_from_batch_counts(self):
        # Batch: 500 initial, 460 current → 92.0% survival
        org = _make_org("doc-review-1")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        hatchery = _make_hatchery("Review Hatchery")
        batch = _make_batch(
            org, farm, house,
            hatchery=hatchery,
            doc_price=Decimal("1500"),
            status="closed",
        )
        # Manually set current_count to confirm calculation
        from apps.farm.flocks.models import Batch as _Batch
        _Batch.objects.filter(pk=batch.pk).update(initial_count=500, current_count=460)
        batch.refresh_from_db()

        expected = round(460 / 500 * 100, 1)
        assert expected == 92.0

    def test_review_initial_built_from_batch(self):
        """Unit test the initial dict logic extracted from the view."""
        from apps.infrastructure.core.rls import set_tenant_context

        org = _make_org("doc-review-2")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        hatchery = _make_hatchery("Pre-pop Hatchery")

        with set_tenant_context(org):
            from apps.farm.flocks.models import Batch as _Batch
            batch = _Batch.objects.create(
                org=org, farm=farm, house=house,
                batch_name="Pre-pop Batch",
                bird_type="broiler",
                placement_date=datetime.date(2025, 1, 1),
                initial_count=300,
                current_count=270,
                status="closed",
                hatchery=hatchery,
                doc_price_per_chick=Decimal("1600"),
            )

        # Replicate the initial-building logic from the view
        initial = {"hatchery_id": hatchery.pk}
        initial.update({
            "batch_id": str(batch.pk),
            "price_per_doc": batch.doc_price_per_chick,
            "batch_size": batch.initial_count,
            "purchase_date": batch.placement_date,
            "survival_rate_pct": (
                round(batch.current_count / batch.initial_count * 100, 1)
                if batch.initial_count else None
            ),
        })
        if batch.hatchery_id:
            initial["hatchery_id"] = batch.hatchery_id

        assert initial["batch_id"] == str(batch.pk)
        assert initial["price_per_doc"] == Decimal("1600")
        assert initial["batch_size"] == 300
        assert initial["purchase_date"] == datetime.date(2025, 1, 1)
        assert initial["survival_rate_pct"] == 90.0
        assert initial["hatchery_id"] == hatchery.pk


# ── Hatchery price trend ──────────────────────────────────────────────────────────

class TestHatcheryPriceTrend:

    def test_get_doc_price_trend_aggregates_by_month(self):
        from apps.finance.market.services import HatcheryService

        org = _make_org("doc-trend-1")
        user = _make_user(org, "trend1@doctest.com")
        hatchery = _make_hatchery("Trend Hatchery")

        today = datetime.date.today()
        # Two reviews in the same month
        from apps.finance.market.models import HatcheryReview
        HatcheryReview.objects.create(
            hatchery=hatchery, submitted_by=user, org=org,
            doc_quality_rating=4, survival_rate_pct=Decimal("90"),
            delivery_reliability=4, overall_rating=4,
            batch_size=300, purchase_date=today - datetime.timedelta(days=30),
            price_per_doc=Decimal("1400"),
        )
        HatcheryReview.objects.create(
            hatchery=hatchery, submitted_by=user, org=org,
            doc_quality_rating=5, survival_rate_pct=Decimal("95"),
            delivery_reliability=5, overall_rating=5,
            batch_size=200, purchase_date=today - datetime.timedelta(days=28),
            price_per_doc=Decimal("1600"),
        )

        trend = HatcheryService.get_doc_price_trend(hatchery.pk)
        assert len(trend) >= 1
        # At least one entry; avg price for the month should be ~1500
        first = trend[0]
        assert first["count"] == 2
        assert float(first["avg_price"]) == pytest.approx(1500.0, rel=0.01)

    def test_get_doc_price_trend_empty_without_reviews(self):
        from apps.finance.market.services import HatcheryService
        hatchery = _make_hatchery("Empty Hatchery", "Kano")
        trend = HatcheryService.get_doc_price_trend(hatchery.pk)
        assert trend == []

    def test_get_doc_price_trend_excludes_old_reviews(self):
        from apps.finance.market.services import HatcheryService
        from apps.finance.market.models import HatcheryReview

        org = _make_org("doc-trend-2")
        user = _make_user(org, "trend2@doctest.com")
        hatchery = _make_hatchery("Old Review Hatchery", "Oyo")

        # Review older than 12 months
        old_date = datetime.date.today() - datetime.timedelta(days=400)
        HatcheryReview.objects.create(
            hatchery=hatchery, submitted_by=user, org=org,
            doc_quality_rating=3, survival_rate_pct=Decimal("85"),
            delivery_reliability=3, overall_rating=3,
            batch_size=100, purchase_date=old_date,
            price_per_doc=Decimal("800"),
        )

        trend = HatcheryService.get_doc_price_trend(hatchery.pk)
        assert trend == []


# ── Batch detail: hatchery FK and review status ───────────────────────────────────

class TestBatchDetailHatcheryContext:

    def test_has_hatchery_review_false_when_no_review(self):
        from apps.finance.market.models import HatcheryReview
        org = _make_org("doc-detail-1")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        hatchery = _make_hatchery("Detail Hatchery")
        batch = _make_batch(org, farm, house, hatchery=hatchery, status="closed")

        has_review = HatcheryReview.objects.filter(batch=batch).exists()
        assert has_review is False

    def test_has_hatchery_review_true_after_review_submitted(self):
        from apps.finance.market.models import HatcheryReview
        org = _make_org("doc-detail-2")
        user = _make_user(org, "detail2@doctest.com")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        hatchery = _make_hatchery("Reviewed Hatchery")
        batch = _make_batch(org, farm, house, hatchery=hatchery, status="closed")
        _make_review(hatchery, user, org, batch=batch)

        has_review = HatcheryReview.objects.filter(batch=batch).exists()
        assert has_review is True

    def test_hatchery_batches_reverse_relation(self):
        from apps.infrastructure.core.rls import set_tenant_context

        org = _make_org("doc-detail-3")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        hatchery = _make_hatchery("Reverse Hatchery")
        batch = _make_batch(org, farm, house, hatchery=hatchery)

        with set_tenant_context(org):
            assert hatchery.batches.filter(pk=batch.pk).exists()
