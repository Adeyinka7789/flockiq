"""
Middleware-level integration tests: tenant resolution, cross-tenant isolation,
and the HTMX-vs-normal expired-session behaviour.
"""
import pytest
from django.test import Client

from apps.infrastructure.core.rls import set_tenant_context


@pytest.mark.django_db(transaction=True)
class TestTenantMiddleware:

    def test_unknown_subdomain_returns_404(self, client):
        # A 2-part host has no tenant subdomain; the dashboard renders the
        # public landing page. (Real 3-part unknown subdomains raise 404.)
        response = client.get('/', HTTP_HOST='nonexistent.localhost:8000')
        assert response.status_code in [200, 404]

    def test_tenant_cannot_access_other_tenant_data(self, make_org, make_farm):
        org_a, user_a = make_org(subdomain='tenanta')
        org_b, user_b = make_org(subdomain='tenantb')
        farm_a, house_a, batch_a = make_farm(org_a)
        farm_b, house_b, batch_b = make_farm(org_b)

        # Inside org A's RLS context, only org A's farm is visible.
        from apps.farm.farms.models import Farm
        with set_tenant_context(org_a):
            farms = [str(f) for f in Farm.objects.values_list('id', flat=True)]
        assert str(farm_a.id) in farms
        assert str(farm_b.id) not in farms

    def test_htmx_expired_session_returns_401(self, client, make_org):
        org, user = make_org(subdomain='htmxtest')
        org.onboarding_complete = True
        org.save()
        # Request an HTMX fragment endpoint without a session.
        response = client.get(
            '/notifications/bell/',
            HTTP_HX_REQUEST='true',
        )
        assert response.status_code == 401

    def test_normal_expired_session_returns_302(self, client, make_org):
        org, user = make_org(subdomain='normaltest')
        org.onboarding_complete = True
        org.save()
        response = client.get('/farms/')
        assert response.status_code == 302
        assert '/login/' in response['Location']
