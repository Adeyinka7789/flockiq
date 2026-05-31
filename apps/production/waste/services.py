import datetime
from decimal import Decimal

import structlog
from django.db import transaction
from django.db.models import Sum

from apps.infrastructure.core.services import BaseService

logger = structlog.get_logger(__name__)


class WasteService(BaseService):

    def log_waste(
        self,
        farm_id: str,
        record_date: datetime.date,
        waste_type: str,
        quantity_kg,
        disposal_method: str = "composting",
        cost=None,
        batch_id: str = None,
        notes: str = "",
    ):
        from apps.farm.farms.models import Farm
        from .models import WasteLog

        try:
            farm = Farm.objects.get(id=farm_id, org=self.org)
        except Farm.DoesNotExist:
            raise ValueError(f"Farm {farm_id} not found.")

        batch = None
        if batch_id:
            from apps.farm.flocks.models import Batch
            try:
                batch = Batch.objects.get(id=batch_id, org=self.org)
            except Batch.DoesNotExist:
                raise ValueError(f"Batch {batch_id} not found.")

        with transaction.atomic():
            log = WasteLog.objects.create(
                org=self.org,
                farm=farm,
                batch=batch,
                record_date=record_date,
                waste_type=waste_type,
                quantity_kg=Decimal(str(quantity_kg)),
                disposal_method=disposal_method,
                cost=Decimal(str(cost)) if cost is not None else Decimal("0"),
                notes=notes,
            )

        self.logger.info(
            "waste.log_created",
            log_id=str(log.pk),
            farm_id=farm_id,
            waste_type=waste_type,
        )
        return log

    def get_waste_summary(self, farm_id: str) -> dict:
        from .models import WasteLog

        logs = WasteLog.objects.filter(farm_id=farm_id)
        totals = logs.aggregate(
            total_quantity_kg=Sum("quantity_kg"),
            total_cost=Sum("cost"),
        )
        return {
            "total_quantity_kg": round(float(totals["total_quantity_kg"] or 0), 2),
            "total_cost": round(float(totals["total_cost"] or 0), 2),
            "last_10_logs": list(logs.order_by("-record_date")[:10]),
        }
