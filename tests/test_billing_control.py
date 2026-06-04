import pytest

pytestmark = pytest.mark.django_db


class TestBillingControlView:
    def test_billing_control_200(self, client, super_admin_user):
        client.force_login(super_admin_user)
        response = client.get('/superadmin/billing/')
        assert response.status_code == 200

    def test_billing_control_requires_superadmin(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get('/superadmin/billing/')
        assert response.status_code == 302

    def test_billing_context_keys(self, client, super_admin_user):
        client.force_login(super_admin_user)
        response = client.get('/superadmin/billing/')
        ctx = response.context
        assert 'mrr_naira' in ctx
        assert 'active_trials' in ctx
        assert 'past_due' in ctx
        assert 'org_list' in ctx

    def test_billing_manage_get(self, client, super_admin_user, tenant_user):
        client.force_login(super_admin_user)
        response = client.get(
            f'/superadmin/billing/{tenant_user.org.pk}/manage/',
            HTTP_HX_REQUEST='true',
        )
        assert response.status_code == 200

    def test_billing_manage_grace_period(self, client, super_admin_user, tenant_user):
        from datetime import date, timedelta
        client.force_login(super_admin_user)
        future = (date.today() + timedelta(days=14)).strftime('%Y-%m-%d')
        response = client.post(
            f'/superadmin/billing/{tenant_user.org.pk}/manage/',
            {'action': 'grace_period', 'grace_end_date': future},
        )
        assert response.status_code == 204
        tenant_user.org.refresh_from_db()
        assert tenant_user.org.grace_period_ends_at is not None

    def test_billing_manage_extend_trial(self, client, super_admin_user, tenant_user):
        client.force_login(super_admin_user)
        response = client.post(
            f'/superadmin/billing/{tenant_user.org.pk}/manage/',
            {'action': 'extend_trial', 'days': '14'},
        )
        assert response.status_code == 204

    def test_billing_manage_change_status(self, client, super_admin_user, tenant_user):
        client.force_login(super_admin_user)
        response = client.post(
            f'/superadmin/billing/{tenant_user.org.pk}/manage/',
            {'action': 'change_status', 'status': 'trial'},
        )
        assert response.status_code == 204
        tenant_user.org.refresh_from_db()
        assert tenant_user.org.subscription_status == 'trial'


class TestAuditTrailView:
    def test_audit_trail_200(self, client, super_admin_user):
        client.force_login(super_admin_user)
        response = client.get('/superadmin/audit/')
        assert response.status_code == 200

    def test_audit_trail_requires_superadmin(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get('/superadmin/audit/')
        assert response.status_code == 302

    def test_audit_trail_context_keys(self, client, super_admin_user):
        client.force_login(super_admin_user)
        response = client.get('/superadmin/audit/')
        ctx = response.context
        assert 'page_obj' in ctx
        assert 'total_count' in ctx
        assert 'all_orgs' in ctx
        assert 'this_week_count' in ctx

    def test_audit_trail_search_filter(self, client, super_admin_user):
        client.force_login(super_admin_user)
        response = client.get('/superadmin/audit/?q=test')
        assert response.status_code == 200

    def test_audit_trail_action_filter(self, client, super_admin_user):
        client.force_login(super_admin_user)
        response = client.get('/superadmin/audit/?action=create')
        assert response.status_code == 200

    def test_audit_trail_htmx_partial(self, client, super_admin_user):
        client.force_login(super_admin_user)
        response = client.get('/superadmin/audit/', HTTP_HX_REQUEST='true')
        assert response.status_code == 200
