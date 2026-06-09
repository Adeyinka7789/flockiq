from decimal import Decimal

import structlog
from django.db.models.signals import post_save
from django.dispatch import receiver

logger = structlog.get_logger(__name__)

# Internal aliased import: signals.py is only imported from AppConfig.ready(),
# so the app registry is fully populated and this is circular-import-safe.
# Using the class (not a string sender) makes dispatch_uid dedup reliable.
from .models import WaterLog as _WaterLog


@receiver(post_save, sender=_WaterLog, dispatch_uid="water.on_water_log_saved")
def on_water_log_saved(sender, instance, created, **kwargs):
    if not created:
        return

    _calculate_and_update(instance)


def _calculate_and_update(instance):
    from apps.infrastructure.core.calculator import BreedCalculator
    from apps.farm.flocks.models import Batch
    from .models import WaterLog

    try:
        batch = Batch.objects.unscoped().filter(
            id=instance.batch_id,
            org_id=instance.org_id,
        ).first()
    except Exception:
        logger.exception("water.signal.batch_fetch_failed", log_id=str(instance.pk))
        return

    updates = {}
    anomaly = False

    if batch:
        try:
            req = BreedCalculator.daily_water_requirement_litres(batch.current_count)
            req_decimal = Decimal(str(req))
            variance = instance.litres_consumed - req_decimal
            updates["requirement_litres"] = req_decimal
            updates["variance_litres"] = variance

            if instance.litres_consumed < req_decimal * Decimal("0.80"):
                anomaly = True
                updates["anomaly_flagged"] = True
        except Exception:
            logger.exception(
                "water.signal.requirement_calc_failed", log_id=str(instance.pk)
            )

    if updates:
        updated = WaterLog.objects.unscoped().filter(pk=instance.pk, org_id=instance.org_id).update(**updates)
        if updated != 1:
            logger.error(
                "water.signal_cross_tenant_log_update_blocked",
                log_id=str(instance.pk),
                org_id=str(instance.org_id),
                updated=updated,
            )
            return
        for k, v in updates.items():
            setattr(instance, k, v)

    if anomaly:
        _fire_water_drop_notification(instance)


def _fire_water_drop_notification(instance):
    from apps.infrastructure.notifications.services import NotificationService
    from apps.infrastructure.core.rls import set_tenant_context

    try:
        with set_tenant_context(instance.org):
            NotificationService(instance.org).send(
                event_type="water_drop",
                context={
                    "farm_name": instance.farm.name if instance.farm_id else "",
                    "batch_name": (
                        instance.batch.batch_name if instance.batch_id else ""
                    ),
                    "value": float(instance.litres_consumed),
                },
            )
        logger.critical(
            "water.anomaly.detected",
            log_id=str(instance.pk),
            farm_id=str(instance.farm_id),
            litres_consumed=str(instance.litres_consumed),
            requirement_litres=str(instance.requirement_litres),
        )
    except Exception:
        logger.exception(
            "water.signal.notification_failed", log_id=str(instance.pk)
        )
