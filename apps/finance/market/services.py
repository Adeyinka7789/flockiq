import datetime

import structlog
from django.db.models import Sum, Avg

from apps.infrastructure.core.services import BaseService

logger = structlog.get_logger(__name__)


class MarketService(BaseService):

    def get_current_prices(self, product_type: str = None):
        from .models import MarketPrice

        qs = MarketPrice.objects.filter(org=self.org).order_by("-date")
        if product_type:
            qs = qs.filter(product_type=product_type)
        return qs[:20]

    def get_minimum_viable_price(self, batch_id: str) -> dict:
        from apps.farm.flocks.models import Batch
        from apps.finance.expenses.models import ExpenseRecord
        from apps.finance.finance.models import SalesRecord
        from .models import MarketPrice

        try:
            batch = Batch.objects.get(id=batch_id, org=self.org)
        except Batch.DoesNotExist:
            raise ValueError(f"Batch {batch_id} not found.")

        total_expenses_kobo = (
            ExpenseRecord.objects.filter(batch=batch, org=self.org)
            .aggregate(t=Sum("amount_kobo"))["t"] or 0
        )
        total_units = float(
            SalesRecord.objects.filter(batch=batch, org=self.org)
            .aggregate(t=Sum("quantity"))["t"] or 0
        )
        if not total_units:
            total_units = batch.current_count or 1

        min_price_kobo = int(total_expenses_kobo / total_units) if total_units else 0
        recommended_price_kobo = int(min_price_kobo * 1.2)

        latest_market = (
            MarketPrice.objects.filter(org=self.org)
            .order_by("-date")
            .first()
        )
        current_market_price_kobo = latest_market.price_per_unit_kobo if latest_market else 0

        return {
            "min_price_kobo": min_price_kobo,
            "min_price_naira": min_price_kobo / 100,
            "recommended_price_kobo": recommended_price_kobo,
            "recommended_price_naira": recommended_price_kobo / 100,
            "current_market_price_kobo": current_market_price_kobo,
            "current_market_price_naira": current_market_price_kobo / 100,
        }

    def get_seasonal_forecast(self, product_type: str) -> dict:
        from .models import SeasonalDemandIndex

        today = datetime.date.today()
        current_month = today.month
        peak_threshold = 8

        indices = list(
            SeasonalDemandIndex.objects.filter(product_type=product_type)
            .order_by("month")
        )

        current_idx = next(
            (i for i in indices if i.month == current_month), None
        )
        if not current_idx:
            return {"available": False}

        next_months = []
        for offset in range(1, 4):
            month = ((current_month - 1 + offset) % 12) + 1
            entry = next((i for i in indices if i.month == month), None)
            if entry:
                next_months.append({"month": month, "index": entry.demand_index})

        if next_months:
            avg_next = sum(m["index"] for m in next_months) / len(next_months)
            if avg_next > current_idx.demand_index + 1:
                trend = "up"
            elif avg_next < current_idx.demand_index - 1:
                trend = "down"
            else:
                trend = "stable"
        else:
            trend = "stable"

        peak_months = [i.month for i in indices if i.demand_index >= peak_threshold]

        if current_idx.demand_index >= peak_threshold:
            recommendation = "Sell now — peak demand season."
        elif trend == "up":
            recommendation = "Consider waiting — demand trending upward next month."
        else:
            recommendation = "Stable market — sell at your target price."

        return {
            "available": True,
            "current_index": current_idx.demand_index,
            "current_month": current_month,
            "trend": trend,
            "next_months": next_months,
            "peak_months": peak_months,
            "recommendation": recommendation,
        }

    def record_market_price(
        self,
        product_type: str,
        price_per_unit_kobo: int,
        unit: str,
        market_name: str,
        region: str = "Lagos",
        recorded_by=None,
    ):
        from .models import MarketPrice

        with self.atomic():
            price = MarketPrice.objects.create(
                org=self.org,
                product_type=product_type,
                price_per_unit_kobo=price_per_unit_kobo,
                unit=unit,
                market_name=market_name,
                region=region,
                recorded_by=recorded_by,
            )

        self.logger.info(
            "market.price_recorded",
            product_type=product_type,
            price_per_unit_kobo=price_per_unit_kobo,
        )
        return price
