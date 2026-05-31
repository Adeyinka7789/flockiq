import structlog
from celery import shared_task

logger = structlog.get_logger(__name__)


@shared_task(name="tasks.generate_daily_tasks_all_orgs")
def generate_daily_tasks_all_orgs():
    from apps.infrastructure.core.rls import no_tenant_context
    from apps.infrastructure.tenants.models import Organization

    with no_tenant_context():
        org_ids = list(
            Organization.objects.filter(subscription_status="active").values_list("id", flat=True)
        )

    for org_id in org_ids:
        generate_daily_tasks_for_org.delay(str(org_id))


@shared_task(name="tasks.generate_daily_tasks_for_org", max_retries=3, default_retry_delay=60)
def generate_daily_tasks_for_org(org_id: str):
    from apps.infrastructure.core.rls import set_tenant_context
    from apps.farm.tasks.services import TaskService

    with set_tenant_context(org_id) as org:
        try:
            TaskService(org).generate_daily_tasks()
        except Exception as exc:
            logger.exception("tasks.generate_daily_failed", org_id=org_id, error=str(exc))
            raise


@shared_task(name="tasks.send_incomplete_task_report_all_orgs")
def send_incomplete_task_report_all_orgs():
    from apps.infrastructure.core.rls import no_tenant_context
    from apps.infrastructure.tenants.models import Organization

    with no_tenant_context():
        org_ids = list(
            Organization.objects.filter(subscription_status="active").values_list("id", flat=True)
        )

    for org_id in org_ids:
        send_incomplete_task_report_for_org.delay(str(org_id))


@shared_task(name="tasks.send_incomplete_task_report_for_org")
def send_incomplete_task_report_for_org(org_id: str):
    from apps.infrastructure.core.rls import set_tenant_context
    from apps.farm.tasks.services import TaskService

    with set_tenant_context(org_id) as org:
        try:
            TaskService(org).send_incomplete_report()
        except Exception as exc:
            logger.exception("tasks.incomplete_report_failed", org_id=org_id, error=str(exc))
            raise
