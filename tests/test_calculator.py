"""
Unit tests for the pure-function calculator engine.
No DB access needed — all methods are stateless.
"""
import pytest
from apps.infrastructure.core.calculator import BreedCalculator, PoultryCalculator


class TestBreedCalculatorFeed:

    def test_broiler_week_1_feed(self):
        result = BreedCalculator.daily_feed_requirement_kg(1000, age_days=3, breed="broiler")
        assert result == pytest.approx(25.0, abs=0.01)

    def test_broiler_week_2_feed(self):
        result = BreedCalculator.daily_feed_requirement_kg(1000, age_days=10, breed="broiler")
        assert result == pytest.approx(45.0, abs=0.01)

    def test_broiler_week_3_feed(self):
        result = BreedCalculator.daily_feed_requirement_kg(1000, age_days=17, breed="broiler")
        assert result == pytest.approx(75.0, abs=0.01)

    def test_broiler_week_4_feed(self):
        result = BreedCalculator.daily_feed_requirement_kg(1000, age_days=24, breed="broiler")
        assert result == pytest.approx(100.0, abs=0.01)

    def test_broiler_week_5_feed(self):
        result = BreedCalculator.daily_feed_requirement_kg(1000, age_days=31, breed="broiler")
        assert result == pytest.approx(120.0, abs=0.01)

    def test_broiler_week_6_plus_clamped(self):
        result = BreedCalculator.daily_feed_requirement_kg(1000, age_days=45, breed="broiler")
        assert result == pytest.approx(140.0, abs=0.01)

    def test_layer_uses_fixed_rate(self):
        result = BreedCalculator.daily_feed_requirement_kg(200, age_days=100, breed="layer")
        assert result == pytest.approx(25.0, abs=0.01)

    def test_layer_zero_birds(self):
        result = BreedCalculator.daily_feed_requirement_kg(0, age_days=10, breed="layer")
        assert result == 0.0


class TestBreedCalculatorWater:

    def test_water_baseline_200_birds(self):
        result = BreedCalculator.daily_water_requirement_litres(200)
        assert result == pytest.approx(40.0, abs=0.1)

    def test_water_1000_birds(self):
        result = BreedCalculator.daily_water_requirement_litres(1000)
        assert result == pytest.approx(200.0, abs=0.1)

    def test_water_zero_birds(self):
        result = BreedCalculator.daily_water_requirement_litres(0)
        assert result == 0.0


class TestBreedCalculatorHenDay:

    def test_hen_day_perfect(self):
        result = BreedCalculator.hen_day_percentage(100, 100)
        assert result == 100.0

    def test_hen_day_below_perfect(self):
        result = BreedCalculator.hen_day_percentage(80, 100)
        assert result == 80.0

    def test_hen_day_zero_hens(self):
        result = BreedCalculator.hen_day_percentage(50, 0)
        assert result == 0.0


class TestBreedCalculatorFCR:

    def test_fcr_normal(self):
        result = BreedCalculator.fcr(1800.0, 1000.0)
        assert result == pytest.approx(1.8, abs=0.001)

    def test_fcr_zero_weight_gain(self):
        result = BreedCalculator.fcr(1000.0, 0.0)
        assert result == 0.0


class TestBreedCalculatorMortality:

    def test_mortality_rate_normal(self):
        result = BreedCalculator.mortality_rate(50, 1000)
        assert result == pytest.approx(5.0, abs=0.01)

    def test_mortality_rate_zero_initial(self):
        result = BreedCalculator.mortality_rate(5, 0)
        assert result == 0.0

    def test_mortality_rate_zero_deaths(self):
        result = BreedCalculator.mortality_rate(0, 1000)
        assert result == 0.0


class TestBreedCalculatorBreakEven:

    def test_break_even_normal(self):
        result = BreedCalculator.break_even_quantity(100000, 500)
        assert result == 200

    def test_break_even_zero_price(self):
        result = BreedCalculator.break_even_quantity(100000, 0)
        assert result == 0

    def test_break_even_ceiling_division(self):
        result = BreedCalculator.break_even_quantity(10001, 100)
        assert result == 101


class TestBreedCalculatorCrates:

    def test_crates_full(self):
        assert BreedCalculator.crates(300) == 10.0

    def test_crates_partial(self):
        assert BreedCalculator.crates(45) == 1.5

    def test_crates_zero(self):
        assert BreedCalculator.crates(0) == 0.0


class TestBreedCalculatorCycleDay:
    @pytest.mark.django_db
    def test_cycle_day_today(self):
        from django.utils import timezone
        today = timezone.now().date()
        result = BreedCalculator.cycle_day(today)
        assert result == 0

    @pytest.mark.django_db
    def test_cycle_day_5_days_ago(self):
        from django.utils import timezone
        import datetime
        placement = timezone.now().date() - datetime.timedelta(days=5)
        result = BreedCalculator.cycle_day(placement)
        assert result == 5


class TestPoultryCalculatorFCR:

    def test_fcr_excellent_rating(self):
        calc = PoultryCalculator("broiler_cobb500")
        result = calc.fcr(cumulative_feed_kg=1500, cumulative_weight_gain_kg=1000)
        assert result.fcr == pytest.approx(1.5, abs=0.01)
        assert result.rating in ("excellent", "good")

    def test_fcr_poor_rating(self):
        calc = PoultryCalculator("broiler_cobb500")
        result = calc.fcr(cumulative_feed_kg=3000, cumulative_weight_gain_kg=1000)
        assert result.rating == "poor"

    def test_fcr_zero_weight_raises(self):
        calc = PoultryCalculator("broiler_cobb500")
        with pytest.raises(ValueError, match="Weight gain"):
            calc.fcr(cumulative_feed_kg=1000, cumulative_weight_gain_kg=0)

    def test_fcr_variance_calculated(self):
        calc = PoultryCalculator("broiler_cobb500")
        result = calc.fcr(cumulative_feed_kg=2000, cumulative_weight_gain_kg=1000)
        assert result.variance == pytest.approx(result.fcr - result.target_fcr, abs=0.001)


class TestPoultryCalculatorHenDay:

    def test_hen_day_excellent(self):
        calc = PoultryCalculator("layer_isa_brown")
        result = calc.hen_day_pct(total_eggs=90, live_hen_count=90)
        assert result.hen_day_pct == 100.0
        assert result.rating in ("excellent",)

    def test_hen_day_not_applicable_for_broiler(self):
        calc = PoultryCalculator("broiler_cobb500")
        with pytest.raises(ValueError, match="not applicable"):
            calc.hen_day_pct(total_eggs=100, live_hen_count=100)

    def test_hen_day_zero_hens_raises(self):
        calc = PoultryCalculator("layer_isa_brown")
        with pytest.raises(ValueError, match="live_hen_count"):
            calc.hen_day_pct(total_eggs=100, live_hen_count=0)


class TestPoultryCalculatorMortality:

    def test_mortality_no_alert_below_threshold(self):
        calc = PoultryCalculator("broiler_cobb500")
        result = calc.mortality_assessment(
            initial_count=1000,
            cumulative_deaths=5,
            deaths_this_week=1,
        )
        assert result.cumulative_mortality_pct == pytest.approx(0.5, abs=0.01)
        assert isinstance(result.alert_required, bool)

    def test_mortality_alert_above_threshold(self):
        calc = PoultryCalculator("broiler_cobb500")
        result = calc.mortality_assessment(
            initial_count=1000,
            cumulative_deaths=100,
            deaths_this_week=80,
        )
        assert result.alert_required is True


class TestPoultryCalculatorWater:

    def test_water_no_heat_adjustment_at_25c(self):
        calc = PoultryCalculator("broiler_cobb500")
        result = calc.daily_water_requirement(bird_count=200, ambient_temp_c=25)
        assert result.base_litres == pytest.approx(40.0, abs=0.1)

    def test_water_higher_at_hot_temp(self):
        calc = PoultryCalculator("broiler_cobb500")
        cool = calc.daily_water_requirement(bird_count=200, ambient_temp_c=25)
        hot = calc.daily_water_requirement(bird_count=200, ambient_temp_c=35)
        assert hot.heat_adjusted_litres >= cool.heat_adjusted_litres


class TestPoultryCalculatorFeed:

    def test_feed_requirement_returns_dataclass(self):
        calc = PoultryCalculator("broiler_cobb500")
        result = calc.daily_feed_requirement(bird_count=1000, age_days=14)
        assert result.total_kg > 0
        assert result.grams_per_bird > 0

    def test_layer_feed_requirement(self):
        calc = PoultryCalculator("layer_isa_brown")
        result = calc.daily_feed_requirement(bird_count=500, age_days=100)
        assert result.total_kg > 0
