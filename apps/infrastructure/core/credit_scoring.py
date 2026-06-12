"""
Farm Credit Score engine.

Weights:
  Financial Health        30%  (profit margin consistency)
  Operational Consistency 20%  (daily data logging frequency)
  Mortality Management    20%  (mortality rate vs benchmark)
  Feed Efficiency         15%  (FCR vs benchmark; layers: neutral)
  Platform Engagement     10%  (subscription payment history)
  Payment History          5%  (plan tier commitment)
"""

import datetime

import structlog

logger = structlog.get_logger(__name__)


class CreditScoringService:
    WEIGHTS = {
        "financial_health": 0.30,
        "operational_consistency": 0.20,
        "mortality_management": 0.20,
        "feed_efficiency": 0.15,
        "platform_engagement": 0.10,
        "payment_history": 0.05,
    }

    def __init__(self, org):
        self.org = org

    # ── Public API ────────────────────────────────────────────────────────────

    def compute(self):
        """Compute and persist a new FarmCreditScore. Returns the instance or None."""
        from django.db.models import Sum
        from django.utils import timezone

        from apps.farm.flocks.models import Batch, MortalityLog, WeightRecord
        from apps.finance.finance.models import BatchFinancialSummary, FarmCreditScore
        from apps.production.feed.models import FeedLog

        all_closed = list(
            Batch.objects.filter(org=self.org, status="closed").order_by("-closed_at")
        )
        batch_count = len(all_closed)

        if batch_count == 0:
            return None

        closed_batches = all_closed[:12]

        if batch_count >= 6:
            confidence = "established"
        elif batch_count >= 3:
            confidence = "growing"
        else:
            confidence = "early"

        financial = self._score_financial_health(closed_batches)
        operational = self._score_operational_consistency(closed_batches)
        mortality = self._score_mortality_management(closed_batches)
        feed = self._score_feed_efficiency(closed_batches)
        engagement = self._score_platform_engagement()
        payment = self._score_payment_history()

        total = int(
            financial * self.WEIGHTS["financial_health"]
            + operational * self.WEIGHTS["operational_consistency"]
            + mortality * self.WEIGHTS["mortality_management"]
            + feed * self.WEIGHTS["feed_efficiency"]
            + engagement * self.WEIGHTS["platform_engagement"]
            + payment * self.WEIGHTS["payment_history"]
        )
        total = max(0, min(100, total))
        grade = self._score_to_grade(total)

        # Supporting snapshot stats
        mortality_rates = []
        fcr_list = []
        margin_list = []
        total_birds = 0

        for batch in closed_batches:
            total_birds += batch.initial_count

            if batch.initial_count > 0:
                deaths = (
                    MortalityLog.objects.filter(batch=batch)
                    .aggregate(total=Sum("count"))["total"] or 0
                )
                mortality_rates.append(deaths / batch.initial_count * 100)

            if batch.bird_type != "layer":
                feed_kg = (
                    FeedLog.objects.filter(batch=batch)
                    .aggregate(total=Sum("quantity_kg"))["total"] or 0
                )
                latest_w = (
                    WeightRecord.objects.filter(batch=batch)
                    .order_by("-sample_date")
                    .first()
                )
                # Surviving birds only — keep in sync with _score_feed_efficiency.
                if (
                    feed_kg
                    and latest_w
                    and float(latest_w.avg_weight_kg) > 0
                    and (batch.current_count or 0) > 0
                ):
                    weight_kg = float(latest_w.avg_weight_kg) * batch.current_count
                    fcr_list.append(float(feed_kg) / weight_kg)

            try:
                summary = BatchFinancialSummary.objects.get(batch=batch)
                margin_list.append(float(summary.profit_margin_pct))
            except BatchFinancialSummary.DoesNotExist:
                pass

        avg_mortality = (
            round(sum(mortality_rates) / len(mortality_rates), 2) if mortality_rates else None
        )
        avg_fcr = round(sum(fcr_list) / len(fcr_list), 3) if fcr_list else None
        avg_margin = round(sum(margin_list) / len(margin_list), 2) if margin_list else None

        months = max(1, (timezone.now() - self.org.created_at).days // 30)

        credit_score = FarmCreditScore.objects.create(
            org=self.org,
            score=total,
            grade=grade,
            confidence=confidence,
            financial_health_score=financial,
            operational_consistency_score=operational,
            mortality_management_score=mortality,
            feed_efficiency_score=feed,
            platform_engagement_score=engagement,
            payment_history_score=payment,
            batches_analysed=len(closed_batches),
            avg_profit_margin_pct=avg_margin,
            avg_mortality_rate_pct=avg_mortality,
            avg_fcr=avg_fcr,
            total_birds_managed=total_birds,
            months_on_platform=months,
        )

        logger.info(
            "credit_score.computed",
            org_id=str(self.org.id),
            score=total,
            grade=grade,
            confidence=confidence,
        )
        return credit_score

    @classmethod
    def get_latest(cls, org):
        """Most recent score for this org, or None."""
        from apps.finance.finance.models import FarmCreditScore

        return FarmCreditScore.objects.filter(org=org).order_by("-computed_at").first()

    @classmethod
    def get_or_compute(cls, org):
        """Return cached score if computed in last 24 h, else recompute."""
        from django.utils import timezone

        latest = cls.get_latest(org)
        if latest:
            age = timezone.now() - latest.computed_at
            if age < datetime.timedelta(hours=24):
                return latest
        return cls(org).compute()

    # ── Sub-scorers ───────────────────────────────────────────────────────────

    def _score_financial_health(self, batches) -> int:
        from apps.finance.finance.models import BatchFinancialSummary

        scores = []
        for batch in batches:
            try:
                summary = BatchFinancialSummary.objects.get(batch=batch)
                margin = float(summary.profit_margin_pct)
                if margin >= 30:
                    scores.append(100)
                elif margin >= 20:
                    scores.append(80)
                elif margin >= 10:
                    scores.append(60)
                elif margin >= 0:
                    scores.append(40)
                else:
                    scores.append(20)
            except BatchFinancialSummary.DoesNotExist:
                scores.append(50)
        return int(sum(scores) / len(scores)) if scores else 50

    def _score_operational_consistency(self, batches) -> int:
        from apps.farm.flocks.models import MortalityLog
        from apps.production.feed.models import FeedLog

        scores = []
        for batch in batches:
            if not batch.placement_date or not batch.closed_at:
                continue
            days = (batch.closed_at.date() - batch.placement_date).days
            if days <= 0:
                continue
            mort_logs = MortalityLog.objects.filter(batch=batch).count()
            feed_logs = FeedLog.objects.filter(batch=batch).count()
            expected = max(1, days // 7)
            mort_ratio = min(1.0, mort_logs / expected)
            feed_ratio = min(1.0, feed_logs / expected)
            scores.append(int((mort_ratio + feed_ratio) / 2 * 100))
        return int(sum(scores) / len(scores)) if scores else 50

    def _score_mortality_management(self, batches) -> int:
        from django.db.models import Sum

        from apps.farm.flocks.models import MortalityLog

        scores = []
        for batch in batches:
            if batch.initial_count <= 0:
                continue
            deaths = (
                MortalityLog.objects.filter(batch=batch)
                .aggregate(total=Sum("count"))["total"] or 0
            )
            rate = deaths / batch.initial_count * 100
            if rate < 2:
                scores.append(100)
            elif rate < 5:
                scores.append(80)
            elif rate < 10:
                scores.append(60)
            elif rate < 15:
                scores.append(40)
            else:
                scores.append(20)
        return int(sum(scores) / len(scores)) if scores else 50

    def _score_feed_efficiency(self, batches) -> int:
        from django.db.models import Sum

        from apps.farm.flocks.models import WeightRecord
        from apps.production.feed.models import FeedLog

        scores = []
        for batch in batches:
            if batch.bird_type == "layer":
                scores.append(70)
                continue
            feed_kg = (
                FeedLog.objects.filter(batch=batch)
                .aggregate(total=Sum("quantity_kg"))["total"] or 0
            )
            if not feed_kg:
                scores.append(50)
                continue
            latest_w = (
                WeightRecord.objects.filter(batch=batch).order_by("-sample_date").first()
            )
            if not latest_w or float(latest_w.avg_weight_kg) <= 0:
                scores.append(50)
                continue
            # FCR uses the SURVIVING bird count, not initial_count: a batch
            # with 20% mortality would otherwise overstate total weight by 25%,
            # understating FCR and making bad farms look better than they are.
            if (batch.current_count or 0) <= 0:
                scores.append(50)
                continue
            weight_kg = float(latest_w.avg_weight_kg) * batch.current_count
            fcr = float(feed_kg) / weight_kg
            if fcr <= 1.8:
                scores.append(100)
            elif fcr <= 2.0:
                scores.append(80)
            elif fcr <= 2.2:
                scores.append(60)
            elif fcr <= 2.5:
                scores.append(40)
            else:
                scores.append(20)
        return int(sum(scores) / len(scores)) if scores else 50

    def _score_platform_engagement(self) -> int:
        from django.utils import timezone

        from apps.infrastructure.billing.models import PaymentRecord

        months = max(1, (timezone.now() - self.org.created_at).days // 30)
        if months <= 1:
            return 80
        payments = PaymentRecord.objects.filter(org=self.org, status="success").count()
        return int(min(1.0, payments / months) * 100)

    def _score_payment_history(self) -> int:
        tier_scores = {
            "yearly": 100,
            "monthly": 80,
            "cycle": 70,
            "trial": 50,
        }
        return tier_scores.get(self.org.plan_tier, 60)

    @staticmethod
    def _score_to_grade(score: int) -> str:
        if score >= 90:
            return "A+"
        if score >= 80:
            return "A"
        if score >= 70:
            return "B"
        if score >= 60:
            return "C"
        if score >= 50:
            return "D"
        return "F"
