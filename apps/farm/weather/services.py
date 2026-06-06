# CORRECTED: apps/infrastructure/farm/weather/services.py
# This version includes proper exception handling for database operations

from decimal import Decimal

import structlog
from django.conf import settings
from django.core.cache import cache
from django.db import transaction, IntegrityError
from django.utils import timezone

logger = structlog.get_logger(__name__)

WEATHER_CACHE_TTL = 6 * 3600

_OPENWEATHERMAP_BASE_URL = "https://api.openweathermap.org/data/2.5"
_DEFAULT_THRESHOLDS = {
    "heat_stress_temp_c": 32,
    "high_humidity_pct": 85,
    "heavy_rain_mm": 10,
}


class WeatherService:
    """
    Not a BaseService — called cross-tenant by Celery workers.
    Methods requiring a tenant context accept org and farm as parameters.
    """

    def fetch_weather(self, farm_id: str, lat, lng) -> dict:
        cache_key = f"weather:{farm_id}"
        cached = cache.get(cache_key)
        if cached:
            return cached

        import requests
        from django.db import IntegrityError

        base_url = getattr(settings, "OPENWEATHERMAP_BASE_URL", _OPENWEATHERMAP_BASE_URL)
        api_key = getattr(settings, "OPENWEATHERMAP_API_KEY", "")

        try:
            response = requests.get(
                f"{base_url}/forecast",
                params={
                    "lat": float(lat),
                    "lon": float(lng),
                    "appid": api_key,
                    "units": "metric",
                    "cnt": 8,
                },
                timeout=10,
            )
            response.raise_for_status()
            raw_data = response.json()
        except requests.Timeout:
            logger.warning("weather.fetch_timeout", farm_id=farm_id)
            return {}
        except requests.RequestException as exc:
            logger.warning("weather.fetch_failed", farm_id=farm_id, error=str(exc))
            return {}
        except ValueError as exc:
            logger.error("weather.json_decode_error", farm_id=farm_id, error=str(exc))
            return {}
        except Exception as exc:
            logger.exception("weather.fetch_unexpected_error", farm_id=farm_id)
            return {}

        from apps.farm.weather.models import WeatherCache

        try:
            WeatherCache.objects.update_or_create(
                farm_id=farm_id,
                defaults={
                    "lat": Decimal(str(float(lat))),
                    "lng": Decimal(str(float(lng))),
                    "data": raw_data,
                },
            )
        except IntegrityError as exc:
            logger.error("weather.cache_integrity_error", farm_id=farm_id, error=str(exc))
            # Cache still available from Redis, continue
        except Exception as exc:
            logger.exception("weather.cache_update_failed", farm_id=farm_id)
            # Continue without updating DB cache

        parsed = self._parse_weather(raw_data)
        cache.set(cache_key, parsed, timeout=WEATHER_CACHE_TTL)
        return parsed

    def _parse_weather(self, raw_data: dict) -> dict:
        """Parse raw OpenWeatherMap API response into internal format."""
        if not raw_data or "list" not in raw_data:
            return {}

        slots = raw_data.get("list", [])
        current = slots[0] if slots else {}

        forecast = []
        for slot in slots:
            rain_mm = (slot.get("rain") or {}).get("3h", 0) or 0
            forecast.append({
                "dt": slot.get("dt"),
                "temp": slot.get("main", {}).get("temp"),
                "humidity": slot.get("main", {}).get("humidity"),
                "description": ((slot.get("weather") or [{}])[0]).get("description", ""),
                "rain_3h_mm": rain_mm,
            })

        return {
            "current_temp": current.get("main", {}).get("temp"),
            "humidity": current.get("main", {}).get("humidity"),
            "description": ((current.get("weather") or [{}])[0]).get("description", ""),
            "forecast": forecast,
            "fetched_at": timezone.now().isoformat(),
        }

    def evaluate_alerts(self, org, farm, weather_data: dict) -> list:
        """
        Evaluate weather data against thresholds and create alerts.
        Handles notification service failures gracefully.
        """
        from apps.farm.weather.models import WeatherAlert
        from apps.infrastructure.notifications.services import NotificationService

        if not weather_data:
            return []

        thresholds = getattr(settings, "WEATHER_THRESHOLDS", _DEFAULT_THRESHOLDS)
        created_alerts = []

        temp = weather_data.get("current_temp")
        humidity = weather_data.get("humidity")
        forecast = weather_data.get("forecast", [])

        candidates = []

        if temp is not None and temp > thresholds.get("heat_stress_temp_c", 32):
            candidates.append({
                "alert_type": WeatherAlert.AlertType.HEAT_STRESS,
                "severity": WeatherAlert.Severity.CRITICAL,
                "temperature": Decimal(str(round(float(temp), 2))),
                "humidity": None,
                "description": f"Temperature {temp:.1f}°C exceeds heat stress threshold.",
            })

        if humidity is not None and humidity > thresholds.get("high_humidity_pct", 85):
            candidates.append({
                "alert_type": WeatherAlert.AlertType.HIGH_HUMIDITY,
                "severity": WeatherAlert.Severity.WARNING,
                "temperature": None,
                "humidity": int(humidity),
                "description": f"Humidity {humidity}% exceeds threshold.",
            })

        max_rain = max((s.get("rain_3h_mm", 0) for s in forecast), default=0)
        if max_rain > thresholds.get("heavy_rain_mm", 10):
            candidates.append({
                "alert_type": WeatherAlert.AlertType.HEAVY_RAIN,
                "severity": WeatherAlert.Severity.INFO,
                "temperature": None,
                "humidity": None,
                "description": f"Heavy rain forecast: {max_rain:.1f}mm in a 3-hour period.",
            })

        # Create alerts and send notifications
        for candidate in candidates:
            # Check if alert already exists and is unacknowledged
            already_active = WeatherAlert.objects.filter(
                org=org,
                farm=farm,
                alert_type=candidate["alert_type"],
                acknowledged_at__isnull=True,
            ).exists()
            if already_active:
                continue

            # Create the alert
            try:
                alert = WeatherAlert.objects.create(org=org, farm=farm, **candidate)
                created_alerts.append(alert)
            except IntegrityError as exc:
                logger.warning("weather.alert_duplicate", farm_id=str(farm.id), alert_type=candidate["alert_type"])
                continue
            except Exception as exc:
                logger.exception("weather.alert_creation_failed", farm_id=str(farm.id))
                continue

            # Send notification for critical alerts
            if candidate["severity"] == WeatherAlert.Severity.CRITICAL:
                try:
                    with transaction.atomic():
                        NotificationService(org).send(
                            event_type=candidate["alert_type"],
                            context={
                                "farm_name": farm.name,
                                "value": str(temp or ""),
                            },
                            severity=candidate["severity"],
                            farm=farm,
                        )
                except Exception as exc:
                    logger.exception("weather.notification_failed", farm_id=str(farm.id), alert_type=candidate["alert_type"])
                    # Alert still created; notification failure shouldn't break alert creation

        return created_alerts

    def get_farm_weather_strip(self, farm_id: str) -> dict:
        """Returns cached weather data for the 4-day strip template. None if no cache."""
        return cache.get(f"weather:{farm_id}")
