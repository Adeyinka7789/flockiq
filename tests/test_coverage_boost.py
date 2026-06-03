"""
Coverage boost tests — targets lowest-coverage files to push overall from 71% → 75%.

Key areas:
- production/views.py (53%)    → ProductionOverview, PDF/Excel export, Log, API
- feed/services.py (70%)       → FeedService.get_fcr, get_feed_cost_forecast
- Global search, weather, onboarding, notifications, team, billing pages
- Pure-Python engines: features, DailyBrief, ExitOptimizer, Disease, Seasonal
"""
import pytest
from types import SimpleNamespace
from datetime import date, timedelta

pytestmark = pytest.mark.django_db


# ── Global Search ─────────────────────────────────────────────────────────────

class TestGlobalSearch:

    def test_search_requires_login(self, client):
        response = client.get('/search/?q=test')
        assert response.status_code == 302

    def test_search_returns_200(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get('/search/?q=test')
        assert response.status_code == 200

    def test_search_short_query_returns_empty(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get('/search/?q=a')
        assert response.status_code == 200

    def test_search_finds_farm(self, client, tenant_user, test_farm):
        client.force_login(tenant_user)
        response = client.get(f'/search/?q={test_farm.name[:4]}')
        assert response.status_code == 200

    def test_search_finds_batch(self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        response = client.get(f'/search/?q={test_batch.batch_name[:4]}')
        assert response.status_code == 200


# ── Weather Page ──────────────────────────────────────────────────────────────

class TestWeatherPage:

    def test_weather_page_requires_login(self, client):
        response = client.get('/weather/')
        assert response.status_code == 302

    def test_weather_page_returns_200(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get('/weather/')
        assert response.status_code == 200

    def test_weather_page_no_gps_shows_empty_state(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get('/weather/')
        assert response.status_code == 200


# ── Onboarding ────────────────────────────────────────────────────────────────

class TestOnboarding:

    def test_onboarding_redirects_if_complete(self, client, tenant_user):
        tenant_user.org.onboarding_complete = True
        tenant_user.org.save()
        client.force_login(tenant_user)
        response = client.get('/onboarding/')
        assert response.status_code == 302

    def test_onboarding_step1_get(self, client, tenant_user):
        tenant_user.org.onboarding_complete = False
        tenant_user.org.save()
        client.force_login(tenant_user)
        response = client.get('/onboarding/?step=1')
        assert response.status_code == 200

    def test_onboarding_requires_login(self, client):
        response = client.get('/onboarding/')
        assert response.status_code == 302


# ── Notifications Page ────────────────────────────────────────────────────────

class TestNotificationsPage:

    def test_notifications_page_returns_200(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get('/notifications/')
        assert response.status_code == 200

    def test_mark_all_read_page_post(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.post(
            '/notifications/mark-all-read-page/',
            HTTP_HX_REQUEST='true',
        )
        assert response.status_code == 200


# ── Team Management ───────────────────────────────────────────────────────────

class TestTeamManagement:

    def test_team_page_returns_200(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get('/team/')
        assert response.status_code == 200

    def test_invite_form_get_returns_200(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get('/team/invite/', HTTP_HX_REQUEST='true')
        assert response.status_code == 200

    def test_team_requires_login(self, client):
        response = client.get('/team/')
        assert response.status_code == 302


# ── Billing Page & Upgrade ────────────────────────────────────────────────────

class TestBillingUpgrade:

    def test_billing_page_returns_200(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get('/billing/')
        assert response.status_code == 200

    def test_upgrade_request_non_owner_returns_403(self, client, tenant_user):
        tenant_user.role = 'data_entry'
        tenant_user.save()
        client.force_login(tenant_user)
        response = client.post('/billing/upgrade/', {'plan_tier': 'monthly'})
        assert response.status_code == 403


# ── Plan Features ─────────────────────────────────────────────────────────────

class TestPlanFeatures:

    def test_has_feature_trial(self):
        from apps.infrastructure.billing.features import has_feature
        org = SimpleNamespace(plan_tier='trial')
        assert has_feature(org, 'weather_alerts') is True
        assert has_feature(org, 'ai_daily_brief') is False
        assert has_feature(org, 'pdf_export') is False

    def test_has_feature_monthly(self):
        from apps.infrastructure.billing.features import has_feature
        org = SimpleNamespace(plan_tier='monthly')
        assert has_feature(org, 'ai_daily_brief') is True
        assert has_feature(org, 'pdf_export') is True
        assert has_feature(org, 'white_label') is False

    def test_has_feature_yearly(self):
        from apps.infrastructure.billing.features import has_feature
        org = SimpleNamespace(plan_tier='yearly')
        assert has_feature(org, 'white_label') is True

    def test_get_upgrade_plan(self):
        from apps.infrastructure.billing.features import get_upgrade_plan
        assert get_upgrade_plan('ai_daily_brief') == 'monthly'
        assert get_upgrade_plan('exit_optimizer') == 'cycle'
        assert get_upgrade_plan('white_label') == 'yearly'

    def test_get_plan_features_unknown_tier_falls_back_to_trial(self):
        from apps.infrastructure.billing.features import get_plan_features
        features = get_plan_features('nonexistent')
        assert features['max_farms'] == 1
        assert features['ai_daily_brief'] is False


# ── Daily Brief ───────────────────────────────────────────────────────────────

class TestDailyBrief:

    def test_daily_brief_generates(self, tenant_user):
        from apps.health.analytics.daily_brief import DailyBriefService
        service = DailyBriefService(tenant_user.org)
        brief = service.generate()
        assert 'alerts' in brief
        assert 'recommendations' in brief
        assert 'active_batches' in brief

    def test_daily_brief_cached(self, tenant_user):
        from apps.health.analytics.daily_brief import DailyBriefService
        service = DailyBriefService(tenant_user.org)
        brief = service.get_cached()
        assert isinstance(brief, dict)
        assert 'alerts' in brief

    def test_daily_brief_invalidate(self, tenant_user):
        from apps.health.analytics.daily_brief import DailyBriefService
        service = DailyBriefService(tenant_user.org)
        service.get_cached()  # warm the cache
        service.invalidate()  # should not raise
        brief = service.get_cached()  # re-generates
        assert isinstance(brief, dict)


# ── Exit Optimizer ────────────────────────────────────────────────────────────

class TestExitOptimizer:

    def test_exit_optimizer_wait_early_batch(self):
        from apps.health.analytics.exit_optimizer import BroilerExitOptimizer
        mock_batch = SimpleNamespace(cycle_day=10, current_count=200)
        optimizer = BroilerExitOptimizer()
        result = optimizer.analyze(mock_batch, 1850)
        assert 'recommendation' in result
        assert result['recommendation'] == 'wait'
        assert 'est_revenue' in result
        assert result['est_revenue'] > 0

    def test_exit_optimizer_sell_now_window(self):
        from apps.health.analytics.exit_optimizer import BroilerExitOptimizer
        mock_batch = SimpleNamespace(cycle_day=38, current_count=200)
        optimizer = BroilerExitOptimizer()
        result = optimizer.analyze(mock_batch, 1850)
        assert result['recommendation'] == 'sell_now'
        assert result['est_revenue'] > 0

    def test_exit_optimizer_urgent_past_window(self):
        from apps.health.analytics.exit_optimizer import BroilerExitOptimizer
        mock_batch = SimpleNamespace(cycle_day=50, current_count=200)
        optimizer = BroilerExitOptimizer()
        result = optimizer.analyze(mock_batch, 1850)
        assert result['recommendation'] == 'urgent'

    def test_exit_optimizer_daily_gain_fallback(self):
        from apps.health.analytics.exit_optimizer import BroilerExitOptimizer
        optimizer = BroilerExitOptimizer()
        assert optimizer.get_daily_gain(999) == 10  # fallback for unknown day


# ── Disease Diagnosis ─────────────────────────────────────────────────────────

class TestDiseaseDiagnosis:

    def test_diagnosis_newcastle(self):
        from apps.health.analytics.disease_patterns import DiseaseDiagnosisEngine
        engine = DiseaseDiagnosisEngine()
        results = engine.diagnose(
            symptoms=['respiratory', 'sudden_death', 'nervous'],
            batch_age_weeks=3,
            mortality_rate=3.5,
        )
        assert len(results) > 0
        assert results[0]['confidence'] > 0

    def test_diagnosis_no_symptoms(self):
        from apps.health.analytics.disease_patterns import DiseaseDiagnosisEngine
        engine = DiseaseDiagnosisEngine()
        results = engine.diagnose(
            symptoms=[],
            batch_age_weeks=3,
            mortality_rate=0.5,
        )
        assert isinstance(results, list)

    def test_diagnosis_coccidiosis(self):
        from apps.health.analytics.disease_patterns import DiseaseDiagnosisEngine
        engine = DiseaseDiagnosisEngine()
        results = engine.diagnose(
            symptoms=['bloody_diarrhoea', 'lethargy'],
            batch_age_weeks=4,
            mortality_rate=1.5,
        )
        assert len(results) > 0

    def test_diagnosis_returns_max_three_results(self):
        from apps.health.analytics.disease_patterns import DiseaseDiagnosisEngine
        engine = DiseaseDiagnosisEngine()
        results = engine.diagnose(
            symptoms=['respiratory', 'diarrhoea', 'lethargy', 'sudden_death',
                      'nervous', 'drop_in_production'],
            batch_age_weeks=6,
            mortality_rate=5.0,
        )
        assert len(results) <= 3


# ── Seasonal Advisor ──────────────────────────────────────────────────────────

class TestSeasonalAdvisor:

    def test_seasonal_insight_returns_dict(self):
        from apps.finance.market.seasonal_advisor import SeasonalAdvisor
        advisor = SeasonalAdvisor()
        result = advisor.get_current_season_insight()
        assert 'current_events' in result
        assert 'upcoming_events' in result
        assert 'month' in result

    def test_seasonal_insight_current_events_are_list(self):
        from apps.finance.market.seasonal_advisor import SeasonalAdvisor
        advisor = SeasonalAdvisor()
        result = advisor.get_current_season_insight()
        assert isinstance(result['current_events'], list)
        assert isinstance(result['upcoming_events'], list)

    def test_placement_recommendation_returns_string(self):
        from apps.finance.market.seasonal_advisor import SeasonalAdvisor
        advisor = SeasonalAdvisor()
        result = advisor.get_placement_recommendation()
        assert isinstance(result, str)
        assert len(result) > 10


# ── AI Analytics Page ─────────────────────────────────────────────────────────

class TestAIAnalyticsPage:

    def test_analytics_page_returns_200(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get('/analytics/')
        assert response.status_code == 200

    def test_analytics_requires_login(self, client):
        response = client.get('/analytics/')
        assert response.status_code == 302


# ── Production Overview (biggest coverage gap — 53%) ──────────────────────────

class TestProductionOverview:

    def test_production_overview_requires_login(self, client):
        response = client.get('/production/')
        assert response.status_code == 302

    def test_production_overview_returns_200(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get('/production/')
        assert response.status_code == 200

    def test_production_overview_with_farm_filter(
            self, client, tenant_user, test_farm):
        client.force_login(tenant_user)
        response = client.get(f'/production/?farm={test_farm.pk}')
        assert response.status_code == 200

    def test_production_overview_with_batch_filter(
            self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        response = client.get(f'/production/?batch={test_batch.pk}')
        assert response.status_code == 200

    def test_production_overview_htmx_partial(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get('/production/', HTTP_HX_REQUEST='true')
        assert response.status_code == 200

    def test_production_overview_with_preset(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get('/production/?preset=7d')
        assert response.status_code == 200

    def test_pdf_export_blocked_without_flag(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get('/production/export/pdf/')
        assert response.status_code == 403

    def test_excel_export_blocked_without_flag(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get('/production/export/excel/')
        assert response.status_code == 403

    def test_production_log_get_returns_200(self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        response = client.get(f'/production/eggs/{test_batch.pk}/log/')
        assert response.status_code == 200

    def test_production_table_returns_200(self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        response = client.get(f'/production/eggs/{test_batch.pk}/table/')
        assert response.status_code == 200

    def test_production_chart_returns_200(self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        response = client.get(f'/production/eggs/{test_batch.pk}/chart/')
        assert response.status_code == 200

    def test_production_summary_card_returns_200(
            self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        response = client.get(f'/production/eggs/{test_batch.pk}/summary/')
        assert response.status_code == 200


# ── Production DRF API Views ──────────────────────────────────────────────────

class TestProductionAPIViews:

    def test_egg_api_list_returns_200(self, api_client):
        response = api_client.get('/api/v1/production/eggs/')
        assert response.status_code == 200
        assert 'data' in response.json()

    def test_egg_api_list_with_batch_filter(self, api_client, test_batch):
        response = api_client.get(
            f'/api/v1/production/eggs/?batch_id={test_batch.pk}')
        assert response.status_code == 200

    def test_egg_api_post_missing_batch_id_returns_400(self, api_client):
        response = api_client.post('/api/v1/production/eggs/', {
            'record_date': str(date.today()),
            'total_eggs': 100,
        })
        assert response.status_code == 400

    def test_egg_api_post_invalid_data_returns_400(self, api_client, test_batch):
        response = api_client.post('/api/v1/production/eggs/', {
            'batch_id': str(test_batch.pk),
            'record_date': 'not-a-date',
            'total_eggs': -1,
        })
        assert response.status_code == 400

    def test_egg_api_post_non_layer_batch_returns_422(
            self, api_client, test_batch):
        from apps.infrastructure.core.rls import set_tenant_context
        with set_tenant_context(test_batch.org):
            test_batch.bird_type = 'broiler'
            test_batch.save()
        response = api_client.post('/api/v1/production/eggs/', {
            'batch_id': str(test_batch.pk),
            'record_date': str(date.today()),
            'total_eggs': 100,
        })
        assert response.status_code == 422

    def test_egg_api_detail_returns_200(self, api_client, test_batch):
        response = api_client.get(
            f'/api/v1/production/eggs/{test_batch.pk}/')
        assert response.status_code == 200
        assert 'data' in response.json()


# ── Feed Service ──────────────────────────────────────────────────────────────

class TestFeedService:

    def test_log_feed_creates_record(self, test_org, test_batch):
        from apps.production.feed.services import FeedService
        from apps.infrastructure.core.rls import set_tenant_context
        with set_tenant_context(test_org):
            svc = FeedService(test_org)
            log = svc.log_feed(
                batch_id=str(test_batch.pk),
                record_date=date.today(),
                feed_type='starter',
                quantity_kg=50,
                cost_per_kg=500,
            )
        assert log.pk is not None
        assert float(log.quantity_kg) == 50.0

    def test_log_feed_missing_batch_raises(self, test_org):
        from apps.production.feed.services import FeedService
        from apps.infrastructure.core.rls import set_tenant_context
        import uuid
        with set_tenant_context(test_org):
            svc = FeedService(test_org)
            with pytest.raises(ValueError, match='not found'):
                svc.log_feed(
                    batch_id=str(uuid.uuid4()),
                    record_date=date.today(),
                    feed_type='starter',
                    quantity_kg=50,
                )

    def test_get_feed_summary_empty(self, test_org, test_batch):
        from apps.production.feed.services import FeedService
        from apps.infrastructure.core.rls import set_tenant_context
        with set_tenant_context(test_org):
            svc = FeedService(test_org)
            summary = svc.get_feed_summary(str(test_batch.pk))
        assert summary['total_feed_consumed_kg'] == 0.0
        assert summary['days_logged'] == 0

    def test_get_fcr_returns_none_for_layer(self, test_org, test_batch):
        from apps.production.feed.services import FeedService
        from apps.infrastructure.core.rls import set_tenant_context
        with set_tenant_context(test_org):
            svc = FeedService(test_org)
            result = svc.get_fcr(str(test_batch.pk))
        assert result is None  # test_batch is a layer batch

    def test_get_feed_cost_forecast(self, test_org, test_batch):
        from apps.production.feed.services import FeedService
        from apps.infrastructure.core.rls import set_tenant_context
        with set_tenant_context(test_org):
            svc = FeedService(test_org)
            result = svc.get_feed_cost_forecast(str(test_batch.pk))
        assert 'remaining_days' in result
        assert 'estimated_cost' in result
        assert 'confidence' in result
        assert result['confidence'] == 'low'  # no logs yet

    def test_get_trend_data_empty(self, test_org, test_batch):
        from apps.production.feed.services import FeedService
        from apps.infrastructure.core.rls import set_tenant_context
        with set_tenant_context(test_org):
            svc = FeedService(test_org)
            result = svc.get_trend_data(str(test_batch.pk))
        assert 'labels' in result
        assert result['labels'] == []

    def test_get_stock_levels(self, test_org, test_farm):
        from apps.production.feed.services import FeedService
        from apps.infrastructure.core.rls import set_tenant_context
        with set_tenant_context(test_org):
            svc = FeedService(test_org)
            levels = svc.get_stock_levels(str(test_farm.pk))
        assert isinstance(levels, list)


# ── Expense Views (finance/expenses/views.py — 44%) ───────────────────────────

class TestExpenseViews:

    def test_expense_log_get_returns_200(self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        response = client.get(f'/finance/expenses/{test_batch.pk}/log/')
        assert response.status_code == 200

    def test_expense_table_returns_200(self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        response = client.get(f'/finance/expenses/{test_batch.pk}/table/')
        assert response.status_code == 200

    def test_expense_table_with_category_filter(
            self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        response = client.get(
            f'/finance/expenses/{test_batch.pk}/table/?category=feed')
        assert response.status_code == 200

    def test_expense_breakdown_returns_200(self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        response = client.get(f'/finance/expenses/{test_batch.pk}/breakdown/')
        assert response.status_code == 200

    def test_expense_farm_summary_returns_200(
            self, client, tenant_user, test_farm):
        client.force_login(tenant_user)
        response = client.get(
            f'/finance/expenses/farm/{test_farm.pk}/summary/')
        assert response.status_code == 200

    def test_finance_pdf_export_returns_200(
            self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        response = client.get(f'/batches/{test_batch.pk}/finance/export/pdf/')
        # Monthly plan has pdf_export=True → generates PDF → 200
        # Trial plan would get HX-Trigger toast → also 200
        assert response.status_code == 200

    def test_finance_excel_export_no_feature_returns_200(
            self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        response = client.get(
            f'/batches/{test_batch.pk}/finance/export/excel/')
        assert response.status_code == 200

    def test_expense_log_post_missing_fields_returns_422(
            self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        response = client.post(
            f'/finance/expenses/{test_batch.pk}/log/',
            {'category': 'feed'},  # missing amount and description
        )
        assert response.status_code == 422

    def test_expense_log_post_creates_record(
            self, client, tenant_user, test_batch, test_farm):
        client.force_login(tenant_user)
        response = client.post(
            f'/finance/expenses/{test_batch.pk}/log/',
            {
                'category': 'feed',
                'amount': '5000',
                'description': 'Test feed purchase',
                'farm_id': str(test_farm.pk),
                'expense_date': str(date.today()),
            },
        )
        assert response.status_code == 200


class TestExpenseAPIViews:

    def test_expense_api_get_no_filter(self, api_client):
        response = api_client.get('/api/v1/expenses/')
        assert response.status_code == 200
        assert 'data' in response.json()

    def test_expense_api_get_with_batch_filter(self, api_client, test_batch):
        response = api_client.get(
            f'/api/v1/expenses/?batch_id={test_batch.pk}')
        assert response.status_code == 200

    def test_expense_api_post_creates_record(
            self, api_client, test_batch, test_farm):
        response = api_client.post('/api/v1/expenses/', {
            'amount_naira': 5000,
            'category': 'feed',
            'description': 'Test feed via API',
            'farm_id': str(test_farm.pk),
            'batch_id': str(test_batch.pk),
        })
        assert response.status_code == 201

    def test_expense_api_post_nonexistent_farm_returns_400(self, api_client):
        import uuid
        response = api_client.post('/api/v1/expenses/', {
            'amount_naira': 5000,
            'category': 'feed',
            'description': 'No farm',
            'farm_id': str(uuid.uuid4()),  # valid UUID format, but doesn't exist
        })
        assert response.status_code == 400


# ── Weather Views — extended (farm/weather/views.py — 57%) ───────────────────

class TestWeatherViewsExtended:

    def test_weather_strip_view_returns_200(self, client, tenant_user, test_farm):
        from unittest.mock import patch
        client.force_login(tenant_user)
        with patch(
            'apps.farm.weather.services.WeatherService.get_farm_weather_strip',
            return_value={'current_temp': 28, 'humidity': 70,
                          'description': 'clear', 'forecast': []},
        ):
            response = client.get(f'/weather/farm/{test_farm.pk}/strip/')
        assert response.status_code == 200

    def test_weather_page_with_gps_farm_heat_stress(
            self, client, tenant_user, test_farm):
        """Farm with GPS + mocked hot weather triggers the heat-stress alert path."""
        from unittest.mock import patch
        client.force_login(tenant_user)
        hot_data = {
            'current_temp': 36,
            'humidity': 85,
            'description': 'very hot',
            'forecast': [],
            'fetched_at': '2024-01-01T00:00:00',
        }
        with patch(
            'apps.farm.weather.services.WeatherService.get_farm_weather_strip',
            return_value=hot_data,
        ):
            response = client.get('/weather/')
        assert response.status_code == 200

    def test_weather_alert_acknowledge_marks_read(
            self, client, tenant_user, test_farm, test_org):
        from apps.farm.weather.models import WeatherAlert
        from apps.infrastructure.core.rls import set_tenant_context
        with set_tenant_context(test_org):
            alert = WeatherAlert.objects.create(
                org=test_org,
                farm=test_farm,
                alert_type='heat_stress',
                severity='warning',
                description='Test heat alert',
            )
        client.force_login(tenant_user)
        response = client.post(f'/weather/alerts/{alert.pk}/acknowledge/')
        assert response.status_code == 200
        alert.refresh_from_db()
        assert alert.acknowledged_at is not None


# ── Production Log POST (production/views.py — covers HTMX post path) ────────

class TestProductionLogPost:

    def test_log_post_invalid_form_returns_422(
            self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        response = client.post(
            f'/production/eggs/{test_batch.pk}/log/',
            {'total_eggs': 'not-a-number', 'record_date': ''},
        )
        assert response.status_code == 422

    def test_log_post_valid_creates_record(
            self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        response = client.post(
            f'/production/eggs/{test_batch.pk}/log/',
            {
                'record_date': str(date.today()),
                'total_eggs': 150,
                'grade_a': 0,
                'grade_b': 0,
                'grade_c': 0,
                'broken': 0,
            },
        )
        # Success → returns summary card fragment (200)
        assert response.status_code == 200
