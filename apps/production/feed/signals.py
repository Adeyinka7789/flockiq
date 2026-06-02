from decimal import Decimal

import structlog
from django.db.models import F
from django.db.models.signals import post_save
from django.dispatch import receiver

logger = structlog.get_logger(__name__)


@receiver(post_save, sender="feed.FeedLog")
def on_feed_log_saved(sender, instance, created, **kwargs):
    if not created:
        return

    _calculate_and_update(instance)
    _deduct_feed_stock(instance)


def _calculate_and_update(instance):
    from apps.infrastructure.core.calculator import BreedCalculator
    from apps.farm.flocks.models import Batch
    from .models import FeedLog

    try:
        batch = Batch.objects.unscoped().filter(
            id=instance.batch_id,
            org_id=instance.org_id,
        ).first()
    except Exception:
        logger.exception("feed.signal.batch_fetch_failed", log_id=str(instance.pk))
        return

    updates = {}

    if batch:
        try:
            req = BreedCalculator.daily_feed_requirement_kg(
                batch.current_count, batch.cycle_day, batch.bird_type
            )
            req_decimal = Decimal(str(req))
            variance = instance.quantity_kg - req_decimal
            updates["requirement_kg"] = req_decimal
            updates["variance_kg"] = variance
        except Exception:
            logger.exception("feed.signal.requirement_calc_failed", log_id=str(instance.pk))

    if instance.cost_per_kg is not None:
        updates["total_cost"] = instance.quantity_kg * instance.cost_per_kg

    if updates:
        updated = FeedLog.objects.unscoped().filter(pk=instance.pk, org_id=instance.org_id).update(**updates)
        if updated != 1:
            logger.error(
                "feed.signal_cross_tenant_log_update_blocked",
                log_id=str(instance.pk),
                org_id=str(instance.org_id),
                updated=updated,
            )
            return
        for k, v in updates.items():
            setattr(instance, k, v)


def _deduct_feed_stock(instance):
    from .models import FeedStock

    try:
        stock, _ = FeedStock.objects.unscoped().get_or_create(
            org_id=instance.org_id,
            farm_id=instance.farm_id,
            feed_type=instance.feed_type,
            defaults={"quantity_kg": Decimal("0")},
        )
        updated = FeedStock.objects.unscoped().filter(pk=stock.pk, org_id=instance.org_id).update(
            quantity_kg=F("quantity_kg") - instance.quantity_kg
        )
        if updated != 1:
            logger.error(
                "feed.signal_cross_tenant_stock_update_blocked",
                stock_id=str(stock.pk),
                log_id=str(instance.pk),
                org_id=str(instance.org_id),
                updated=updated,
            )
            return
        stock = FeedStock.objects.unscoped().get(pk=stock.pk)
        if stock.is_low_stock:
            logger.warning(
                "feed.stock.low",
                farm_id=str(instance.farm_id),
                feed_type=instance.feed_type,
                quantity_kg=str(stock.quantity_kg),
                threshold_kg=str(stock.low_stock_threshold_kg),
            )
    except Exception:
        logger.exception("feed.signal.stock_deduct_failed", log_id=str(instance.pk))
