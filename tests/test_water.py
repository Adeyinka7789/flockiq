"""
Phase 3B — Water app tests.
"""

import datetime
import uuid
from decimal import Decimal
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.django_db


# ── Helpers ─────────────────────────────────────────────────────────────────────

def _make_org(subdomain):
    from apps.infrastructure.tenants.models import Organization
    return Organization.objects.create(name="Water Org", subdomain=subdomain)


def _make_user(org, email, username):
    from apps.infrastructure.accounts.models import CustomUser
    return CustomUser.objects.create_user(
        email=email, password="testpass123", username=username, org=org,
    )


def _make_farm(org, name="Water Farm"):
    from apps.farm.farms.models import Farm
    from apps.infrastructure.core.rls import set_tenant_context
    with set_tenant_context(org):
        farm = Farm(
            org=org, name=name, location="Abuja",
            latitude=Decimal("9.0765"), longitude=Decimal("7.3986"),
            farm_type="layer",
        )
        farm.clean()
        farm.save()
    return farm


def _make_house(org, farm):
    from apps.farm.farms.models import House
    from apps.infrastructure.core.rls import set_tenant_context
    with set_tenant_context(org):
        return House.objects.create(
            org=org, farm=farm, name="House A", capacity=2000, house_type="layer",
        )


def _make_batch(org, farm, house, status="active"):
    from apps.farm.flocks.models import Batch
    from apps.infrastructure.core.rls import set_tenant_context
    with set_tenant_context(org):
        return Batch.objects.create(
            org=org, farm=farm, house=house,
            batch_name="Water Test Batch",
            bird_type="layer",
            placement_date=datetime.date.today() - datetime.timedelta(days=20),
            initial_count=1000,
            current_count=1000,
            status=status,
        )


def _log_water(org, batch, litres_consumed=40, record_date=None):
    from apps.production.water.services import WaterService
    from apps.infrastructure.core.rls import set_tenant_context

    with set_tenant_context(org):
        return WaterService(org).log_water(
            batch_id=str(batch.id),
            record_date=record_date or datetime.date.today(),
            litres_consumed=litres_consumed,
        )


# ── 1. WaterLog model ─────────────────────────────────────────────────────────────

class TestWaterLogModel:

    def test_water_log_created(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        org = _make_org("watermodel1")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house)

        with set_tenant_context(org):
            log = _log_water(org, batch, litres_consumed=40)

        assert log.pk is not None
        assert float(log.litres_consumed) == 40.0
        assert log.org == org

    def test_requirement_auto_calculated(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        org = _make_org("waterreq")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house)

        with set_tenant_context(org):
            log = _log_water(org, batch, litres_consumed=40)
            log.refresh_from_db()

        assert log.requirement_litres is not None
        # 1000 birds: (1000/200)*40 = 200 L
        assert float(log.requirement_litres) == pytest.approx(200.0, abs=1.0)

    def test_variance_calculated_correctly(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        org = _make_org("watervariance")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house)

        with set_tenant_context(org):
            log = _log_water(org, batch, litres_consumed=40)
            log.refresh_from_db()

        if log.requirement_litres is not None:
            expected = Decimal("40") - log.requirement_litres
            assert float(log.variance_litres) == pytest.approx(float(expected), abs=0.1)

    def test_anomaly_flagged_below_80pct(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        org = _make_org("wateranomaly")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        # Small batch so requirement is low and we can trigger anomaly easily
        from apps.farm.flocks.models import Batch
        with set_tenant_context(org):
            batch = Batch.objects.create(
                org=org, farm=farm, house=house,
                batch_name="Anomaly Batch",
                bird_type="layer",
                placement_date=datetime.date.today() - datetime.timedelta(days=10),
                initial_count=200,
                current_count=200,
                status="active",
            )
        # requirement = (200/200)*40 = 40L; 80% threshold = 32L; log 10L → anomaly
        with set_tenant_context(org):
            log = _log_water(org, batch, litres_consumed=10)
            log.refresh_from_db()

        assert log.anomaly_flagged is True

    def test_no_anomaly_above_80pct(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        org = _make_org("waternoanomaly")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        from apps.farm.flocks.models import Batch
        with set_tenant_context(org):
            batch = Batch.objects.create(
                org=org, farm=farm, house=house,
                batch_name="Normal Batch",
                bird_type="layer",
                placement_date=datetime.date.today() - datetime.timedelta(days=10),
                initial_count=200,
                current_count=200,
                status="active",
            )
        # requirement = 40L; 80% = 32L; log 35L → no anomaly
        with set_tenant_context(org):
            log = _log_water(org, batch, litres_consumed=35)
            log.refresh_from_db()

        assert log.anomaly_flagged is False


# ── 2. WaterService ───────────────────────────────────────────────────────────────

class TestWaterService:

    def test_water_anomaly_fires_notification(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.infrastructure.notifications.models import AlertRule, OutboxEvent
        from apps.farm.flocks.models import Batch
        org = _make_org("waternotif")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        user = _make_user(org, "waternotif@example.com", "waternotif")
        with set_tenant_context(org):
            batch = Batch.objects.create(
                org=org, farm=farm, house=house,
                batch_name="Notif Batch",
                bird_type="layer",
                placement_date=datetime.date.today() - datetime.timedelta(days=10),
                initial_count=200,
                current_count=200,
                status="active",
            )
            AlertRule.objects.filter(org=org, event_type="water_drop").update(
                channels=["in_app"],
                notify_roles=["owner"],
                is_active=True,
                cooldown_minutes=0,
            )
        user.role = "owner"
        user.save()

        with set_tenant_context(org):
            _log_water(org, batch, litres_consumed=5)

        assert OutboxEvent.objects.filter(event_type="water_drop").exists()

    def test_water_summary_returns_correct_structure(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.production.water.services import WaterService
        org = _make_org("watersummary")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house)

        with set_tenant_context(org):
            _log_water(org, batch, litres_consumed=40)
            summary = WaterService(org).get_water_summary(str(batch.id))

        assert "avg_daily_consumption" in summary
        assert "anomaly_count_last_7days" in summary
        assert "last_7_days" in summary

    def test_log_water_inactive_batch_raises(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.production.water.services import WaterService
        org = _make_org("waterinactive")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house, status="closed")

        with set_tenant_context(org):
            with pytest.raises(ValueError, match="closed"):
                WaterService(org).log_water(
                    batch_id=str(batch.id),
                    record_date=datetime.date.today(),
                    litres_consumed=40,
                )


# ── 3. HTMX views ─────────────────────────────────────────────────────────────────

class TestWaterHTMXViews:

    def _setup(self, db, subdomain):
        org = _make_org(subdomain)
        user = _make_user(org, f"{subdomain}@example.com", subdomain)
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house)
        return org, user, farm, house, batch

    def test_log_view_requires_login(self, db, client):
        import uuid
        response = client.post(f"/production/water/{uuid.uuid4()}/log/", {})
        assert response.status_code in (302, 301)

    def test_log_view_valid_post_returns_200(self, db, client):
        org, user, farm, house, batch = self._setup(db, "waterview1")
        client.force_login(user)
        response = client.post(
            f"/production/water/{batch.id}/log/",
            {
                "record_date": datetime.date.today().isoformat(),
                "litres_consumed": "40",
                "notes": "",
            },
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        assert "waterLogged" in response["HX-Trigger"]

    def test_table_view_returns_200(self, db, client):
        org, user, farm, house, batch = self._setup(db, "waterviewtable")
        client.force_login(user)
        response = client.get(f"/production/water/{batch.id}/table/")
        assert response.status_code == 200
        assert b"water-table" in response.content

    def test_summary_view_returns_200(self, db, client):
        org, user, farm, house, batch = self._setup(db, "waterviewsummary")
        client.force_login(user)
        response = client.get(f"/production/water/{batch.id}/summary/")
        assert response.status_code == 200
        assert b"water-summary-card" in response.content


# ── 4. RLS isolation ──────────────────────────────────────────────────────────────

class TestWaterRLSIsolation:

    def test_water_log_rls_isolation(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.production.water.models import WaterLog

        org_a = _make_org("waterrlsa")
        farm_a = _make_farm(org_a, "Farm A")
        house_a = _make_house(org_a, farm_a)
        batch_a = _make_batch(org_a, farm_a, house_a)

        org_b = _make_org("waterrlsb")
        farm_b = _make_farm(org_b, "Farm B")
        house_b = _make_house(org_b, farm_b)
        batch_b = _make_batch(org_b, farm_b, house_b)

        with set_tenant_context(org_a):
            _log_water(org_a, batch_a, litres_consumed=40)

        with set_tenant_context(org_b):
            _log_water(org_b, batch_b, litres_consumed=50)

        with set_tenant_context(org_a):
            count_a = WaterLog.objects.count()

        with set_tenant_context(org_b):
            count_b = WaterLog.objects.count()

        assert count_a == 1
        assert count_b == 1


# ── 5. Service edge cases (services.py lines 28-29, 73-90) ───────────────────

class TestWaterServiceEdgeCases:

    def test_log_water_batch_not_found_raises(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.production.water.services import WaterService
        org = _make_org("waternotfound1")
        with set_tenant_context(org):
            with pytest.raises(ValueError, match="not found"):
                WaterService(org).log_water(
                    batch_id=str(uuid.uuid4()),
                    record_date=datetime.date.today(),
                    litres_consumed=40,
                )

    def test_get_trend_data_with_logs(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.production.water.services import WaterService
        org = _make_org("watertrend1")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house)

        with set_tenant_context(org):
            _log_water(org, batch, litres_consumed=40)
            trend = WaterService(org).get_trend_data(str(batch.id))

        assert "labels" in trend
        assert "actual_data" in trend
        assert "requirement_data" in trend
        assert len(trend["labels"]) >= 1
        assert float(trend["actual_data"][0]) == pytest.approx(40.0)

    def test_get_trend_data_empty(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.production.water.services import WaterService
        org = _make_org("watertrend2")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house)

        with set_tenant_context(org):
            trend = WaterService(org).get_trend_data(str(batch.id))

        assert trend["labels"] == []
        assert trend["actual_data"] == []
        assert trend["requirement_data"] == []

    def test_get_trend_data_custom_days_parameter(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.production.water.services import WaterService
        org = _make_org("watertrend3")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house)

        with set_tenant_context(org):
            _log_water(org, batch, litres_consumed=40)
            trend_7 = WaterService(org).get_trend_data(str(batch.id), days=7)
            trend_90 = WaterService(org).get_trend_data(str(batch.id), days=90)

        assert isinstance(trend_7["labels"], list)
        assert isinstance(trend_90["requirement_data"], list)


# ── 6. Signal branches (signals.py lines 13, 28-30, 46-47, 54-60, 89-90) ─────

class TestWaterSignalBranches:

    def test_signal_skips_calculation_on_update(self, db):
        """Line 13: created=False path returns immediately without recalculating."""
        from apps.infrastructure.core.rls import set_tenant_context
        org = _make_org("watersigupd1")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house)

        with set_tenant_context(org):
            log = _log_water(org, batch, litres_consumed=40)
            log.refresh_from_db()
            original_req = log.requirement_litres

            log.notes = "trigger signal with created=False"
            log.save()
            log.refresh_from_db()

        assert log.requirement_litres == original_req

    def test_signal_batch_fetch_exception_is_handled(self, db):
        """Lines 28-30: DB exception while fetching Batch is swallowed."""
        from apps.production.water.signals import _calculate_and_update
        from apps.infrastructure.core.rls import set_tenant_context
        org = _make_org("watersigbatch1")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house)

        with set_tenant_context(org):
            log = _log_water(org, batch, litres_consumed=40)

        with patch("apps.farm.flocks.models.Batch") as MockBatch:
            MockBatch.objects.unscoped.side_effect = Exception("DB down")
            _calculate_and_update(log)  # must not raise

    def test_signal_calculator_exception_is_handled(self, db):
        """Lines 46-47: BreedCalculator exception inside try block is swallowed."""
        from apps.production.water.signals import _calculate_and_update
        from apps.infrastructure.core.rls import set_tenant_context
        org = _make_org("watersigcalc1")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house)

        with set_tenant_context(org):
            log = _log_water(org, batch, litres_consumed=40)

        with patch(
            "apps.infrastructure.core.calculator.BreedCalculator"
            ".daily_water_requirement_litres",
            side_effect=Exception("Calc failure"),
        ):
            _calculate_and_update(log)  # must not raise

    def test_signal_cross_tenant_update_blocked(self, db):
        """Lines 54-60: update() returning 0 (deleted row) is handled gracefully."""
        from apps.production.water.signals import _calculate_and_update
        from apps.production.water.models import WaterLog
        from apps.infrastructure.core.rls import set_tenant_context
        org = _make_org("watersigcross1")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house)

        with set_tenant_context(org):
            log = _log_water(org, batch, litres_consumed=40)

        # Delete the row so the subsequent update() returns 0
        WaterLog.objects.unscoped().filter(pk=log.pk).delete()

        # Must not raise; logs error and returns early
        _calculate_and_update(log)

    def test_signal_notification_exception_is_handled(self, db):
        """Lines 89-90: NotificationService.send exception is swallowed."""
        from apps.production.water.signals import _fire_water_drop_notification
        from apps.infrastructure.notifications.services import NotificationService
        from apps.infrastructure.core.rls import set_tenant_context
        org = _make_org("watersignotif1")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house)

        with set_tenant_context(org):
            log = _log_water(org, batch, litres_consumed=5)

        with set_tenant_context(org), patch.object(
            NotificationService, "send", side_effect=Exception("Notif failed")
        ):
            _fire_water_drop_notification(log)  # must not raise


# ── 7. View missing branches (views.py lines 21-28, 43-45, 59-61, 71) ─────────

class TestWaterViewMissingBranches:

    def _setup(self, db, subdomain):
        org = _make_org(subdomain)
        user = _make_user(org, f"{subdomain}@example.com", subdomain)
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house)
        return org, user, farm, house, batch

    def test_log_view_get_renders_form(self, db, client):
        """Lines 21-28: GET request renders the water log form fragment."""
        org, user, farm, house, batch = self._setup(db, "waterviewget1")
        client.force_login(user)
        response = client.get(f"/production/water/{batch.id}/log/")
        assert response.status_code == 200

    def test_log_view_post_invalid_form_returns_422(self, db, client):
        """Lines 43-45, 71: invalid POST data → _error() helper → 422."""
        org, user, farm, house, batch = self._setup(db, "waterviewinv1")
        client.force_login(user)
        response = client.post(
            f"/production/water/{batch.id}/log/",
            {"record_date": "not-a-date", "litres_consumed": "not-a-number"},
        )
        assert response.status_code == 422

    def test_log_view_post_closed_batch_shows_error(self, db, client):
        """Lines 59-61: ValueError from WaterService → form error → _error() → 422."""
        org = _make_org("waterviewval1")
        user = _make_user(org, "waterviewval1@example.com", "waterviewval1")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house, status="closed")
        client.force_login(user)
        response = client.post(
            f"/production/water/{batch.id}/log/",
            {
                "record_date": datetime.date.today().isoformat(),
                "litres_consumed": "40",
                "notes": "",
            },
        )
        assert response.status_code == 422


# ── 8. Form validation (forms.py line 17) ────────────────────────────────────

class TestWaterLogFormValidation:

    def test_future_date_is_rejected(self):
        """Line 17: date in the future raises ValidationError."""
        from apps.production.water.forms import WaterLogForm
        future = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
        form = WaterLogForm({"record_date": future, "litres_consumed": "40"})
        assert not form.is_valid()
        assert "Record date cannot be in the future" in str(form.errors)

    def test_today_date_is_accepted(self):
        """clean_record_date happy path: today is valid."""
        from apps.production.water.forms import WaterLogForm
        form = WaterLogForm({
            "record_date": datetime.date.today().isoformat(),
            "litres_consumed": "40",
        })
        assert form.is_valid()
