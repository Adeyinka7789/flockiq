"""
Phase 2D — Weather app tests.

Coverage:
- WeatherService.fetch_weather: mocked HTTP, cache, DB record
- WeatherService.evaluate_alerts: heat stress threshold, duplicate prevention
- WeatherStripView: returns HTML fragment
- WeatherAlert RLS isolation
- Graceful fallback when no cache
"""

import datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.django_db


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_org(subdomain="testweather"):
    from apps.infrastructure.tenants.models import Organization
    return Organization.objects.create(name="Test Weather Org", subdomain=subdomain)


def _make_farm(org, name="Weather Farm", lat="9.0579", lng="7.4951"):
    from apps.farm.farms.models import Farm
    farm = Farm(
        org=org,
        name=name,
        location="Abuja",
        latitude=Decimal(lat),
        longitude=Decimal(lng),
        farm_type="broiler",
    )
    farm.clean()
    farm.save()
    return farm


def _set_rls(org_id):
    from apps.infrastructure.core.rls import set_tenant_context
    from apps.infrastructure.tenants.models import Organization
    org = Organization.objects.get(id=org_id)
    return set_tenant_context(org)


_MOCK_OWM_RESPONSE = {
    "list": [
        {
            "dt": 1700000000,
            "main": {"temp": 35.0, "humidity": 70},
            "weather": [{"description": "clear sky"}],
            "rain": {"3h": 0},
        },
        {
            "dt": 1700010800,
            "main": {"temp": 33.0, "humidity": 72},
            "weather": [{"description": "few clouds"}],
            "rain": {},
        },
    ]
}


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestFetchWeather:

    def test_weather_fetched_and_cached(self):
        from django.core.cache import cache
        from apps.farm.weather.services import WeatherService
        from apps.farm.weather.models import WeatherCache

        org = _make_org("weather-fetch-1")
        farm = _make_farm(org)
        farm_id = str(farm.id)

        with patch("requests.get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200,
                json=lambda: _MOCK_OWM_RESPONSE,
            )
            mock_get.return_value.raise_for_status = lambda: None

            result = WeatherService().fetch_weather(farm_id, 9.0579, 7.4951)

        assert result["current_temp"] == 35.0
        assert result["humidity"] == 70

        # Cached in Redis
        cached = cache.get(f"weather:{farm_id}")
        assert cached is not None

        # Persisted in DB
        assert WeatherCache.objects.filter(farm_id=farm_id).exists()

    def test_weather_returns_empty_on_api_failure(self):
        from apps.farm.weather.services import WeatherService

        farm_id = "00000000-0000-0000-0000-000000000001"
        with patch("requests.get", side_effect=Exception("network error")):
            result = WeatherService().fetch_weather(farm_id, 9.0579, 7.4951)

        assert result == {}


class TestEvaluateAlerts:

    def test_heat_stress_alert_created_above_threshold(self):
        from apps.farm.weather.models import WeatherAlert
        from apps.farm.weather.services import WeatherService

        org = _make_org("weather-heat-1")
        farm = _make_farm(org)

        weather_data = {
            "current_temp": 35.0,
            "humidity": 60,
            "description": "clear sky",
            "forecast": [{"temp": 35.0, "humidity": 60, "rain_3h_mm": 0, "description": ""}],
            "fetched_at": "2026-05-31T10:00:00",
        }

        with _set_rls(org.id):
            alerts = WeatherService().evaluate_alerts(org, farm, weather_data)
            alert_ids = [str(a.id) for a in alerts]

            assert len(alerts) == 1
            alert = WeatherAlert.objects.get(alert_type="heat_stress", farm=farm)
            assert str(alert.id) in alert_ids
            assert alert.severity == "critical"

    def test_no_duplicate_alert_within_cooldown(self):
        from apps.farm.weather.models import WeatherAlert
        from apps.farm.weather.services import WeatherService

        org = _make_org("weather-dup-1")
        farm = _make_farm(org)

        weather_data = {
            "current_temp": 36.0,
            "humidity": 50,
            "description": "sunny",
            "forecast": [{"temp": 36.0, "humidity": 50, "rain_3h_mm": 0, "description": ""}],
            "fetched_at": "2026-05-31T10:00:00",
        }

        with _set_rls(org.id):
            first = WeatherService().evaluate_alerts(org, farm, weather_data)
            second = WeatherService().evaluate_alerts(org, farm, weather_data)

        assert len(first) == 1
        assert len(second) == 0  # Existing unacknowledged alert — skip

        with _set_rls(org.id):
            assert WeatherAlert.objects.filter(farm=farm, alert_type="heat_stress").count() == 1


class TestWeatherViews:

    def test_weather_strip_view_returns_fragment(self):
        from django.core.cache import cache
        from django.test import Client
        from apps.infrastructure.accounts.models import CustomUser

        org = _make_org("weather-view-1")
        farm = _make_farm(org)

        cache.set(f"weather:{farm.id}", {
            "current_temp": 28.0,
            "humidity": 65,
            "description": "partly cloudy",
            "forecast": [
                {"temp": 28.0, "humidity": 65, "rain_3h_mm": 0, "description": "partly cloudy"}
            ] * 4,
            "fetched_at": "2026-05-31T10:00:00",
        })

        user = CustomUser.objects.create_user(
            email="wx@view.test",
            password="testpass",
            username="wx_view",
            org=org,
            role="manager",
        )

        client = Client()
        client.force_login(user)

        response = client.get(f"/weather/farm/{farm.id}/strip/")

        assert response.status_code == 200
        assert b"28" in response.content or b"cloudy" in response.content.lower()

    def test_graceful_fallback_when_no_cache(self):
        from django.core.cache import cache
        from django.test import Client
        from apps.infrastructure.accounts.models import CustomUser

        org = _make_org("weather-fallback-1")
        farm = _make_farm(org)

        cache.delete(f"weather:{farm.id}")

        user = CustomUser.objects.create_user(
            email="fallback@view.test",
            password="testpass",
            username="fallback_view",
            org=org,
            role="manager",
        )

        client = Client()
        client.force_login(user)

        response = client.get(f"/weather/farm/{farm.id}/strip/")

        assert response.status_code == 200
        assert b"unavailable" in response.content.lower()


class TestWeatherAlertRLS:

    def test_weather_alert_rls_isolation(self):
        from apps.farm.weather.models import WeatherAlert
        from apps.farm.weather.services import WeatherService

        org_a = _make_org("weather-rls-a")
        org_b = _make_org("weather-rls-b")
        farm_a = _make_farm(org_a, "Farm A")
        farm_b = _make_farm(org_b, "Farm B")

        hot_weather = {
            "current_temp": 38.0,
            "humidity": 50,
            "description": "hot",
            "forecast": [{"temp": 38.0, "humidity": 50, "rain_3h_mm": 0, "description": ""}],
            "fetched_at": "2026-05-31T10:00:00",
        }

        with _set_rls(org_a.id):
            WeatherService().evaluate_alerts(org_a, farm_a, hot_weather)

        with _set_rls(org_b.id):
            WeatherService().evaluate_alerts(org_b, farm_b, hot_weather)

        # Tenant A only sees its own alerts
        with _set_rls(org_a.id):
            alert_ids = set(str(i) for i in WeatherAlert.objects.values_list("id", flat=True))

        with _set_rls(org_b.id):
            b_ids = set(str(i) for i in WeatherAlert.objects.values_list("id", flat=True))

        # No cross-tenant overlap
        assert alert_ids.isdisjoint(b_ids)
        assert len(alert_ids) == 1
        assert len(b_ids) == 1
