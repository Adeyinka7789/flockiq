import datetime
from decimal import Decimal

import structlog
from django.db import transaction
from django.db.models import Sum

from apps.infrastructure.core.services import BaseService

logger = structlog.get_logger(__name__)


class FeedService(BaseService):

    def log_feed(
        self,
        batch_id: str,
        record_date: datetime.date,
        feed_type: str,
        quantity_kg,
        cost_per_kg=None,
        notes: str = "",
        recorded_by=None,
    ):
        from apps.farm.flocks.models import Batch
        from .models import FeedLog

        try:
            batch = Batch.objects.get(id=batch_id, org=self.org)
        except Batch.DoesNotExist:
            raise ValueError(f"Batch {batch_id} not found.")

        if batch.status != "active":
            raise ValueError(f"Cannot log feed for a {batch.status} batch.")

        with transaction.atomic():
            log = FeedLog.objects.create(
                org=self.org,
                batch=batch,
                farm=batch.farm,
                record_date=record_date,
                feed_type=feed_type,
                quantity_kg=Decimal(str(quantity_kg)),
                cost_per_kg=Decimal(str(cost_per_kg)) if cost_per_kg is not None else None,
                recorded_by=recorded_by,
                notes=notes,
            )

        self.logger.info(
            "feed.log_created",
            log_id=str(log.pk),
            batch_id=batch_id,
            quantity_kg=str(quantity_kg),
        )
        return log

    def get_feed_summary(self, batch_id: str) -> dict:
        from .models import FeedLog

        logs = FeedLog.objects.filter(org_id=self.org.id, batch_id=batch_id)
        totals = logs.aggregate(
            total_feed_consumed_kg=Sum("quantity_kg"),
            total_feed_cost=Sum("total_cost"),
        )

        count = logs.count()
        avg_daily = (
            round(float(totals["total_feed_consumed_kg"]) / count, 2)
            if count and totals["total_feed_consumed_kg"]
            else 0.0
        )

        return {
            "total_feed_consumed_kg": round(float(totals["total_feed_consumed_kg"] or 0), 2),
            "total_feed_cost": round(float(totals["total_feed_cost"] or 0), 2),
            "average_daily_consumption": avg_daily,
            "current_fcr": self.get_fcr(batch_id),
            "days_logged": count,
            "last_7_days": list(logs.order_by("-record_date")[:7]),
        }

    def get_fcr(self, batch_id: str):
        from apps.farm.flocks.models import Batch, WeightRecord
        from apps.infrastructure.core.calculator import BreedCalculator
        from .models import FeedLog

        try:
            batch = Batch.objects.get(id=batch_id, org=self.org)
        except Batch.DoesNotExist:
            return None

        if batch.bird_type != "broiler":
            return None

        latest_weight = (
            WeightRecord.objects.filter(batch=batch)
            .order_by("-sample_date")
            .first()
        )
        if not latest_weight:
            return None

        total_feed = (
            FeedLog.objects.filter(org_id=self.org.id, batch_id=batch_id)
            .aggregate(total=Sum("quantity_kg"))["total"]
        )
        if not total_feed:
            return None

        total_weight_gain = float(latest_weight.avg_weight_kg) * batch.current_count
        if total_weight_gain <= 0:
            return None

        return BreedCalculator.fcr(float(total_feed), total_weight_gain)

    def get_feed_cost_forecast(self, batch_id: str) -> dict:
        from apps.farm.flocks.models import Batch
        from .models import FeedLog

        try:
            batch = Batch.objects.get(id=batch_id, org=self.org)
        except Batch.DoesNotExist:
            raise ValueError(f"Batch {batch_id} not found.")

        logs = FeedLog.objects.filter(org_id=self.org.id, batch_id=batch_id)
        totals = logs.aggregate(
            total_cost=Sum("total_cost"),
            total_days=Sum("quantity_kg"),
        )
        count = logs.count()
        total_cost = float(totals["total_cost"] or 0)
        avg_daily_cost = round(total_cost / count, 2) if count else 0.0

        # Estimate remaining days: broiler target 42 days, layer 365 days
        target_days = 42 if batch.bird_type == "broiler" else 365
        remaining_days = max(0, target_days - batch.cycle_day)
        estimated_cost = round(avg_daily_cost * remaining_days, 2)

        confidence = "low" if count < 7 else ("medium" if count < 21 else "high")

        return {
            "remaining_days": remaining_days,
            "estimated_cost": estimated_cost,
            "confidence": confidence,
        }

    def get_trend_data(self, batch_id: str, days: int = 30) -> dict:
        from .models import FeedLog

        cutoff = datetime.date.today() - datetime.timedelta(days=days)
        logs = list(
            FeedLog.objects
            .filter(org_id=self.org.id, batch_id=batch_id, record_date__gte=cutoff)
            .order_by("record_date")
            .values("record_date", "quantity_kg", "requirement_kg")
        )

        labels = [str(r["record_date"]) for r in logs]
        actual_data = [float(r["quantity_kg"]) for r in logs]
        requirement_data = [
            float(r["requirement_kg"]) if r["requirement_kg"] else 0.0
            for r in logs
        ]

        return {
            "labels": labels,
            "actual_data": actual_data,
            "requirement_data": requirement_data,
        }

    def get_stock_levels(self, farm_id: str) -> list:
        from .models import FeedStock

        return list(FeedStock.objects.filter(org_id=self.org.id, farm_id=farm_id))
