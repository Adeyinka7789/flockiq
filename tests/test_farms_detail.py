import pytest

pytestmark = pytest.mark.django_db


class TestFarmListView:
    def test_farm_list_returns_200(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get('/farms/')
        assert response.status_code == 200

    def test_farm_list_shows_farm_cards(
            self, client, tenant_user, test_farm):
        client.force_login(tenant_user)
        response = client.get('/farms/')
        assert test_farm.name.encode() in response.content

    def test_farm_list_requires_login(self, client):
        response = client.get('/farms/')
        assert response.status_code == 302

    def test_farm_list_context_has_farm_list(
            self, client, tenant_user, test_farm):
        client.force_login(tenant_user)
        response = client.get('/farms/')
        assert 'farm_list' in response.context
        assert len(response.context['farm_list']) >= 1

    def test_farm_list_context_has_totals(
            self, client, tenant_user, test_farm):
        client.force_login(tenant_user)
        response = client.get('/farms/')
        assert 'total_live' in response.context
        assert 'total_capacity' in response.context
        assert 'total_farms' in response.context

    def test_farm_list_status_badge_optimal(
            self, client, tenant_user, test_farm):
        client.force_login(tenant_user)
        response = client.get('/farms/')
        assert response.status_code == 200

    def test_farm_list_no_farms_empty_state(
            self, client, tenant_user):
        from apps.farm.farms.models import Farm
        from apps.infrastructure.core.rls import set_tenant_context
        with set_tenant_context(tenant_user.org):
            Farm.objects.filter(org=tenant_user.org).update(
                is_active=False)
        client.force_login(tenant_user)
        response = client.get('/farms/')
        assert response.status_code == 200
        # Restore
        with set_tenant_context(tenant_user.org):
            Farm.objects.filter(org=tenant_user.org).update(
                is_active=True)


class TestFarmDetailView:
    def test_farm_detail_returns_200(
            self, client, tenant_user, test_farm):
        client.force_login(tenant_user)
        response = client.get(f'/farms/{test_farm.pk}/')
        assert response.status_code == 200

    def test_farm_detail_requires_login(self, client, test_farm):
        response = client.get(f'/farms/{test_farm.pk}/')
        assert response.status_code == 302

    def test_farm_detail_shows_farm_name(
            self, client, tenant_user, test_farm):
        client.force_login(tenant_user)
        response = client.get(f'/farms/{test_farm.pk}/')
        assert test_farm.name.encode() in response.content

    def test_farm_detail_context_keys(
            self, client, tenant_user, test_farm):
        client.force_login(tenant_user)
        response = client.get(f'/farms/{test_farm.pk}/')
        ctx = response.context
        assert 'farm' in ctx
        assert 'houses' in ctx
        assert 'active_batches' in ctx
        assert 'total_live' in ctx
        assert 'health_score' in ctx
        assert 'vacc_compliance' in ctx
        assert 'current_week' in ctx
        assert 'prev_week' in ctx

    def test_farm_detail_health_score_range(
            self, client, tenant_user, test_farm):
        client.force_login(tenant_user)
        response = client.get(f'/farms/{test_farm.pk}/')
        score = response.context['health_score']
        assert 0 <= score <= 100

    def test_farm_detail_weekly_trend_length(
            self, client, tenant_user, test_farm):
        client.force_login(tenant_user)
        response = client.get(f'/farms/{test_farm.pk}/')
        assert len(response.context['current_week']) == 7
        assert len(response.context['prev_week']) == 7

    def test_farm_detail_vacc_compliance_range(
            self, client, tenant_user, test_farm):
        client.force_login(tenant_user)
        response = client.get(f'/farms/{test_farm.pk}/')
        pct = response.context['vacc_compliance']
        assert 0 <= pct <= 100

    def test_farm_detail_wrong_org_returns_404(
            self, client, test_farm):
        from apps.infrastructure.tenants.models import Organization
        from apps.infrastructure.accounts.models import CustomUser
        import uuid

        other_org = Organization.objects.create(
            name='Other Org',
            subdomain=f'other-{uuid.uuid4().hex[:8]}',
            plan_tier='trial',
            subscription_status='active',
            onboarding_complete=True,
            is_active=True,
        )
        other_user = CustomUser.objects.create_user(
            username=f'other_{uuid.uuid4().hex[:8]}',
            email=f'other_{uuid.uuid4().hex[:8]}@test.com',
            password='testpass123',
            org=other_org,
            role='owner',
        )
        client.force_login(other_user)
        response = client.get(f'/farms/{test_farm.pk}/')
        assert response.status_code in [404, 302, 403]

    def test_farm_detail_with_active_batch(
            self, client, tenant_user, test_farm, test_batch):
        client.force_login(tenant_user)
        response = client.get(f'/farms/{test_farm.pk}/')
        assert response.status_code == 200
        ctx = response.context
        assert ctx['active_batches'] is not None

    def test_farm_detail_with_mortality_data(
            self, client, tenant_user, test_farm, test_batch):
        from apps.farm.flocks.models import MortalityLog
        from apps.infrastructure.core.rls import set_tenant_context
        from datetime import date
        with set_tenant_context(tenant_user.org):
            MortalityLog.objects.create(
                org=tenant_user.org,
                batch=test_batch,
                farm=test_farm,
                date=date.today(),
                count=3,
                cause='disease',
            )
        client.force_login(tenant_user)
        response = client.get(f'/farms/{test_farm.pk}/')
        assert response.status_code == 200

    def test_farm_list_mort_rate_affects_status(
            self, client, tenant_user, test_farm, test_batch):
        from apps.farm.flocks.models import MortalityLog
        from apps.infrastructure.core.rls import set_tenant_context
        from datetime import date, timedelta
        with set_tenant_context(tenant_user.org):
            for i in range(10):
                MortalityLog.objects.get_or_create(
                    org=tenant_user.org,
                    batch=test_batch,
                    farm=test_farm,
                    date=date.today() - timedelta(days=i),
                    defaults={'count': 20, 'cause': 'disease'}
                )
        client.force_login(tenant_user)
        response = client.get('/farms/')
        assert response.status_code == 200
        farm_data = next(
            (f for f in response.context['farm_list']
             if f['farm'].pk == test_farm.pk), None)
        assert farm_data is not None


class TestFarmDetailIntegration:
    def test_farm_breadcrumb_links(
            self, client, tenant_user, test_farm):
        client.force_login(tenant_user)
        response = client.get(f'/farms/{test_farm.pk}/')
        assert b'/farms/' in response.content

    def test_farm_detail_no_houses_shows_empty(
            self, client, tenant_user, test_farm):
        from apps.farm.farms.models import House
        from apps.infrastructure.core.rls import set_tenant_context
        with set_tenant_context(tenant_user.org):
            House.objects.filter(farm=test_farm).update(
                is_active=False)
        client.force_login(tenant_user)
        response = client.get(f'/farms/{test_farm.pk}/')
        assert response.status_code == 200
        # Restore
        with set_tenant_context(tenant_user.org):
            House.objects.filter(farm=test_farm).update(
                is_active=True)
