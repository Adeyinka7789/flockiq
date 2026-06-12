import structlog
from celery import shared_task

from apps.infrastructure.core.rls import set_tenant_context

logger = structlog.get_logger(__name__)


@shared_task
def create_batch_async(org_id, farm_id, house_id, batch_name, bird_type, placement_date, initial_count, breed_name):
    from apps.infrastructure.tenants.models import Organization
    from apps.farm.flocks.services import BatchService
    
    try:
        org = Organization.objects.get(id=org_id)
        with set_tenant_context(org):
            BatchService(org).create_batch(
                farm_id=farm_id,
                house_id=house_id,
                batch_name=batch_name,
                bird_type=bird_type,
                placement_date=placement_date,
                initial_count=initial_count,
                breed_name=breed_name,
            )
        logger.info("onboarding.batch_created", org_id=org_id, batch_name=batch_name)
    except Exception as exc:
        logger.exception("create_batch_async.failed", org_id=org_id, error=str(exc))
        raise
