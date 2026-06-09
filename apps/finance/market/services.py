import datetime

import structlog
from django.db.models import Sum, Avg, Min, Max, Count
from django.shortcuts import get_object_or_404

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


# ── Community Intelligence Services ──────────────────────────────────────────────

class FeedPriceService:

    @staticmethod
    def get_current_prices(feed_type=None, state=None, days=30) -> dict:
        """Returns aggregated price data for the last N days. Never returns individual submissions."""
        from django.utils import timezone
        from .models import FeedPriceReport

        cutoff = timezone.now().date() - datetime.timedelta(days=days)
        qs = FeedPriceReport.objects.filter(reported_date__gte=cutoff)
        if feed_type:
            qs = qs.filter(feed_type=feed_type)
        if state:
            qs = qs.filter(state=state)

        national = qs.aggregate(
            avg=Avg("price_per_25kg_bag"),
            min=Min("price_per_25kg_bag"),
            max=Max("price_per_25kg_bag"),
            count=Count("id"),
        )

        by_state = list(
            qs.values("state")
            .annotate(avg=Avg("price_per_25kg_bag"), count=Count("id"))
            .order_by("state")
        )

        by_brand = list(
            qs.values("brand")
            .annotate(avg=Avg("price_per_25kg_bag"), count=Count("id"))
            .order_by("avg")
        )

        trend = []
        for i in range(8, 0, -1):
            week_start = datetime.date.today() - datetime.timedelta(weeks=i)
            week_end = week_start + datetime.timedelta(weeks=1)
            filter_kwargs = {"reported_date__range": [week_start, week_end]}
            if feed_type:
                filter_kwargs["feed_type"] = feed_type
            week_avg = FeedPriceReport.objects.filter(**filter_kwargs).aggregate(
                avg=Avg("price_per_25kg_bag")
            )["avg"]
            if week_avg:
                trend.append({"week": week_start.strftime("%b %d"), "avg": float(week_avg)})

        return {
            "national": national,
            "by_state": by_state,
            "by_brand": by_brand,
            "trend": trend,
            "feed_type": feed_type,
            "state": state,
            "days": days,
            "last_updated": datetime.datetime.now(),
        }

    @staticmethod
    def submit_price(user, org, feed_type, brand, price, state, lga="", brand_other=""):
        """Submit a new price report. Rate limit: 1 per feed type per day."""
        from django.core.cache import cache
        from .models import FeedPriceReport

        cache_key = f"feed_price_{user.id}_{feed_type}"
        if cache.get(cache_key):
            raise ValueError(
                "You already submitted a price for this feed type today. Come back tomorrow."
            )
        report = FeedPriceReport.objects.create(
            submitted_by=user,
            org=org,
            feed_type=feed_type,
            brand=brand,
            brand_other=brand_other,
            price_per_25kg_bag=price,
            state=state,
            lga=lga,
        )
        cache.set(cache_key, True, timeout=86400)
        return report


class HatcheryService:

    @staticmethod
    def get_top_hatcheries(state=None, bird_type=None, limit=20) -> list:
        from .models import Hatchery

        qs = Hatchery.objects.annotate(
            avg_rating=Avg("reviews__overall_rating"),
            review_count=Count("reviews"),
            avg_survival=Avg("reviews__survival_rate_pct"),
            avg_doc_price=Avg("reviews__price_per_doc"),
        )
        if state:
            qs = qs.filter(state=state)
        if bird_type:
            qs = qs.filter(bird_types__contains=bird_type)

        return list(qs.order_by("-avg_rating", "-review_count")[:limit])

    @staticmethod
    def submit_review(hatchery_id: int, batch, user, org, data: dict):
        from .models import Hatchery, HatcheryReview

        hatchery = get_object_or_404(Hatchery, id=hatchery_id)
        return HatcheryReview.objects.create(
            hatchery=hatchery,
            batch=batch,
            submitted_by=user,
            org=org,
            **data,
        )

    @staticmethod
    def get_doc_price_trend(hatchery_id: int) -> list:
        """Monthly average DOC price from farmer reviews for the last 12 months."""
        from django.db.models.functions import TruncMonth
        from .models import HatcheryReview

        cutoff = datetime.date.today().replace(day=1)
        cutoff = cutoff.replace(year=cutoff.year - 1)

        return list(
            HatcheryReview.objects.filter(
                hatchery_id=hatchery_id,
                purchase_date__gte=cutoff,
            )
            .annotate(month=TruncMonth("purchase_date"))
            .values("month")
            .annotate(avg_price=Avg("price_per_doc"), count=Count("id"))
            .order_by("month")
        )

    @staticmethod
    def suggest_hatchery(user, org, name, state, lga="", address="", phone="", website="", bird_types=None):
        from .models import Hatchery

        return Hatchery.objects.create(
            name=name,
            state=state,
            lga=lga,
            address=address,
            phone=phone,
            website=website,
            bird_types=bird_types or [],
            is_verified=False,
            added_by=user,
        )
