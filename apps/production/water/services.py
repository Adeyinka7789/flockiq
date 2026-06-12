import datetime
from decimal import Decimal

import structlog
from django.db import transaction
from django.db.models import Avg

from apps.infrastructure.core.services import BaseService

logger = structlog.get_logger(__name__)


class WaterService(BaseService):

    def log_water(
        self,
        batch_id: str,
        record_date: datetime.date,
        litres_consumed,
        notes: str = "",
        recorded_by=None,
    ):
        from apps.farm.flocks.models import Batch
        from .models import WaterLog

        try:
            batch = Batch.objects.get(id=batch_id, org=self.org)
        except Batch.DoesNotExist:
            raise ValueError(f"Batch {batch_id} not found.")

        if batch.status != "active":
            raise ValueError(f"Cannot log water for a {batch.status} batch.")

        with transaction.atomic():
            log = WaterLog.objects.create(
                org=self.org,
                batch=batch,
                farm=batch.farm,
                record_date=record_date,
                litres_consumed=Decimal(str(litres_consumed)),
                recorded_by=recorded_by,
                notes=notes,
            )

        self.logger.info(
            "water.log_created",
            log_id=str(log.pk),
            batch_id=batch_id,
            litres_consumed=str(litres_consumed),
        )
        return log

    def get_water_summary(self, batch_id: str) -> dict:
        from .models import WaterLog

        logs = WaterLog.objects.filter(org_id=self.org.id, batch_id=batch_id)
        cutoff_7 = datetime.date.today() - datetime.timedelta(days=7)

        aggregates = logs.aggregate(avg_daily=Avg("litres_consumed"))
        anomaly_count = logs.filter(
            record_date__gte=cutoff_7, anomaly_flagged=True
        ).count()

        return {
            "avg_daily_consumption": round(
                float(aggregates["avg_daily"] or 0), 1
            ),
            "anomaly_count_last_7days": anomaly_count,
            "last_7_days": list(logs.order_by("-record_date")[:7]),
        }

    def get_trend_data(self, batch_id: str, days: int = 30) -> dict:
        from .models import WaterLog

        cutoff = datetime.date.today() - datetime.timedelta(days=days)
        logs = list(
            WaterLog.objects
            .filter(org_id=self.org.id, batch_id=batch_id, record_date__gte=cutoff)
            .order_by("record_date")
            .values("record_date", "litres_consumed", "requirement_litres", "anomaly_flagged")
        )

        labels = [str(r["record_date"]) for r in logs]
        actual_data = [float(r["litres_consumed"]) for r in logs]
        requirement_data = [
            float(r["requirement_litres"]) if r["requirement_litres"] else 0.0
            for r in logs
        ]

        return {
            "labels": labels,
            "actual_data": actual_data,
            "requirement_data": requirement_data,
        }
