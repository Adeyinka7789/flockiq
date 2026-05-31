# Skill: Breed-Specific Logic for FlockIQ

## The Golden Rule
ALWAYS check `batch.bird_type` before applying any calculation.
Layers and Broilers have fundamentally different production cycles, feed regimes, and benchmarks.

---

## Reference Data Models (No RLS — Static Config)

```python
# apps/feed/models.py — reference tables seeded once at deployment

class AgeFeedRate(models.Model):
    """Static reference — daily feed rate per bird by age and type."""
    bird_type = models.CharField(max_length=20)  # broiler or layer
    min_age_days = models.IntegerField()
    max_age_days = models.IntegerField()
    stage = models.CharField(max_length=20)
    grams_per_bird_min = models.IntegerField()
    grams_per_bird_max = models.IntegerField()
    feed_type = models.CharField(max_length=50)

    class Meta:
        db_table = 'age_based_feed_rates'


class AgeWaterRate(models.Model):
    """Static reference — daily water per bird by age and type."""
    bird_type = models.CharField(max_length=20)
    min_age_days = models.IntegerField()
    max_age_days = models.IntegerField()
    ml_per_bird_min = models.IntegerField()
    ml_per_bird_max = models.IntegerField()

    class Meta:
        db_table = 'age_based_water_rates'
```

## Seed Data (run in a migration or management command)
```python
FEED_RATES = [
    # (bird_type, min_day, max_day, stage, g_min, g_max, feed_type)
    ('broiler', 0, 13, 'starter', 20, 40, 'Broiler Starter'),
    ('broiler', 14, 27, 'grower', 60, 90, 'Broiler Grower'),
    ('broiler', 28, 42, 'finisher', 100, 130, 'Broiler Finisher'),
    ('layer', 0, 56, 'chick', 20, 50, 'Chick Starter'),
    ('layer', 57, 125, 'grower', 60, 90, 'Grower Mash'),
    ('layer', 126, 999, 'laying', 100, 120, 'Layer Mash'),
]

WATER_RATES = [
    # (bird_type, min_day, max_day, ml_min, ml_max)
    ('broiler', 0, 6, 50, 80),
    ('broiler', 7, 13, 80, 120),
    ('broiler', 14, 20, 120, 160),
    ('broiler', 21, 27, 160, 200),
    ('broiler', 28, 42, 200, 250),
    ('layer', 0, 56, 50, 80),
    ('layer', 57, 125, 80, 150),
    ('layer', 126, 999, 180, 250),
]
```

---

## Service Functions

```python
# apps/feed/services.py

from apps.feed.models import AgeFeedRate, AgeWaterRate
import logging

logger = logging.getLogger(__name__)


def get_daily_feed_requirement(bird_type: str, age_days: int, bird_count: int) -> float:
    """
    Returns daily feed requirement in kg.
    Uses midpoint of min/max range.
    """
    try:
        rate = AgeFeedRate.objects.get(
            bird_type=bird_type,
            min_age_days__lte=age_days,
            max_age_days__gte=age_days
        )
        avg_grams = (rate.grams_per_bird_min + rate.grams_per_bird_max) / 2
        return round(avg_grams * bird_count / 1000, 2)  # convert g to kg
    except AgeFeedRate.DoesNotExist:
        logger.warning(f"No feed rate for {bird_type} at {age_days} days")
        # Fallback: 100g per bird
        return round(100 * bird_count / 1000, 2)


def get_daily_water_requirement(bird_type: str, age_days: int, bird_count: int) -> float:
    """
    Returns daily water requirement in litres.
    Benchmark: 200 layer birds = 40 litres/day; 200 broiler birds = 40 litres/day at peak.
    """
    try:
        rate = AgeWaterRate.objects.get(
            bird_type=bird_type,
            min_age_days__lte=age_days,
            max_age_days__gte=age_days
        )
        avg_ml = (rate.ml_per_bird_min + rate.ml_per_bird_max) / 2
        return round(avg_ml * bird_count / 1000, 2)  # convert ml to litres
    except AgeWaterRate.DoesNotExist:
        logger.warning(f"No water rate for {bird_type} at {age_days} days")
        return round(200 * bird_count / 1000, 2)


def get_feed_type_for_batch(batch) -> str:
    """Returns the correct feed type name for the current batch stage."""
    try:
        rate = AgeFeedRate.objects.get(
            bird_type=batch.bird_type,
            min_age_days__lte=batch.age_days,
            max_age_days__gte=batch.age_days
        )
        return rate.feed_type
    except AgeFeedRate.DoesNotExist:
        return 'Unknown'


def calculate_fcr(batch) -> float | None:
    """
    Feed Conversion Ratio = total feed consumed (kg) / total weight gained (kg).
    Only meaningful for broilers. Returns None for layers.
    """
    if batch.bird_type != 'broiler':
        return None

    from apps.feed.models import FeedConsumptionLog
    from apps.flocks.models import WeightRecord

    total_feed = FeedConsumptionLog.objects.filter(
        batch=batch).aggregate(
        total=models.Sum('quantity_kg'))['total'] or 0

    weights = WeightRecord.objects.filter(
        batch=batch).order_by('sample_date')

    if weights.count() < 2:
        return None

    first_weight = float(weights.first().avg_weight_grams) / 1000 * batch.initial_count
    latest_weight = float(weights.last().avg_weight_grams) / 1000 * batch.current_count
    weight_gain = latest_weight - first_weight

    if weight_gain <= 0:
        return None

    return round(float(total_feed) / weight_gain, 2)
```

---

## Layer-Specific Logic

```python
# apps/production/services.py

LAYER_BENCHMARKS = {
    # (min_week, max_week): (min_laying_pct, max_laying_pct)
    (18, 24): (20, 30),
    (25, 59): (90, 95),
    (60, 100): (70, 85),
}


def get_expected_laying_pct(age_weeks: int) -> tuple[int, int] | None:
    """Returns (min%, max%) expected laying rate for this age."""
    for (min_wk, max_wk), (min_pct, max_pct) in LAYER_BENCHMARKS.items():
        if min_wk <= age_weeks <= max_wk:
            return (min_pct, max_pct)
    return None


def check_production_drop(batch, today_log) -> bool:
    """
    Alert if laying % drops more than 10% within 48 hours.
    FRD requirement EGG-05.
    """
    from apps.production.models import EggProductionLog
    from datetime import timedelta

    yesterday = today_log.record_date - timedelta(days=1)
    try:
        yesterday_log = EggProductionLog.objects.get(
            batch=batch, record_date=yesterday)
        if yesterday_log.hen_day_pct and today_log.hen_day_pct:
            drop = float(yesterday_log.hen_day_pct) - float(today_log.hen_day_pct)
            return drop >= 10.0
    except EggProductionLog.DoesNotExist:
        pass
    return False


def check_7day_rolling_drop(batch, today_log) -> bool:
    """
    Alert if today's laying % is more than 5% below 7-day rolling average.
    FRD requirement EGG-06.
    """
    from apps.production.models import EggProductionLog
    from datetime import timedelta

    seven_days_ago = today_log.record_date - timedelta(days=7)
    recent = EggProductionLog.objects.filter(
        batch=batch,
        record_date__gte=seven_days_ago,
        record_date__lt=today_log.record_date
    ).exclude(hen_day_pct__isnull=True)

    if recent.count() < 3:
        return False

    avg = sum(float(r.hen_day_pct) for r in recent) / recent.count()
    if today_log.hen_day_pct:
        return (avg - float(today_log.hen_day_pct)) > 5.0
    return False
```

---

## Broiler-Specific Logic

```python
# apps/flocks/services.py

BROILER_WEIGHT_TARGETS = {
    # week: target_grams
    1: 180,
    2: 430,
    3: 840,
    4: 1260,
    5: 1680,
    6: 2100,
}


def get_broiler_weight_target(age_weeks: int) -> int | None:
    """Returns target body weight in grams for given age week."""
    return BROILER_WEIGHT_TARGETS.get(age_weeks)


def check_weight_deviation(weight_record) -> bool:
    """
    Alert if actual weight is more than 10% below breed-age target.
    FRD requirement STCK-10.
    """
    target = get_broiler_weight_target(weight_record.batch.age_weeks)
    if not target:
        return False
    deviation = (target - float(weight_record.avg_weight_grams)) / target * 100
    return deviation > 10.0


def get_sale_timing_recommendation(batch) -> dict:
    """
    Optimal broiler sale timing: when projected revenue - remaining feed cost is maximised.
    FRD requirement AI-04.
    Returns dict with recommendation and reasoning.
    """
    from apps.feed.services import get_daily_feed_requirement

    age_days = batch.age_days
    current_weight = None

    from apps.flocks.models import WeightRecord
    latest_weight = WeightRecord.objects.filter(
        batch=batch).order_by('-sample_date').first()

    if latest_weight:
        current_weight = float(latest_weight.avg_weight_grams)

    if not current_weight:
        return {'recommend': False, 'reason': 'Insufficient weight data'}

    # Optimal sale window: day 38-42 for standard broilers
    days_until_optimal = max(0, 38 - age_days)
    days_past_optimal = max(0, age_days - 42)

    daily_feed_kg = get_daily_feed_requirement(
        batch.bird_type, age_days, batch.current_count)
    # Estimate feed cost at ₦300/kg (configurable)
    daily_feed_cost = daily_feed_kg * 300

    if 38 <= age_days <= 42:
        return {
            'recommend': True,
            'urgency': 'now',
            'message': f'Optimal sale window. Birds are {age_days} days old at ~{current_weight:.0f}g.',
            'days_remaining': 42 - age_days,
            'daily_holding_cost': daily_feed_cost,
        }
    elif age_days > 42:
        return {
            'recommend': True,
            'urgency': 'urgent',
            'message': f'Past optimal window by {days_past_optimal} days. Daily holding cost: ₦{daily_feed_cost:,.0f}',
            'days_past_optimal': days_past_optimal,
            'daily_holding_cost': daily_feed_cost,
        }
    else:
        return {
            'recommend': False,
            'urgency': 'wait',
            'message': f'Optimal window in ~{days_until_optimal} days.',
            'days_until_optimal': days_until_optimal,
        }
```

---

## Theft Detection Logic

```python
# apps/analytics/services.py

THEFT_THRESHOLD_PCT = 0.015  # 1.5% unexplained variance


def run_theft_detection(batch) -> dict:
    """
    Flags when unaccounted birds exceed 1.5% of initial placement.
    FRD requirement AI-03.
    """
    from apps.flocks.models import MortalityLog
    from apps.finance.models import SaleRecord

    total_mortality = MortalityLog.objects.filter(
        batch=batch).aggregate(
        total=models.Sum('count'))['total'] or 0

    total_sold = SaleRecord.objects.filter(
        batch=batch).aggregate(
        total=models.Sum('quantity'))['total'] or 0

    accounted = int(total_mortality) + int(total_sold) + batch.current_count
    unaccounted = batch.initial_count - accounted
    variance_pct = unaccounted / batch.initial_count if batch.initial_count > 0 else 0

    return {
        'unaccounted_birds': max(0, unaccounted),
        'variance_pct': round(variance_pct * 100, 2),
        'theft_suspected': variance_pct > THEFT_THRESHOLD_PCT,
        'initial_count': batch.initial_count,
        'total_mortality': total_mortality,
        'total_sold': int(total_sold),
        'current_count': batch.current_count,
    }
```

---

## Vaccination Compliance Check

```python
# apps/health/services.py

LAYER_VACCINATION_SCHEDULE = [
    # (vaccine_name, recommended_age_days, notes)
    ('Marek\'s Disease', 1, 'At hatchery or day of placement'),
    ('Newcastle + IB (ND+IB)', 7, 'Drinking water or spray'),
    ('Gumboro (IBD)', 14, 'Drinking water'),
    ('Newcastle Booster', 21, 'Eye drop or spray'),
    ('Gumboro Booster', 28, 'Drinking water'),
    ('Newcastle + IB (killed)', 70, 'Injection — critical before lay'),
    ('Fowl Pox', 84, 'Wing web stab'),
]

BROILER_VACCINATION_SCHEDULE = [
    ('Newcastle + IB (ND+IB)', 7, 'Drinking water'),
    ('Gumboro (IBD)', 14, 'Drinking water'),
    ('Newcastle Booster', 21, 'Eye drop — if birds going beyond 4 weeks'),
]


def check_vaccination_compliance(batch) -> list:
    """
    Returns list of missed or overdue vaccinations for this batch.
    Flags improper schedule that may cause production drop at ~10 weeks for layers.
    FRD requirement MED-04.
    """
    from apps.health.models import VaccinationSchedule
    from django.utils import timezone

    schedule = LAYER_VACCINATION_SCHEDULE if batch.bird_type == 'layer' else BROILER_VACCINATION_SCHEDULE
    issues = []

    for vaccine_name, recommended_day, notes in schedule:
        if batch.age_days >= recommended_day:
            completed = VaccinationSchedule.objects.filter(
                batch=batch,
                vaccine_name__icontains=vaccine_name.split('(')[0].strip(),
                status='completed'
            ).exists()

            if not completed:
                days_overdue = batch.age_days - recommended_day
                issues.append({
                    'vaccine': vaccine_name,
                    'recommended_day': recommended_day,
                    'days_overdue': days_overdue,
                    'notes': notes,
                    'severity': 'critical' if days_overdue > 7 else 'high',
                })

    return issues
```
