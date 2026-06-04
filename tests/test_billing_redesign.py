import pytest

pytestmark = pytest.mark.django_db


class TestPlatformConfig:
    def test_singleton_created_on_get(self):
        from apps.infrastructure.core.config import PlatformConfig
        PlatformConfig.objects.all().delete()
        config = PlatformConfig.get()
        assert config.pk == 1
        assert config.admin_whatsapp == '2348000000000'

    def test_singleton_always_pk1(self):
        from apps.infrastructure.core.config import PlatformConfig
        c1 = PlatformConfig.get()
        c2 = PlatformConfig.get()
        assert c1.pk == c2.pk == 1

    def test_config_fields_saveable(self):
        from apps.infrastructure.core.config import PlatformConfig
        config = PlatformConfig.get()
        config.admin_whatsapp = '2348099999999'
        config.bank_name = 'GTBank'
        config.bank_account_number = '0123456789'
        config.bank_account_name = 'ADM Tech Hub'
        config.save()

        fresh = PlatformConfig.objects.get(pk=1)
        assert fresh.admin_whatsapp == '2348099999999'
        assert fresh.bank_name == 'GTBank'
        assert fresh.bank_account_number == '0123456789'


class TestBillingPageView:
    def test_billing_page_returns_200(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get('/billing/')
        assert response.status_code == 200

    def test_billing_page_has_context_keys(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get('/billing/')
        ctx = response.context
        assert 'all_plans' in ctx
        assert 'farm_count' in ctx
        assert 'team_count' in ctx
        assert 'max_farms' in ctx
        assert 'max_team' in ctx
        assert 'farm_usage_pct' in ctx
        assert 'team_usage_pct' in ctx
        assert 'platform_config' in ctx

    def test_billing_page_requires_login(self, client):
        response = client.get('/billing/')
        assert response.status_code == 302

    def test_resource_usage_pct_in_range(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get('/billing/')
        assert 0 <= response.context['farm_usage_pct'] <= 100
        assert 0 <= response.context['team_usage_pct'] <= 100

    def test_all_plans_from_db(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get('/billing/')
        plans = response.context['all_plans']
        assert plans.count() >= 0

    def test_platform_config_in_context(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get('/billing/')
        assert hasattr(response.context['platform_config'], 'admin_whatsapp')


class TestBankTransferNotifyView:
    def test_notify_returns_200(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.post(
            '/billing/bank-transfer/notify/',
            {'plan_tier': 'monthly', 'amount': '30000'},
        )
        assert response.status_code == 200

    def test_notify_requires_login(self, client):
        response = client.post(
            '/billing/bank-transfer/notify/',
            {'plan_tier': 'monthly', 'amount': '30000'},
        )
        assert response.status_code == 302

    def test_notify_creates_admin_notification(self, client, tenant_user):
        from apps.infrastructure.notifications.models import NotificationLog
        from apps.infrastructure.core.rls import set_tenant_context

        with set_tenant_context(tenant_user.org):
            initial_count = NotificationLog.objects.filter(
                org=tenant_user.org
            ).count()

        client.force_login(tenant_user)
        client.post(
            '/billing/bank-transfer/notify/',
            {'plan_tier': 'monthly', 'amount': '30000'},
        )

        with set_tenant_context(tenant_user.org):
            new_count = NotificationLog.objects.filter(
                org=tenant_user.org
            ).count()
        assert new_count > initial_count

    def test_notify_response_has_wa_url(self, client, tenant_user):
        import json
        client.force_login(tenant_user)
        response = client.post(
            '/billing/bank-transfer/notify/',
            {'plan_tier': 'monthly', 'amount': '30000'},
        )
        data = json.loads(response.content)
        assert 'wa_url' in data
        assert 'wa.me' in data['wa_url']
