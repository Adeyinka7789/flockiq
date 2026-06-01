import datetime

import structlog
from django.db.models import Sum

from apps.infrastructure.core.services import BaseService

logger = structlog.get_logger(__name__)


class ExpenseService(BaseService):

    def record_expense(
        self,
        farm_id: str,
        category: str,
        amount_kobo: int,
        description: str,
        expense_date: datetime.date = None,
        batch_id: str = None,
        receipt_ref: str = "",
        notes: str = "",
        recorded_by=None,
    ):
        from .models import ExpenseRecord
        from apps.farm.farms.models import Farm
        from apps.infrastructure.core.services import LedgerService

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

        expense_date = expense_date or datetime.date.today()

        with self.atomic():
            record = ExpenseRecord.objects.create(
                org=self.org,
                farm=farm,
                batch=batch,
                category=category,
                amount_kobo=amount_kobo,
                description=description,
                expense_date=expense_date,
                receipt_ref=receipt_ref,
                notes=notes,
                recorded_by=recorded_by,
            )
            if batch:
                LedgerService(self.org).record_transaction(
                    batch=batch,
                    amount_kobo=amount_kobo,
                    category=category,
                    direction="debit",
                )

        self.logger.info(
            "expense.recorded",
            record_id=str(record.id),
            category=category,
            amount_kobo=amount_kobo,
        )
        return record

    def get_batch_expenses(self, batch_id: str):
        from .models import ExpenseRecord
        return ExpenseRecord.objects.filter(
            batch_id=batch_id, org=self.org
        ).order_by("-expense_date")

    def get_expense_breakdown(
        self,
        batch_id: str = None,
        farm_id: str = None,
        date_from: datetime.date = None,
        date_to: datetime.date = None,
    ) -> dict:
        from .models import ExpenseRecord

        qs = ExpenseRecord.objects.filter(org=self.org)
        if batch_id:
            qs = qs.filter(batch_id=batch_id)
        if farm_id:
            qs = qs.filter(farm_id=farm_id)
        if date_from:
            qs = qs.filter(expense_date__gte=date_from)
        if date_to:
            qs = qs.filter(expense_date__lte=date_to)

        totals = qs.values("category").annotate(total=Sum("amount_kobo")).order_by("-total")
        labels = []
        data = []
        total_kobo = 0
        for row in totals:
            labels.append(dict(ExpenseRecord.CATEGORY_CHOICES).get(row["category"], row["category"]))
            data.append(row["total"])
            total_kobo += row["total"]

        return {"labels": labels, "data": data, "total_kobo": total_kobo}

    def get_total_cost_of_production(self, batch_id: str) -> int:
        from .models import ExpenseRecord
        result = ExpenseRecord.objects.filter(
            batch_id=batch_id, org=self.org
        ).aggregate(total=Sum("amount_kobo"))
        return result["total"] or 0

    def get_farm_expenses_summary(self, farm_id: str, month: int = None) -> dict:
        from .models import ExpenseRecord

        qs = ExpenseRecord.objects.filter(farm_id=farm_id, org=self.org)
        if month:
            qs = qs.filter(expense_date__month=month)

        totals = qs.values("category").annotate(total=Sum("amount_kobo")).order_by("-total")
        grand_total = qs.aggregate(total=Sum("amount_kobo"))["total"] or 0

        return {
            "by_category": list(totals),
            "grand_total_kobo": grand_total,
            "grand_total_naira": grand_total / 100,
        }
