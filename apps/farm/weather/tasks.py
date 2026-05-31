import structlog
from celery import shared_task

logger = structlog.get_logger(__name__)


@shared_task(name="weather.refresh_weather_cache_all_farms")
def refresh_weather_cache_all_farms():
    from apps.infrastructure.core.rls import no_tenant_context
    from apps.farm.farms.models import Farm

    with no_tenant_context():
        # Farm has RLS enabled — use unscoped() to read all active farms cross-tenant
        farms = list(
            Farm.objects.unscoped()
            .filter(is_active=True)
            .values("id", "org_id", "latitude", "longitude")
        )

    for farm_row in farms:
        refresh_weather_for_farm.delay(
            str(farm_row["id"]),
            float(farm_row["latitude"]) if farm_row["latitude"] else None,
            float(farm_row["longitude"]) if farm_row["longitude"] else None,
            str(farm_row["org_id"]),
        )


@shared_task(name="weather.refresh_weather_for_farm", max_retries=2, default_retry_delay=120)
def refresh_weather_for_farm(farm_id: str, lat, lng, org_id: str):
    from apps.infrastructure.core.rls import set_tenant_context
    from apps.farm.farms.models import Farm
    from apps.farm.weather.services import WeatherService

    if lat is None or lng is None:
        logger.info("weather.skip_no_coords", farm_id=farm_id)
        return

    service = WeatherService()
    weather_data = service.fetch_weather(farm_id, lat, lng)

    if not weather_data:
        return

    with set_tenant_context(org_id) as org:
        try:
            farm = Farm.objects.get(id=farm_id)
            service.evaluate_alerts(org, farm, weather_data)
        except Farm.DoesNotExist:
            logger.warning("weather.farm_not_found", farm_id=farm_id)
        except Exception as exc:
            logger.exception("weather.evaluate_alerts_failed", farm_id=farm_id, error=str(exc))
            raise
