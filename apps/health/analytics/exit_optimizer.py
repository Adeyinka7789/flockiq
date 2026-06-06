class HarvestTimingOptimizerV2:
    """
    Enhanced harvest timing using real weight data, FCR trend,
    and breed-specific targets.
    """

    HOLDING_COST_PER_BIRD_DAY = 45  # ₦ feed + overhead

    def __init__(self, org, batch):
        self.org = org
        self.batch = batch

    def get_weight_trajectory(self) -> list:
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.health.analytics.breed_benchmarks import get_benchmark

        benchmark = get_benchmark(
            getattr(self.batch, 'breed_name', None),
            self.batch.bird_type)

        with set_tenant_context(self.org):
            try:
                from apps.farm.flocks.models import WeightRecord
                records = list(WeightRecord.objects.filter(
                    batch=self.batch,
                ).order_by('sample_date').values(
                    'sample_date', 'avg_weight_kg'))

                if records:
                    trajectory = []
                    for r in records:
                        day = (r['sample_date'] -
                               self.batch.placement_date).days
                        trajectory.append({
                            'day': day,
                            'weight_kg': float(r['avg_weight_kg']),
                            'source': 'actual',
                        })
                    return trajectory
            except Exception:
                pass

        # Fallback: breed growth curve projection
        daily_gain = benchmark.get('daily_weight_gain_g', 55)
        current_day = self.batch.cycle_day or 0
        trajectory = []
        for day in range(current_day, min(current_day + 14, 56)):
            trajectory.append({
                'day': day,
                'weight_kg': round(daily_gain * day / 1000, 2),
                'source': 'projected',
            })
        return trajectory

    def compute_optimal_harvest_window(self) -> dict:
        from apps.health.analytics.breed_benchmarks import get_benchmark
        from apps.health.analytics.feed_efficiency import FeedEfficiencyService

        benchmark = get_benchmark(
            getattr(self.batch, 'breed_name', None),
            self.batch.bird_type)

        optimal_day = benchmark.get('optimal_slaughter_day', 42)
        target_weight = benchmark.get('target_weight_day42_kg', 2.2)
        current_day = self.batch.cycle_day or 0

        fcr_svc = FeedEfficiencyService(self.org, self.batch)
        fcr_data = fcr_svc.compute_current_fcr()
        current_fcr = fcr_data.get('fcr')
        target_fcr = fcr_data.get('target_fcr', 1.80)

        days_remaining = max(0, optimal_day - current_day)
        holding_cost_total = (
            days_remaining *
            self.HOLDING_COST_PER_BIRD_DAY *
            self.batch.current_count)

        trajectory = self.get_weight_trajectory()
        current_weight = (trajectory[-1]['weight_kg']
                          if trajectory else 1.8)

        if current_day >= optimal_day + 5:
            recommendation = 'sell_now'
            urgency = 'critical'
            reason = (
                f'Batch is {current_day - optimal_day} days past optimal '
                f'harvest age. FCR is declining. Every extra day costs '
                f'₦{self.HOLDING_COST_PER_BIRD_DAY:,}/bird.')
        elif current_day >= optimal_day - 3:
            recommendation = 'sell_this_week'
            urgency = 'high'
            reason = (
                f'Batch is approaching optimal harvest window '
                f'({optimal_day} days). Weight ~{current_weight}kg '
                f'vs target {target_weight}kg. Book buyers now.')
        elif current_day >= optimal_day - 7:
            recommendation = 'prepare_to_sell'
            urgency = 'medium'
            reason = (
                f'{days_remaining} days to optimal harvest. '
                f'Start contacting buyers and arranging logistics.')
        else:
            recommendation = 'continue_growing'
            urgency = 'low'
            reason = (
                f'{days_remaining} days to harvest window. '
                f'Focus on maintaining FCR below {target_fcr}.')

        # FCR-based override
        if (current_fcr and
                current_fcr > target_fcr + 0.30 and
                current_day >= optimal_day - 5):
            recommendation = 'sell_now'
            urgency = 'high'
            reason = (
                f'FCR ({current_fcr}) is significantly above target '
                f'({target_fcr}). Feed costs are outpacing weight gain. '
                f'Sell now to maximise profit.')

        return {
            'current_day': current_day,
            'optimal_day': optimal_day,
            'days_remaining': days_remaining,
            'current_weight_kg': current_weight,
            'target_weight_kg': target_weight,
            'current_fcr': current_fcr,
            'target_fcr': target_fcr,
            'recommendation': recommendation,
            'urgency': urgency,
            'reason': reason,
            'holding_cost_total': holding_cost_total,
            'breed': benchmark.get('name', 'Standard'),
            'trajectory': trajectory,
        }


class BroilerExitOptimizer:
    """
    Calculates optimal sell date for broiler batches.
    Shows daily cost of holding vs expected gain.
    Pure Python — no ORM access.
    """

    # Cobb 500 daily weight gain by age (grams)
    DAILY_GAIN_TABLE = [
        (range(1, 8), 18),
        (range(8, 15), 35),
        (range(15, 22), 55),
        (range(22, 29), 65),
        (range(29, 36), 58),
        (range(36, 43), 45),
        (range(43, 50), 30),
        (range(50, 60), 18),
    ]

    def get_daily_gain(self, day: int) -> int:
        for day_range, gain in self.DAILY_GAIN_TABLE:
            if day in day_range:
                return gain
        return 10

    def analyze(self, batch, price_per_kg_naira: int = 1850) -> dict:
        """
        Returns exit analysis for a broiler batch.
        """
        day = batch.cycle_day
        bird_count = batch.current_count

        # Cumulative weight from day 1
        estimated_weight_g = sum(self.get_daily_gain(d) for d in range(1, day + 1))

        # Daily feed cost estimate
        feed_per_bird_g = min(130, 60 + day * 2)
        feed_cost_per_kg = 500  # ₦500/kg feed estimate
        daily_feed_cost = bird_count * feed_per_bird_g / 1000 * feed_cost_per_kg

        # Daily weight gain value
        daily_gain_g = self.get_daily_gain(day)
        daily_gain_value = bird_count * daily_gain_g / 1000 * price_per_kg_naira

        # Optimal window: day 35–42
        if day < 35:
            recommendation = "wait"
            days_until = 35 - day
            message = f"Optimal window in {days_until} days (Day 35)"
        elif day <= 42:
            recommendation = "sell_now"
            days_until = 0
            message = "You are in the optimal sale window"
        else:
            recommendation = "urgent"
            days_until = 0
            message = f"Past optimal window by {day - 42} days"

        est_weight_kg = bird_count * estimated_weight_g / 1000
        est_revenue = est_weight_kg * price_per_kg_naira
        net_daily = daily_gain_value - daily_feed_cost

        return {
            "day": day,
            "estimated_weight_g": round(estimated_weight_g),
            "est_weight_kg": round(est_weight_kg, 1),
            "est_revenue": round(est_revenue),
            "daily_feed_cost": round(daily_feed_cost),
            "daily_gain_value": round(daily_gain_value),
            "net_daily_value": round(net_daily),
            "recommendation": recommendation,
            "days_until_optimal": days_until,
            "message": message,
            "price_per_kg": price_per_kg_naira,
        }
