import structlog
from celery import shared_task

logger = structlog.get_logger(__name__)


@shared_task(name="flocks.check_mortality_anomaly")
def check_mortality_anomaly(batch_id: str, org_id: str):
    """
    Stub for Phase 4 ML anomaly detection.
    Fires after every MortalityLog save. Logs only — no DB writes.
    """
    logger.info(
        "flocks.mortality_anomaly_check_stub",
        batch_id=batch_id,
        org_id=org_id,
    )


@shared_task(name="flocks.activate_cycle_subscription")
def activate_cycle_subscription(org_id: str, batch_id: str):
    """
    Stub for billing integration.
    Fires when a broiler batch is placed for a cycle-tier org.
    """
    logger.info(
        "flocks.activate_cycle_subscription_stub",
        org_id=org_id,
        batch_id=batch_id,
    )


@shared_task(name="flocks.deactivate_cycle_subscription")
def deactivate_cycle_subscription(org_id: str, batch_id: str):
    """
    Stub for billing integration.
    Fires when a broiler batch is closed.
    """
    logger.info(
        "flocks.deactivate_cycle_subscription_stub",
        org_id=org_id,
        batch_id=batch_id,
    )
