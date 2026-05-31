import structlog
from celery import shared_task

logger = structlog.get_logger(__name__)


@shared_task(name="health.send_vaccination_reminders_all_orgs")
def send_vaccination_reminders_all_orgs():
    from apps.infrastructure.core.rls import no_tenant_context
    from apps.infrastructure.tenants.models import Organization

    with no_tenant_context():
        org_ids = list(
            Organization.objects.filter(subscription_status="active").values_list("id", flat=True)
        )

    for org_id in org_ids:
        send_vaccination_reminders_for_org.delay(str(org_id))


@shared_task(name="health.send_vaccination_reminders_for_org", max_retries=3, default_retry_delay=60)
def send_vaccination_reminders_for_org(org_id: str):
    import datetime

    from apps.infrastructure.core.rls import set_tenant_context
    from apps.infrastructure.notifications.services import NotificationService

    today = datetime.date.today()
    reminder_cutoff = today + datetime.timedelta(days=3)

    with set_tenant_context(org_id) as org:
        try:
            from .models import VaccinationSchedule

            due_soon = VaccinationSchedule.objects.filter(
                status="scheduled",
                due_date__gte=today,
                due_date__lte=reminder_cutoff,
                reminder_sent=False,
            ).select_related("batch", "farm")

            svc = NotificationService(org)
            reminded_ids = []
            for vacc in due_soon:
                svc.send(
                    "vaccination_due",
                    context={
                        "batch_name": str(vacc.batch),
                        "farm_name": str(vacc.farm),
                        "date": str(vacc.due_date),
                    },
                    farm=vacc.farm,
                    batch=vacc.batch,
                )
                reminded_ids.append(vacc.pk)

            if reminded_ids:
                VaccinationSchedule.objects.filter(pk__in=reminded_ids).update(reminder_sent=True)

            overdue = VaccinationSchedule.objects.filter(
                status="scheduled",
                due_date__lt=today,
            ).select_related("batch", "farm")

            overdue_ids = []
            for vacc in overdue:
                svc.send(
                    "vaccination_overdue",
                    context={
                        "batch_name": str(vacc.batch),
                        "farm_name": str(vacc.farm),
                        "date": str(vacc.due_date),
                    },
                    farm=vacc.farm,
                    batch=vacc.batch,
                )
                overdue_ids.append(vacc.pk)

            if overdue_ids:
                VaccinationSchedule.objects.filter(pk__in=overdue_ids).update(status="missed")

            logger.info(
                "health.reminders_sent",
                org_id=org_id,
                reminded=len(reminded_ids),
                marked_missed=len(overdue_ids),
            )

        except Exception as exc:
            logger.exception("health.reminders_failed", org_id=org_id, error=str(exc))
            raise
