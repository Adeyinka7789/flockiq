import pytest

pytestmark = pytest.mark.django_db


class TestBreedBenchmarks:
    def test_get_benchmark_cobb500(self):
        from apps.health.analytics.breed_benchmarks import get_benchmark
        b = get_benchmark('Cobb 500', 'broiler')
        assert b['target_fcr'] == 1.65
        assert b['type'] == 'broiler'

    def test_get_benchmark_alias(self):
        from apps.health.analytics.breed_benchmarks import get_benchmark
        b = get_benchmark('cobb', 'broiler')
        assert b['name'] == 'Cobb 500'

    def test_get_benchmark_fallback(self):
        from apps.health.analytics.breed_benchmarks import get_benchmark
        b = get_benchmark('unknown breed', 'broiler')
        assert 'target_fcr' in b

    def test_get_benchmark_layer(self):
        from apps.health.analytics.breed_benchmarks import get_benchmark
        b = get_benchmark('Hy-Line', 'layer')
        assert 'target_hen_day_pct' in b

    def test_compare_batch_good_fcr(self, test_batch):
        from apps.health.analytics.breed_benchmarks import compare_batch_to_benchmark
        from apps.infrastructure.core.rls import set_tenant_context
        with set_tenant_context(test_batch.org):
            test_batch.breed_name = 'Cobb 500'
            test_batch.bird_type = 'broiler'
            test_batch.save()
        result = compare_batch_to_benchmark(test_batch, fcr=1.60)
        assert result['comparisons'][0]['status'] == 'good'

    def test_compare_batch_bad_fcr(self, test_batch):
        from apps.health.analytics.breed_benchmarks import compare_batch_to_benchmark
        from apps.infrastructure.core.rls import set_tenant_context
        with set_tenant_context(test_batch.org):
            test_batch.breed_name = 'Cobb 500'
            test_batch.bird_type = 'broiler'
            test_batch.save()
        result = compare_batch_to_benchmark(test_batch, fcr=2.50)
        assert result['comparisons'][0]['status'] == 'critical'

    def test_compare_batch_mortality(self, test_batch):
        from apps.health.analytics.breed_benchmarks import compare_batch_to_benchmark
        result = compare_batch_to_benchmark(test_batch, mortality_rate=2.0)
        assert len(result['comparisons']) > 0


class TestFarmMemoryService:
    def test_init(self, tenant_user, test_batch):
        from apps.health.analytics.farm_memory import FarmMemoryService
        svc = FarmMemoryService(tenant_user.org, test_batch)
        assert svc.org == tenant_user.org
        assert svc.batch == test_batch

    def test_get_mortality_patterns_no_history(self, tenant_user, test_batch):
        from apps.health.analytics.farm_memory import FarmMemoryService
        svc = FarmMemoryService(tenant_user.org, test_batch)
        patterns = svc.get_mortality_patterns()
        assert isinstance(patterns, list)

    def test_get_feed_patterns_no_data(self, tenant_user, test_batch):
        from apps.health.analytics.farm_memory import FarmMemoryService
        svc = FarmMemoryService(tenant_user.org, test_batch)
        patterns = svc.get_feed_patterns()
        assert isinstance(patterns, list)

    def test_get_all_patterns_returns_list(self, tenant_user, test_batch):
        from apps.health.analytics.farm_memory import FarmMemoryService
        svc = FarmMemoryService(tenant_user.org, test_batch)
        patterns = svc.get_all_patterns()
        assert isinstance(patterns, list)

    def test_get_performance_grade(self, tenant_user, test_batch):
        from apps.health.analytics.farm_memory import FarmMemoryService
        from apps.infrastructure.core.rls import set_tenant_context
        with set_tenant_context(tenant_user.org):
            test_batch.breed_name = 'Cobb 500'
            test_batch.save()
        svc = FarmMemoryService(tenant_user.org, test_batch)
        grade = svc.get_batch_performance_grade(fcr=1.70, mortality_rate=3.0)
        assert 'grade' in grade
        assert grade['grade'] in ['A', 'B', 'C', 'D']


class TestAIDailyBriefModel:
    def test_create_brief(self, tenant_user):
        from apps.health.analytics.models import AIDailyBrief
        from apps.infrastructure.core.rls import set_tenant_context
        from datetime import date
        with set_tenant_context(tenant_user.org):
            brief = AIDailyBrief.objects.create(
                org=tenant_user.org,
                brief_date=date.today(),
                overall_status='optimal',
                headline='All systems normal',
                critical_count=0,
                warning_count=0,
            )
            assert brief.pk is not None
            assert str(brief) != ''

    def test_brief_unique_per_day(self, tenant_user):
        from apps.health.analytics.models import AIDailyBrief
        from apps.infrastructure.core.rls import set_tenant_context
        from datetime import date
        from django.db import IntegrityError
        with set_tenant_context(tenant_user.org):
            AIDailyBrief.objects.create(
                org=tenant_user.org,
                brief_date=date.today(),
                overall_status='optimal',
                headline='Test',
            )
            with pytest.raises(IntegrityError):
                AIDailyBrief.objects.create(
                    org=tenant_user.org,
                    brief_date=date.today(),
                    overall_status='optimal',
                    headline='Duplicate',
                )


class TestAIDeepDiveView:
    def test_deep_dive_200(self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        response = client.get(f'/ai/insights/{test_batch.pk}/')
        assert response.status_code == 200

    def test_deep_dive_requires_login(self, client, test_batch):
        response = client.get(f'/ai/insights/{test_batch.pk}/')
        assert response.status_code == 302

    def test_deep_dive_context_keys(self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        response = client.get(f'/ai/insights/{test_batch.pk}/')
        ctx = response.context
        assert 'batch' in ctx
        assert 'benchmark_result' in ctx
        assert 'all_patterns' in ctx
        assert 'performance_grade' in ctx
        assert 'mort_trend' in ctx

    def test_deep_dive_wrong_org(self, client, tenant_user, test_batch):
        from apps.infrastructure.accounts.models import CustomUser
        from apps.infrastructure.tenants.models import Organization
        other_org = Organization.objects.create(
            name='Other Org',
            subdomain='other-org-test',
        )
        other_user = CustomUser.objects.create_user(
            username='otheruser',
            email='other@testfarm.com',
            password='Test2026!',
            org=other_org,
            role='owner',
        )
        client.force_login(other_user)
        response = client.get(f'/ai/insights/{test_batch.pk}/')
        assert response.status_code == 404
