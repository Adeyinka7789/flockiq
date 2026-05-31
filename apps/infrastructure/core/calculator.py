"""
Poultry calculation engine.

Two public classes live here:

  BreedCalculator  — static-method API used by services for quick inline calculations.
                     All methods are pure functions; no DB access, no side effects.

  PoultryCalculator — breed-aware class that delegates to BreedStandard objects.
                      Returns structured dataclasses for richer dashboard data.
                      Used by ProphetForecastService, AnomalyDetectionService, and
                      the batch-close summary workflow.

Both classes are pure Python — safe to call from services, Celery tasks, and tests.
Never call them from views or models directly.
"""

from dataclasses import dataclass
from typing import Optional

from .breed_standards import BreedStandard, get_breed_standard


# ── BreedCalculator ─────────────────────────────────────────────────────────

class BreedCalculator:
    """
    Simple static-method calculator.
    All inputs and outputs are primitives (int / float).
    Called from services; never instantiated.
    """

    # Generic feed rates kg/bird/day keyed by week of age (broiler only)
    BROILER_FEED_RATE = {
        1: 0.025,
        2: 0.045,
        3: 0.075,
        4: 0.100,
        5: 0.120,
        6: 0.140,
    }
    LAYER_FEED_RATE_KG_PER_DAY = 0.125        # 125 g/bird/day (layer mash)
    WATER_RATE_LITRES_PER_200_BIRDS = 40.0    # Baseline: 200 birds = 40 L/day

    @staticmethod
    def daily_feed_requirement_kg(bird_count: int, age_days: int, breed: str) -> float:
        """
        Total kg of feed required today for the flock.
        breed: 'broiler' or 'layer'
        """
        if breed == "broiler":
            week = min((age_days // 7) + 1, 6)
            rate = BreedCalculator.BROILER_FEED_RATE.get(week, 0.140)
        else:
            rate = BreedCalculator.LAYER_FEED_RATE_KG_PER_DAY
        return round(bird_count * rate, 2)

    @staticmethod
    def daily_water_requirement_litres(bird_count: int) -> float:
        """200 birds = 40 L baseline. Scales linearly."""
        return round(
            (bird_count / 200) * BreedCalculator.WATER_RATE_LITRES_PER_200_BIRDS, 1
        )

    @staticmethod
    def hen_day_percentage(total_eggs: int, live_hen_count: int) -> float:
        """Egg production efficiency. 100 % means 1 egg per bird per day."""
        if live_hen_count == 0:
            return 0.0
        return round((total_eggs / live_hen_count) * 100, 2)

    @staticmethod
    def fcr(cumulative_feed_kg: float, cumulative_weight_gain_kg: float) -> float:
        """Feed Conversion Ratio. Lower is better. Target broiler: 1.8–2.0."""
        if cumulative_weight_gain_kg == 0:
            return 0.0
        return round(cumulative_feed_kg / cumulative_weight_gain_kg, 3)

    @staticmethod
    def mortality_rate(cumulative_deaths: int, initial_count: int) -> float:
        """Cumulative mortality % since batch placement."""
        if initial_count == 0:
            return 0.0
        return round((cumulative_deaths / initial_count) * 100, 2)

    @staticmethod
    def break_even_quantity(total_expenses_kobo: int, unit_sale_price_kobo: int) -> int:
        """
        Minimum units to sell to recover all expenses.
        All values in kobo (integers). Uses ceiling division.
        """
        if unit_sale_price_kobo == 0:
            return 0
        return -(-total_expenses_kobo // unit_sale_price_kobo)  # ceiling division

    @staticmethod
    def crates(total_eggs: int) -> float:
        """Standard Nigerian egg crate = 30 eggs."""
        return round(total_eggs / 30, 1)

    @staticmethod
    def cycle_day(placement_date) -> int:
        """Days elapsed since batch placement. Day 0 = placement date."""
        from django.utils import timezone
        return (timezone.now().date() - placement_date).days


# ── PoultryCalculator dataclasses ────────────────────────────────────────────

@dataclass
class FCRResult:
    fcr: float
    target_fcr: float
    variance: float           # Positive = worse than target
    performance_pct: float    # > 100 = better than target
    rating: str               # "excellent" | "good" | "acceptable" | "poor"


@dataclass
class HenDayResult:
    hen_day_pct: float
    target_pct: float
    variance: float
    rating: str


@dataclass
class MortalityResult:
    cumulative_mortality_pct: float
    weekly_mortality_pct: float
    is_above_threshold: bool
    threshold_pct: float
    alert_required: bool


@dataclass
class WaterRequirement:
    base_litres: float
    heat_adjusted_litres: float   # Adjusted for ambient temperature
    temperature_used: float


@dataclass
class FeedRequirement:
    grams_per_bird: float
    total_kg: float
    week_of_age: int
    is_interpolated: bool         # True if week exceeds the breed table


# ── PoultryCalculator ────────────────────────────────────────────────────────

class PoultryCalculator:
    """
    Breed-aware calculator. Returns structured dataclasses for dashboard display.
    Instantiate with a bird_type_code from breed_standards.BREED_STANDARDS.

    Usage:
        calc = PoultryCalculator("broiler_cobb500")
        fcr  = calc.fcr(cumulative_feed_kg=850, cumulative_weight_gain_kg=480)
        water = calc.daily_water_requirement(bird_count=5000, ambient_temp_c=32)
    """

    def __init__(self, bird_type_code: str):
        self.bird_type_code = bird_type_code
        self.standard: BreedStandard = get_breed_standard(bird_type_code)

    def fcr(self, cumulative_feed_kg: float, cumulative_weight_gain_kg: float) -> FCRResult:
        if cumulative_weight_gain_kg <= 0:
            raise ValueError("Weight gain must be > 0 to calculate FCR")
        value = round(cumulative_feed_kg / cumulative_weight_gain_kg, 3)
        target = self.standard.target_fcr_at_close
        variance = round(value - target, 3)
        performance_pct = round((target / value) * 100, 1) if value > 0 else 0
        if value <= target * 0.95:
            rating = "excellent"
        elif value <= target:
            rating = "good"
        elif value <= target * 1.10:
            rating = "acceptable"
        else:
            rating = "poor"
        return FCRResult(value, target, variance, performance_pct, rating)

    def hen_day_pct(self, total_eggs: int, live_hen_count: int) -> HenDayResult:
        if self.standard.bird_type != "layer":
            raise ValueError(f"Hen-day % not applicable for bird_type={self.standard.bird_type}")
        if live_hen_count <= 0:
            raise ValueError("live_hen_count must be > 0")
        hdp = round((total_eggs / live_hen_count) * 100, 2)
        target = self.standard.target_hen_day_pct
        variance = round(hdp - target, 2)
        if hdp >= target * 1.05:
            rating = "excellent"
        elif hdp >= target:
            rating = "good"
        elif hdp >= target * 0.90:
            rating = "acceptable"
        else:
            rating = "poor"
        return HenDayResult(hdp, target, variance, rating)

    def mortality_assessment(
        self,
        initial_count: int,
        cumulative_deaths: int,
        deaths_this_week: int,
    ) -> MortalityResult:
        cumulative_pct = round((cumulative_deaths / initial_count) * 100, 3) if initial_count else 0
        weekly_pct = round((deaths_this_week / initial_count) * 100, 3) if initial_count else 0
        threshold = self.standard.acceptable_mortality_pct_weekly
        above = weekly_pct > threshold
        return MortalityResult(
            cumulative_mortality_pct=cumulative_pct,
            weekly_mortality_pct=weekly_pct,
            is_above_threshold=above,
            threshold_pct=threshold,
            alert_required=above,
        )

    def daily_water_requirement(
        self,
        bird_count: int,
        ambient_temp_c: float = 25.0,
    ) -> WaterRequirement:
        base_ml = self.standard.water_ml_per_bird_per_day * bird_count
        # Industry standard: +10 % per degree above 25 °C
        heat_factor = max(0, (ambient_temp_c - 25) * 0.10)
        adjusted_ml = base_ml * (1 + heat_factor)
        return WaterRequirement(
            base_litres=round(base_ml / 1000, 2),
            heat_adjusted_litres=round(adjusted_ml / 1000, 2),
            temperature_used=ambient_temp_c,
        )

    def daily_feed_requirement(self, bird_count: int, age_days: int) -> FeedRequirement:
        week = (age_days // 7) + 1
        rates = self.standard.feed_rates
        if week <= len(rates):
            rate = rates[week - 1].grams_per_bird_per_day
            interpolated = False
        else:
            rate = rates[-1].grams_per_bird_per_day
            interpolated = True
        total_g = rate * bird_count
        return FeedRequirement(
            grams_per_bird=rate,
            total_kg=round(total_g / 1000, 3),
            week_of_age=week,
            is_interpolated=interpolated,
        )

    def batch_performance_summary(
        self,
        initial_count: int,
        final_count: int,
        total_feed_kg: float,
        total_weight_gain_kg: float,
        total_eggs: Optional[int],
        total_days: int,
    ) -> dict:
        """Full performance summary for a closed batch."""
        result = {
            "bird_type": self.standard.bird_type,
            "breed": self.standard.name,
            "total_days": total_days,
            "initial_count": initial_count,
            "final_count": final_count,
        }
        deaths = initial_count - final_count
        mort = self.mortality_assessment(initial_count, deaths, 0)
        result["cumulative_mortality_pct"] = mort.cumulative_mortality_pct

        if total_weight_gain_kg > 0:
            result["fcr"] = self.fcr(total_feed_kg, total_weight_gain_kg).__dict__

        if self.standard.bird_type == "layer" and total_eggs and final_count > 0:
            avg_live = (initial_count + final_count) / 2
            hdp = self.hen_day_pct(total_eggs // total_days, int(avg_live))
            result["hen_day_pct"] = hdp.__dict__

        return result
