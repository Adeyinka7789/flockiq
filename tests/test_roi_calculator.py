"""
ROI Calculator — service and view tests.

All monetary values from ROICalculatorService are in NAIRA (not kobo).
"""

import datetime
from decimal import Decimal

import pytest

pytestmark = pytest.mark.django_db

# ── Shared helpers ────────────────────────────────────────────────────────────


def _make_org(subdomain, plan_tier="monthly"):
    from apps.infrastructure.tenants.models import Organization
    return Organization.objects.create(
        name="ROI Test Org",
        subdomain=subdomain,
        plan_tier=plan_tier,
        subscription_status="active",
        onboarding_complete=True,
        is_active=True,
    )


def _make_user(org):
    from apps.infrastructure.accounts.models import CustomUser
    return CustomUser.objects.create_user(
        username=f"owner-{org.subdomain}",
        email=f"owner@{org.subdomain}.com",
        password="testpass123",
        org=org,
        role="owner",
    )


def _make_farm(org):
    from apps.farm.farms.models import Farm
    farm = Farm(
        org=org, name="ROI Farm", location="Lagos",
        latitude=Decimal("6.5244"), longitude=Decimal("3.3792"),
        farm_type="broiler",
    )
    farm.clean()
    farm.save()
    return farm


def _make_house(org, farm):
    from apps.farm.farms.models import House
    return House.objects.create(
        org=org, farm=farm, name="House A", capacity=5000, house_type="broiler",
    )


def _make_batch(org, farm, house, count=5000, status="active"):
    from apps.farm.flocks.models import Batch
    return Batch.objects.create(
        org=org, farm=farm, house=house,
        batch_name="ROI Batch",
        bird_type="broiler",
        placement_date=datetime.date.today() - datetime.timedelta(days=42),
        initial_count=count,
        current_count=count,
        status=status,
    )


# ── Service tests ─────────────────────────────────────────────────────────────


class TestROICalculatorServiceStructure:

    def test_returns_complete_dict_when_no_batch(self):
        """No batches → still returns a fully-keyed dict, no exceptions."""
        from apps.finance.finance.roi_service import ROICalculatorService

        org = _make_org("roi_no_batch")
        result = ROICalculatorService(org).calculate()

        required_keys = {
            "mortality_savings", "feed_savings", "theft_prevention_value",
            "subscription_cost", "net_value_delivered", "roi_multiple",
            "vaccination_compliance_rate", "alerts_fired", "time_period",
            "has_data",
        }
        assert required_keys.issubset(result.keys())
        assert result["has_data"] is False

    def test_returns_complete_dict_when_batch_has_no_records(self):
        """Batch with no feed/sales/anomaly records → zeros, no exceptions."""
        from apps.finance.finance.roi_service import ROICalculatorService
        from apps.infrastructure.core.rls import set_tenant_context

        org = _make_org("roi_empty_batch")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        with set_tenant_context(org):
            batch = _make_batch(org, farm, house)
            result = ROICalculatorService(org, batch).calculate()

        assert result["has_data"] is True
        assert result["mortality_savings"] == 0
        assert result["feed_savings"] == 0
        assert result["theft_prevention_value"] == 0
        assert result["vaccination_compliance_rate"] == 0.0
        assert result["alerts_fired"] == 0
        assert result["time_period"]["batch_name"] == "ROI Batch"

    def test_net_value_delivered_formula(self):
        """net_value_delivered = savings total - subscription_cost."""
        from apps.finance.finance.roi_service import ROICalculatorService
        from apps.infrastructure.core.rls import set_tenant_context

        org = _make_org("roi_net_value")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        with set_tenant_context(org):
            batch = _make_batch(org, farm, house)
            result = ROICalculatorService(org, batch).calculate()

        expected_net = (
            result["mortality_savings"]
            + result["feed_savings"]
            + result["theft_prevention_value"]
            - result["subscription_cost"]
        )
        assert result["net_value_delivered"] == expected_net

    def test_roi_multiple_correct_when_subscription_cost_nonzero(self):
        """roi_multiple = net_value_delivered / subscription_cost."""
        from apps.finance.finance.roi_service import ROICalculatorService
        from apps.infrastructure.billing.models import BillingPlan
        from apps.infrastructure.core.rls import set_tenant_context

        org = _make_org("roi_multiple_check")
        BillingPlan.objects.create(
            name="Monthly Test Plan",
            plan_tier="monthly",
            amount_kobo=5_000_00,  # ₦5,000
            billing_interval="monthly",
            is_active=True,
        )
        farm = _make_farm(org)
        house = _make_house(org, farm)
        with set_tenant_context(org):
            batch = _make_batch(org, farm, house)
            result = ROICalculatorService(org, batch).calculate()

        if result["subscription_cost"] > 0:
            expected = round(
                result["net_value_delivered"] / result["subscription_cost"], 2
            )
            assert result["roi_multiple"] == expected

    def test_roi_multiple_is_zero_when_subscription_cost_is_zero(self):
        """If subscription_cost = 0 (no payments, no plan), roi_multiple = 0.0."""
        from apps.finance.finance.roi_service import ROICalculatorService
        from apps.infrastructure.core.rls import set_tenant_context

        # No BillingPlan created → subscription_cost falls back to 0
        org = _make_org("roi_zero_sub", plan_tier="trial")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        with set_tenant_context(org):
            batch = _make_batch(org, farm, house)
            result = ROICalculatorService(org, batch).calculate()

        assert result["subscription_cost"] == 0
        assert result["roi_multiple"] == 0.0

    def test_mortality_savings_scale_with_alert_count(self):
        """More mortality anomaly alerts → larger mortality_savings (up to 10% cap)."""
        from apps.finance.finance.roi_service import ROICalculatorService
        from apps.health.analytics.models import AnomalyRecord
        from apps.infrastructure.core.rls import set_tenant_context

        org = _make_org("roi_mort_scale")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        with set_tenant_context(org):
            batch = _make_batch(org, farm, house, count=1000)
            AnomalyRecord.objects.create(
                org=org, batch=batch,
                anomaly_type="mortality_spike",
                severity="warning",
                description="Test spike",
            )
            result_one = ROICalculatorService(org, batch).calculate()

            AnomalyRecord.objects.create(
                org=org, batch=batch,
                anomaly_type="mortality_spike",
                severity="critical",
                description="Second spike",
            )
            result_two = ROICalculatorService(org, batch).calculate()

        assert result_two["mortality_savings"] > result_one["mortality_savings"]

    def test_theft_prevention_only_counts_low_variance_flags(self):
        """TheftFlags with variance_pct >= 1.5% are excluded (not caught early enough)."""
        from apps.finance.finance.roi_service import ROICalculatorService
        from apps.health.analytics.models import TheftFlag
        from apps.infrastructure.core.rls import set_tenant_context

        org = _make_org("roi_theft_filter")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        with set_tenant_context(org):
            batch = _make_batch(org, farm, house, count=1000)
            # High variance — should be excluded
            TheftFlag.objects.create(
                org=org, batch=batch,
                unaccounted_birds=50,
                variance_pct=Decimal("5.00"),
                initial_count=1000,
                total_mortality=10,
                total_sold=940,
                current_count=0,
            )
            result_excluded = ROICalculatorService(org, batch).calculate()

            # Low variance — should be included
            TheftFlag.objects.create(
                org=org, batch=batch,
                unaccounted_birds=10,
                variance_pct=Decimal("1.00"),
                initial_count=1000,
                total_mortality=10,
                total_sold=980,
                current_count=0,
            )
            result_included = ROICalculatorService(org, batch).calculate()

        assert result_excluded["theft_prevention_value"] == 0
        assert result_included["theft_prevention_value"] > 0


# ── View tests ────────────────────────────────────────────────────────────────


class TestROIReportView:

    def test_roi_report_requires_login(self, client, test_batch):
        response = client.get("/finance/roi/")
        assert response.status_code in (301, 302)

    def test_roi_report_returns_200_for_authenticated_user(
        self, client, tenant_user, test_batch,
    ):
        client.force_login(tenant_user)
        response = client.get("/finance/roi/")
        assert response.status_code == 200

    def test_roi_report_shows_upgrade_prompt_on_trial_plan(self, client):
        org = _make_org("roi_trial_view", plan_tier="trial")
        user = _make_user(org)
        client.force_login(user)
        response = client.get("/finance/roi/")
        assert response.status_code == 200
        assert b"Upgrade" in response.content

    def test_roi_report_batch_htmx_endpoint_returns_200(
        self, client, tenant_user, test_batch,
    ):
        client.force_login(tenant_user)
        response = client.get(
            f"/finance/roi/batch/{test_batch.pk}/",
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200

    def test_roi_report_batch_htmx_404_for_wrong_org(self, client, test_batch):
        other_org = _make_org("roi_htmx_other")
        other_user = _make_user(other_org)
        client.force_login(other_user)
        response = client.get(f"/finance/roi/batch/{test_batch.pk}/")
        assert response.status_code == 404

    def test_roi_report_htmx_partial_returns_200(self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        response = client.get("/finance/roi/", HTTP_HX_REQUEST="true")
        assert response.status_code == 200

    def test_roi_report_with_batch_query_param(self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        response = client.get(f"/finance/roi/?batch={test_batch.pk}")
        assert response.status_code == 200

    def test_roi_calculate_exception_in_compute_returns_fallback(self):
        from apps.finance.finance.roi_service import ROICalculatorService
        from apps.infrastructure.core.rls import set_tenant_context
        from unittest.mock import patch

        org = _make_org("roi_exc_fallback")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        with set_tenant_context(org):
            batch = _make_batch(org, farm, house)
            svc = ROICalculatorService(org, batch)
            with patch.object(svc, "_compute", side_effect=Exception("compute boom")):
                result = svc.calculate()

        assert result["has_data"] is False
        assert result["time_period"]["batch_name"] == "ROI Batch"

    def test_roi_market_price_path_with_market_price_record(self):
        from apps.finance.finance.roi_service import ROICalculatorService
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.finance.market.models import MarketPrice

        org = _make_org("roi_mktprice")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        with set_tenant_context(org):
            batch = _make_batch(org, farm, house)
            MarketPrice.objects.create(
                org=org,
                product_type="live_birds",
                price_per_unit_kobo=420_000,
                date=datetime.date.today(),
                unit="bird",
                market_name="Lagos Market",
            )
            result = ROICalculatorService(org, batch).calculate()

        assert result["has_data"] is True
