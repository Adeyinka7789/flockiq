import structlog
from celery import shared_task
from django.core.management import call_command

logger = structlog.get_logger(__name__)


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
