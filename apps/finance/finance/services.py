import datetime
from decimal import Decimal

import structlog
from django.db import transaction
from django.db.models import Sum

from apps.infrastructure.core.services import BaseService

logger = structlog.get_logger(__name__)


class FinanceService(BaseService):

    def record_sale(
        self,
        batch_id: str,
        sale_date: datetime.date,
        product_type: str,
        quantity,
        unit: str,
        unit_price_kobo: int,
        buyer_name: str = "",
        notes: str = "",
        recorded_by=None,
    ):
        from .models import SalesRecord
        from apps.farm.flocks.models import Batch
        from apps.infrastructure.core.services import LedgerService

        try:
            batch = Batch.objects.get(id=batch_id, org=self.org)
        except Batch.DoesNotExist:
            raise ValueError(f"Batch {batch_id} not found.")

        with transaction.atomic():
            record = SalesRecord.objects.create(
                org=self.org,
                batch=batch,
                farm=batch.farm,
                sale_date=sale_date,
                product_type=product_type,
                quantity=Decimal(str(quantity)),
                unit=unit,
                unit_price_kobo=unit_price_kobo,
                total_revenue_kobo=0,  # overridden by save()
                buyer_name=buyer_name,
                notes=notes,
                recorded_by=recorded_by,
            )
            self._update_financial_summary(batch)
            LedgerService(self.org).record_transaction(
                batch=batch,
                amount_kobo=record.total_revenue_kobo,
                category=product_type,
                direction="credit",
            )

        self.logger.info(
            "sale.recorded",
            record_id=str(record.id),
            product_type=product_type,
            total_revenue_kobo=record.total_revenue_kobo,
        )
        return record

    def get_pl_summary(self, batch_id: str) -> dict:
        from .models import SalesRecord, BatchFinancialSummary
        from apps.finance.expenses.models import ExpenseRecord
        from apps.farm.flocks.models import Batch

        try:
            batch = Batch.objects.get(id=batch_id, org=self.org)
        except Batch.DoesNotExist:
            raise ValueError(f"Batch {batch_id} not found.")

        total_revenue_kobo = (
            SalesRecord.objects.filter(batch=batch, org=self.org)
            .aggregate(t=Sum("total_revenue_kobo"))["t"] or 0
        )
        total_expenses_kobo = (
            ExpenseRecord.objects.filter(batch=batch, org=self.org)
            .aggregate(t=Sum("amount_kobo"))["t"] or 0
        )
        gross_profit_kobo = total_revenue_kobo - total_expenses_kobo
        profit_margin_pct = (
            round((gross_profit_kobo / total_revenue_kobo) * 100, 2)
            if total_revenue_kobo else 0
        )
        bird_count = batch.initial_count or 1
        cost_per_bird_naira = round((total_expenses_kobo / 100) / bird_count, 2)
        revenue_per_bird_naira = round((total_revenue_kobo / 100) / bird_count, 2)
        roi_pct = (
            round((gross_profit_kobo / total_expenses_kobo) * 100, 2)
            if total_expenses_kobo else 0
        )

        expense_breakdown = (
            ExpenseRecord.objects.filter(batch=batch, org=self.org)
            .values("category")
            .annotate(total=Sum("amount_kobo"))
            .order_by("-total")
        )
        revenue_breakdown = (
            SalesRecord.objects.filter(batch=batch, org=self.org)
            .values("product_type")
            .annotate(total=Sum("total_revenue_kobo"))
            .order_by("-total")
        )

        return {
            "total_revenue_naira": total_revenue_kobo / 100,
            "total_expenses_naira": total_expenses_kobo / 100,
            "gross_profit_naira": gross_profit_kobo / 100,
            "profit_margin_pct": profit_margin_pct,
            "cost_per_bird_naira": cost_per_bird_naira,
            "revenue_per_bird_naira": revenue_per_bird_naira,
            "roi_pct": roi_pct,
            "break_even_quantity": self.calculate_break_even(batch_id).get("break_even_quantity", 0),
            "expense_breakdown": list(expense_breakdown),
            "revenue_breakdown": list(revenue_breakdown),
        }

    def calculate_break_even(self, batch_id: str) -> dict:
        from .models import SalesRecord
        from apps.finance.expenses.models import ExpenseRecord
        from apps.farm.flocks.models import Batch
        from django.db.models import Avg

        try:
            batch = Batch.objects.get(id=batch_id, org=self.org)
        except Batch.DoesNotExist:
            raise ValueError(f"Batch {batch_id} not found.")

        total_expenses_kobo = (
            ExpenseRecord.objects.filter(batch=batch, org=self.org)
            .aggregate(t=Sum("amount_kobo"))["t"] or 0
        )
        avg_unit_price_kobo = (
            SalesRecord.objects.filter(batch=batch, org=self.org)
            .aggregate(avg=Avg("unit_price_kobo"))["avg"] or 0
        )
        units_sold = float(
            SalesRecord.objects.filter(batch=batch, org=self.org)
            .aggregate(t=Sum("quantity"))["t"] or 0
        )

        break_even_quantity = (
            int(total_expenses_kobo / avg_unit_price_kobo)
            if avg_unit_price_kobo else 0
        )

        return {
            "break_even_quantity": break_even_quantity,
            "total_expenses_kobo": total_expenses_kobo,
            "avg_unit_price_kobo": int(avg_unit_price_kobo),
            "units_sold_so_far": units_sold,
        }

    def get_roi_calculator_data(self, batch_id: str) -> dict:
        from apps.finance.expenses.models import ExpenseRecord

        from apps.farm.flocks.models import Batch

        try:
            batch = Batch.objects.get(id=batch_id, org=self.org)
        except Batch.DoesNotExist:
            raise ValueError(f"Batch {batch_id} not found.")

        total_expenses_kobo = (
            ExpenseRecord.objects.filter(batch=batch, org=self.org)
            .aggregate(t=Sum("amount_kobo"))["t"] or 0
        )

        price_points = [
            int(total_expenses_kobo / batch.initial_count * multiplier)
            for multiplier in [0.8, 1.0, 1.2, 1.4, 1.6]
        ] if batch.initial_count else []

        scenarios = []
        for price_kobo in price_points:
            projected_revenue = price_kobo * batch.initial_count
            projected_profit = projected_revenue - total_expenses_kobo
            roi = (
                round((projected_profit / total_expenses_kobo) * 100, 2)
                if total_expenses_kobo else 0
            )
            scenarios.append({
                "price_per_unit_kobo": price_kobo,
                "price_per_unit_naira": price_kobo / 100,
                "projected_revenue_naira": projected_revenue / 100,
                "projected_profit_naira": projected_profit / 100,
                "roi_pct": roi,
            })

        return {
            "total_expenses_kobo": total_expenses_kobo,
            "total_expenses_naira": total_expenses_kobo / 100,
            "initial_count": batch.initial_count,
            "scenarios": scenarios,
        }

    def recalculate_summary(self, batch) -> "BatchFinancialSummary":
        """Public entry-point called from signals."""
        return self._update_financial_summary(batch)

    def _update_financial_summary(self, batch) -> "BatchFinancialSummary":
        from .models import SalesRecord, BatchFinancialSummary
        from apps.finance.expenses.models import ExpenseRecord

        total_revenue_kobo = (
            SalesRecord.objects.filter(batch=batch, org=self.org)
            .aggregate(t=Sum("total_revenue_kobo"))["t"] or 0
        )
        total_expenses_kobo = (
            ExpenseRecord.objects.filter(batch=batch, org=self.org)
            .aggregate(t=Sum("amount_kobo"))["t"] or 0
        )
        gross_profit_kobo = total_revenue_kobo - total_expenses_kobo
        profit_margin_pct = (
            Decimal(str(round((gross_profit_kobo / total_revenue_kobo) * 100, 2)))
            if total_revenue_kobo else Decimal("0")
        )
        bird_count = batch.initial_count or 1
        cost_per_bird_kobo = int(total_expenses_kobo / bird_count)
        revenue_per_bird_kobo = int(total_revenue_kobo / bird_count)
        roi_pct = (
            Decimal(str(round((gross_profit_kobo / total_expenses_kobo) * 100, 2)))
            if total_expenses_kobo else Decimal("0")
        )

        from apps.finance.expenses.services import ExpenseService
        break_even = self.calculate_break_even(str(batch.id))
        break_even_quantity = break_even.get("break_even_quantity", 0)

        summary, _ = BatchFinancialSummary.objects.update_or_create(
            batch=batch,
            org=self.org,
            defaults={
                "total_revenue_kobo": total_revenue_kobo,
                "total_expenses_kobo": total_expenses_kobo,
                "gross_profit_kobo": gross_profit_kobo,
                "profit_margin_pct": profit_margin_pct,
                "cost_per_bird_kobo": cost_per_bird_kobo,
                "revenue_per_bird_kobo": revenue_per_bird_kobo,
                "break_even_quantity": break_even_quantity,
                "roi_pct": roi_pct,
            },
        )
        return summary
