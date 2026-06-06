import pytest

pytestmark = pytest.mark.django_db


class TestFeedEfficiencyService:
    def test_init(self, tenant_user, test_batch):
        from apps.health.analytics.feed_efficiency import FeedEfficiencyService
        svc = FeedEfficiencyService(tenant_user.org, test_batch)
        assert svc.batch == test_batch

    def test_compute_fcr_no_feed_data(self, tenant_user, test_batch):
        from apps.health.analytics.feed_efficiency import FeedEfficiencyService
        svc = FeedEfficiencyService(tenant_user.org, test_batch)
        result = svc.compute_current_fcr()
        assert result['status'] == 'no_data'
        assert 'target_fcr' in result

    def test_weekly_fcr_trend_returns_list(self, tenant_user, test_batch):
        from apps.health.analytics.feed_efficiency import FeedEfficiencyService
        svc = FeedEfficiencyService(tenant_user.org, test_batch)
        result = svc.get_weekly_fcr_trend()
        assert isinstance(result, list)

    def test_feed_recommendations_no_data(self, tenant_user, test_batch):
        from apps.health.analytics.feed_efficiency import FeedEfficiencyService
        svc = FeedEfficiencyService(tenant_user.org, test_batch)
        recs = svc.get_feed_recommendations()
        assert isinstance(recs, list)
        assert len(recs) > 0

    def test_fcr_status_with_feed_data(self, tenant_user, test_batch):
        from apps.health.analytics.feed_efficiency import FeedEfficiencyService
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.production.feed.models import FeedLog
        from datetime import date, timedelta

        with set_tenant_context(tenant_user.org):
            test_batch.bird_type = 'broiler'
            test_batch.breed_name = 'Cobb 500'
            test_batch.save()
            for i in range(10):
                FeedLog.objects.create(
                    org=tenant_user.org,
                    batch=test_batch,
                    farm=test_batch.farm,
                    quantity_kg=50,
                    record_date=date.today() - timedelta(days=i),
                )

        svc = FeedEfficiencyService(tenant_user.org, test_batch)
        result = svc.compute_current_fcr()
        assert result['fcr'] is not None
        assert result['status'] in ('good', 'acceptable', 'warning', 'critical')

    def test_detect_feed_brand_issues_insufficient_data(
            self, tenant_user, test_batch):
        from apps.health.analytics.feed_efficiency import FeedEfficiencyService
        svc = FeedEfficiencyService(tenant_user.org, test_batch)
        issues = svc.detect_feed_brand_issues()
        assert isinstance(issues, list)
        assert len(issues) == 0


class TestProactiveAlertEngine:
    def test_init(self, tenant_user):
        from apps.health.analytics.proactive_alerts import ProactiveAlertEngine
        engine = ProactiveAlertEngine(tenant_user.org)
        assert engine.org == tenant_user.org

    def test_run_all_checks_returns_list(self, tenant_user):
        from apps.health.analytics.proactive_alerts import ProactiveAlertEngine
        engine = ProactiveAlertEngine(tenant_user.org)
        alerts = engine.run_all_checks()
        assert isinstance(alerts, list)

    def test_check_mortality_trajectory_no_data(
            self, tenant_user, test_batch):
        from apps.health.analytics.proactive_alerts import ProactiveAlertEngine
        engine = ProactiveAlertEngine(tenant_user.org)
        result = engine.check_mortality_trajectory(test_batch)
        assert result is None

    def test_check_egg_production_broiler_skipped(
            self, tenant_user, test_batch):
        from apps.health.analytics.proactive_alerts import ProactiveAlertEngine
        from apps.infrastructure.core.rls import set_tenant_context
        with set_tenant_context(tenant_user.org):
            test_batch.bird_type = 'broiler'
            test_batch.save()
        engine = ProactiveAlertEngine(tenant_user.org)
        result = engine.check_egg_production_drop(test_batch)
        assert result is None

    def test_check_fcr_drift_no_data(self, tenant_user, test_batch):
        from apps.health.analytics.proactive_alerts import ProactiveAlertEngine
        from apps.infrastructure.core.rls import set_tenant_context
        with set_tenant_context(tenant_user.org):
            test_batch.bird_type = 'broiler'
            test_batch.save()
        engine = ProactiveAlertEngine(tenant_user.org)
        result = engine.check_fcr_drift(test_batch)
        # No feed data → no_data status → returns None
        assert result is None

    def test_fire_alerts_returns_int(self, tenant_user):
        from apps.health.analytics.proactive_alerts import ProactiveAlertEngine
        engine = ProactiveAlertEngine(tenant_user.org)
        count = engine.fire_alerts()
        assert isinstance(count, int)


class TestHarvestTimingOptimizerV2:
    def test_init(self, tenant_user, test_batch):
        from apps.health.analytics.exit_optimizer import HarvestTimingOptimizerV2
        opt = HarvestTimingOptimizerV2(tenant_user.org, test_batch)
        assert opt.batch == test_batch

    def test_compute_harvest_window(self, tenant_user, test_batch):
        from apps.health.analytics.exit_optimizer import HarvestTimingOptimizerV2
        from apps.infrastructure.core.rls import set_tenant_context
        with set_tenant_context(tenant_user.org):
            test_batch.bird_type = 'broiler'
            test_batch.breed_name = 'Cobb 500'
            test_batch.save()
        opt = HarvestTimingOptimizerV2(tenant_user.org, test_batch)
        result = opt.compute_optimal_harvest_window()
        assert 'recommendation' in result
        assert 'urgency' in result
        assert 'days_remaining' in result
        assert 'reason' in result
        assert result['recommendation'] in (
            'sell_now', 'sell_this_week', 'prepare_to_sell', 'continue_growing')

    def test_weight_trajectory_fallback(self, tenant_user, test_batch):
        from apps.health.analytics.exit_optimizer import HarvestTimingOptimizerV2
        from apps.infrastructure.core.rls import set_tenant_context
        with set_tenant_context(tenant_user.org):
            test_batch.bird_type = 'broiler'
            test_batch.save()
        opt = HarvestTimingOptimizerV2(tenant_user.org, test_batch)
        trajectory = opt.get_weight_trajectory()
        assert isinstance(trajectory, list)

    def test_sell_now_past_optimal(self, tenant_user, test_batch):
        from apps.health.analytics.exit_optimizer import HarvestTimingOptimizerV2
        from apps.infrastructure.core.rls import set_tenant_context
        from datetime import date, timedelta
        with set_tenant_context(tenant_user.org):
            test_batch.bird_type = 'broiler'
            test_batch.breed_name = 'Cobb 500'
            test_batch.placement_date = date.today() - timedelta(days=50)
            test_batch.save()
        opt = HarvestTimingOptimizerV2(tenant_user.org, test_batch)
        result = opt.compute_optimal_harvest_window()
        assert result['recommendation'] == 'sell_now'

    def test_continue_growing_early_batch(self, tenant_user, test_batch):
        from apps.health.analytics.exit_optimizer import HarvestTimingOptimizerV2
        from apps.infrastructure.core.rls import set_tenant_context
        from datetime import date, timedelta
        with set_tenant_context(tenant_user.org):
            test_batch.bird_type = 'broiler'
            test_batch.breed_name = 'Cobb 500'
            test_batch.placement_date = date.today() - timedelta(days=10)
            test_batch.save()
        opt = HarvestTimingOptimizerV2(tenant_user.org, test_batch)
        result = opt.compute_optimal_harvest_window()
        assert result['recommendation'] == 'continue_growing'


class TestFarmHistoryScore:
    def test_no_history(self, tenant_user, test_batch):
        from apps.health.analytics.farm_memory import FarmMemoryService
        svc = FarmMemoryService(tenant_user.org, test_batch)
        score = svc.get_batch_score_vs_farm_history()
        assert isinstance(score, dict)
        assert score.get('has_history') is False

    def test_returns_dict(self, tenant_user, test_batch):
        from apps.health.analytics.farm_memory import FarmMemoryService
        svc = FarmMemoryService(tenant_user.org, test_batch)
        score = svc.get_batch_score_vs_farm_history()
        assert isinstance(score, dict)

    def test_no_batch_returns_empty(self, tenant_user):
        from apps.health.analytics.farm_memory import FarmMemoryService
        svc = FarmMemoryService(tenant_user.org, batch=None)
        score = svc.get_batch_score_vs_farm_history()
        assert score == {}


class TestAIDeepDiveViewPhases234:
    def test_deep_dive_has_new_context_keys(
            self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        response = client.get(f'/ai/insights/{test_batch.pk}/')
        assert response.status_code == 200
        ctx = response.context
        assert 'fcr_data' in ctx
        assert 'weekly_fcr' in ctx
        assert 'feed_recommendations' in ctx
        assert 'farm_score' in ctx
        assert 'proactive_alerts' in ctx

    def test_harvest_timing_none_for_layer(
            self, client, tenant_user, test_batch):
        from apps.infrastructure.core.rls import set_tenant_context
        client.force_login(tenant_user)
        with set_tenant_context(tenant_user.org):
            test_batch.bird_type = 'layer'
            test_batch.save()
        response = client.get(f'/ai/insights/{test_batch.pk}/')
        assert response.status_code == 200
        assert response.context['harvest_timing'] is None

    def test_harvest_timing_present_for_broiler(
            self, client, tenant_user, test_batch):
        from apps.infrastructure.core.rls import set_tenant_context
        client.force_login(tenant_user)
        with set_tenant_context(tenant_user.org):
            test_batch.bird_type = 'broiler'
            test_batch.breed_name = 'Cobb 500'
            test_batch.save()
        response = client.get(f'/ai/insights/{test_batch.pk}/')
        assert response.status_code == 200
        assert response.context['harvest_timing'] is not None

    def test_proactive_alerts_is_list(
            self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        response = client.get(f'/ai/insights/{test_batch.pk}/')
        assert response.status_code == 200
        assert isinstance(response.context['proactive_alerts'], list)
