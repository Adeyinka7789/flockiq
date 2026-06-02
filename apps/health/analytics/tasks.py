import structlog
from celery import shared_task

logger = structlog.get_logger(__name__)


@shared_task(name="analytics.check_mortality_anomaly")
def check_mortality_anomaly(org_id: str, batch_id: str):
    """Fired from MortalityLog signal after save. Sets tenant context first."""
    from apps.infrastructure.core.rls import set_tenant_context
    from apps.infrastructure.tenants.models import Organization
    from apps.farm.flocks.models import Batch
    from .services import AnomalyDetectionService

    with set_tenant_context(org_id):
        try:
            org = Organization.objects.get(id=org_id)
            batch = Batch.objects.get(id=batch_id, org_id=org_id)
            AnomalyDetectionService(org).check_mortality_anomaly(batch)
        except Exception as exc:
            logger.error(
                "Mortality anomaly check failed",
                org_id=org_id,
                batch_id=batch_id,
                error=str(exc),
            )
            raise


@shared_task(name="analytics.run_egg_forecast_all_active_batches")
def run_egg_forecast_all_active_batches():
    """Beat: 06:15 daily. Fan-out to all orgs with active layer batches."""
    from apps.infrastructure.core.rls import no_tenant_context

    with no_tenant_context():
        from apps.infrastructure.tenants.models import Organization

        org_ids = list(
            Organization.objects.filter(
                is_active=True,
                subscription_status__in=["active", "trial"],
            ).values_list("id", flat=True)
        )

    for org_id in org_ids:
        run_egg_forecast_for_org.delay(str(org_id))


@shared_task(name="analytics.run_egg_forecast_for_org")
def run_egg_forecast_for_org(org_id: str):
    """Sets tenant context and fans out forecasts for one org's active layer batches."""
    from apps.infrastructure.core.rls import set_tenant_context
    from apps.farm.flocks.models import Batch

    with set_tenant_context(org_id):
        rows = list(
            Batch.objects.filter(org_id=org_id, status="active", bird_type="layer")
            .values("id", "org_id")
        )

    for row in rows:
        run_egg_forecast_for_batch.delay(str(row["org_id"]), str(row["id"]))


@shared_task(name="analytics.run_egg_forecast_for_batch")
def run_egg_forecast_for_batch(org_id: str, batch_id: str):
    """Sets tenant context and runs Prophet forecast for one batch."""
    from apps.infrastructure.core.rls import set_tenant_context
    from apps.infrastructure.tenants.models import Organization
    from apps.farm.flocks.models import Batch
    from .services import ProphetForecastService

    with set_tenant_context(org_id):
        try:
            org = Organization.objects.get(id=org_id)
            batch = Batch.objects.get(id=batch_id, org_id=org_id)
            ProphetForecastService(org).forecast_egg_production(batch)
        except Exception as exc:
            logger.error(
                "Egg forecast task failed",
                org_id=org_id,
                batch_id=batch_id,
                error=str(exc),
            )
            raise


@shared_task(name="analytics.run_theft_detection_all_orgs")
def run_theft_detection_all_orgs():
    """Beat: weekly Sunday. Fan-out theft reconciliation to all orgs."""
    from apps.infrastructure.core.rls import no_tenant_context

    with no_tenant_context():
        from apps.infrastructure.tenants.models import Organization

        org_ids = list(
            Organization.objects.filter(
                is_active=True,
                subscription_status__in=["active", "trial"],
            ).values_list("id", flat=True)
        )

    for org_id in org_ids:
        run_theft_detection_for_org.delay(str(org_id))


@shared_task(name="analytics.run_theft_detection_for_org")
def run_theft_detection_for_org(org_id: str):
    """Reconciles all active batches for one org."""
    from apps.infrastructure.core.rls import set_tenant_context
    from apps.infrastructure.tenants.models import Organization
    from apps.farm.flocks.models import Batch
    from .services import TheftDetectionService

    with set_tenant_context(org_id):
        try:
            org = Organization.objects.get(id=org_id)
            batches = Batch.objects.filter(org=org, org_id=org_id, status="active")
            svc = TheftDetectionService(org)
            for batch in batches:
                svc.reconcile_batch(batch)
        except Exception as exc:
            logger.error(
                "Theft detection task failed",
                org_id=org_id,
                error=str(exc),
            )
            raise
