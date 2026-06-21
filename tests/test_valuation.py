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
        from apps.infrastructure.billing.models import ValuationSettings
        from apps.infrastructure.core.valuation import FlockValuationService
        org = _make_org("val-broiler-3")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house, bird_type="broiler")

        result = FlockValuationService(batch).estimate_value()
        # Fallback now sourced from the admin-configured ValuationSettings row.
        assert result["price_per_unit"] == ValuationSettings.get_current().broiler_price_per_kg
        assert result["price_source"] == "fallback"
        assert result["confidence"] == "low"


# ── Service: breed-specific estimated weight ────────────────────────────────────

class TestBroilerBreedAwareWeight:
    """The estimated (no-WeightRecord) broiler weight curve must be breed-aware:
    scaled to each breed's benchmark target_weight_day42_kg rather than always
    using the heavy Cobb-class curve. Day 42 is used because it is a curve anchor
    and the benchmark day-42 targets divide it cleanly."""

    def test_cobb_uses_cobb_specific_curve(self):
        # Cobb 500's target_weight_day42_kg (2.4) equals the reference curve's
        # day-42 anchor, so the scale is 1.0 and day 42 → exactly 2.40 kg.
        from apps.infrastructure.core.valuation import FlockValuationService
        org = _make_org("val-breed-cobb")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(
            org, farm, house, bird_type="broiler",
            breed_name="Cobb 500", days_old=42,
        )

        result = FlockValuationService(batch).estimate_value()
        assert result["weight_source"] == "estimated"
        assert result["avg_weight_kg"] == Decimal("2.40")

    def test_noiler_uses_lighter_breed_specific_curve(self):
        # Noiler's target_weight_day42_kg is 1.6 → scale 1.6/2.4 → day 42 = 1.60 kg,
        # markedly lighter than Cobb at the same age (the bug being fixed).
        from apps.infrastructure.core.valuation import FlockValuationService
        org = _make_org("val-breed-noiler")
        farm = _make_farm(org)
        # One active batch per house — the unique_active_batch_per_house
        # constraint forbids two active batches sharing a house, so the two
        # breeds being compared each get their own house.
        cobb_house = _make_house(org, farm)
        noiler_house = _make_house(org, farm)
        cobb = _make_batch(
            org, farm, cobb_house, bird_type="broiler",
            breed_name="Cobb 500", days_old=42, current=480,
        )
        noiler = _make_batch(
            org, farm, noiler_house, bird_type="broiler",
            breed_name="Noiler", days_old=42, current=480,
        )

        cobb_result = FlockValuationService(cobb).estimate_value()
        noiler_result = FlockValuationService(noiler).estimate_value()

        assert noiler_result["avg_weight_kg"] == Decimal("1.60")
        # Same age and count, lighter breed → lower estimated weight and value.
        assert noiler_result["avg_weight_kg"] < cobb_result["avg_weight_kg"]
        assert noiler_result["estimated_value_naira"] < cobb_result["estimated_value_naira"]

    def test_unknown_breed_falls_back_to_default_broiler_curve(self):
        # An unrecognised breed name resolves via get_benchmark() to
        # default_broiler (target 2.2), NOT a hardcoded Cobb-only curve (2.4).
        from apps.infrastructure.core.valuation import FlockValuationService
        org = _make_org("val-breed-unknown")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(
            org, farm, house, bird_type="broiler",
            breed_name="Marshall", days_old=42,
        )

        result = FlockValuationService(batch).estimate_value()
        # default_broiler day-42 target (2.2) → distinct from the old Cobb 2.4.
        assert result["avg_weight_kg"] == Decimal("2.20")

    def test_blank_breed_falls_back_to_default_broiler_curve(self):
        from apps.infrastructure.core.valuation import FlockValuationService
        org = _make_org("val-breed-blank")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(
            org, farm, house, bird_type="broiler",
            breed_name="", days_old=42,
        )

        result = FlockValuationService(batch).estimate_value()
        assert result["avg_weight_kg"] == Decimal("2.20")


# ── Service: layer ─────────────────────────────────────────────────────────────

class TestLayerValuation:

    def test_layer_returns_point_of_lay_estimate(self):
        from apps.infrastructure.billing.models import ValuationSettings
        from apps.infrastructure.core.valuation import FlockValuationService
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
        assert result["price_per_unit"] == ValuationSettings.get_current().layer_point_of_lay_price
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


# ── ValuationSettings singleton ─────────────────────────────────────────────────

class TestValuationSettingsModel:

    def test_get_current_creates_singleton_with_seeded_defaults(self):
        from apps.infrastructure.billing.models import ValuationSettings
        # Drop any existing row (the seed migration created one) to exercise the
        # create path, then confirm get_current() recreates it with defaults.
        ValuationSettings.objects.all().delete()

        row = ValuationSettings.get_current()
        assert row.pk == 1
        assert row.broiler_price_per_kg == Decimal("1850.00")
        assert row.layer_point_of_lay_price == Decimal("2800.00")
        assert row.generic_per_bird_price == Decimal("2000.00")

    def test_get_current_is_idempotent_singleton(self):
        from apps.infrastructure.billing.models import ValuationSettings
        a = ValuationSettings.get_current()
        b = ValuationSettings.get_current()
        assert a.pk == b.pk == 1
        assert ValuationSettings.objects.count() == 1

    def test_save_enforces_singleton_pk(self):
        from apps.infrastructure.billing.models import ValuationSettings
        row = ValuationSettings.get_current()
        row.broiler_price_per_kg = Decimal("1999.00")
        row.save()
        assert row.pk == 1
        assert ValuationSettings.objects.count() == 1
        assert ValuationSettings.get_current().broiler_price_per_kg == Decimal("1999.00")

    def test_migration_seeded_settings_row_exists(self):
        # The 0004_seed_valuation_settings data migration runs when the test DB
        # is built, so the singleton row is present before any get_current call.
        from apps.infrastructure.billing.models import ValuationSettings
        assert ValuationSettings.objects.filter(pk=1).exists()


# ── Service: admin fallback (ValuationSettings) ─────────────────────────────────

class TestAdminFallbackValuation:

    def test_broiler_fallback_uses_configured_settings_price(self):
        from apps.infrastructure.billing.models import ValuationSettings
        from apps.infrastructure.core.valuation import FlockValuationService

        row = ValuationSettings.get_current()
        row.broiler_price_per_kg = Decimal("2500.00")
        row.save()

        org = _make_org("val-admin-broiler")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house, bird_type="broiler")

        result = FlockValuationService(batch).estimate_value()
        # No override, no market data → admin fallback at the configured price.
        assert result["price_source"] == "fallback"
        assert result["confidence"] == "low"
        assert result["price_per_unit"] == Decimal("2500")

    def test_layer_fallback_uses_configured_settings_price(self):
        from apps.infrastructure.billing.models import ValuationSettings
        from apps.infrastructure.core.valuation import FlockValuationService

        row = ValuationSettings.get_current()
        row.layer_point_of_lay_price = Decimal("3100.00")
        row.save()

        org = _make_org("val-admin-layer")
        farm = _make_farm(org)
        house = _make_house(org, farm, house_type="layer")
        batch = _make_batch(
            org, farm, house, bird_type="layer",
            breed_name="ISA Brown", days_old=200, initial=100, current=100,
        )

        result = FlockValuationService(batch).estimate_value()
        assert result["price_source"] == "fallback"
        assert result["price_per_unit"] == Decimal("3100")
        assert result["estimated_value_naira"] == Decimal("310000")  # 100 × 3100


# ── Service: farmer override ────────────────────────────────────────────────────

class TestFarmerOverrideValuation:

    def _set_override(self, org, batch, price, unit):
        from apps.infrastructure.core.rls import set_tenant_context
        from django.utils import timezone
        with set_tenant_context(org):
            batch.valuation_override_per_unit = Decimal(price)
            batch.valuation_override_unit = unit
            batch.valuation_override_set_at = timezone.now()
            batch.save()

    def test_override_per_bird_wins_with_high_confidence(self):
        from apps.infrastructure.core.valuation import FlockValuationService
        org = _make_org("val-ovr-bird")
        farm = _make_farm(org)
        house = _make_house(org, farm, house_type="layer")
        batch = _make_batch(
            org, farm, house, bird_type="layer", current=200,
        )
        self._set_override(org, batch, "2500.00", "bird")

        result = FlockValuationService(batch).estimate_value()
        assert result["valuation_method"] == "farmer_override"
        assert result["price_source"] == "override"
        assert result["confidence"] == "high"
        assert result["unit"] == "bird"
        assert result["price_per_unit"] == Decimal("2500")
        # 200 birds × ₦2,500 = ₦500,000
        assert result["estimated_value_naira"] == Decimal("500000")

    def test_override_per_kg_uses_weight_estimate(self):
        from apps.farm.flocks.models import WeightRecord
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.infrastructure.core.valuation import FlockValuationService

        org = _make_org("val-ovr-kg")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house, bird_type="broiler", current=300)
        with set_tenant_context(org):
            WeightRecord.objects.create(
                org=org, batch=batch, sample_date=datetime.date.today(),
                sample_size=20, avg_weight_kg=Decimal("2.000"),
            )
        self._set_override(org, batch, "1800.00", "kg")

        result = FlockValuationService(batch).estimate_value()
        assert result["valuation_method"] == "farmer_override"
        assert result["unit"] == "kg"
        # 300 birds × 2.0 kg × ₦1,800 = ₦1,080,000
        assert result["estimated_value_naira"] == Decimal("1080000")

    def test_override_beats_market_and_settings(self):
        """Priority order: override > market data > admin settings fallback."""
        from apps.farm.flocks.models import WeightRecord
        from apps.finance.market.models import MarketPrice
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.infrastructure.core.valuation import FlockValuationService

        org = _make_org("val-priority")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house, bird_type="broiler", current=400)

        with set_tenant_context(org):
            # Real market data present (would normally win over fallback)…
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
        # …but the farmer override outranks everything.
        self._set_override(org, batch, "3000.00", "bird")

        result = FlockValuationService(batch).estimate_value()
        assert result["valuation_method"] == "farmer_override"
        assert result["confidence"] == "high"
        assert result["price_per_unit"] == Decimal("3000")
        assert result["estimated_value_naira"] == Decimal("1200000")  # 400 × 3000


# ── Superadmin settings UI ──────────────────────────────────────────────────────

class TestValuationSettingsSuperadmin:

    def _make_superadmin(self):
        from apps.infrastructure.accounts.models import CustomUser
        return CustomUser.objects.create_user(
            username="val-superadmin",
            email="val-admin@flockiq.com",
            password="testpass123",
            org=None, role="super_admin",
            is_staff=True, is_superuser=True,
        )

    def test_superadmin_can_view_settings(self, client):
        client.force_login(self._make_superadmin())
        resp = client.get("/superadmin/valuation-settings/")
        assert resp.status_code == 200
        assert b"Valuation Settings" in resp.content

    def test_superadmin_can_update_settings(self, client):
        from apps.infrastructure.billing.models import ValuationSettings
        admin = self._make_superadmin()
        client.force_login(admin)
        resp = client.post("/superadmin/valuation-settings/", {
            "broiler_price_per_kg": "2100.00",
            "layer_point_of_lay_price": "3000.00",
            "generic_per_bird_price": "2200.00",
        })
        assert resp.status_code == 200
        row = ValuationSettings.get_current()
        assert row.broiler_price_per_kg == Decimal("2100.00")
        assert row.layer_point_of_lay_price == Decimal("3000.00")
        assert row.generic_per_bird_price == Decimal("2200.00")
        assert row.updated_by_id == admin.pk

    def test_invalid_price_is_rejected(self, client):
        from apps.infrastructure.billing.models import ValuationSettings
        client.force_login(self._make_superadmin())
        before = ValuationSettings.get_current().broiler_price_per_kg
        resp = client.post("/superadmin/valuation-settings/", {
            "broiler_price_per_kg": "-5",
            "layer_point_of_lay_price": "3000.00",
            "generic_per_bird_price": "2200.00",
        })
        assert resp.status_code == 422
        assert ValuationSettings.get_current().broiler_price_per_kg == before

    def test_non_superadmin_cannot_access(self, client):
        # SuperAdminMixin redirects non-admins to the dashboard rather than 200.
        from apps.infrastructure.accounts.models import CustomUser
        org = _make_org("val-nonadmin")
        owner = CustomUser.objects.create_user(
            username="val-owner", email="owner@val-nonadmin.com",
            password="testpass123", org=org, role="owner", email_verified=True,
        )
        client.force_login(owner)
        resp = client.get("/superadmin/valuation-settings/")
        assert resp.status_code == 302
        assert "/superadmin/" not in resp.url


# ── Farmer override UI (batch detail) ───────────────────────────────────────────

class TestValuationOverrideView:

    def _make_user(self, org, role):
        from apps.infrastructure.accounts.models import CustomUser
        return CustomUser.objects.create_user(
            username=f"{role}-{org.subdomain}",
            email=f"{role}@{org.subdomain}.com",
            password="testpass123",
            org=org, role=role, email_verified=True,
        )

    def _batch(self, subdomain, current=200):
        org = _make_org(subdomain)
        farm = _make_farm(org)
        house = _make_house(org, farm, house_type="layer")
        batch = _make_batch(
            org, farm, house, bird_type="layer", current=current,
        )
        return org, batch

    def test_owner_can_set_override(self, client):
        from apps.farm.flocks.models import Batch
        from apps.infrastructure.core.rls import set_tenant_context

        org, batch = self._batch("ovr-owner")
        client.force_login(self._make_user(org, "owner"))
        resp = client.post(f"/batches/{batch.pk}/valuation-override/", {
            "price": "2400.00", "unit": "bird",
        })
        assert resp.status_code == 204
        with set_tenant_context(org):
            refreshed = Batch.objects.get(pk=batch.pk)
        assert refreshed.valuation_override_per_unit == Decimal("2400.00")
        assert refreshed.valuation_override_unit == "bird"
        assert refreshed.valuation_override_set_by_id is not None
        assert refreshed.valuation_override_set_at is not None

    def test_manager_can_set_override(self, client):
        org, batch = self._batch("ovr-manager")
        client.force_login(self._make_user(org, "manager"))
        resp = client.post(f"/batches/{batch.pk}/valuation-override/", {
            "price": "2400.00", "unit": "bird",
        })
        assert resp.status_code == 204

    def test_supervisor_cannot_set_override(self, client):
        org, batch = self._batch("ovr-supervisor")
        client.force_login(self._make_user(org, "supervisor"))
        resp = client.post(f"/batches/{batch.pk}/valuation-override/", {
            "price": "2400.00", "unit": "bird",
        })
        assert resp.status_code == 403

    def test_data_entry_cannot_set_override(self, client):
        org, batch = self._batch("ovr-dataentry")
        client.force_login(self._make_user(org, "data_entry"))
        resp = client.post(f"/batches/{batch.pk}/valuation-override/", {
            "price": "2400.00", "unit": "bird",
        })
        assert resp.status_code == 403

    def test_clear_override_reverts_to_fallback(self, client):
        from apps.farm.flocks.models import Batch
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.infrastructure.core.valuation import FlockValuationService

        org, batch = self._batch("ovr-clear")
        client.force_login(self._make_user(org, "owner"))

        # Set an override, then clear it.
        client.post(f"/batches/{batch.pk}/valuation-override/", {
            "price": "2400.00", "unit": "bird",
        })
        resp = client.post(f"/batches/{batch.pk}/valuation-override/", {
            "action": "clear",
        })
        assert resp.status_code == 204

        with set_tenant_context(org):
            refreshed = Batch.objects.get(pk=batch.pk)
        assert refreshed.valuation_override_per_unit is None
        result = FlockValuationService(refreshed).estimate_value()
        assert result["valuation_method"] != "farmer_override"
        assert result["price_source"] != "override"
