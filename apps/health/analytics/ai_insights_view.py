from django.shortcuts import render, get_object_or_404
from django.views import View

from apps.infrastructure.core.views import TenantRequiredMixin


class AIInsightsDeepDiveView(TenantRequiredMixin, View):
    """Per-batch AI intelligence deep dive page."""

    def get(self, request, batch_pk):
        from apps.farm.flocks.models import Batch, MortalityLog
        from apps.production.feed.models import FeedLog
        from apps.production.production.models import EggProductionLog
        from apps.health.analytics.farm_memory import FarmMemoryService
        from apps.health.analytics.breed_benchmarks import compare_batch_to_benchmark
        from apps.health.analytics.models import AIDailyBrief, ForecastResult
        from apps.infrastructure.core.rls import set_tenant_context
        from datetime import date, timedelta
        from django.db.models import Sum, Avg

        org = request.user.org
        today = date.today()

        with set_tenant_context(org):
            batch = get_object_or_404(Batch, pk=batch_pk, org=org)

            last_30 = today - timedelta(days=30)

            total_feed = FeedLog.objects.filter(
                batch=batch,
            ).aggregate(total=Sum('quantity_kg'))['total'] or 0

            total_mort = MortalityLog.objects.filter(
                batch=batch,
            ).aggregate(total=Sum('count'))['total'] or 0
            mortality_rate = total_mort / max(batch.initial_count, 1) * 100

            avg_weight_kg = 1.8
            total_weight = batch.current_count * avg_weight_kg
            fcr = (round(float(total_feed) / float(total_weight), 2)
                   if total_weight > 0 and total_feed > 0 else None)

            hen_day_pct = None
            if batch.bird_type == 'layer':
                recent_egg = EggProductionLog.objects.filter(
                    batch=batch,
                    record_date__gte=last_30,
                ).aggregate(avg=Avg('hen_day_pct'))['avg']
                hen_day_pct = round(recent_egg, 1) if recent_egg else None

            benchmark_result = compare_batch_to_benchmark(
                batch,
                fcr=fcr,
                mortality_rate=round(mortality_rate, 2),
                hen_day_pct=hen_day_pct)

            memory_service = FarmMemoryService(org, batch)
            all_patterns = memory_service.get_all_patterns()
            performance_grade = memory_service.get_batch_performance_grade(
                fcr=fcr,
                mortality_rate=round(mortality_rate, 2),
                hen_day_pct=hen_day_pct)

            forecasts = ForecastResult.objects.filter(
                batch=batch,
                forecast_date__gte=today,
            ).order_by('forecast_date')[:14]

            mort_trend = list(
                MortalityLog.objects.filter(
                    batch=batch,
                    date__gte=today - timedelta(days=14),
                ).order_by('date').values('date', 'count'))

            recent_briefs = AIDailyBrief.objects.filter(
                org=org,
            ).order_by('-brief_date')[:7]

            similar_batches = Batch.objects.filter(
                org=org,
                bird_type=batch.bird_type,
                status='closed',
            ).exclude(pk=batch.pk).order_by('-placement_date')[:5]

        context = {
            'batch': batch,
            'fcr': fcr,
            'mortality_rate': round(mortality_rate, 2),
            'total_mort': total_mort,
            'hen_day_pct': hen_day_pct,
            'benchmark_result': benchmark_result,
            'all_patterns': all_patterns,
            'performance_grade': performance_grade,
            'forecasts': forecasts,
            'mort_trend': mort_trend,
            'recent_briefs': recent_briefs,
            'similar_batches': similar_batches,
            'today': today,
        }
        return render(request, 'analytics/ai_deep_dive.html', context)
