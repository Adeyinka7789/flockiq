import pytest
from django.http import Http404, HttpResponse

pytestmark = pytest.mark.django_db


# ── Organization model tests ─────────────────────────────────────────────────

class TestOrganizationModel:

    def test_str_representation(self, db):
        from apps.infrastructure.tenants.models import Organization
        org = Organization.objects.create(name="ApeCheck Farms", subdomain="apecheck")
        assert str(org) == "ApeCheck Farms (apecheck)"

    def test_is_on_trial_true(self, db):
        from apps.infrastructure.tenants.models import Organization
        from django.utils import timezone
        from datetime import timedelta
        org = Organization.objects.create(
            name="Trial Org",
            subdomain="trialorg",
            plan_tier="trial",
            trial_ends_at=timezone.now() + timedelta(days=10),
        )
        assert org.is_on_trial is True

    def test_is_on_trial_expired(self, db):
        from apps.infrastructure.tenants.models import Organization
        from django.utils import timezone
        from datetime import timedelta
        org = Organization.objects.create(
            name="Expired Org",
            subdomain="expiredorg",
            plan_tier="trial",
            trial_ends_at=timezone.now() - timedelta(days=1),
        )
        assert org.is_on_trial is False

    def test_is_on_trial_not_trial_plan(self, db):
        from apps.infrastructure.tenants.models import Organization
        org = Organization.objects.create(
            name="Monthly Org",
            subdomain="monthlyorg",
            plan_tier="monthly",
        )
        assert org.is_on_trial is False

    def test_default_settings_properties(self, db):
        from apps.infrastructure.tenants.models import Organization
        org = Organization.objects.create(name="Defaults Org", subdomain="defaultsorg")
        assert org.sms_alerts_enabled is True
        assert org.email_alerts_enabled is True
        assert org.white_label_enabled is False


# ── Subdomain validation tests ────────────────────────────────────────────────

class TestSubdomainValidation:

    def test_valid_subdomain(self):
        from apps.infrastructure.tenants.serializers import OrganizationOnboardingSerializer
        s = OrganizationOnboardingSerializer(data={
            "name": "Test Farm",
            "subdomain": "apecheck",
            "owner_name": "Michael",
            "owner_phone": "+2348012345678",
            "owner_email": "michael@test.com",
        })
        assert s.is_valid(), s.errors

    def test_reserved_subdomain_rejected(self):
        from apps.infrastructure.tenants.serializers import OrganizationOnboardingSerializer
        for reserved in ["www", "api", "admin", "app"]:
            s = OrganizationOnboardingSerializer(data={
                "name": "Test Farm",
                "subdomain": reserved,
                "owner_name": "Michael",
                "owner_phone": "+2348012345678",
                "owner_email": "michael@test.com",
            })
            assert not s.is_valid(), f"Expected {reserved!r} to be rejected"
            assert "subdomain" in s.errors

    def test_uppercase_subdomain_rejected(self):
        from apps.infrastructure.tenants.serializers import OrganizationOnboardingSerializer
        s = OrganizationOnboardingSerializer(data={
            "name": "Test",
            "subdomain": "ApeCheck",
            "owner_name": "Michael",
            "owner_phone": "+2348012345678",
            "owner_email": "michael@test.com",
        })
        assert not s.is_valid()
        assert "subdomain" in s.errors


# ── Middleware tests ──────────────────────────────────────────────────────────

class TestTenantMiddleware:

    def test_localhost_bypasses_resolution(self, db, rf):
        """Dev mode: localhost should not attempt tenant lookup; org is None."""
        from apps.infrastructure.core.middleware import TenantMiddleware

        middleware = TenantMiddleware(lambda req: HttpResponse("ok"))
        request = rf.get("/", SERVER_NAME="localhost")
        response = middleware(request)
        assert response.status_code == 200
        assert request.org is None

    def test_127_0_0_1_bypasses_resolution(self, db, rf):
        """127.0.0.1 also bypasses tenant resolution."""
        from apps.infrastructure.core.middleware import TenantMiddleware

        middleware = TenantMiddleware(lambda req: HttpResponse("ok"))
        request = rf.get("/", SERVER_NAME="127.0.0.1")
        response = middleware(request)
        assert response.status_code == 200
        assert request.org is None

    def test_unknown_subdomain_raises_404(self, db, rf):
        """Unknown subdomain with no matching Organization raises Http404."""
        from apps.infrastructure.core.middleware import TenantMiddleware

        middleware = TenantMiddleware(lambda req: HttpResponse("should not reach"))
        request = rf.get("/", SERVER_NAME="unknowntenant.flockiq.com")
        with pytest.raises(Http404):
            middleware(request)

    def test_known_subdomain_sets_org(self, db, rf):
        """A request to a known subdomain attaches the org to the request."""
        from apps.infrastructure.tenants.models import Organization
        from apps.infrastructure.core.middleware import TenantMiddleware

        org = Organization.objects.create(
            name="Known Farm",
            subdomain="knownfarm",
            is_active=True,
        )

        captured = {}

        def view(req):
            captured["org"] = req.org
            return HttpResponse("ok")

        middleware = TenantMiddleware(view)
        request = rf.get("/", SERVER_NAME="knownfarm.flockiq.com")
        response = middleware(request)
        assert response.status_code == 200
        assert captured["org"].id == org.id

    def test_inactive_org_redirects_authenticated_user(self, db, rf, tenant_user):
        """An authenticated user on a suspended org's subdomain is logged out
        and bounced to /login/?suspended=1 (no longer a bare 404)."""
        from django.contrib.sessions.middleware import SessionMiddleware

        from apps.infrastructure.tenants.models import Organization
        from apps.infrastructure.core.middleware import TenantMiddleware

        Organization.objects.create(
            name="Inactive Farm",
            subdomain="inactivefarm",
            is_active=False,
        )

        middleware = TenantMiddleware(lambda req: HttpResponse("should not reach"))
        request = rf.get("/", SERVER_NAME="inactivefarm.flockiq.com")
        # logout() needs a session attached.
        SessionMiddleware(lambda r: HttpResponse()).process_request(request)
        request.session.save()
        request.user = tenant_user  # authenticated, non-superadmin

        response = middleware(request)
        assert response.status_code == 302
        assert "/login/?suspended=1" in response["Location"]

    def test_inactive_org_anonymous_falls_through(self, db, rf):
        """Anonymous requests to a suspended subdomain fall through so the
        login page can render with a suspension banner (no redirect loop)."""
        from django.contrib.auth.models import AnonymousUser

        from apps.infrastructure.tenants.models import Organization
        from apps.infrastructure.core.middleware import TenantMiddleware

        Organization.objects.create(
            name="Inactive Farm 2",
            subdomain="inactivefarm2",
            is_active=False,
        )

        middleware = TenantMiddleware(lambda req: HttpResponse("login page"))
        request = rf.get("/", SERVER_NAME="inactivefarm2.flockiq.com")
        request.user = AnonymousUser()

        response = middleware(request)
        assert response.status_code == 200
