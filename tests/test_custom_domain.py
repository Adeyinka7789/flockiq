"""Custom domain feature tests.

Covers the Organization custom-domain fields, the owner-only settings views
(add / verify / remove), and TenantMiddleware custom-domain resolution.
"""
import pytest
from django.contrib.auth.models import AnonymousUser
from django.http import HttpResponse
from django.urls import reverse
from django.utils import timezone

pytestmark = pytest.mark.django_db


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def non_owner_user(db, test_org):
    """A non-owner member of test_org (managers may not touch the domain)."""
    from apps.infrastructure.accounts.models import CustomUser
    return CustomUser.objects.create_user(
        username=f"manager-{test_org.subdomain}",
        email=f"manager@{test_org.subdomain}.com",
        password="testpass123",
        org=test_org,
        role="manager",
        email_verified=True,
    )


# ── Model field tests ───────────────────────────────────────────────────────

class TestCustomDomainFields:

    def test_defaults(self, test_org):
        assert test_org.custom_domain is None
        assert test_org.custom_domain_verified is False
        assert test_org.custom_domain_verification_token == ""
        assert test_org.custom_domain_verified_at is None

    def test_custom_domain_unique(self, db):
        from django.db import IntegrityError, transaction
        from apps.infrastructure.tenants.models import Organization

        Organization.objects.create(
            name="A", subdomain="org-a", custom_domain="app.a.com"
        )
        with pytest.raises(IntegrityError), transaction.atomic():
            Organization.objects.create(
                name="B", subdomain="org-b", custom_domain="app.a.com"
            )


# ── Add-domain view tests ─────────────────────────────────────────────────────

class TestAddCustomDomain:

    def _url(self):
        return reverse("tenants:custom_domain_settings")

    def test_owner_get_renders_page(self, client, tenant_user):
        client.force_login(tenant_user)
        resp = client.get(self._url())
        assert resp.status_code == 200
        assert b"Custom Domain" in resp.content

    def test_non_owner_get_sees_forbidden_notice(self, client, non_owner_user):
        client.force_login(non_owner_user)
        resp = client.get(self._url())
        assert resp.status_code == 200
        assert b"Only the account owner" in resp.content

    def test_add_valid_domain_sets_pending_state(self, client, tenant_user, test_org):
        client.force_login(tenant_user)
        resp = client.post(self._url(), {"custom_domain": "app.obasanjofarm.com"})
        assert resp.status_code == 200
        assert b"Verify your domain" in resp.content

        test_org.refresh_from_db()
        assert test_org.custom_domain == "app.obasanjofarm.com"
        assert test_org.custom_domain_verified is False
        assert test_org.custom_domain_verification_token  # non-empty token issued

    def test_add_strips_scheme_and_path(self, client, tenant_user, test_org):
        client.force_login(tenant_user)
        resp = client.post(
            self._url(), {"custom_domain": "https://App.Obasanjofarm.com/dashboard"}
        )
        assert resp.status_code == 200
        test_org.refresh_from_db()
        assert test_org.custom_domain == "app.obasanjofarm.com"

    def test_empty_domain_rejected(self, client, tenant_user, test_org):
        client.force_login(tenant_user)
        resp = client.post(self._url(), {"custom_domain": "   "})
        assert resp.status_code == 200
        assert b"Please enter a domain" in resp.content
        test_org.refresh_from_db()
        assert test_org.custom_domain is None

    def test_invalid_domain_rejected(self, client, tenant_user, test_org):
        client.force_login(tenant_user)
        resp = client.post(self._url(), {"custom_domain": "not a domain"})
        assert resp.status_code == 200
        assert b"valid domain" in resp.content
        test_org.refresh_from_db()
        assert test_org.custom_domain is None

    def test_flockiq_domain_rejected(self, client, tenant_user, test_org):
        client.force_login(tenant_user)
        resp = client.post(self._url(), {"custom_domain": "evil.flockiq.com"})
        assert resp.status_code == 200
        assert b"cannot use a flockiq.com domain" in resp.content
        test_org.refresh_from_db()
        assert test_org.custom_domain is None

    def test_duplicate_domain_rejected(self, client, tenant_user, test_org):
        from apps.infrastructure.tenants.models import Organization
        Organization.objects.create(
            name="Other", subdomain="other-org", custom_domain="taken.example.com"
        )
        client.force_login(tenant_user)
        resp = client.post(self._url(), {"custom_domain": "taken.example.com"})
        assert resp.status_code == 200
        assert b"already in use" in resp.content
        test_org.refresh_from_db()
        assert test_org.custom_domain is None

    def test_non_owner_post_forbidden(self, client, non_owner_user, test_org):
        client.force_login(non_owner_user)
        resp = client.post(self._url(), {"custom_domain": "app.sneaky.com"})
        assert resp.status_code == 403
        test_org.refresh_from_db()
        assert test_org.custom_domain is None


# ── Verify-domain view tests ──────────────────────────────────────────────────

class TestVerifyCustomDomain:

    def _url(self):
        return reverse("tenants:verify_custom_domain")

    def _set_pending(self, org):
        org.custom_domain = "app.obasanjofarm.com"
        org.custom_domain_verified = False
        org.custom_domain_verification_token = "tok-123"
        org.save()

    def test_verification_success(self, client, tenant_user, test_org, monkeypatch):
        from apps.infrastructure.tenants import domain_views

        self._set_pending(test_org)
        monkeypatch.setattr(
            domain_views.VerifyCustomDomainView,
            "_dns_txt_matches",
            staticmethod(lambda domain, token: True),
        )
        client.force_login(tenant_user)
        resp = client.post(self._url())
        assert resp.status_code == 200
        assert b"is active" in resp.content

        test_org.refresh_from_db()
        assert test_org.custom_domain_verified is True
        assert test_org.custom_domain_verified_at is not None

    def test_verification_failure_stays_pending(
        self, client, tenant_user, test_org, monkeypatch
    ):
        from apps.infrastructure.tenants import domain_views

        self._set_pending(test_org)
        monkeypatch.setattr(
            domain_views.VerifyCustomDomainView,
            "_dns_txt_matches",
            staticmethod(lambda domain, token: False),
        )
        client.force_login(tenant_user)
        resp = client.post(self._url())
        assert resp.status_code == 200
        # NB: the apostrophe in "couldn't" is HTML-escaped to &#x27; in the
        # rendered template, so match on a substring without it.
        assert b"find the TXT record yet" in resp.content

        test_org.refresh_from_db()
        assert test_org.custom_domain_verified is False

    def test_verify_without_domain_returns_empty_state(
        self, client, tenant_user, test_org
    ):
        client.force_login(tenant_user)
        resp = client.post(self._url())
        assert resp.status_code == 200
        assert b"Add Custom Domain" in resp.content

    def test_non_owner_verify_forbidden(self, client, non_owner_user, test_org):
        self._set_pending(test_org)
        client.force_login(non_owner_user)
        resp = client.post(self._url())
        assert resp.status_code == 403


# ── Remove-domain view tests ──────────────────────────────────────────────────

class TestRemoveCustomDomain:

    def _url(self):
        return reverse("tenants:remove_custom_domain")

    def test_remove_clears_all_fields(self, client, tenant_user, test_org):
        test_org.custom_domain = "app.obasanjofarm.com"
        test_org.custom_domain_verified = True
        test_org.custom_domain_verified_at = timezone.now()
        test_org.custom_domain_verification_token = "tok-123"
        test_org.save()

        client.force_login(tenant_user)
        resp = client.post(self._url())
        assert resp.status_code == 200
        assert b"Add Custom Domain" in resp.content

        test_org.refresh_from_db()
        assert test_org.custom_domain is None
        assert test_org.custom_domain_verified is False
        assert test_org.custom_domain_verified_at is None
        assert test_org.custom_domain_verification_token == ""

    def test_non_owner_remove_forbidden(self, client, non_owner_user, test_org):
        test_org.custom_domain = "app.obasanjofarm.com"
        test_org.save()
        client.force_login(non_owner_user)
        resp = client.post(self._url())
        assert resp.status_code == 403
        test_org.refresh_from_db()
        assert test_org.custom_domain == "app.obasanjofarm.com"


# ── Middleware custom-domain resolution tests ─────────────────────────────────

class TestCustomDomainMiddleware:

    def _middleware(self, view=None):
        from apps.infrastructure.core.middleware import TenantMiddleware
        return TenantMiddleware(view or (lambda req: HttpResponse("ok")))

    def test_verified_custom_domain_resolves_org(self, db, rf):
        from apps.infrastructure.tenants.models import Organization

        org = Organization.objects.create(
            name="Obasanjo Farms",
            subdomain="obasanjo",
            custom_domain="app.obasanjofarm.com",
            custom_domain_verified=True,
            is_active=True,
        )

        captured = {}

        def view(req):
            captured["org"] = req.org
            return HttpResponse("ok")

        request = rf.get("/", SERVER_NAME="app.obasanjofarm.com")
        request.user = AnonymousUser()
        resp = self._middleware(view)(request)
        assert resp.status_code == 200
        assert captured["org"].id == org.id

    def test_unverified_custom_domain_does_not_resolve(self, db, rf):
        from apps.infrastructure.tenants.models import Organization

        # Use a two-label custom domain so that when the (correctly failing)
        # custom-domain lookup falls through to subdomain parsing, the host has
        # < 3 labels and lands in the root-domain branch (org=None) — rather than
        # being resolved by a subdomain that happens to match the first label.
        Organization.objects.create(
            name="Pending Farms",
            subdomain="pendingfarm",
            custom_domain="pendingfarm.com",
            custom_domain_verified=False,
            is_active=True,
        )

        request = rf.get("/", SERVER_NAME="pendingfarm.com")
        request.user = AnonymousUser()
        resp = self._middleware()(request)
        # Unverified custom domain must not resolve; root-domain branch → None.
        assert resp.status_code == 200
        assert request.org is None

    def test_inactive_org_custom_domain_does_not_resolve(self, db, rf):
        from apps.infrastructure.tenants.models import Organization

        Organization.objects.create(
            name="Dead Farms",
            subdomain="deadfarm",
            custom_domain="deadfarm.com",
            custom_domain_verified=True,
            is_active=False,
        )
        request = rf.get("/", SERVER_NAME="deadfarm.com")
        request.user = AnonymousUser()
        resp = self._middleware()(request)
        # Inactive org's custom domain must not resolve; root-domain branch → None.
        assert resp.status_code == 200
        assert request.org is None

    def test_marketing_domain_unaffected(self, db, rf):
        """flockiq.com (root) must not be hijacked by custom-domain resolution."""
        request = rf.get("/", SERVER_NAME="flockiq.com")
        request.user = AnonymousUser()
        resp = self._middleware()(request)
        assert resp.status_code == 200
        assert request.org is None
