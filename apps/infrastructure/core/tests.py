import pytest

from apps.infrastructure.core.calculator import BreedCalculator


class TestBreedCalculator:
    """
    Unit tests for BreedCalculator static methods.
    No DB required — pure Python calculations.
    """

    def test_broiler_feed_week_1(self):
        result = BreedCalculator.daily_feed_requirement_kg(200, 3, "broiler")
        assert result == round(200 * 0.025, 2)

    def test_broiler_feed_week_6(self):
        result = BreedCalculator.daily_feed_requirement_kg(200, 40, "broiler")
        assert result == round(200 * 0.140, 2)

    def test_layer_feed(self):
        result = BreedCalculator.daily_feed_requirement_kg(200, 120, "layer")
        assert result == round(200 * 0.125, 2)

    def test_water_200_birds(self):
        assert BreedCalculator.daily_water_requirement_litres(200) == 40.0

    def test_water_scales_linearly(self):
        assert BreedCalculator.daily_water_requirement_litres(400) == 80.0

    def test_hen_day_pct_at_peak(self):
        assert BreedCalculator.hen_day_percentage(190, 200) == 95.0

    def test_hen_day_pct_zero_hens(self):
        assert BreedCalculator.hen_day_percentage(0, 0) == 0.0

    def test_fcr_target(self):
        assert BreedCalculator.fcr(180, 100) == 1.8

    def test_mortality_rate(self):
        assert BreedCalculator.mortality_rate(10, 200) == 5.0

    def test_break_even_ceiling(self):
        # 1,050,000 kobo expenses / 500,000 kobo per unit = 2.1 → ceiling = 3 units
        assert BreedCalculator.break_even_quantity(1_050_000, 500_000) == 3

    def test_crates(self):
        assert BreedCalculator.crates(300) == 10.0
