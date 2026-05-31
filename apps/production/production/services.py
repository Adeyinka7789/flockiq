import datetime
from decimal import Decimal

import structlog
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Avg, Sum

from apps.infrastructure.core.services import BaseService

logger = structlog.get_logger(__name__)


class EggProductionService(BaseService):

    def log_production(
        self,
        batch_id: str,
        record_date: datetime.date,
        total_eggs: int,
        grade_a: int = 0,
        grade_b: int = 0,
        grade_c: int = 0,
        broken: int = 0,
        recorded_by=None,
        notes: str = "",
    ):
        from apps.farm.flocks.models import Batch
        from .exceptions import BatchNotLayerError, ProductionBatchClosedError
        from .models import EggProductionLog

        try:
            batch = Batch.objects.get(id=batch_id, org=self.org)
        except Batch.DoesNotExist:
            raise ValueError(f"Batch {batch_id} not found.")

        if batch.bird_type != "layer":
            raise BatchNotLayerError(
                "Egg production can only be logged for layer batches."
            )

        if batch.status != "active":
            raise ProductionBatchClosedError(
                f"Cannot log production on a {batch.status} batch."
            )

        total_grades = grade_a + grade_b + grade_c + broken
        if total_grades > 0 and total_grades != total_eggs:
            raise ValueError(
                f"Grade counts ({total_grades}) must equal total_eggs ({total_eggs})."
            )

        with transaction.atomic():
            log = EggProductionLog.objects.create(
                org=self.org,
                batch=batch,
                farm=batch.farm,
                house=batch.house,
                record_date=record_date,
                total_eggs=total_eggs,
                grade_a=grade_a,
                grade_b=grade_b,
                grade_c=grade_c,
                broken=broken,
                recorded_by=recorded_by,
                notes=notes,
            )

        self.logger.info(
            "production.egg_log_created",
            log_id=str(log.pk),
            batch_id=batch_id,
            total_eggs=total_eggs,
        )
        return log

    def get_production_summary(self, batch_id: str) -> dict:
        from .models import EggProductionLog

        logs = EggProductionLog.objects.filter(batch_id=batch_id)
        totals = logs.aggregate(
            total_eggs_to_date=Sum("total_eggs"),
            average_hen_day_pct=Avg("hen_day_pct"),
            total_crates=Sum("crates"),
        )

        best_day = logs.order_by("-total_eggs").first()
        worst_day = logs.order_by("total_eggs").first()
        last_7_days = list(logs.order_by("-record_date")[:7])

        return {
            "total_eggs_to_date": totals["total_eggs_to_date"] or 0,
            "average_hen_day_pct": round(
                float(totals["average_hen_day_pct"] or 0), 2
            ),
            "best_day": best_day,
            "worst_day": worst_day,
            "total_crates": round(float(totals["total_crates"] or 0), 1),
            "last_7_days": last_7_days,
        }

    def get_trend_data(self, batch_id: str, days: int = 30) -> dict:
        from apps.farm.flocks.models import Batch
        from apps.infrastructure.core.calculator import PoultryCalculator
        from .models import EggProductionLog

        cutoff = datetime.date.today() - datetime.timedelta(days=days)
        logs = list(
            EggProductionLog.objects
            .filter(batch_id=batch_id, record_date__gte=cutoff)
            .order_by("record_date")
            .values("record_date", "hen_day_pct")
        )

        try:
            batch = Batch.objects.get(id=batch_id, org=self.org)
            calc = PoultryCalculator(batch.bird_type)
            benchmark_pct = calc.standard.target_hen_day_pct
        except Batch.DoesNotExist:
            benchmark_pct = 80.0

        labels = [str(r["record_date"]) for r in logs]
        actual_data = [
            float(r["hen_day_pct"]) if r["hen_day_pct"] is not None else 0.0
            for r in logs
        ]
        benchmark_data = [benchmark_pct] * len(logs)

        return {
            "labels": labels,
            "actual_data": actual_data,
            "benchmark_data": benchmark_data,
        }

    def get_production_table(self, batch_id: str, page: int = 1):
        from .models import EggProductionLog

        qs = (
            EggProductionLog.objects
            .filter(batch_id=batch_id)
            .select_related("recorded_by")
            .order_by("-record_date")
        )
        return Paginator(qs, 20).get_page(page)

    def check_against_benchmark(self, batch_id: str) -> dict:
        from apps.farm.flocks.models import Batch
        from apps.infrastructure.core.calculator import PoultryCalculator
        from .models import EggProductionLog

        try:
            batch = Batch.objects.get(id=batch_id, org=self.org)
        except Batch.DoesNotExist:
            raise ValueError(f"Batch {batch_id} not found.")

        calc = PoultryCalculator(batch.bird_type)
        target = calc.standard.target_hen_day_pct

        cutoff = datetime.date.today() - datetime.timedelta(days=7)
        result = (
            EggProductionLog.objects
            .filter(batch_id=batch_id, record_date__gte=cutoff)
            .aggregate(avg=Avg("hen_day_pct"))
        )
        actual_avg = float(result["avg"] or 0)

        if actual_avg >= target * 0.90:
            status = "on_track"
        elif actual_avg >= target * 0.80:
            status = "below_benchmark"
        else:
            status = "critical"

        return {
            "status": status,
            "expected_range": f"{target * 0.90:.1f}–{target * 1.10:.1f}%",
            "actual_avg_7day": round(actual_avg, 2),
        }
