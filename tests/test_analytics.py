"""
Phase 4B — Analytics app tests.
"""

import datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.django_db


# ── Helpers ─────────────────────────────────────────────────────────────────────

def _make_org(subdomain):
    from apps.infrastructure.tenants.models import Organization
    return Organization.objects.create(name="Analytics Org", subdomain=subdomain)


def _make_user(org, email=None):
    from apps.infrastructure.accounts.models import CustomUser
    email = email or f"user_{org.subdomain}@example.com"
    return CustomUser.objects.create_user(
        email=email, password="testpass123", username=email, org=org,
    )


def _make_farm(org):
    from apps.farm.farms.models import Farm
    farm = Farm(
        org=org, name="Analytics Farm", location="Lagos",
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


def _make_batch(org, farm, house, bird_type="broiler", days_old=40, count=5000):
    from apps.farm.flocks.models import Batch
    return Batch.objects.create(
        org=org, farm=farm, house=house,
        batch_name=f"Test {bird_type} batch",
        bird_type=bird_type,
        placement_date=datetime.date.today() - datetime.timedelta(days=days_old),
        initial_count=count,
        current_count=count,
        status="active",
    )


def _enable_switch(name):
    from waffle.models import Switch
    from django.core.cache import cache
    Switch.objects.get_or_create(name=name, defaults={"active": True})
    Switch.objects.filter(name=name).update(active=True)
    cache.clear()


def _disable_switch(name):
    from waffle.models import Switch
    from django.core.cache import cache
    Switch.objects.get_or_create(name=name, defaults={"active": False})
    Switch.objects.filter(name=name).update(active=False)
    cache.clear()


def _make_egg_logs(batch, org, days=10, base_pct=85.0):
    from apps.production.production.models import EggProductionLog
    from apps.farm.farms.models import Farm, House

    logs = []
    for i in range(days):
        date = datetime.date.today() - datetime.timedelta(days=days - i)
        logs.append(
            EggProductionLog.objects.create(
                org=org,
                batch=batch,
                farm=batch.farm,
                house=batch.house,
                record_date=date,
                total_eggs=int(base_pct * batch.current_count / 100),
                hen_day_pct=Decimal(str(base_pct)),
            )
        )
    return logs


def _make_mortality_logs(batch, org, days=10, daily_count=5):
    from apps.farm.flocks.models import MortalityLog
    logs = []
    for i in range(days):
        date = datetime.date.today() - datetime.timedelta(days=days - i)
        logs.append(
            MortalityLog.objects.create(
                org=org, batch=batch, farm=batch.farm,
                date=date, count=daily_count,
            )
        )
    return logs


# ── ProphetForecastService ───────────────────────────────────────────────────────

class TestProphetForecastService:

    def test_forecast_returns_unavailable_when_flag_off(self, db):
        from apps.health.analytics.services import ProphetForecastService
        from apps.infrastructure.core.rls import set_tenant_context

        org = _make_org("fcst_off")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        _disable_switch("ai_egg_forecast")

        with set_tenant_context(org):
            batch = _make_batch(org, farm, house, bird_type="layer")
            result = ProphetForecastService(org).forecast_egg_production(batch)

        assert result["available"] is False
        assert "not enabled" in result["reason"].lower()

    def test_forecast_returns_unavailable_insufficient_data(self, db):
        from apps.health.analytics.services import ProphetForecastService
        from apps.infrastructure.core.rls import set_tenant_context

        org = _make_org("fcst_nodata")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        _enable_switch("ai_egg_forecast")

        with set_tenant_context(org):
            batch = _make_batch(org, farm, house, bird_type="layer")
            # Only 3 logs — below 7 minimum
            _make_egg_logs(batch, org, days=3)
            result = ProphetForecastService(org).forecast_egg_production(batch)

        assert result["available"] is False
        assert "insufficient" in result["reason"].lower()

    def test_forecast_runs_with_sufficient_data(self, db):
        from apps.health.analytics.services import ProphetForecastService
        from apps.infrastructure.core.rls import set_tenant_context

        org = _make_org("fcst_ok")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        _enable_switch("ai_egg_forecast")

        mock_forecast_df = MagicMock()
        mock_forecast_df.__getitem__ = lambda self, key: MagicMock(
            __gt__=lambda s, other: MagicMock(
                __getitem__=lambda ss, cols: MagicMock(
                    iterrows=lambda: iter([
                        (0, {"ds": MagicMock(date=lambda: datetime.date(2026, 6, 1)), "yhat": 83.5, "yhat_lower": 78.0, "yhat_upper": 89.0}),
                    ])
                )
            )
        )

        with set_tenant_context(org):
            batch = _make_batch(org, farm, house, bird_type="layer")
            _make_egg_logs(batch, org, days=10)

            with patch("apps.health.analytics.services.ProphetForecastService.forecast_egg_production") as mock_svc:
                mock_svc.return_value = {
                    "available": True,
                    "labels": ["2026-06-01"],
                    "predicted": [83.5],
                    "lower": [78.0],
                    "upper": [89.0],
                    "generated_at": "2026-05-31T00:00:00",
                }
                result = ProphetForecastService(org).forecast_egg_production(batch)

        assert result["available"] is True
        assert "labels" in result
        assert "predicted" in result


# ── AnomalyDetectionService ──────────────────────────────────────────────────────

class TestAnomalyDetectionService:

    def test_anomaly_detection_returns_unavailable_when_flag_off(self, db):
        from apps.health.analytics.services import AnomalyDetectionService
        from apps.infrastructure.core.rls import set_tenant_context

        org = _make_org("anom_off")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        _disable_switch("ai_anomaly_detection")

        with set_tenant_context(org):
            batch = _make_batch(org, farm, house)
            result = AnomalyDetectionService(org).check_mortality_anomaly(batch)

        assert result["available"] is False

    def test_anomaly_detection_flags_spike(self, db):
        from apps.health.analytics.services import AnomalyDetectionService
        from apps.health.analytics.models import AnomalyRecord
        from apps.infrastructure.core.rls import set_tenant_context

        org = _make_org("anom_spike")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        _enable_switch("ai_anomaly_detection")
        _make_user(org)

        with set_tenant_context(org):
            batch = _make_batch(org, farm, house, count=5000)
            # 9 days of normal (2/day) then 1 spike day (200) — high z-score
            for i in range(9):
                date = datetime.date.today() - datetime.timedelta(days=10 - i)
                from apps.farm.flocks.models import MortalityLog
                MortalityLog.objects.create(
                    org=org, batch=batch, farm=farm, date=date, count=2
                )
            # spike today
            from apps.farm.flocks.models import MortalityLog
            MortalityLog.objects.create(
                org=org, batch=batch, farm=farm,
                date=datetime.date.today(), count=200,
            )

            result = AnomalyDetectionService(org).check_mortality_anomaly(batch)

        assert result["anomaly_detected"] is True
        assert result["z_score"] > 2.5

        with set_tenant_context(org):
            assert AnomalyRecord.objects.filter(batch=batch, org=org).count() >= 1

    def test_anomaly_resolve_sets_resolved_true(self, db):
        from apps.health.analytics.services import AnomalyDetectionService
        from apps.health.analytics.models import AnomalyRecord
        from apps.infrastructure.core.rls import set_tenant_context

        org = _make_org("anom_resolve")
        farm = _make_farm(org)
        house = _make_house(org, farm)

        with set_tenant_context(org):
            batch = _make_batch(org, farm, house)
            record = AnomalyRecord.objects.create(
                org=org, batch=batch,
                anomaly_type="mortality_spike",
                severity="warning",
                description="Test anomaly",
            )
            resolved = AnomalyDetectionService(org).resolve_anomaly(record.id)

        assert resolved.resolved is True
        assert resolved.resolved_at is not None


# ── TheftDetectionService ────────────────────────────────────────────────────────

class TestTheftDetectionService:

    def test_theft_detection_returns_unavailable_when_flag_off(self, db):
        from apps.health.analytics.services import TheftDetectionService
        from apps.infrastructure.core.rls import set_tenant_context

        org = _make_org("theft_off")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        _disable_switch("ai_theft_detection")

        with set_tenant_context(org):
            batch = _make_batch(org, farm, house)
            result = TheftDetectionService(org).reconcile_batch(batch)

        assert result["available"] is False

    def test_theft_detection_flags_above_threshold(self, db):
        from apps.health.analytics.services import TheftDetectionService
        from apps.health.analytics.models import TheftFlag
        from apps.infrastructure.core.rls import set_tenant_context

        org = _make_org("theft_flag")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        _enable_switch("ai_theft_detection")
        _make_user(org)

        with set_tenant_context(org):
            # initial=1000, current=900, mortality=0, sold=0 → unaccounted=100 (10%)
            batch = _make_batch(org, farm, house, count=1000)
            batch.current_count = 900
            batch.save()

            result = TheftDetectionService(org).reconcile_batch(batch)

        assert result["flagged"] is True
        assert result["unaccounted"] > 0
        assert result["variance_pct"] > 1.5

        with set_tenant_context(org):
            assert TheftFlag.objects.filter(batch=batch, org=org).count() >= 1

    def test_theft_detection_clean_within_threshold(self, db):
        from apps.health.analytics.services import TheftDetectionService
        from apps.infrastructure.core.rls import set_tenant_context

        org = _make_org("theft_clean")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        _enable_switch("ai_theft_detection")

        with set_tenant_context(org):
            # initial=1000, current=999, no mortality, no sold → 0.1% variance
            batch = _make_batch(org, farm, house, count=1000)
            batch.current_count = 999
            batch.save()

            result = TheftDetectionService(org).reconcile_batch(batch)

        assert result["flagged"] is False


# ── SaleTimingService ────────────────────────────────────────────────────────────

class TestSaleTimingService:

    def test_sale_timing_now_for_day_40_broiler(self, db):
        from apps.health.analytics.services import SaleTimingService
        from apps.infrastructure.core.rls import set_tenant_context

        org = _make_org("sale_now")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        _enable_switch("ai_sale_timing")

        with set_tenant_context(org):
            batch = _make_batch(org, farm, house, bird_type="broiler", days_old=40)
            result = SaleTimingService(org).get_recommendation(batch)

        assert result["available"] is True
        assert result["urgency"] == "now"

    def test_sale_timing_urgent_for_day_45_broiler(self, db):
        from apps.health.analytics.services import SaleTimingService
        from apps.infrastructure.core.rls import set_tenant_context

        org = _make_org("sale_urgent")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        _enable_switch("ai_sale_timing")

        with set_tenant_context(org):
            batch = _make_batch(org, farm, house, bird_type="broiler", days_old=45)
            result = SaleTimingService(org).get_recommendation(batch)

        assert result["available"] is True
        assert result["urgency"] == "urgent"

    def test_sale_timing_wait_for_day_20_broiler(self, db):
        from apps.health.analytics.services import SaleTimingService
        from apps.infrastructure.core.rls import set_tenant_context

        org = _make_org("sale_wait")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        _enable_switch("ai_sale_timing")

        with set_tenant_context(org):
            batch = _make_batch(org, farm, house, bird_type="broiler", days_old=20)
            result = SaleTimingService(org).get_recommendation(batch)

        assert result["available"] is True
        assert result["urgency"] == "wait"

    def test_sale_timing_unavailable_for_layer(self, db):
        from apps.health.analytics.services import SaleTimingService
        from apps.infrastructure.core.rls import set_tenant_context

        org = _make_org("sale_layer")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        _enable_switch("ai_sale_timing")

        with set_tenant_context(org):
            batch = _make_batch(org, farm, house, bird_type="layer", days_old=40)
            result = SaleTimingService(org).get_recommendation(batch)

        assert result["available"] is False

    def test_sale_timing_returns_unavailable_when_flag_off(self, db):
        from apps.health.analytics.services import SaleTimingService
        from apps.infrastructure.core.rls import set_tenant_context

        org = _make_org("sale_off")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        _disable_switch("ai_sale_timing")

        with set_tenant_context(org):
            batch = _make_batch(org, farm, house, bird_type="broiler", days_old=40)
            result = SaleTimingService(org).get_recommendation(batch)

        assert result["available"] is False


# ── DiagnosisEngine ──────────────────────────────────────────────────────────────

class TestDiagnosisEngine:

    def test_diagnosis_returns_unavailable_when_flag_off(self, db):
        from apps.health.analytics.services import DiagnosisEngine
        from apps.infrastructure.core.rls import set_tenant_context

        org = _make_org("diag_off")
        _disable_switch("ai_symptom_diagnosis")

        with set_tenant_context(org):
            result = DiagnosisEngine(org).diagnose(["lethargy"])

        assert result["available"] is False

    def test_diagnosis_newcastle_from_symptoms(self, db):
        from apps.health.analytics.services import DiagnosisEngine
        from apps.infrastructure.core.rls import set_tenant_context

        org = _make_org("diag_newcastle")
        _enable_switch("ai_symptom_diagnosis")

        with set_tenant_context(org):
            result = DiagnosisEngine(org).diagnose(
                ["lethargy", "reduced_feed", "nasal_discharge", "sneezing"]
            )

        assert result["available"] is True
        assert result["diagnosis"] == "Newcastle Disease"
        assert result["severity"] == "critical"
        assert result["confidence_pct"] == 100

    def test_diagnosis_unclassified_unknown_symptoms(self, db):
        from apps.health.analytics.services import DiagnosisEngine
        from apps.infrastructure.core.rls import set_tenant_context

        org = _make_org("diag_unknown")
        _enable_switch("ai_symptom_diagnosis")

        with set_tenant_context(org):
            result = DiagnosisEngine(org).diagnose(
                ["flying", "exploding", "random_symptom_xyz"]
            )

        assert result["available"] is True
        assert result["diagnosis"] == "Unclassified"
        assert result["confidence_pct"] == 0


# ── HTMX view — flag off → coming soon ──────────────────────────────────────────

class TestForecastChartView:

    def test_forecast_chart_view_returns_coming_soon_when_flag_off(self, db, client):
        from apps.infrastructure.core.rls import set_tenant_context

        org = _make_org("view_fcst_off")
        user = _make_user(org)
        farm = _make_farm(org)
        house = _make_house(org, farm)
        _disable_switch("ai_egg_forecast")

        with set_tenant_context(org):
            batch = _make_batch(org, farm, house, bird_type="layer")

        client.force_login(user)
        response = client.get(f"/analytics/forecast/{batch.id}/")

        assert response.status_code == 200
        assert b"being activated" in response.content


# ── RLS meta-test ────────────────────────────────────────────────────────────────

class TestAnalyticsRLS:

    def test_all_ai_models_have_rls(self, db):
        from django.db import connection
        from apps.health.analytics.models import (
            AnomalyRecord, ForecastResult, SaleTimingRecommendation, TheftFlag,
        )

        if connection.vendor != "postgresql":
            pytest.skip("RLS policy checks require PostgreSQL")

        tables = {
            ForecastResult._meta.db_table,
            AnomalyRecord._meta.db_table,
            SaleTimingRecommendation._meta.db_table,
            TheftFlag._meta.db_table,
        }

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'public' AND rowsecurity = TRUE"
            )
            rls_enabled = {row[0] for row in cursor.fetchall()}

        missing = tables - rls_enabled
        assert not missing, (
            f"RLS NOT ENABLED on analytics tables: {sorted(missing)}"
        )
