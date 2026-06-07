"""
FarmBaselineService

Computes and persists farm-specific performance baselines from closed-batch
history, and serves them back to the recommendation engines. Once a farm has
at least one closed batch, its own learned averages replace the static breed
benchmark as the comparison target; new farms fall back to breed benchmarks.

Unit conventions (kept consistent across the codebase):
  - FCR uses biomass = current_count * latest avg_weight_kg, matching
    FeedEfficiencyService.compute_current_fcr so "vs your farm average" is a
    like-for-like comparison.
  - Mortality is a cumulative fraction per batch: total deaths / initial_count
    (e.g. 0.045 == 4.5%). The serialised dict also exposes an explicit
    *_pct value for display so templates never have to multiply.
"""

from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Sum

from apps.infrastructure.core.rls import set_tenant_context


# Max closed batches to fold into a baseline (recency bias — recent
# performance is more representative than ancient history).
MAX_BATCHES = 20


def _q(value, places: int):
    """Quantize a float to a Decimal with the given number of places, or None."""
    if value is None:
        return None
    return Decimal(str(value)).quantize(
        Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP
    )


def _safe_avg(values):
    return sum(values) / len(values) if values else None


class FarmBaselineService:
    """Computes, persists, and serves per-farm performance baselines."""

    def __init__(self, org):
        self.org = org

    # ── Compute / persist ──────────────────────────────────────────────────

    def compute_and_save(self, bird_type: str, breed_name: str = ""):
        """
        Recompute the baseline from this org's closed batches of the given
        bird_type/breed_name and upsert it into FarmBaseline.

        Returns the FarmBaseline instance, or None if there is no closed
        history to learn from.
        """
        from apps.farm.flocks.models import Batch, MortalityLog, WeightRecord
        from apps.production.feed.models import FeedLog
        from apps.production.water.models import WaterLog
        from apps.health.analytics.models import FarmBaseline

        breed_name = breed_name or ""

        with set_tenant_context(self.org):
            closed_batches = Batch.objects.filter(
                org=self.org,
                bird_type=bird_type,
                status="closed",
            )
            if breed_name:
                closed_batches = closed_batches.filter(breed_name__iexact=breed_name)

            # Most recent first, capped at MAX_BATCHES.
            closed_batches = list(
                closed_batches.order_by("-closed_at", "-placement_date")[:MAX_BATCHES]
            )

            batch_count = len(closed_batches)
            if batch_count == 0:
                return None

            fcr_values = []
            mortality_rates = []
            feed_per_bird_values = []
            water_per_bird_values = []
            daily_gain_values = []

            for batch in closed_batches:
                try:
                    total_feed = float(
                        FeedLog.objects.filter(batch=batch).aggregate(
                            total=Sum("quantity_kg")
                        )["total"] or 0
                    )

                    latest_weight = (
                        WeightRecord.objects.filter(batch=batch)
                        .order_by("-sample_date")
                        .first()
                    )
                    avg_weight_kg = (
                        float(latest_weight.avg_weight_kg)
                        if latest_weight and latest_weight.avg_weight_kg
                        else None
                    )

                    # FCR: feed / surviving biomass (same basis as live FCR).
                    if avg_weight_kg and total_feed > 0 and batch.current_count > 0:
                        biomass = avg_weight_kg * batch.current_count
                        if biomass > 0:
                            fcr_values.append(total_feed / biomass)

                    # Daily weight gain (g/day) over the cycle length.
                    if avg_weight_kg:
                        cycle_days = self._cycle_days(batch)
                        if cycle_days > 0:
                            daily_gain_values.append(avg_weight_kg * 1000 / cycle_days)

                    # Cumulative mortality fraction.
                    total_deaths = (
                        MortalityLog.objects.filter(batch=batch).aggregate(
                            total=Sum("count")
                        )["total"] or 0
                    )
                    if batch.initial_count > 0:
                        mortality_rates.append(total_deaths / batch.initial_count)

                    # Feed per placed bird (kg).
                    if total_feed > 0 and batch.initial_count > 0:
                        feed_per_bird_values.append(total_feed / batch.initial_count)

                    # Water per placed bird (litres).
                    total_water = float(
                        WaterLog.objects.filter(batch=batch).aggregate(
                            total=Sum("litres_consumed")
                        )["total"] or 0
                    )
                    if total_water > 0 and batch.initial_count > 0:
                        water_per_bird_values.append(total_water / batch.initial_count)
                except Exception:
                    continue  # skip corrupt/incomplete batches silently

            baseline, _ = FarmBaseline.objects.update_or_create(
                org=self.org,
                bird_type=bird_type,
                breed_name=breed_name,
                defaults={
                    "avg_fcr": _q(_safe_avg(fcr_values), 3),
                    "best_fcr": _q(min(fcr_values), 3) if fcr_values else None,
                    "worst_fcr": _q(max(fcr_values), 3) if fcr_values else None,
                    "avg_mortality_rate": _q(_safe_avg(mortality_rates), 3),
                    "best_mortality_rate": (
                        _q(min(mortality_rates), 3) if mortality_rates else None
                    ),
                    "worst_mortality_rate": (
                        _q(max(mortality_rates), 3) if mortality_rates else None
                    ),
                    "avg_feed_per_bird_kg": _q(_safe_avg(feed_per_bird_values), 3),
                    "avg_water_per_bird_l": _q(_safe_avg(water_per_bird_values), 3),
                    "avg_daily_gain_g": _q(_safe_avg(daily_gain_values), 2),
                    "batch_count": batch_count,
                },
            )
            return baseline

    @staticmethod
    def _cycle_days(batch) -> int:
        """Days from placement to close (falls back to today if not closed)."""
        end = batch.closed_at.date() if batch.closed_at else None
        if not end or not batch.placement_date:
            return 0
        return max((end - batch.placement_date).days, 0)

    # ── Read / serve ───────────────────────────────────────────────────────

    def get_baseline(self, bird_type: str, breed_name: str = ""):
        """Return the persisted FarmBaseline, or None if none exists yet."""
        from apps.health.analytics.models import FarmBaseline

        with set_tenant_context(self.org):
            try:
                return FarmBaseline.objects.get(
                    org=self.org,
                    bird_type=bird_type,
                    breed_name__iexact=breed_name or "",
                )
            except FarmBaseline.DoesNotExist:
                return None

    def get_baseline_or_benchmark(self, bird_type: str, breed_name: str = "") -> dict:
        """
        Return the farm baseline if there is real history (>=1 batch), else the
        static breed benchmark. Always returns the same dict shape so callers
        never branch on the source.

        Dict keys:
          source, confidence, confidence_label,
          avg_fcr, best_fcr, worst_fcr,
          avg_mortality_rate (fraction), avg_mortality_rate_pct (percent),
          avg_feed_per_bird_kg, batch_count
        """
        baseline = self.get_baseline(bird_type, breed_name)

        if baseline and baseline.batch_count >= 1 and baseline.avg_fcr is not None:
            mort = float(baseline.avg_mortality_rate or 0)
            return {
                "source": "farm_history",
                "confidence": baseline.confidence_level,
                "confidence_label": baseline.confidence_label,
                "avg_fcr": float(baseline.avg_fcr or 0),
                "best_fcr": float(baseline.best_fcr or baseline.avg_fcr or 0),
                "worst_fcr": float(baseline.worst_fcr or baseline.avg_fcr or 0),
                "avg_mortality_rate": mort,
                "avg_mortality_rate_pct": round(mort * 100, 2),
                "avg_feed_per_bird_kg": float(baseline.avg_feed_per_bird_kg or 0),
                "batch_count": baseline.batch_count,
            }

        # Fall back to the static breed benchmark.
        from apps.health.analytics.breed_benchmarks import get_benchmark

        benchmark = get_benchmark(breed_name, bird_type)
        target_fcr = benchmark.get("target_fcr", 1.8)
        mort_pct = benchmark.get("target_mortality_rate_pct", 5.0)
        mort_fraction = mort_pct / 100.0

        # Estimate total feed per bird from daily intake × cycle length.
        feed_day_g = benchmark.get("feed_per_bird_day_g")
        cycle_days = benchmark.get("optimal_slaughter_day")
        if feed_day_g and cycle_days:
            feed_per_bird_kg = feed_day_g * cycle_days / 1000.0
        else:
            feed_per_bird_kg = 4.5

        return {
            "source": "breed_benchmark",
            "confidence": "none",
            "confidence_label": (
                "No farm history yet — using breed benchmarks. "
                "Complete your first batch to unlock farm memory."
            ),
            "avg_fcr": target_fcr,
            "best_fcr": target_fcr,
            "worst_fcr": round(target_fcr * 1.2, 3),
            "avg_mortality_rate": mort_fraction,
            "avg_mortality_rate_pct": round(mort_pct, 2),
            "avg_feed_per_bird_kg": round(feed_per_bird_kg, 3),
            "batch_count": 0,
        }
