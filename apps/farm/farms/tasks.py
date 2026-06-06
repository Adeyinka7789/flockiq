# apps/farm/farms/tasks.py
from celery import shared_task
from apps.infrastructure.core.rls import set_tenant_context
import structlog

logger = structlog.get_logger(__name__)

@shared_task
def create_farm_async(org_id, name, location, lat, lng, farm_type):
    from apps.infrastructure.tenants.models import Organization
    from apps.farm.farms.services import FarmService
    
    try:
        org = Organization.objects.get(id=org_id)
        with set_tenant_context(org):
            FarmService(org).create_farm(
                name=name,
                location=location,
                lat=lat,
                lng=lng,
                farm_type=farm_type,
            )
        logger.info("onboarding.farm_created", org_id=org_id)
    except Exception as exc:
        logger.exception("create_farm_async.failed", org_id=org_id, error=str(exc))
        raise

@shared_task
def create_house_async(org_id, farm_id, name, capacity, house_type):
    from apps.infrastructure.tenants.models import Organization
    from apps.farm.farms.services import FarmService
    
    try:
        org = Organization.objects.get(id=org_id)
        with set_tenant_context(org):
            FarmService(org).create_house(
                farm_id=farm_id,
                name=name,
                capacity=capacity,
                house_type=house_type,
            )
        logger.info("onboarding.house_created", org_id=org_id, farm_id=farm_id)
    except Exception as exc:
        logger.exception("create_house_async.failed", org_id=org_id, error=str(exc))
        raise