import datetime
from decimal import Decimal

import structlog
import waffle

from apps.infrastructure.core.rls import assert_tenant_context
from apps.infrastructure.core.services import BaseService

logger = structlog.get_logger(__name__)

UNAVAILABLE_FLAG_OFF = {"available": False, "reason": "Feature not enabled"}


class ProphetForecastService(BaseService):
    """Egg production forecasting using Facebook Prophet."""

    FLAG = "ai_egg_forecast"
    MIN_RECORDS = 7
    FORECAST_DAYS = 30

    def forecast_egg_production(self, batch, days=30) -> dict:
        if not waffle.switch_is_active(self.FLAG):
            return UNAVAILABLE_FLAG_OFF

        from apps.production.production.models import EggProductionLog
        from .models import ForecastResult

        cutoff = datetime.date.today() - datetime.timedelta(days=60)
        records = list(
            EggProductionLog.objects.filter(batch=batch, org=self.org, record_date__gte=cutoff)
            .order_by("record_date")
            .values("record_date", "hen_day_pct")
        )

        if len(records) < self.MIN_RECORDS:
            return {"available": False, "reason": f"Insufficient data (need {self.MIN_RECORDS}+ days)"}

        try:
            import pandas as pd
            from prophet import Prophet
        except ImportError:
            return {"available": False, "reason": "Forecasting engine not installed"}

        df = pd.DataFrame(records)
        df = df.rename(columns={"record_date": "ds", "hen_day_pct": "y"})
        df["ds"] = pd.to_datetime(df["ds"])
        df["y"] = df["y"].astype(float)

        try:
            model = Prophet(
                yearly_seasonality=False,
                weekly_seasonality=True,
                daily_seasonality=False,
                changepoint_prior_scale=0.05,
                interval_width=0.80,
            )
            model.fit(df[["ds", "y"]])
            future = model.make_future_dataframe(periods=days)
            forecast = model.predict(future)
            future_rows = forecast[forecast["ds"] > df["ds"].max()][
                ["ds", "yhat", "yhat_lower", "yhat_upper"]
            ]
        except Exception as exc:
            self.logger.error("Prophet forecast failed", batch_id=str(batch.id), error=str(exc))
            return {"available": False, "reason": "Forecast failed — check data quality"}

        labels = [row["ds"].date().isoformat() for _, row in future_rows.iterrows()]
        predicted = [round(max(0.0, float(row["yhat"])), 2) for _, row in future_rows.iterrows()]
        lower = [round(max(0.0, float(row["yhat_lower"])), 2) for _, row in future_rows.iterrows()]
        upper = [round(min(100.0, float(row["yhat_upper"])), 2) for _, row in future_rows.iterrows()]

        ForecastResult.objects.filter(
            org=self.org, batch=batch, forecast_type="egg"
        ).delete()

        from django.utils import timezone

        ForecastResult.objects.bulk_create([
            ForecastResult(
                org=self.org,
                batch=batch,
                forecast_type="egg",
                forecast_date=datetime.date.fromisoformat(labels[i]),
                predicted_value=Decimal(str(predicted[i])),
                confidence_lower=Decimal(str(lower[i])),
                confidence_upper=Decimal(str(upper[i])),
            )
            for i in range(len(labels))
        ])

        return {
            "available": True,
            "labels": labels,
            "predicted": predicted,
            "lower": lower,
            "upper": upper,
            "generated_at": timezone.now().isoformat(),
        }


class AnomalyDetectionService(BaseService):
    """Z-score anomaly detection for mortality and water consumption."""

    FLAG = "ai_anomaly_detection"
    LOOKBACK_DAYS = 14
    MIN_RECORDS = 5
    Z_THRESHOLD = 2.5

    def check_mortality_anomaly(self, batch) -> dict:
        if not waffle.switch_is_active(self.FLAG):
            return UNAVAILABLE_FLAG_OFF
        assert_tenant_context()

        from apps.farm.flocks.models import MortalityLog

        cutoff = datetime.date.today() - datetime.timedelta(days=self.LOOKBACK_DAYS)
        counts = list(
            MortalityLog.objects.filter(batch=batch, org=self.org, date__gte=cutoff)
            .order_by("date")
            .values_list("count", flat=True)
        )

        if len(counts) < self.MIN_RECORDS:
            return {"available": False, "reason": "Insufficient data"}

        return self._run_zscore_check(
            batch=batch,
            values=counts,
            anomaly_type="mortality_spike",
            metric_label="mortality count",
        )

    def check_water_anomaly(self, batch) -> dict:
        if not waffle.switch_is_active(self.FLAG):
            return UNAVAILABLE_FLAG_OFF

        from apps.production.water.models import WaterLog

        cutoff = datetime.date.today() - datetime.timedelta(days=self.LOOKBACK_DAYS)
        values = list(
            WaterLog.objects.filter(batch=batch, org=self.org, record_date__gte=cutoff)
            .order_by("record_date")
            .values_list("litres_consumed", flat=True)
        )

        if len(values) < self.MIN_RECORDS:
            return {"available": False, "reason": "Insufficient data"}

        float_values = [float(v) for v in values]
        return self._run_zscore_check(
            batch=batch,
            values=float_values,
            anomaly_type="water_drop",
            metric_label="water consumption",
            invert=True,
        )

    def _run_zscore_check(self, batch, values, anomaly_type, metric_label, invert=False) -> dict:
        import statistics

        mean = statistics.mean(values)
        stdev = statistics.stdev(values) if len(values) > 1 else 0.0
        latest = values[-1]

        if stdev == 0:
            z_score = 0.0
        elif invert:
            z_score = (mean - latest) / stdev
        else:
            z_score = (latest - mean) / stdev

        anomaly_detected = z_score > self.Z_THRESHOLD

        if anomaly_detected:
            severity = "critical" if z_score > 3.5 else "warning"
            description = (
                f"Unusual {metric_label} detected. "
                f"Latest: {latest:.1f}, mean: {mean:.1f}, z-score: {z_score:.2f}"
            )
            from .models import AnomalyRecord
            from django.db import transaction
            from apps.infrastructure.notifications.services import NotificationService

            with transaction.atomic():
                record = AnomalyRecord.objects.create(
                    org=self.org,
                    batch=batch,
                    anomaly_type=anomaly_type,
                    severity=severity,
                    z_score=Decimal(str(round(z_score, 3))),
                    description=description,
                )
                manager = self._get_manager()
                if manager:
                    NotificationService(self.org).send(
                        anomaly_type,
                        context={
                            "batch_name": str(batch),
                            "description": description,
                        },
                        severity="critical" if z_score > 3.5 else "warning",
                        batch=batch,
                    )
        else:
            description = f"{metric_label} is within normal range (z-score: {z_score:.2f})"

        return {
            "anomaly_detected": anomaly_detected,
            "z_score": round(z_score, 3),
            "description": description,
            "severity": "critical" if z_score > 3.5 else ("warning" if anomaly_detected else "info"),
        }

    def get_active_anomalies(self, batch_id=None):
        from .models import AnomalyRecord

        qs = AnomalyRecord.objects.filter(org=self.org, resolved=False)
        if batch_id:
            qs = qs.filter(batch_id=batch_id)
        return qs.order_by("-detected_at")

    def resolve_anomaly(self, anomaly_id, note=""):
        from .models import AnomalyRecord
        from django.utils import timezone

        record = AnomalyRecord.objects.get(id=anomaly_id, org=self.org)
        record.resolved = True
        record.resolved_at = timezone.now()
        record.save(update_fields=["resolved", "resolved_at"])
        return record

    def _get_manager(self):
        from apps.infrastructure.accounts.models import CustomUser

        return CustomUser.tenant_objects.first()


class TheftDetectionService(BaseService):
    """Bird count reconciliation to detect potential theft."""

    FLAG = "ai_theft_detection"
    VARIANCE_THRESHOLD_PCT = 1.5

    def reconcile_batch(self, batch) -> dict:
        if not waffle.switch_is_active(self.FLAG):
            return UNAVAILABLE_FLAG_OFF

        from apps.farm.flocks.models import MortalityLog
        from django.db.models import Sum

        total_mortality = (
            MortalityLog.objects.filter(batch=batch, org=self.org)
            .aggregate(total=Sum("count"))["total"]
            or 0
        )

        # Finance Phase 5 stub — use 0 until SalesRecord exists
        total_sold = self._get_total_sold(batch)

        initial_count = batch.initial_count
        current_count = batch.current_count
        accounted = total_mortality + total_sold + current_count
        unaccounted = initial_count - accounted
        variance_pct = (unaccounted / initial_count * 100) if initial_count else 0.0

        result = {
            "initial_count": initial_count,
            "total_mortality": total_mortality,
            "total_sold": total_sold,
            "current_count": current_count,
            "accounted": accounted,
            "unaccounted": unaccounted,
            "variance_pct": round(variance_pct, 2),
            "flagged": False,
        }

        if variance_pct > self.VARIANCE_THRESHOLD_PCT:
            result["flagged"] = True
            self._create_flag(batch, result)

        return result

    def _get_total_sold(self, batch) -> int:
        try:
            from apps.finance.finance.models import SaleRecord
            from django.db.models import Sum

            total = (
                SaleRecord.objects.filter(batch=batch, org=self.org)
                .aggregate(total=Sum("quantity"))["total"]
                or 0
            )
            return int(total)
        except Exception:
            return 0

    def _create_flag(self, batch, result):
        from .models import TheftFlag
        from apps.infrastructure.notifications.services import NotificationService
        from django.db import transaction

        with transaction.atomic():
            flag = TheftFlag.objects.create(
                org=self.org,
                batch=batch,
                unaccounted_birds=result["unaccounted"],
                variance_pct=Decimal(str(result["variance_pct"])),
                initial_count=result["initial_count"],
                total_mortality=result["total_mortality"],
                total_sold=result["total_sold"],
                current_count=result["current_count"],
            )
            manager = self._get_manager()
            if manager:
                NotificationService(self.org).send(
                    "theft_suspected",
                    context={
                        "batch_name": str(batch),
                        "unaccounted": result["unaccounted"],
                        "variance_pct": f"{result['variance_pct']:.1f}",
                    },
                    severity="critical",
                    batch=batch,
                )

    def _get_manager(self):
        from apps.infrastructure.accounts.models import CustomUser

        return CustomUser.tenant_objects.first()


class SaleTimingService(BaseService):
    """Optimal sale timing recommendation for broiler batches."""

    FLAG = "ai_sale_timing"

    def get_recommendation(self, batch) -> dict:
        if not waffle.switch_is_active(self.FLAG):
            return UNAVAILABLE_FLAG_OFF

        if batch.bird_type != "broiler":
            return {"available": False, "reason": "Sale timing is only applicable to broiler batches"}

        cycle_day = batch.cycle_day
        estimated_weight_kg = self._get_latest_weight(batch)
        daily_holding_cost_kobo = self._get_daily_holding_cost(batch)

        if cycle_day < 38:
            days_until = 38 - cycle_day
            urgency = "wait"
            recommended_date = datetime.date.today() + datetime.timedelta(days=days_until)
            message = (
                f"Batch is {cycle_day} days old. Optimal sale window starts at day 38. "
                f"Wait {days_until} more days."
            )
        elif 38 <= cycle_day <= 42:
            urgency = "now"
            recommended_date = datetime.date.today()
            message = (
                f"Batch is {cycle_day} days old — prime sale window (days 38–42). "
                "Sell now for best FCR and profitability."
            )
        else:
            days_over = cycle_day - 42
            urgency = "urgent"
            recommended_date = datetime.date.today()
            message = (
                f"Batch is {cycle_day} days old ({days_over} days past optimal window). "
                "Every additional day increases feed cost and reduces margin. Sell urgently."
            )

        from .models import SaleTimingRecommendation

        rec = SaleTimingRecommendation.objects.create(
            org=self.org,
            batch=batch,
            recommended_sale_date=recommended_date,
            urgency=urgency,
            estimated_weight_kg=(
                Decimal(str(estimated_weight_kg)) if estimated_weight_kg else None
            ),
            daily_holding_cost_kobo=daily_holding_cost_kobo,
            message=message,
        )

        return {
            "available": True,
            "urgency": urgency,
            "cycle_day": cycle_day,
            "recommended_sale_date": recommended_date.isoformat(),
            "estimated_weight_kg": float(estimated_weight_kg) if estimated_weight_kg else None,
            "daily_holding_cost_kobo": daily_holding_cost_kobo,
            "message": message,
            "recommendation_id": str(rec.id),
        }

    def _get_latest_weight(self, batch):
        from apps.farm.flocks.models import WeightRecord

        record = (
            WeightRecord.objects.filter(batch=batch, org=self.org)
            .order_by("-sample_date")
            .first()
        )
        return float(record.avg_weight_kg) if record else None

    def _get_daily_holding_cost(self, batch) -> int | None:
        from apps.production.feed.models import FeedLog
        from django.db.models import Avg

        avg = (
            FeedLog.objects.filter(batch=batch, org=self.org)
            .aggregate(avg_kg=Avg("quantity_kg"), avg_cost=Avg("cost_per_kg"))
        )
        avg_kg = avg["avg_kg"]
        avg_cost = avg["avg_cost"]
        if avg_kg and avg_cost:
            return int(float(avg_kg) * float(avg_cost) * 100)
        return None


DISEASE_RULES = {
    frozenset(["lethargy", "reduced_feed", "nasal_discharge", "sneezing"]): (
        "Newcastle Disease",
        "critical",
        "Isolate affected birds immediately. Contact vet. No treatment — vaccination is prevention.",
    ),
    frozenset(["lethargy", "swollen_head", "nasal_discharge"]): (
        "Infectious Coryza",
        "warning",
        "Sulphonamides or tetracyclines. Improve ventilation.",
    ),
    frozenset(["lethargy", "bloody_droppings", "reduced_feed"]): (
        "Coccidiosis",
        "warning",
        "Amprolium or Toltrazuril in drinking water for 3-5 days.",
    ),
    frozenset(["swollen_joints", "lameness", "lethargy"]): (
        "Marek's Disease",
        "critical",
        "No treatment. Cull affected birds. Ensure vaccination at day 1.",
    ),
    frozenset(["reduced_water", "lethargy", "pale_comb"]): (
        "Anaemia / Nutritional deficiency",
        "info",
        "Check feed quality. Add vitamin/mineral supplement.",
    ),
    frozenset(["reduced_feed", "increased_mortality", "respiratory_distress"]): (
        "Infectious Bronchitis",
        "critical",
        "Supportive care. Broad-spectrum antibiotics to prevent secondary infection.",
    ),
    frozenset(["diarrhoea", "lethargy", "reduced_feed"]): (
        "Salmonellosis",
        "warning",
        "Enrofloxacin or amoxicillin. Improve biosecurity.",
    ),
    frozenset(["swollen_hock", "lameness"]): (
        "Staphylococcal arthritis",
        "warning",
        "Penicillin or amoxicillin. Improve litter management.",
    ),
}


class DiagnosisEngine(BaseService):
    """Rule-based symptom-to-disease diagnosis for poultry."""

    FLAG = "ai_symptom_diagnosis"
    CONFIDENCE_THRESHOLD = 0.6

    def diagnose(self, symptom_list: list, batch=None) -> dict:
        if not waffle.switch_is_active(self.FLAG):
            return UNAVAILABLE_FLAG_OFF
        assert_tenant_context()

        symptom_set = frozenset(symptom_list)

        best_match = None
        best_score = 0.0
        best_rule = None

        for rule_symptoms, disease_info in DISEASE_RULES.items():
            if not rule_symptoms:
                continue
            overlap = len(symptom_set & rule_symptoms)
            score = overlap / len(rule_symptoms)
            if score > best_score:
                best_score = score
                best_match = disease_info
                best_rule = rule_symptoms

        if best_match and best_score >= self.CONFIDENCE_THRESHOLD:
            disease, severity, treatment = best_match
            confidence_pct = round(best_score * 100)

            if batch:
                self._update_symptom_log(batch, symptom_list, disease)

            return {
                "available": True,
                "diagnosis": disease,
                "severity": severity,
                "treatment": treatment,
                "confidence_pct": confidence_pct,
                "matched_symptoms": sorted(best_rule & symptom_set),
            }

        if batch:
            self._update_symptom_log(batch, symptom_list, "Unclassified")

        return {
            "available": True,
            "diagnosis": "Unclassified",
            "recommendation": "Contact a veterinarian",
            "severity": "info",
            "confidence_pct": 0,
        }

    def _update_symptom_log(self, batch, symptom_list, diagnosis):
        from apps.health.health.models import SymptomLog

        log = (
            SymptomLog.objects.filter(batch=batch, org=self.org)
            .order_by("-record_date")
            .first()
        )
        if log:
            log.diagnosis_result = diagnosis[:300]
            log.save(update_fields=["diagnosis_result"])
