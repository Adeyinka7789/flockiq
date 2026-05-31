"""
Breed performance standards registry.

Standards sourced from Cobb, Ross, and Hy-Line breed guides (2024 editions).
Update this registry when new breeds or updated performance targets are adopted.
Do NOT scatter breed-specific numbers elsewhere in the codebase — all constants
live here and are referenced through get_breed_standard().
"""

from dataclasses import dataclass
from typing import Dict, List


@dataclass(frozen=True)
class WeeklyFeedRate:
    week: int
    grams_per_bird_per_day: float


@dataclass(frozen=True)
class BreedStandard:
    name: str
    bird_type: str                          # "broiler" | "layer" | "cockerel" | "turkey"
    water_ml_per_bird_per_day: float        # Base rate; add +10% per °C above 25°C
    acceptable_mortality_pct_weekly: float  # Alert threshold for anomaly detection
    target_fcr_at_close: float              # Broiler: typically 1.7–1.9
    target_hen_day_pct: float               # Layer: 80–90 %
    expected_egg_weight_g: float            # Layer: typically 55–65 g
    feed_rates: List[WeeklyFeedRate]        # Per-week standard feed rate


BREED_STANDARDS: Dict[str, BreedStandard] = {

    "broiler_cobb500": BreedStandard(
        name="Cobb 500",
        bird_type="broiler",
        water_ml_per_bird_per_day=200,
        acceptable_mortality_pct_weekly=0.5,
        target_fcr_at_close=1.80,
        target_hen_day_pct=0.0,
        expected_egg_weight_g=0.0,
        feed_rates=[
            WeeklyFeedRate(1, 25), WeeklyFeedRate(2, 50),
            WeeklyFeedRate(3, 80), WeeklyFeedRate(4, 110),
            WeeklyFeedRate(5, 140), WeeklyFeedRate(6, 160),
        ],
    ),

    "broiler_ross308": BreedStandard(
        name="Ross 308",
        bird_type="broiler",
        water_ml_per_bird_per_day=200,
        acceptable_mortality_pct_weekly=0.5,
        target_fcr_at_close=1.75,
        target_hen_day_pct=0.0,
        expected_egg_weight_g=0.0,
        feed_rates=[
            WeeklyFeedRate(1, 23), WeeklyFeedRate(2, 48),
            WeeklyFeedRate(3, 78), WeeklyFeedRate(4, 107),
            WeeklyFeedRate(5, 138), WeeklyFeedRate(6, 158),
        ],
    ),

    "layer_hyline_brown": BreedStandard(
        name="Hy-Line Brown",
        bird_type="layer",
        water_ml_per_bird_per_day=250,
        acceptable_mortality_pct_weekly=0.3,
        target_fcr_at_close=2.20,
        target_hen_day_pct=85.0,
        expected_egg_weight_g=62.0,
        feed_rates=[WeeklyFeedRate(w, 110) for w in range(1, 73)],
    ),

    "layer_isa_brown": BreedStandard(
        name="ISA Brown",
        bird_type="layer",
        water_ml_per_bird_per_day=240,
        acceptable_mortality_pct_weekly=0.3,
        target_fcr_at_close=2.10,
        target_hen_day_pct=88.0,
        expected_egg_weight_g=63.0,
        feed_rates=[WeeklyFeedRate(w, 112) for w in range(1, 73)],
    ),

    "generic_broiler": BreedStandard(
        name="Generic Broiler",
        bird_type="broiler",
        water_ml_per_bird_per_day=200,
        acceptable_mortality_pct_weekly=0.8,
        target_fcr_at_close=2.00,
        target_hen_day_pct=0.0,
        expected_egg_weight_g=0.0,
        feed_rates=[WeeklyFeedRate(w, 100) for w in range(1, 9)],
    ),

    "generic_layer": BreedStandard(
        name="Generic Layer",
        bird_type="layer",
        water_ml_per_bird_per_day=240,
        acceptable_mortality_pct_weekly=0.5,
        target_fcr_at_close=2.20,
        target_hen_day_pct=80.0,
        expected_egg_weight_g=58.0,
        feed_rates=[WeeklyFeedRate(w, 110) for w in range(1, 73)],
    ),
}


def get_breed_standard(bird_type_code: str) -> BreedStandard:
    """
    Returns the BreedStandard for the given code.
    Never raises — falls back to generic_broiler or generic_layer.
    """
    if bird_type_code in BREED_STANDARDS:
        return BREED_STANDARDS[bird_type_code]
    if "layer" in bird_type_code.lower():
        return BREED_STANDARDS["generic_layer"]
    return BREED_STANDARDS["generic_broiler"]
