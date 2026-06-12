import structlog
from django.db.models import F
from django.db.models.signals import post_save
from django.dispatch import receiver

# Internal aliased imports: signals.py is only imported from AppConfig.ready(),
# by which point the app registry is fully populated — so importing the concrete
# model classes here is circular-import-safe. Using the class (not a string
# sender) makes dispatch_uid deduplication reliable across import orders.
from apps.farm.flocks.models import Batch as _Batch, MortalityLog as _MortalityLog

logger = structlog.get_logger(__name__)


@receiver(post_save, sender=_MortalityLog, dispatch_uid="flocks.on_mortality_log_saved")
def on_mortality_log_saved(sender, instance, created, **kwargs):
    if not created:
        return

    from apps.farm.flocks.models import Batch

    # Atomically decrement current_count only when the batch belongs to this org.
    updated = Batch.objects.unscoped().filter(pk=instance.batch_id, org_id=instance.org_id).update(
        current_count=F("current_count") - instance.count
    )
    if updated != 1:
        logger.error(
            "flocks.mortality_cross_tenant_batch_blocked",
            mortality_log_id=str(instance.pk),
            batch_id=str(instance.batch_id),
            org_id=str(instance.org_id),
            updated=updated,
        )
        return

    # Reload batch to check threshold
    batch = Batch.objects.unscoped().get(pk=instance.batch_id, org_id=instance.org_id)
    threshold = batch.initial_count * 0.10

    if batch.current_count < threshold:
        try:
            from apps.infrastructure.notifications.services import NotificationService
            NotificationService(instance.org).send(
                event_type="mortality_spike",
                context={
                    "farm_name": batch.farm.name if batch.farm_id else "",
                    "batch_name": batch.batch_name,
                    "count": instance.count,
                    "normal": round(threshold),
                },
                farm=batch.farm if batch.farm_id else None,
                batch=batch,
            )
        except Exception:
            # Notification failure must never abort the domain write
            logger.exception("flocks.mortality_spike_notification_failed", batch_id=str(batch.pk))

    # Fire the real ML anomaly detection task (fire-and-forget)
    try:
        from apps.health.analytics.tasks import check_mortality_anomaly
        check_mortality_anomaly.delay(
            org_id=str(instance.org_id),
            batch_id=str(instance.batch_id),
        )
    except Exception:
        logger.warning("flocks.anomaly_task_enqueue_failed", batch_id=str(instance.batch_id))


@receiver(post_save, sender=_Batch, dispatch_uid="flocks.on_batch_saved")
def on_batch_saved(sender, instance, created, **kwargs):
    # Cycle billing is a Paystack-driven pricing tier the farmer selects manually
    # on the billing page (activated via the Paystack webhook in billing/views.py),
    # NOT tied to batch placement/closure. This handler only emits lifecycle logs.
    if created:
        logger.info(
            "flocks.batch_placed",
            batch_id=str(instance.pk),
            batch_name=instance.batch_name,
            bird_type=instance.bird_type,
            initial_count=instance.initial_count,
        )
        return

    # Status changed to closed
    if instance.status == "closed":
        logger.info(
            "flocks.batch_closed",
            batch_id=str(instance.pk),
            batch_name=instance.batch_name,
        )
