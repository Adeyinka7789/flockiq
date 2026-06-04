import pytest

pytestmark = pytest.mark.django_db


class TestTenantQuotas:
    def test_quotas_200(self, client, super_admin_user):
        client.force_login(super_admin_user)
        response = client.get('/superadmin/quotas/')
        assert response.status_code == 200

    def test_quotas_blocked_regular_user(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get('/superadmin/quotas/')
        assert response.status_code == 302

    def test_quotas_context_keys(self, client, super_admin_user):
        client.force_login(super_admin_user)
        response = client.get('/superadmin/quotas/')
        assert 'org_list' in response.context
        assert 'total_orgs' in response.context

    def test_quota_edit_get(self, client, super_admin_user, tenant_user):
        client.force_login(super_admin_user)
        response = client.get(
            f'/superadmin/quotas/{tenant_user.org.pk}/edit/',
            HTTP_HX_REQUEST='true')
        assert response.status_code == 200

    def test_quota_edit_post(self, client, super_admin_user, tenant_user):
        client.force_login(super_admin_user)
        response = client.post(
            f'/superadmin/quotas/{tenant_user.org.pk}/edit/',
            {'max_users': 10, 'storage_quota_gb': 20})
        assert response.status_code == 204
        tenant_user.org.refresh_from_db()
        assert tenant_user.org.max_users == 10
        assert tenant_user.org.storage_quota_gb == 20


class TestImpersonation:
    def test_impersonation_page_200(self, client, super_admin_user):
        client.force_login(super_admin_user)
        response = client.get('/superadmin/impersonation/')
        assert response.status_code == 200

    def test_impersonation_blocked_regular_user(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get('/superadmin/impersonation/')
        assert response.status_code == 302

    def test_impersonation_context_keys(self, client, super_admin_user):
        client.force_login(super_admin_user)
        response = client.get('/superadmin/impersonation/')
        assert 'users' in response.context
        assert 'recent_logs' in response.context

    def test_impersonate_start(self, client, super_admin_user, tenant_user):
        client.force_login(super_admin_user)
        response = client.post(
            f'/superadmin/impersonate/{tenant_user.pk}/start/',
            {'reason': 'Support test'})
        assert response.status_code == 302
        assert '_impersonated_user_id' in client.session

    def test_impersonate_stop(self, client, super_admin_user, tenant_user):
        client.force_login(super_admin_user)
        client.post(
            f'/superadmin/impersonate/{tenant_user.pk}/start/',
            {'reason': 'Test'})
        response = client.post('/superadmin/impersonate/stop/')
        assert response.status_code == 302
        assert '_impersonated_user_id' not in client.session

    def test_cannot_impersonate_super_admin(self, client, super_admin_user):
        client.force_login(super_admin_user)
        response = client.post(
            f'/superadmin/impersonate/{super_admin_user.pk}/start/',
            {'reason': 'Test'})
        assert response.status_code == 400

    def test_impersonation_log_created(self, client, super_admin_user, tenant_user):
        from apps.infrastructure.accounts.impersonation import ImpersonationLog
        initial = ImpersonationLog.objects.count()
        client.force_login(super_admin_user)
        client.post(
            f'/superadmin/impersonate/{tenant_user.pk}/start/',
            {'reason': 'Coverage test'})
        assert ImpersonationLog.objects.count() > initial


class TestSystemHealth:
    def test_system_health_200(self, client, super_admin_user):
        client.force_login(super_admin_user)
        response = client.get('/superadmin/system-health/')
        assert response.status_code == 200

    def test_system_health_blocked_regular_user(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get('/superadmin/system-health/')
        assert response.status_code == 302

    def test_system_health_context_keys(self, client, super_admin_user):
        client.force_login(super_admin_user)
        response = client.get('/superadmin/system-health/')
        ctx = response.context
        assert 'queue_size' in ctx
        assert 'failed_today' in ctx
        assert 'recent_tasks' in ctx
        assert 'success_rate' in ctx
        assert 'periodic_tasks' in ctx
