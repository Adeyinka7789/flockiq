"""
FeedEfficiencyService
Analyses feed conversion efficiency per batch,
detects FCR drift, flags underperforming feed periods,
and gives actionable recommendations.
"""
from datetime import timedelta
from django.db.models import Sum


class FeedEfficiencyService:

    # Nigerian/WA broiler FCR benchmarks by week
    FCR_WEEKLY_TARGETS = {
        1: 1.20,
        2: 1.35,
        3: 1.50,
        4: 1.60,
        5: 1.70,
        6: 1.80,
    }

    FCR_DRIFT_THRESHOLD = 0.15

    def __init__(self, org, batch):
        self.org = org
        self.batch = batch

    def compute_current_fcr(self) -> dict:
        from apps.production.feed.models import FeedLog
        from apps.infrastructure.core.rls import set_tenant_context

        with set_tenant_context(self.org):
            total_feed = FeedLog.objects.filter(
                batch=self.batch,
            ).aggregate(total=Sum('quantity_kg'))['total'] or 0

            avg_weight_kg = 1.8
            try:
                from apps.farm.flocks.models import WeightRecord
                wr = WeightRecord.objects.filter(
                    batch=self.batch,
                ).order_by('-sample_date').first()
                if wr and wr.avg_weight_kg:
                    avg_weight_kg = float(wr.avg_weight_kg)
            except Exception:
                pass

            biomass = self.batch.current_count * avg_weight_kg
            fcr = (round(float(total_feed) / float(biomass), 2)
                   if biomass > 0 and total_feed > 0 else None)

            from apps.health.analytics.breed_benchmarks import get_benchmark
            benchmark = get_benchmark(
                getattr(self.batch, 'breed_name', None),
                self.batch.bird_type)
            target_fcr = benchmark.get('target_fcr', 1.80)

            if fcr is None:
                status = 'no_data'
            elif fcr <= target_fcr:
                status = 'good'
            elif fcr <= target_fcr + self.FCR_DRIFT_THRESHOLD:
                status = 'acceptable'
            elif fcr <= target_fcr + 0.30:
                status = 'warning'
            else:
                status = 'critical'

            return {
                'fcr': fcr,
                'target_fcr': target_fcr,
                'total_feed_kg': float(total_feed),
                'biomass_kg': round(biomass, 1),
                'avg_weight_kg': avg_weight_kg,
                'status': status,
                'breed': benchmark.get('name', 'Standard'),
            }

    def get_weekly_fcr_trend(self) -> list:
        from apps.production.feed.models import FeedLog
        from apps.infrastructure.core.rls import set_tenant_context

        weekly = []
        if not self.batch.placement_date:
            return weekly

        with set_tenant_context(self.org):
            cycle_days = self.batch.cycle_day or 0
            weeks = min(cycle_days // 7 + 1, 8)

            cumulative_feed = 0
            for week in range(1, weeks + 1):
                week_start = (self.batch.placement_date +
                              timedelta(days=(week - 1) * 7))
                week_end = (self.batch.placement_date +
                            timedelta(days=week * 7))

                week_feed = FeedLog.objects.filter(
                    batch=self.batch,
                    record_date__range=[week_start, week_end],
                ).aggregate(total=Sum('quantity_kg'))['total'] or 0

                cumulative_feed += float(week_feed)
                target = self.FCR_WEEKLY_TARGETS.get(week, 1.80)

                est_weight = week * 0.35
                biomass = self.batch.initial_count * est_weight

                week_fcr = (round(cumulative_feed / biomass, 2)
                            if biomass > 0 and cumulative_feed > 0 else None)

                weekly.append({
                    'week': week,
                    'fcr': week_fcr,
                    'target': target,
                    'status': (
                        'good' if week_fcr and week_fcr <= target
                        else 'warning' if week_fcr
                        else 'no_data'),
                    'feed_kg': round(float(week_feed), 1),
                })

        return weekly

    def detect_feed_brand_issues(self) -> list:
        from apps.production.feed.models import FeedLog
        from apps.farm.flocks.models import MortalityLog
        from apps.infrastructure.core.rls import set_tenant_context

        issues = []
        with set_tenant_context(self.org):
            logs = list(FeedLog.objects.filter(
                batch=self.batch,
            ).order_by('record_date'))

            if len(logs) < 10:
                return issues

            prev_type = logs[0].feed_type or 'unknown'
            for i, log in enumerate(logs[1:], 1):
                curr_type = log.feed_type or 'unknown'
                if (curr_type != prev_type and
                        curr_type != 'unknown' and
                        prev_type != 'unknown'):

                    change_date = log.record_date

                    before_feed = sum(
                        float(l.quantity_kg or 0)
                        for l in logs[max(0, i - 7):i])
                    after_feed = sum(
                        float(l.quantity_kg or 0)
                        for l in logs[i:i + 7])

                    before_mort = MortalityLog.objects.filter(
                        batch=self.batch,
                        date__range=[
                            change_date - timedelta(days=7),
                            change_date],
                    ).aggregate(t=Sum('count'))['t'] or 0

                    after_mort = MortalityLog.objects.filter(
                        batch=self.batch,
                        date__range=[
                            change_date,
                            change_date + timedelta(days=7)],
                    ).aggregate(t=Sum('count'))['t'] or 0

                    if (after_feed > before_feed * 1.15 or
                            after_mort > before_mort * 1.5):
                        issues.append({
                            'change_date': change_date.strftime('%b %d'),
                            'from_type': prev_type,
                            'to_type': curr_type,
                            'feed_increase_pct': round(
                                (after_feed - before_feed) /
                                max(before_feed, 1) * 100, 1),
                            'mort_increase': int(after_mort - before_mort),
                            'recommendation': (
                                f'Monitor closely. Feed intake increased after '
                                f'switching to {curr_type} on '
                                f'{change_date.strftime("%b %d")}. '
                                f'Consider reverting if FCR continues to rise.'
                            ),
                        })
                prev_type = curr_type

        return issues

    def get_feed_recommendations(self) -> list:
        recs = []
        fcr_data = self.compute_current_fcr()
        fcr = fcr_data.get('fcr')
        status = fcr_data.get('status')
        target = fcr_data.get('target_fcr')

        if status == 'no_data':
            recs.append({
                'priority': 'medium',
                'text': (
                    'No feed records logged yet. '
                    'Start logging daily feed intake to enable FCR tracking.'),
            })
        elif status == 'critical':
            recs.append({
                'priority': 'high',
                'text': (
                    f'FCR {fcr} is significantly above '
                    f'{fcr_data["breed"]} target of {target}. '
                    f'Check water availability, feed wastage, '
                    f'and bird health immediately.'),
            })
        elif status == 'warning':
            recs.append({
                'priority': 'medium',
                'text': (
                    f'FCR {fcr} is above target {target}. '
                    f'Review feeding times and ensure feeders '
                    f'are at correct height for bird age.'),
            })
        elif status == 'good':
            recs.append({
                'priority': 'low',
                'text': (
                    f'FCR {fcr} is within {fcr_data["breed"]} '
                    f'benchmark. Maintain current feeding regime.'),
            })

        for issue in self.detect_feed_brand_issues():
            recs.append({'priority': 'high', 'text': issue['recommendation']})

        return recs
