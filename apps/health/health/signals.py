import datetime

import structlog
from django.db.models.signals import post_save
from django.dispatch import receiver

logger = structlog.get_logger(__name__)

LAYER_VACCINATION_SCHEDULE = [
    ("Marek's Disease", 1, "injection"),
    ("Newcastle + IB", 7, "oral"),
    ("Gumboro IBD", 14, "oral"),
    ("Newcastle Booster", 21, "spray"),
    ("Gumboro Booster", 28, "oral"),
    ("Newcastle + IB killed", 70, "injection"),
    ("Fowl Pox", 84, "wing_web"),
]

BROILER_VACCINATION_SCHEDULE = [
    ("Newcastle + IB", 7, "oral"),
    ("Gumboro IBD", 14, "oral"),
    ("Newcastle Booster", 21, "spray"),
]


@receiver(post_save, sender="flocks.Batch")
def on_batch_created_generate_vaccinations(sender, instance, created, **kwargs):
    if not created:
        return
    _generate_vaccination_schedule(instance)


def _generate_vaccination_schedule(batch):
    from .models import VaccinationSchedule

    schedule = (
        LAYER_VACCINATION_SCHEDULE
        if batch.bird_type == "layer"
        else BROILER_VACCINATION_SCHEDULE
    )

    records = []
    for vaccine_name, recommended_day, route in schedule:
        due_date = batch.placement_date + datetime.timedelta(days=recommended_day)
        records.append(
            VaccinationSchedule(
                org=batch.org,
                batch=batch,
                farm=batch.farm,
                vaccine_name=vaccine_name,
                due_date=due_date,
                route=route,
            )
        )

    try:
        VaccinationSchedule.objects.bulk_create(records)
        logger.info(
            "health.vaccinations_scheduled",
            batch_id=str(batch.id),
            count=len(records),
        )
    except Exception:
        logger.exception("health.vaccination_schedule_failed", batch_id=str(batch.id))


@receiver(post_save, sender="health.MedicationRecord")
def on_medication_saved_check_withdrawal(sender, instance, created, **kwargs):
    if not instance.withdrawal_active:
        return

    try:
        from apps.infrastructure.notifications.services import NotificationService

        svc = NotificationService(instance.org)
        svc.send(
            "medication_withdrawal",
            context={
                "batch_name": str(instance.batch),
                "farm_name": str(instance.farm),
                "date": str(instance.withdrawal_cleared_date),
            },
            farm=instance.farm,
            batch=instance.batch,
        )
    except Exception:
        logger.exception(
            "health.withdrawal_notification_failed",
            medication_id=str(instance.id),
        )
