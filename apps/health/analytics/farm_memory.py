"""
FarmMemoryService — finds recurring patterns in farm history.
Pure Python + SQL, no ML libraries needed.
"""
from datetime import date, timedelta
from django.db.models import Avg, Sum


class FarmMemoryService:
    """
    Analyses historical data for a specific org/batch
    to find recurring patterns, correlations, and warnings.
    """

    def __init__(self, org, batch=None):
        self.org = org
        self.batch = batch

    def get_mortality_patterns(self) -> list:
        from apps.farm.flocks.models import MortalityLog, Batch
        from apps.infrastructure.core.rls import set_tenant_context

        patterns = []
        today = date.today()
        lookback = today - timedelta(days=180)

        with set_tenant_context(self.org):
            historical_batches = Batch.objects.filter(
                status__in=['closed', 'active'],
                placement_date__gte=lookback - timedelta(days=180),
            ).exclude(
                pk=self.batch.pk if self.batch else None
            )

            if not historical_batches.exists():
                return patterns

            if self.batch:
                current_day = self.batch.cycle_day
                current_mort = MortalityLog.objects.filter(
                    batch=self.batch,
                    date__gte=today - timedelta(days=7),
                ).aggregate(total=Sum('count'))['total'] or 0

                current_rate = (
                    current_mort / max(self.batch.current_count, 1) * 100)

                similar_count = 0
                preceded_disease = 0

                for hist_batch in historical_batches[:10]:
                    start_date = (hist_batch.placement_date +
                                  timedelta(days=current_day - 3))
                    end_date = (hist_batch.placement_date +
                                timedelta(days=current_day + 3))

                    hist_mort = MortalityLog.objects.filter(
                        batch=hist_batch,
                        date__range=[start_date, end_date],
                    ).aggregate(total=Sum('count'))['total'] or 0

                    hist_birds = hist_batch.initial_count or 1
                    hist_rate = hist_mort / hist_birds * 100

                    if hist_rate >= current_rate * 0.7:
                        similar_count += 1
                        from apps.health.health.models import OutbreakAlert
                        disease_after = OutbreakAlert.objects.filter(
                            farm=hist_batch.farm,
                            created_at__date__range=[
                                start_date,
                                end_date + timedelta(days=10),
                            ],
                        ).exists()
                        if disease_after:
                            preceded_disease += 1

                if similar_count >= 2 and current_rate > 0.5:
                    patterns.append({
                        'type': 'mortality_pattern',
                        'severity': (
                            'critical' if preceded_disease >= 2 else 'warning'),
                        'title': 'Recurring Mortality Pattern Detected',
                        'detail': (
                            f'Current mortality rate ({current_rate:.1f}%) '
                            f'at Day {current_day} matches a pattern '
                            f'seen {similar_count} times in your farm history.'
                            + (f' In {preceded_disease} of those cases, '
                               f'a disease outbreak followed within 10 days.'
                               if preceded_disease > 0 else '')
                        ),
                        'action': 'Increase monitoring frequency. Check vaccination records.',
                        'confidence': min(95, similar_count * 20 + preceded_disease * 15),
                    })

        return patterns

    def get_feed_patterns(self) -> list:
        from apps.production.feed.models import FeedLog
        from apps.infrastructure.core.rls import set_tenant_context

        patterns = []
        if not self.batch:
            return patterns

        with set_tenant_context(self.org):
            feed_logs = list(FeedLog.objects.filter(
                batch=self.batch,
            ).order_by('record_date'))

            if len(feed_logs) < 7:
                return patterns

            feed_types = [
                (log.record_date, log.feed_type or 'unknown', log.quantity_kg)
                for log in feed_logs
            ]

            prev_type = feed_types[0][1]
            for i, (dt, ftype, qty) in enumerate(feed_types[1:], 1):
                if ftype != prev_type and ftype != 'unknown':
                    from apps.farm.flocks.models import MortalityLog
                    before_mort = MortalityLog.objects.filter(
                        batch=self.batch,
                        date__range=[dt - timedelta(days=7), dt],
                    ).aggregate(total=Sum('count'))['total'] or 0
                    after_mort = MortalityLog.objects.filter(
                        batch=self.batch,
                        date__range=[dt, dt + timedelta(days=7)],
                    ).aggregate(total=Sum('count'))['total'] or 0

                    if after_mort > before_mort * 1.5 and after_mort > 3:
                        patterns.append({
                            'type': 'feed_change_correlation',
                            'severity': 'warning',
                            'title': 'Feed Change Correlated with Mortality Rise',
                            'detail': (
                                f'Mortality increased {after_mort - before_mort} '
                                f'birds in the 7 days after switching '
                                f'from {prev_type} to {ftype} '
                                f'on {dt.strftime("%b %d")}.'
                            ),
                            'action': (
                                'Review feed quality. Consider reverting '
                                'to previous feed type if available.'
                            ),
                            'confidence': 65,
                        })
                    prev_type = ftype

        return patterns

    def get_seasonal_patterns(self) -> list:
        from apps.farm.flocks.models import Batch, MortalityLog
        from apps.infrastructure.core.rls import set_tenant_context

        patterns = []
        today = date.today()
        current_month = today.month

        with set_tenant_context(self.org):
            same_month_batches = Batch.objects.filter(
                placement_date__month=current_month,
                status='closed',
            ).exclude(
                pk=self.batch.pk if self.batch else None
            )

            if same_month_batches.count() >= 2:
                avg_mort = same_month_batches.annotate(
                    mort=Sum('mortality_logs__count')
                ).aggregate(avg=Avg('mort'))['avg'] or 0

                patterns.append({
                    'type': 'seasonal_pattern',
                    'severity': 'info',
                    'title': f'Seasonal Insight for {today.strftime("%B")}',
                    'detail': (
                        f'Based on {same_month_batches.count()} '
                        f'previous batches started in '
                        f'{today.strftime("%B")}, average mortality '
                        f'was {avg_mort:.0f} birds. '
                        f'Plan feed and medication accordingly.'
                    ),
                    'action': None,
                    'confidence': 70,
                })

        return patterns

    def get_all_patterns(self) -> list:
        patterns = []
        try:
            patterns += self.get_mortality_patterns()
        except Exception:
            pass
        try:
            patterns += self.get_feed_patterns()
        except Exception:
            pass
        try:
            patterns += self.get_seasonal_patterns()
        except Exception:
            pass

        severity_order = {'critical': 0, 'warning': 1, 'info': 2, 'good': 3}
        patterns.sort(key=lambda x: severity_order.get(x['severity'], 99))
        return patterns

    def get_batch_score_vs_farm_history(self) -> dict:
        from apps.farm.flocks.models import Batch, MortalityLog
        from apps.infrastructure.core.rls import set_tenant_context
        from django.db.models import Sum

        if not self.batch:
            return {}

        with set_tenant_context(self.org):
            historical = Batch.objects.filter(
                bird_type=self.batch.bird_type,
                status='closed',
            ).exclude(pk=self.batch.pk)

            if not historical.exists():
                return {
                    'has_history': False,
                    'message': (
                        'Complete your first batch to unlock '
                        'farm-specific performance scoring.'),
                }

            hist_mort_rates = []
            for hb in historical[:10]:
                total_mort = MortalityLog.objects.filter(
                    batch=hb,
                ).aggregate(t=Sum('count'))['t'] or 0
                rate = total_mort / max(hb.initial_count, 1) * 100
                hist_mort_rates.append(rate)

            avg_hist_mort = (
                sum(hist_mort_rates) / len(hist_mort_rates)
                if hist_mort_rates else 0)

            total_curr_mort = MortalityLog.objects.filter(
                batch=self.batch,
            ).aggregate(t=Sum('count'))['t'] or 0
            curr_mort_rate = (
                total_curr_mort / max(self.batch.initial_count, 1) * 100)

            mort_vs_farm = round(curr_mort_rate - avg_hist_mort, 2)

            if mort_vs_farm < -0.5:
                verdict = 'better_than_usual'
                verdict_text = (
                    f'Mortality {abs(mort_vs_farm):.1f}% LOWER than your farm '
                    f'average. Best-in-farm performance so far.')
            elif mort_vs_farm > 1.0:
                verdict = 'worse_than_usual'
                verdict_text = (
                    f'Mortality {mort_vs_farm:.1f}% HIGHER than your farm '
                    f'average. Investigate housing, feed, or biosecurity.')
            else:
                verdict = 'on_track'
                verdict_text = (
                    f'Mortality rate is consistent with your farm '
                    f'average of {avg_hist_mort:.1f}%.')

            return {
                'has_history': True,
                'historical_batches': historical.count(),
                'avg_hist_mort_rate': round(avg_hist_mort, 2),
                'curr_mort_rate': round(curr_mort_rate, 2),
                'mort_vs_farm': mort_vs_farm,
                'verdict': verdict,
                'verdict_text': verdict_text,
            }

    def get_batch_performance_grade(self, fcr=None, mortality_rate=None, hen_day_pct=None) -> dict:
        from apps.health.analytics.breed_benchmarks import compare_batch_to_benchmark

        if not self.batch:
            return {}

        benchmark_result = compare_batch_to_benchmark(
            self.batch, fcr=fcr, mortality_rate=mortality_rate, hen_day_pct=hen_day_pct)

        score = 100
        for comp in benchmark_result['comparisons']:
            if comp['status'] == 'warning':
                score -= 10
            elif comp['status'] == 'critical':
                score -= 25

        if score >= 85:
            grade, grade_color, grade_label = 'A', '#16a34a', 'Excellent'
        elif score >= 70:
            grade, grade_color, grade_label = 'B', '#3d5a99', 'Good'
        elif score >= 55:
            grade, grade_color, grade_label = 'C', '#d97706', 'Average'
        else:
            grade, grade_color, grade_label = 'D', '#dc2626', 'Below Target'

        return {
            'grade': grade,
            'score': score,
            'color': grade_color,
            'label': grade_label,
            'benchmark': benchmark_result,
        }
