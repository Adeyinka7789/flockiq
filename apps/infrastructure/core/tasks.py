import structlog
from celery import shared_task
from django.core.management import call_command

logger = structlog.get_logger(__name__)


@shared_task(name="core.backup_database")
def backup_database():
    """Nightly database backup."""
    try:
        call_command("backup_database")
    except Exception as e:
        logger.error("backup.task_failed", error=str(e))
        import sentry_sdk
        sentry_sdk.capture_exception(e)


@shared_task(name="core.check_disk_space")
def check_disk_space():
    """Alert via Sentry if disk usage exceeds 80%."""
    import shutil
    import sentry_sdk

    total, used, free = shutil.disk_usage("/")
    usage_pct = (used / total) * 100

    if usage_pct > 80:
        logger.warning(
            "disk.usage_high",
            usage_pct=round(usage_pct, 1),
            free_gb=round(free / (1024 ** 3), 2),
        )
        sentry_sdk.capture_message(
            f"Disk usage at {usage_pct:.1f}% on FlockIQ VPS",
            level="warning",
        )
    else:
        logger.info("disk.usage_ok", usage_pct=round(usage_pct, 1))


@shared_task(name="core.clear_expired_sessions")
def clear_expired_sessions():
    call_command("clearsessions")
    logger.info("sessions.cleared")


@shared_task(name="core.recompute_all_credit_scores")
def recompute_all_credit_scores():
    """Nightly fan-out: dispatch per-org credit score recomputation."""
    from apps.infrastructure.core.rls import no_tenant_context
    from apps.infrastructure.tenants.models import Organization

    with no_tenant_context():
        org_ids = list(
            Organization.objects.filter(is_active=True).values_list("id", flat=True)
        )

    logger.info("credit_score.nightly_fanout_start", org_count=len(org_ids))
    for org_id in org_ids:
        recompute_credit_score_for_org.delay(str(org_id))


@shared_task(name="core.recompute_credit_score_for_org")
def recompute_credit_score_for_org(org_id: str):
    """Recompute credit score for a single org."""
    from apps.infrastructure.core.credit_scoring import CreditScoringService
    from apps.infrastructure.core.rls import set_tenant_context
    from apps.infrastructure.tenants.models import Organization

    try:
        org = Organization.objects.get(id=org_id)
    except Organization.DoesNotExist:
        logger.warning("credit_score.org_not_found", org_id=org_id)
        return

    with set_tenant_context(org):
        CreditScoringService(org).compute()

    logger.info("credit_score.recomputed", org_id=org_id)
