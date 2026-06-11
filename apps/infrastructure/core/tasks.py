import datetime

import structlog
from celery import shared_task
from django.core.management import call_command
from django.db.models.deletion import ProtectedError
from django.utils import timezone

logger = structlog.get_logger(__name__)


@shared_task(name="core.hard_delete_expired_records")
def hard_delete_expired_records():
    """
    Permanently delete records soft-deleted more than 90 days ago.
    Runs nightly at 03:30.

    PostgreSQL RLS only exposes a tenant's rows while a matching GUC is active,
    so the sweep fans out per org inside set_tenant_context(org). Within each org
    models are purged leaf-first (logs → batch → house → farm) so PROTECT foreign
    keys do not block a parent whose children are also expired. A model that still
    has live (not-yet-expired) children raises ProtectedError; we log and skip it
    — it is retried on a future night once the children expire.
    """
    from apps.farm.farms.models import Farm, House
    from apps.farm.flocks.models import Batch, MortalityLog, WeightRecord
    from apps.infrastructure.core.rls import no_tenant_context, set_tenant_context
    from apps.infrastructure.tenants.models import Organization
    from apps.production.feed.models import FeedLog
    from apps.production.production.models import EggProductionLog
    from apps.production.water.models import WaterLog

    cutoff = timezone.now() - datetime.timedelta(days=90)

    # Leaf-first ordering: children before the parents they PROTECT.
    models_to_clean = [
        WaterLog,
        FeedLog,
        EggProductionLog,
        MortalityLog,
        WeightRecord,
        Batch,
        House,
        Farm,
    ]

    # Organization has RLS disabled — safe to enumerate without a tenant context.
    with no_tenant_context():
        org_ids = list(Organization.objects.values_list("id", flat=True))

    total = 0
    for org_id in org_ids:
        with set_tenant_context(org_id):
            for Model in models_to_clean:
                # GUC = this org, so all_objects (tenant-scoped, deleted included)
                # returns exactly this org's expired rows.
                qs = Model.all_objects.filter(
                    is_deleted=True,
                    deleted_at__lt=cutoff,
                )
                try:
                    deleted, _ = qs.delete()
                    total += deleted
                except ProtectedError:
                    logger.warning(
                        "core.hard_delete_blocked",
                        model=Model.__name__,
                        org_id=str(org_id),
                        hint="rows still referenced by live (not-yet-expired) children",
                    )

    if total:
        logger.info(
            "core.hard_delete_completed",
            count=total,
            cutoff=str(cutoff.date()),
        )
    return total


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
