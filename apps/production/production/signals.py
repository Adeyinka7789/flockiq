import datetime
from decimal import Decimal

import structlog
from django.db.models.signals import post_save
from django.dispatch import receiver

logger = structlog.get_logger(__name__)


@receiver(post_save, sender="production.EggProductionLog")
def on_egg_log_saved(sender, instance, created, **kwargs):
    if not created:
        return

    _calculate_and_update(instance)
    _update_crate_inventory(instance)
    _check_production_drop(instance)
    _maybe_trigger_forecast(instance)


def _calculate_and_update(instance):
    from apps.infrastructure.core.calculator import BreedCalculator
    from .models import EggProductionLog

    batch_count = (
        _get_batch_count(instance.batch_id)
    )

    hdp = None
    if batch_count and batch_count > 0:
        hdp = BreedCalculator.hen_day_percentage(instance.total_eggs, batch_count)

    crates = BreedCalculator.crates(instance.total_eggs)

    EggProductionLog.objects.filter(pk=instance.pk).update(
        hen_day_pct=Decimal(str(hdp)) if hdp is not None else None,
        crates=Decimal(str(crates)),
    )
    instance.hen_day_pct = Decimal(str(hdp)) if hdp is not None else None
    instance.crates = Decimal(str(crates))


def _get_batch_count(batch_id):
    from apps.farm.flocks.models import Batch

    return (
        Batch.objects.unscoped()
        .filter(id=batch_id)
        .values_list("current_count", flat=True)
        .first()
    )


def _update_crate_inventory(instance):
    from .models import CrateInventory

    try:
        inventory, _ = CrateInventory.objects.get_or_create(
            org=instance.org,
            farm=instance.farm,
            date=instance.record_date,
            defaults={"crates_produced": Decimal("0.0")},
        )
        crates = instance.crates or Decimal("0.0")
        new_produced = inventory.crates_produced + crates
        CrateInventory.objects.filter(pk=inventory.pk).update(
            crates_produced=new_produced,
            crates_balance=new_produced - inventory.crates_sold,
        )
    except Exception:
        logger.exception(
            "production.signal.crate_inventory_update_failed log_id=%s",
            str(instance.pk),
        )


def _check_production_drop(instance):
    from apps.infrastructure.notifications.services import NotificationService
    from .models import EggProductionLog

    yesterday = instance.record_date - datetime.timedelta(days=1)
    yesterday_hdp = (
        EggProductionLog.objects
        .filter(batch=instance.batch, record_date=yesterday)
        .values_list("hen_day_pct", flat=True)
        .first()
    )

    if yesterday_hdp is None or yesterday_hdp == 0:
        return

    current_hdp = instance.hen_day_pct
    if current_hdp is None:
        return

    drop_pct = float(yesterday_hdp - current_hdp) / float(yesterday_hdp) * 100
    if drop_pct >= 10:
        try:
            NotificationService(instance.org).send(
                event_type="production_drop",
                context={
                    "farm_name": instance.farm.name if instance.farm_id else "",
                    "batch_name": (
                        instance.batch.batch_name if instance.batch_id else ""
                    ),
                    "value": round(float(current_hdp), 1),
                    "normal": round(float(yesterday_hdp), 1),
                },
            )
        except Exception:
            logger.exception(
                "production.signal.production_drop_notification_failed log_id=%s",
                str(instance.pk),
            )


def _maybe_trigger_forecast(instance):
    from .models import EggProductionLog

    record_count = EggProductionLog.objects.filter(batch=instance.batch).count()
    if record_count >= 7:
        try:
            from .tasks import run_egg_forecast

            run_egg_forecast.delay(
                org_id=str(instance.org_id),
                batch_id=str(instance.batch_id),
            )
        except Exception:
            logger.exception(
                "production.signal.forecast_task_failed log_id=%s",
                str(instance.pk),
            )
