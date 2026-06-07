"""
ROICalculatorService — computes the value FlockIQ delivered to a tenant farm.

This is a retention tool. It shows farmers:
  "Here is what FlockIQ saved or earned you this cycle."

All monetary outputs are in NAIRA (not kobo) so templates can render them
directly with |intcomma without division.
"""

import datetime

import structlog
from django.db.models import Avg, Sum

from apps.infrastructure.core.rls import set_tenant_context

logger = structlog.get_logger(__name__)

ALERT_EVENT_TYPES = frozenset({
    "mortality_spike",
    "water_drop",
    "production_drop",
    "theft_suspected",
    "heat_stress",
    "ai_anomaly",
    "disease_outbreak",
})

_EMPTY_RESULT = {
    "mortality_savings": 0,
    "feed_savings": 0,
    "theft_prevention_value": 0,
    "subscription_cost": 0,
    "net_value_delivered": 0,
    "roi_multiple": 0.0,
    "vaccination_compliance_rate": 0.0,
    "alerts_fired": 0,
    "time_period": {
        "start": None,
        "end": None,
        "batch_name": "—",
        "bird_type": "—",
    },
    "has_data": False,
}


class ROICalculatorService:

    def __init__(self, org, batch=None):
        self.org = org
        self.batch = batch
        self.logger = structlog.get_logger(__name__).bind(
            org_id=str(org.id),
            service="ROICalculatorService",
        )

    # ── Public API ─────────────────────────────────────────────────────────

    def calculate(self) -> dict:
        batch = self._resolve_batch()
        if batch is None:
            return dict(_EMPTY_RESULT)

        try:
            result = self._compute(batch)
            result["has_data"] = True
            return result
        except Exception:
            self.logger.exception("roi.calculation_failed", batch_id=str(batch.id))
            fallback = dict(_EMPTY_RESULT)
            fallback["time_period"] = {
                "start": batch.placement_date,
                "end": (
                    batch.closed_at.date() if batch.closed_at
                    else datetime.date.today()
                ),
                "batch_name": batch.batch_name,
                "bird_type": batch.get_bird_type_display(),
            }
            return fallback

    # ── Internal helpers ───────────────────────────────────────────────────

    def _resolve_batch(self):
        if self.batch is not None:
            return self.batch
        from apps.farm.flocks.models import Batch
        with set_tenant_context(self.org):
            return (
                Batch.objects.filter(org=self.org)
                .order_by("-placement_date")
                .first()
            )

    def _market_price_per_bird_kobo(self) -> int:
        from apps.finance.market.models import MarketPrice
        from apps.finance.finance.models import SalesRecord

        with set_tenant_context(self.org):
            latest = (
                MarketPrice.objects.filter(org=self.org, product_type="live_birds")
                .order_by("-date")
                .first()
            )
            if latest:
                return latest.price_per_unit_kobo

            avg = (
                SalesRecord.objects.filter(org=self.org, product_type="live_birds")
                .aggregate(avg=Avg("unit_price_kobo"))["avg"]
            )
            return int(avg) if avg else 350_000  # ₦3,500 default

    def _compute(self, batch) -> dict:
        start = batch.placement_date
        end = (
            batch.closed_at.date() if batch.closed_at
            else datetime.date.today()
        )

        market_kobo = self._market_price_per_bird_kobo()

        mortality_savings = self._mortality_savings(batch, market_kobo)
        feed_savings = self._feed_savings(batch)
        theft_prevention = self._theft_prevention_value(batch, market_kobo)
        subscription_cost = self._subscription_cost(start, end)

        net_value = mortality_savings + feed_savings + theft_prevention - subscription_cost
        roi_multiple = (
            round(net_value / subscription_cost, 2)
            if subscription_cost > 0 else 0.0
        )

        return {
            "mortality_savings": mortality_savings,
            "feed_savings": feed_savings,
            "theft_prevention_value": theft_prevention,
            "subscription_cost": subscription_cost,
            "net_value_delivered": net_value,
            "roi_multiple": roi_multiple,
            "vaccination_compliance_rate": self._vaccination_compliance(batch),
            "alerts_fired": self._alerts_fired(batch, start, end),
            "time_period": {
                "start": start,
                "end": end,
                "batch_name": batch.batch_name,
                "bird_type": batch.get_bird_type_display(),
            },
        }

    def _mortality_savings(self, batch, market_kobo: int) -> int:
        from apps.health.analytics.models import AnomalyRecord

        with set_tenant_context(self.org):
            alert_count = AnomalyRecord.objects.filter(
                batch=batch, anomaly_type="mortality_spike",
            ).count()

        if alert_count == 0:
            return 0

        prevented_pct = min(0.02 * alert_count, 0.10)
        prevented_birds = int(batch.initial_count * prevented_pct)
        return int(prevented_birds * market_kobo / 100)  # kobo → naira

    def _feed_savings(self, batch) -> int:
        try:
            from apps.health.analytics.feed_efficiency import FeedEfficiencyService
            from apps.production.feed.models import FeedLog

            fcr_data = FeedEfficiencyService(self.org, batch).compute_current_fcr()
            actual_fcr = fcr_data.get("fcr")
            target_fcr = fcr_data.get("target_fcr")
            biomass_kg = fcr_data.get("biomass_kg", 0)

            if actual_fcr is None or actual_fcr >= target_fcr or biomass_kg <= 0:
                return 0

            feed_saved_kg = (target_fcr - actual_fcr) * float(biomass_kg)

            with set_tenant_context(self.org):
                avg_cost_naira = (
                    FeedLog.objects.filter(batch=batch, cost_per_kg__isnull=False)
                    .aggregate(avg=Avg("cost_per_kg"))["avg"]
                )

            cost_per_kg = float(avg_cost_naira) if avg_cost_naira else 400.0
            return int(feed_saved_kg * cost_per_kg)
        except Exception:
            self.logger.warning("roi.feed_savings_failed", batch_id=str(batch.id))
            return 0

    def _theft_prevention_value(self, batch, market_kobo: int) -> int:
        from apps.health.analytics.models import TheftFlag

        with set_tenant_context(self.org):
            flags = list(TheftFlag.objects.filter(batch=batch))

        total_unaccounted = sum(
            f.unaccounted_birds
            for f in flags
            if float(f.variance_pct) < 1.5
        )
        return int(total_unaccounted * market_kobo / 100)  # kobo → naira

    def _subscription_cost(self, start: datetime.date, end: datetime.date) -> int:
        from apps.infrastructure.billing.models import BillingPlan, PaymentRecord

        with set_tenant_context(self.org):
            total_kobo = (
                PaymentRecord.objects.filter(
                    org=self.org,
                    status="success",
                    paid_at__date__range=[start, end],
                )
                .aggregate(t=Sum("amount_kobo"))["t"]
            )

        if total_kobo:
            return int(total_kobo / 100)  # kobo → naira

        plan = (
            BillingPlan.objects.filter(
                plan_tier=self.org.plan_tier, is_active=True
            ).first()
        )
        return int(plan.amount_kobo / 100) if plan else 0

    def _vaccination_compliance(self, batch) -> float:
        try:
            from apps.health.health.services import HealthService

            with set_tenant_context(self.org):
                return HealthService(self.org).get_compliance_rate(batch_id=batch.id)
        except Exception:
            return 0.0

    def _alerts_fired(
        self, batch, start: datetime.date, end: datetime.date,
    ) -> int:
        from apps.infrastructure.notifications.models import NotificationLog

        with set_tenant_context(self.org):
            return NotificationLog.objects.filter(
                org=self.org,
                severity__in=["warning", "critical"],
                created_at__date__range=[start, end],
                event_type__in=list(ALERT_EVENT_TYPES),
            ).count()
