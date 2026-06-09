import pytest

pytestmark = pytest.mark.django_db


class TestTenantDetailView:
    def test_superadmin_can_access_tenant_detail(self, client, super_admin_user, test_org):
        client.force_login(super_admin_user)
        response = client.get(f'/superadmin/tenants/{test_org.pk}/')
        assert response.status_code == 200

    def test_non_superadmin_cannot_access_tenant_detail(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get(f'/superadmin/tenants/{tenant_user.org.pk}/')
        assert response.status_code == 302

    def test_anonymous_cannot_access_tenant_detail(self, client, test_org):
        response = client.get(f'/superadmin/tenants/{test_org.pk}/')
        assert response.status_code == 302

    def test_context_contains_required_keys(self, client, super_admin_user, test_org, tenant_user):
        client.force_login(super_admin_user)
        response = client.get(f'/superadmin/tenants/{test_org.pk}/')
        ctx = response.context
        assert ctx['org'] == test_org
        assert ctx['owner'] == tenant_user
        assert 'farms' in ctx
        assert 'payments' in ctx
        assert 'team_members' in ctx
        assert 'support_tickets' in ctx
        assert 'total_live_birds' in ctx
        assert 'farms_count' in ctx
        assert 'batches_count' in ctx

    def test_404_for_nonexistent_org(self, client, super_admin_user):
        import uuid
        client.force_login(super_admin_user)
        response = client.get(f'/superadmin/tenants/{uuid.uuid4()}/')
        assert response.status_code == 404
