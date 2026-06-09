import datetime

import structlog
from django.db.models.signals import post_save
from django.dispatch import receiver

logger = structlog.get_logger(__name__)

# Internal aliased imports: signals.py is only imported from AppConfig.ready(),
# so the app registry is fully populated — importing these concrete model
# classes (including the cross-app flocks.Batch) is circular-import-safe.
# Using the class (not a string sender) makes dispatch_uid dedup reliable.
from apps.farm.flocks.models import Batch as _Batch
from .models import MedicationRecord as _MedicationRecord

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


@receiver(post_save, sender=_Batch, dispatch_uid="health.on_batch_created_generate_vaccinations")
def on_batch_created_generate_vaccinations(sender, instance, created, **kwargs):
    if not created:
        return
    _generate_vaccination_schedule(instance)


def _generate_vaccination_schedule(batch):
    from .models import VaccinationSchedule
    from apps.infrastructure.core.rls import set_tenant_context

    schedule = (
        LAYER_VACCINATION_SCHEDULE
        if batch.bird_type == "layer"
        else BROILER_VACCINATION_SCHEDULE
    )

    records = []
    for vaccine_name, recommended_day, route in schedule:
        placement_date = batch.placement_date
        if isinstance(placement_date, str):
            placement_date = datetime.datetime.strptime(placement_date, '%Y-%m-%d').date()
        due_date = placement_date + datetime.timedelta(days=recommended_day)
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
        with set_tenant_context(batch.org):
            VaccinationSchedule.objects.bulk_create(records, ignore_conflicts=True)
        logger.info(
            "health.vaccinations_scheduled",
            batch_id=str(batch.id),
            count=len(records),
        )
    except Exception:
        logger.exception("health.vaccination_schedule_failed", batch_id=str(batch.id))


@receiver(post_save, sender=_MedicationRecord, dispatch_uid="health.on_medication_saved_check_withdrawal")
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
