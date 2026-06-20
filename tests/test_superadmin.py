import pytest

pytestmark = pytest.mark.django_db


class TestSuperAdminMixin:
    def test_regular_user_redirected(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get('/superadmin/')
        assert response.status_code == 302

    def test_anonymous_redirected(self, client):
        response = client.get('/superadmin/')
        assert response.status_code == 302


class TestSuperAdminDashboard:
    def test_dashboard_returns_200(self, client, super_admin_user):
        client.force_login(super_admin_user)
        response = client.get('/superadmin/')
        assert response.status_code == 200

    def test_dashboard_context_keys(self, client, super_admin_user):
        client.force_login(super_admin_user)
        response = client.get('/superadmin/')
        ctx = response.context
        assert 'total_orgs' in ctx
        assert 'active_orgs' in ctx
        assert 'mrr_naira' in ctx
        assert 'revenue_trend' in ctx
        assert 'recent_orgs' in ctx

    def test_revenue_trend_length(self, client, super_admin_user):
        client.force_login(super_admin_user)
        response = client.get('/superadmin/')
        assert len(response.context['revenue_trend']) == 6


class TestSuperAdminTenants:
    def test_tenants_returns_200(self, client, super_admin_user):
        client.force_login(super_admin_user)
        response = client.get('/superadmin/tenants/')
        assert response.status_code == 200

    def test_tenants_context_keys(self, client, super_admin_user):
        client.force_login(super_admin_user)
        response = client.get('/superadmin/tenants/')
        ctx = response.context
        assert 'org_list' in ctx
        assert 'page_obj' in ctx
        assert 'total_count' in ctx

    def test_tenants_search_filter(self, client, super_admin_user):
        client.force_login(super_admin_user)
        response = client.get('/superadmin/tenants/?q=test')
        assert response.status_code == 200

    def test_tenants_status_filter(self, client, super_admin_user):
        client.force_login(super_admin_user)
        response = client.get('/superadmin/tenants/?status=active')
        assert response.status_code == 200

    def test_tenant_action_suspend(self, client, super_admin_user, tenant_user):
        org = tenant_user.org
        client.force_login(super_admin_user)
        response = client.post(
            f'/superadmin/tenants/{org.pk}/action/',
            {'action': 'suspend'},
        )
        assert response.status_code == 204
        org.refresh_from_db()
        assert org.is_active is False
        org.is_active = True
        org.save()

    def test_tenant_action_activate(self, client, super_admin_user, tenant_user):
        org = tenant_user.org
        org.is_active = False
        org.save()
        client.force_login(super_admin_user)
        response = client.post(
            f'/superadmin/tenants/{org.pk}/action/',
            {'action': 'activate'},
        )
        assert response.status_code == 204
        org.refresh_from_db()
        assert org.is_active is True

    def test_tenant_action_change_plan(self, client, super_admin_user, tenant_user):
        org = tenant_user.org
        client.force_login(super_admin_user)
        response = client.post(
            f'/superadmin/tenants/{org.pk}/action/',
            {'action': 'change_plan', 'plan_tier': 'monthly'},
        )
        assert response.status_code == 204
        org.refresh_from_db()
        assert org.plan_tier == 'monthly'


class TestSuperAdminSuspensionOrchestration:
    """Regression: superadmin suspend/activate still route through
    TenantService and notify the org owner end-to-end."""

    def test_suspend_action_sends_owner_email(
            self, client, super_admin_user, tenant_user):
        from unittest.mock import patch
        org = tenant_user.org
        client.force_login(super_admin_user)
        with patch("apps.infrastructure.tenants.services.EmailService") as mock_email:
            response = client.post(
                f'/superadmin/tenants/{org.pk}/action/',
                {'action': 'suspend'},
                HTTP_HX_PROMPT='Non-payment',
            )
        assert response.status_code == 204
        org.refresh_from_db()
        assert org.is_active is False
        assert org.suspension_reason == 'Non-payment'
        mock_email.send_suspension.assert_called_once()
        assert (mock_email.send_suspension.call_args.kwargs['recipient_email']
                == tenant_user.email)

    def test_activate_action_sends_owner_email(
            self, client, super_admin_user, tenant_user):
        from unittest.mock import patch
        org = tenant_user.org
        org.is_active = False
        org.suspension_reason = 'Non-payment'
        org.save()
        client.force_login(super_admin_user)
        with patch("apps.infrastructure.tenants.services.EmailService") as mock_email:
            response = client.post(
                f'/superadmin/tenants/{org.pk}/action/',
                {'action': 'activate'},
            )
        assert response.status_code == 204
        org.refresh_from_db()
        assert org.is_active is True
        assert org.suspension_reason == ''
        mock_email.send_reactivation.assert_called_once()


class TestSuperAdminAnalytics:
    def test_analytics_returns_200(self, client, super_admin_user):
        client.force_login(super_admin_user)
        response = client.get('/superadmin/analytics/')
        assert response.status_code == 200

    def test_analytics_context_keys(self, client, super_admin_user):
        client.force_login(super_admin_user)
        response = client.get('/superadmin/analytics/')
        ctx = response.context
        assert 'total_orgs' in ctx
        assert 'total_birds' in ctx
        assert 'total_revenue_naira' in ctx
        assert 'top_orgs' in ctx
        assert 'top_revenue_orgs' in ctx

    def test_regular_user_blocked(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get('/superadmin/analytics/')
        assert response.status_code == 302


class TestBroadcastFeature:
    def test_broadcast_form_get(self, client, super_admin_user):
        client.force_login(super_admin_user)
        response = client.get('/superadmin/broadcast/', HTTP_HX_REQUEST='true')
        assert response.status_code == 200

    def test_broadcast_post_creates_notifications(
            self, client, super_admin_user, tenant_user):
        from apps.infrastructure.notifications.models import NotificationLog
        initial = NotificationLog.objects.unscoped().count()
        client.force_login(super_admin_user)
        response = client.post('/superadmin/broadcast/', {
            'title': 'Test Announcement',
            'message': 'This is a test broadcast.',
            'audience': 'owners_managers',
            'channel': 'in_app',
        })
        assert response.status_code == 204
        assert NotificationLog.objects.unscoped().count() > initial

    def test_broadcast_post_missing_title(self, client, super_admin_user):
        client.force_login(super_admin_user)
        response = client.post('/superadmin/broadcast/', {
            'title': '',
            'message': 'Test',
            'audience': 'all',
            'channel': 'in_app',
        })
        assert response.status_code == 200

    def test_broadcast_history_returns_200(self, client, super_admin_user):
        client.force_login(super_admin_user)
        response = client.get('/superadmin/broadcasts/')
        assert response.status_code == 200

    def test_regular_user_cannot_broadcast(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.post('/superadmin/broadcast/', {
            'title': 'Hack',
            'message': 'Test',
            'audience': 'all',
            'channel': 'in_app',
        })
        assert response.status_code == 302
