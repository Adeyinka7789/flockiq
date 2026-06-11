from django.shortcuts import render, get_object_or_404
from django.views import View

from apps.infrastructure.core.views import TenantRequiredMixin


class AIInsightsDeepDiveView(TenantRequiredMixin, View):
    """Per-batch AI intelligence deep dive page."""

    def get(self, request, batch_pk):
        from apps.farm.flocks.models import Batch, MortalityLog, WeightRecord
        from apps.production.feed.models import FeedLog
        from apps.production.production.models import EggProductionLog
        from apps.health.analytics.farm_memory import FarmMemoryService
        from apps.health.analytics.breed_benchmarks import compare_batch_to_benchmark
        from apps.health.analytics.models import AIDailyBrief, ForecastResult
        from apps.health.analytics.feed_efficiency import FeedEfficiencyService
        from apps.health.analytics.proactive_alerts import ProactiveAlertEngine
        from apps.infrastructure.core.rls import set_tenant_context
        from datetime import date, timedelta
        from django.db.models import Sum, Avg

        org = request.user.org
        today = date.today()

        with set_tenant_context(org):
            # select_related('farm') — the template reads batch.farm.name during
            # rendering, outside set_tenant_context().
            batch = get_object_or_404(Batch.objects.select_related("farm"), pk=batch_pk, org=org)

            last_30 = today - timedelta(days=30)

            total_feed = FeedLog.objects.filter(
                batch=batch,
            ).aggregate(total=Sum('quantity_kg'))['total'] or 0

            total_mort = MortalityLog.objects.filter(
                batch=batch,
            ).aggregate(total=Sum('count'))['total'] or 0
            mortality_rate = total_mort / max(batch.initial_count, 1) * 100

            # Real weight from WeightRecord — fallback to 1.8 kg
            avg_weight_kg = 1.8
            try:
                wr = WeightRecord.objects.filter(
                    batch=batch,
                ).order_by('-sample_date').first()
                if wr and wr.avg_weight_kg:
                    avg_weight_kg = float(wr.avg_weight_kg)
            except Exception:
                pass

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

            # Materialise the querysets the template iterates during rendering
            # (outside set_tenant_context()).
            forecasts = list(ForecastResult.objects.filter(
                batch=batch,
                forecast_date__gte=today,
            ).order_by('forecast_date')[:14])

            mort_trend = list(
                MortalityLog.objects.filter(
                    batch=batch,
                    date__gte=today - timedelta(days=14),
                ).order_by('date').values('date', 'count'))

            recent_briefs = list(AIDailyBrief.objects.filter(
                org=org,
            ).order_by('-brief_date')[:7])

            similar_batches = list(Batch.objects.filter(
                org=org,
                bird_type=batch.bird_type,
                status='closed',
            ).exclude(pk=batch.pk).order_by('-placement_date')[:5])

            # Phase 2–4: Feed efficiency
            feed_svc = FeedEfficiencyService(org, batch)
            fcr_data = feed_svc.compute_current_fcr()
            weekly_fcr = feed_svc.get_weekly_fcr_trend()
            feed_recommendations = feed_svc.get_feed_recommendations()

            # Phase 2: Farm history comparison
            farm_score = memory_service.get_batch_score_vs_farm_history()

            # Phase 4: Harvest timing (broilers only)
            harvest_timing = None
            if batch.bird_type == 'broiler':
                from apps.health.analytics.exit_optimizer import (
                    HarvestTimingOptimizerV2)
                optimizer = HarvestTimingOptimizerV2(org, batch)
                harvest_timing = optimizer.compute_optimal_harvest_window()

            # Phase 3: Proactive alerts for this batch only
            engine = ProactiveAlertEngine(org)
            proactive_alerts = [
                a for a in engine.run_all_checks()
                if a['batch'].pk == batch.pk
            ]

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
            # Phase 2–4
            'fcr_data': fcr_data,
            'weekly_fcr': weekly_fcr,
            'feed_recommendations': feed_recommendations,
            'farm_score': farm_score,
            'harvest_timing': harvest_timing,
            'proactive_alerts': proactive_alerts,
        }
        return render(request, 'analytics/ai_deep_dive.html', context)
