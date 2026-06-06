# NEW FILE: apps/farm/farms/tasks.py
# Add these Celery tasks to handle async farm and house creation

from celery import shared_task, current_app
from django.db import IntegrityError
import structlog

logger = structlog.get_logger(__name__)


@shared_task(bind=True, max_retries=3)
def create_farm_async(self, org_id, name, location, lat, lng, farm_type):
    """
    Asynchronously create a farm for the given organization.
    Retries up to 3 times on failure.
    """
    from apps.infrastructure.tenants.models import Organization
    from apps.farm.farms.services import FarmService
    from apps.infrastructure.core.rls import set_tenant_context

    try:
        org = Organization.objects.get(id=org_id, is_active=True)
    except Organization.DoesNotExist:
        logger.error("create_farm_async.org_not_found", org_id=org_id)
        return {"status": "error", "reason": "Organization not found"}

    try:
        with set_tenant_context(org):
            farm = FarmService(org).create_farm(
                name=name,
                location=location,
                lat=lat,
                lng=lng,
                farm_type=farm_type,
            )
        logger.info("create_farm_async.success", org_id=org_id, farm_id=str(farm.id))
        return {"status": "success", "farm_id": str(farm.id)}
    except IntegrityError as exc:
        logger.warning("create_farm_async.integrity_error", org_id=org_id, error=str(exc))
        raise self.retry(countdown=5, exc=exc)
    except Exception as exc:
        logger.exception("create_farm_async.failure", org_id=org_id)
        # Retry after exponential backoff: 5s, 25s, 125s
        raise self.retry(countdown=5 ** self.request.retries, exc=exc)


@shared_task(bind=True, max_retries=3)
def create_house_async(self, org_id, farm_id, name, capacity, house_type):
    """
    Asynchronously create a house for the given farm.
    Retries up to 3 times on failure.
    """
    from apps.infrastructure.tenants.models import Organization
    from apps.farm.farms.services import FarmService
    from apps.infrastructure.core.rls import set_tenant_context

    try:
        org = Organization.objects.get(id=org_id, is_active=True)
    except Organization.DoesNotExist:
        logger.error("create_house_async.org_not_found", org_id=org_id)
        return {"status": "error", "reason": "Organization not found"}

    try:
        with set_tenant_context(org):
            house = FarmService(org).create_house(
                farm_id=farm_id,
                name=name,
                capacity=capacity,
                house_type=house_type,
            )
        logger.info("create_house_async.success", org_id=org_id, farm_id=farm_id, house_id=str(house.id))
        return {"status": "success", "house_id": str(house.id)}
    except IntegrityError as exc:
        logger.warning("create_house_async.integrity_error", org_id=org_id, error=str(exc))
        raise self.retry(countdown=5, exc=exc)
    except ValueError as exc:
        logger.warning("create_house_async.validation_error", org_id=org_id, error=str(exc))
        # Don't retry on validation errors
        return {"status": "error", "reason": str(exc)}
    except Exception as exc:
        logger.exception("create_house_async.failure", org_id=org_id)
        raise self.retry(countdown=5 ** self.request.retries, exc=exc)


# apps/farm/flocks/tasks.py
# Add these tasks:

@shared_task(bind=True, max_retries=3)
def create_batch_async(self, org_id, farm_id, house_id, batch_name, bird_type, placement_date, initial_count, breed_name):
    """
    Asynchronously create a batch for the given farm and house.
    Retries up to 3 times on failure.
    """
    from apps.infrastructure.tenants.models import Organization
    from apps.farm.flocks.services import BatchService
    from apps.infrastructure.core.rls import set_tenant_context

    try:
        org = Organization.objects.get(id=org_id, is_active=True)
    except Organization.DoesNotExist:
        logger.error("create_batch_async.org_not_found", org_id=org_id)
        return {"status": "error", "reason": "Organization not found"}

    try:
        with set_tenant_context(org):
            batch = BatchService(org).create_batch(
                farm_id=farm_id,
                house_id=house_id,
                batch_name=batch_name,
                bird_type=bird_type,
                placement_date=placement_date,
                initial_count=initial_count,
                breed_name=breed_name,
            )
        logger.info("create_batch_async.success", org_id=org_id, batch_id=str(batch.id), batch_name=batch_name)
        return {"status": "success", "batch_id": str(batch.id)}
    except IntegrityError as exc:
        logger.warning("create_batch_async.integrity_error", org_id=org_id, error=str(exc))
        raise self.retry(countdown=5, exc=exc)
    except ValueError as exc:
        logger.warning("create_batch_async.validation_error", org_id=org_id, error=str(exc))
        # Don't retry on validation errors (e.g., house occupied)
        return {"status": "error", "reason": str(exc)}
    except Exception as exc:
        logger.exception("create_batch_async.failure", org_id=org_id, batch_name=batch_name)
        raise self.retry(countdown=5 ** self.request.retries, exc=exc)
