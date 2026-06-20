from unittest.mock import patch

import pytest
from django.http import Http404, HttpResponse
from structlog.testing import capture_logs

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


# ── TenantService lifecycle tests ─────────────────────────────────────────────

class TestTenantService:
    """suspend_org / reactivate_org orchestration — status, owner email, logs."""

    def test_suspend_org_sets_status(self, db, tenant_user):
        from apps.infrastructure.tenants.services import TenantService
        org = tenant_user.org
        with patch("apps.infrastructure.tenants.services.EmailService"):
            TenantService.suspend_org(org, reason="Non-payment")
        org.refresh_from_db()
        assert org.is_active is False
        assert org.suspension_reason == "Non-payment"

    def test_suspend_org_emails_owner(self, db, tenant_user):
        from apps.infrastructure.tenants.services import TenantService
        org = tenant_user.org
        with patch("apps.infrastructure.tenants.services.EmailService") as mock_email:
            TenantService.suspend_org(org, reason="Non-payment")
        mock_email.send_suspension.assert_called_once()
        kwargs = mock_email.send_suspension.call_args.kwargs
        assert kwargs["recipient_email"] == tenant_user.email
        assert kwargs["reason"] == "Non-payment"

    def test_suspend_org_logs_event(self, db, tenant_user):
        from apps.infrastructure.tenants.services import TenantService
        org = tenant_user.org
        with patch("apps.infrastructure.tenants.services.EmailService"):
            with capture_logs() as logs:
                TenantService.suspend_org(org, suspended_by=tenant_user)
        assert any(
            e["event"] == "tenant.suspended"
            and e["org_id"] == str(org.pk)
            and e["suspended_by"] == str(tenant_user.pk)
            for e in logs
        )

    def test_reactivate_org_sets_status(self, db, tenant_user):
        from apps.infrastructure.tenants.services import TenantService
        org = tenant_user.org
        org.is_active = False
        org.suspension_reason = "old reason"
        org.save(update_fields=["is_active", "suspension_reason", "updated_at"])
        with patch("apps.infrastructure.tenants.services.EmailService"):
            TenantService.reactivate_org(org)
        org.refresh_from_db()
        assert org.is_active is True
        assert org.suspension_reason == ""

    def test_reactivate_org_emails_owner(self, db, tenant_user):
        from apps.infrastructure.tenants.services import TenantService
        org = tenant_user.org
        with patch("apps.infrastructure.tenants.services.EmailService") as mock_email:
            TenantService.reactivate_org(org)
        mock_email.send_reactivation.assert_called_once()
        kwargs = mock_email.send_reactivation.call_args.kwargs
        assert kwargs["recipient_email"] == tenant_user.email
        assert kwargs["login_url"].endswith("/login/")

    def test_reactivate_org_logs_event(self, db, tenant_user):
        from apps.infrastructure.tenants.services import TenantService
        org = tenant_user.org
        with patch("apps.infrastructure.tenants.services.EmailService"):
            with capture_logs() as logs:
                TenantService.reactivate_org(org, reactivated_by=tenant_user)
        assert any(
            e["event"] == "tenant.reactivated"
            and e["org_id"] == str(org.pk)
            and e["reactivated_by"] == str(tenant_user.pk)
            for e in logs
        )

    # ── owner resolution fallback chain ──────────────────────────────────────

    def test_owner_resolution_prefers_owner_user(self, db, tenant_user):
        from apps.infrastructure.tenants.services import TenantService
        org = tenant_user.org
        with patch("apps.infrastructure.tenants.services.EmailService") as mock_email:
            TenantService.suspend_org(org, reason="x")
        kwargs = mock_email.send_suspension.call_args.kwargs
        assert kwargs["recipient_email"] == tenant_user.email
        assert kwargs["owner_name"] == tenant_user.get_full_name()

    def test_owner_resolution_falls_back_to_owner_email(self, db, test_org):
        """Org with no member users falls back to the org.owner_email field."""
        from apps.infrastructure.tenants.services import TenantService
        test_org.owner_email = "fallback@farm.com"
        test_org.save(update_fields=["owner_email", "updated_at"])
        with patch("apps.infrastructure.tenants.services.EmailService") as mock_email:
            TenantService.suspend_org(test_org, reason="x")
        kwargs = mock_email.send_suspension.call_args.kwargs
        assert kwargs["recipient_email"] == "fallback@farm.com"
        assert kwargs["owner_name"] == "fallback@farm.com"

    def test_no_recipient_skips_email(self, db, test_org):
        """No owner user and no owner_email → no email attempted, no crash."""
        from apps.infrastructure.tenants.services import TenantService
        test_org.owner_email = ""
        test_org.save(update_fields=["owner_email", "updated_at"])
        with patch("apps.infrastructure.tenants.services.EmailService") as mock_email:
            TenantService.suspend_org(test_org, reason="x")
        mock_email.send_suspension.assert_not_called()
        test_org.refresh_from_db()
        assert test_org.is_active is False


# ── TenantService.create_organization — unified org+owner creation ────────────

class TestCreateOrganization:
    """The single authoritative path both SignupView and TenantOnboardingView
    call. Verifies field defaults, country propagation, atomicity and the
    generated-password contract."""

    def _create(self, **overrides):
        from apps.infrastructure.tenants.services import TenantService
        kwargs = {
            "org_name": "Acme Poultry",
            "subdomain": "acmepoultry",
            "owner_email": "owner@acme.com",
            "owner_password": "supersecret123",
            "owner_name": "Ada Eze",
            "owner_phone": "+2348012345678",
            "country": "Nigeria",
            "state_region": "Lagos",
        }
        kwargs.update(overrides)
        return TenantService.create_organization(**kwargs)

    def test_creates_organization_with_correct_fields(self, db):
        org, _user, _tmp = self._create()
        org.refresh_from_db()
        assert org.name == "Acme Poultry"
        assert org.subdomain == "acmepoultry"
        assert org.owner_email == "owner@acme.com"
        assert org.owner_name == "Ada Eze"
        assert org.owner_phone == "+2348012345678"
        assert org.plan_tier == "trial"
        assert org.subscription_status == "trial"
        assert org.trial_ends_at is not None
        assert org.is_active is True

    def test_creates_owner_user_with_role_owner(self, db):
        _org, user, _tmp = self._create()
        assert user.role == "owner"
        assert user.email == "owner@acme.com"
        assert user.username == "owner@acme.com"
        # owner_name split into first/last
        assert user.first_name == "Ada"
        assert user.last_name == "Eze"
        assert user.check_password("supersecret123")

    def test_org_country_set_from_parameter(self, db):
        org, _user, _tmp = self._create(subdomain="ghanaco", owner_email="g@x.com",
                                        country="Ghana")
        org.refresh_from_db()
        assert org.country == "Ghana"

    def test_user_country_matches_org_country(self, db):
        org, user, _tmp = self._create(subdomain="kenyaco", owner_email="k@x.com",
                                       country="Kenya")
        assert user.country == "Kenya"
        assert org.country == user.country

    def test_timezone_derived_from_country(self, db):
        _org, user, _tmp = self._create(subdomain="ghtz", owner_email="ghtz@x.com",
                                        country="Ghana")
        assert user.timezone == "Africa/Accra"

    def test_generates_temp_password_when_none_supplied(self, db):
        _org, user, temp_password = self._create(
            subdomain="notmp", owner_email="notmp@x.com", owner_password=None,
        )
        assert temp_password
        assert user.check_password(temp_password)

    def test_returns_none_temp_password_when_password_supplied(self, db):
        _org, _user, temp_password = self._create()
        assert temp_password is None

    def test_atomicity_no_user_when_org_fails(self, db):
        """If the org INSERT fails, the owner user must not exist either."""
        from apps.infrastructure.accounts.models import CustomUser
        from apps.infrastructure.tenants.models import Organization
        from apps.infrastructure.tenants.services import TenantService

        # Pre-claim the subdomain so the org create hits the unique constraint.
        Organization.objects.create(name="Taken", subdomain="taken")
        with pytest.raises(Exception):
            TenantService.create_organization(
                org_name="Dupe", subdomain="taken",
                owner_email="dupe@x.com", owner_password="x12345678",
            )
        assert not CustomUser.objects.filter(email="dupe@x.com").exists()

    def test_logs_tenant_created(self, db):
        from apps.infrastructure.tenants.services import TenantService
        with capture_logs() as logs:
            TenantService.create_organization(
                org_name="Logged Co", subdomain="loggedco",
                owner_email="logged@x.com", owner_password="x12345678",
                country="Ghana",
            )
        assert any(
            e["event"] == "tenant.created"
            and e["owner_email"] == "logged@x.com"
            and e["country"] == "Ghana"
            for e in logs
        )
