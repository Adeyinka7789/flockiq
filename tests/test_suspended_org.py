"""
Suspended-organisation handling.

Covers:
- WebLoginView blocks login for users whose org has been suspended (FIX 1)
- TenantMiddleware kicks already-logged-in users out on their next request (FIX 2)
- Superadmins are never affected by org suspension
- Superadmin suspend invalidates the org-active cache immediately (FIX 3)
- Suspension stores a reason and emails the org owner (FIX 5)
"""
import pytest
from django.core import mail
from django.core.cache import cache

pytestmark = pytest.mark.django_db


def _cache_key(org):
    return f"org_active:{org.id}"


# ── FIX 1 — block login for suspended org users ───────────────────────────────

class TestSuspendedLoginBlocked:

    def test_suspended_org_user_cannot_login(self, client, tenant_user, test_org):
        test_org.is_active = False
        test_org.save()

        resp = client.post("/login/", {
            "email": tenant_user.email,
            "password": "testpass123",
        })

        assert resp.status_code == 403
        assert b"suspended" in resp.content.lower()
        # No session was established.
        assert "_auth_user_id" not in client.session

    def test_active_org_user_can_login(self, client, tenant_user, test_org):
        assert test_org.is_active is True

        resp = client.post("/login/", {
            "email": tenant_user.email,
            "password": "testpass123",
        })

        assert resp.status_code == 302
        assert "_auth_user_id" in client.session

    def test_login_page_shows_banner_for_suspended_query(self, client):
        resp = client.get("/login/?suspended=1")
        assert resp.status_code == 200
        assert b"Account Suspended" in resp.content


# ── FIX 2 — kick already-logged-in users out on next request ──────────────────

class TestSuspendedMiddlewareKickout:

    def test_logged_in_user_kicked_when_org_suspended(self, client, tenant_user, test_org):
        client.force_login(tenant_user)
        # Sanity: an active-org user is not bounced.
        cache.delete(_cache_key(test_org))

        # Suspend the org and clear the middleware cache (mirrors FIX 3).
        test_org.is_active = False
        test_org.save()
        cache.delete(_cache_key(test_org))

        resp = client.get("/")

        assert resp.status_code == 302
        assert "/login/?suspended=1" in resp["Location"]
        # Session was cleared — user is logged out.
        assert "_auth_user_id" not in client.session

    def test_active_user_not_kicked(self, client, tenant_user, test_org):
        client.force_login(tenant_user)
        cache.delete(_cache_key(test_org))

        resp = client.get("/")

        # Whatever "/" resolves to, the user must NOT be bounced to the
        # suspended login page.
        if resp.status_code == 302:
            assert "suspended=1" not in resp.get("Location", "")
        assert "_auth_user_id" in client.session


# ── Superadmin is never affected ──────────────────────────────────────────────

class TestSuperadminNeverSuspended:

    def test_superadmin_not_affected(self, client, super_admin_user, test_org):
        client.force_login(super_admin_user)
        test_org.is_active = False
        test_org.save()
        cache.delete(_cache_key(test_org))

        resp = client.get("/superadmin/")
        assert resp.status_code == 200

    def test_superuser_with_suspended_org_not_kicked(self, client, test_org):
        from apps.infrastructure.accounts.models import CustomUser

        su = CustomUser.objects.create_user(
            username="su-with-org",
            email="su-with-org@flockiq.com",
            password="testpass123",
            org=test_org,
            role="super_admin",
            is_staff=True,
            is_superuser=True,
            email_verified=True,
        )
        client.force_login(su)

        test_org.is_active = False
        test_org.save()
        cache.delete(_cache_key(test_org))

        resp = client.get("/")
        if resp.status_code == 302:
            assert "suspended=1" not in resp.get("Location", "")
        # Still logged in.
        assert "_auth_user_id" in client.session


# ── FIX 3 / FIX 5 — superadmin suspend: cache + reason + email ─────────────────

class TestSuperadminSuspendAction:

    def _action_url(self, org):
        return f"/superadmin/tenants/{org.id}/action/"

    def test_suspend_invalidates_cache(self, client, super_admin_user, test_org):
        # Warm the cache as active.
        cache.set(_cache_key(test_org), True, timeout=300)
        client.force_login(super_admin_user)

        resp = client.post(self._action_url(test_org), {"action": "suspend"})

        assert resp.status_code == 204
        # Cache key was dropped so the next request re-reads from the DB.
        assert cache.get(_cache_key(test_org)) is None
        test_org.refresh_from_db()
        assert test_org.is_active is False

    def test_suspend_stores_reason_and_emails_owner(self, client, super_admin_user,
                                                    tenant_user, test_org):
        mail.outbox.clear()
        client.force_login(super_admin_user)

        resp = client.post(self._action_url(test_org), {
            "action": "suspend",
            "suspension_reason": "Non-payment of invoice",
        })

        assert resp.status_code == 204
        test_org.refresh_from_db()
        assert test_org.suspension_reason == "Non-payment of invoice"
        assert len(mail.outbox) == 1
        assert tenant_user.email in mail.outbox[0].to
        assert "Non-payment of invoice" in mail.outbox[0].body

    def test_activate_clears_reason_and_cache(self, client, super_admin_user, test_org):
        test_org.is_active = False
        test_org.suspension_reason = "old reason"
        test_org.save()
        cache.set(_cache_key(test_org), False, timeout=60)
        client.force_login(super_admin_user)

        resp = client.post(self._action_url(test_org), {"action": "activate"})

        assert resp.status_code == 204
        assert cache.get(_cache_key(test_org)) is None
        test_org.refresh_from_db()
        assert test_org.is_active is True
        assert test_org.suspension_reason == ""

    def test_activate_sends_reactivation_email(self, client, super_admin_user,
                                               tenant_user, test_org):
        test_org.is_active = False
        test_org.suspension_reason = "old reason"
        test_org.save()
        mail.outbox.clear()
        client.force_login(super_admin_user)

        resp = client.post(self._action_url(test_org), {"action": "activate"})

        assert resp.status_code == 204
        assert len(mail.outbox) == 1
        assert tenant_user.email in mail.outbox[0].to
        assert "reactivated" in mail.outbox[0].subject.lower()


# ── Modal-based suspension flow (suspend_modal + suspend_org) ──────────────────

class TestSuspendModalFlow:

    def _modal_url(self, org):
        return f"/superadmin/tenants/{org.id}/suspend-modal/"

    def _suspend_url(self, org):
        return f"/superadmin/tenants/{org.id}/suspend/"

    def test_modal_fragment_renders(self, client, super_admin_user, test_org):
        client.force_login(super_admin_user)
        resp = client.get(self._modal_url(test_org))
        assert resp.status_code == 200
        assert test_org.name.encode() in resp.content
        assert b'name="suspension_reason"' in resp.content

    def test_modal_blocks_non_superadmin(self, client, tenant_user, test_org):
        client.force_login(tenant_user)
        resp = client.get(self._modal_url(test_org))
        # SuperAdminMixin redirects non-admins to the dashboard.
        assert resp.status_code == 302
        assert "suspension_reason" not in resp.content.decode(errors="ignore")

    def test_suspend_with_reason_succeeds(self, client, super_admin_user,
                                          tenant_user, test_org):
        cache.set(_cache_key(test_org), True, timeout=300)
        mail.outbox.clear()
        client.force_login(super_admin_user)

        resp = client.post(self._suspend_url(test_org), {
            "suspension_reason": "Policy violation",
        })

        assert resp.status_code == 200
        assert b"Account Suspended" in resp.content
        test_org.refresh_from_db()
        assert test_org.is_active is False
        assert test_org.suspension_reason == "Policy violation"
        # Cache invalidated immediately.
        assert cache.get(_cache_key(test_org)) is None
        # Owner emailed with the reason.
        assert len(mail.outbox) == 1
        assert tenant_user.email in mail.outbox[0].to
        assert "Policy violation" in mail.outbox[0].body

    def test_suspend_without_reason_re_renders_modal(self, client, super_admin_user,
                                                     test_org):
        mail.outbox.clear()
        client.force_login(super_admin_user)

        resp = client.post(self._suspend_url(test_org), {"suspension_reason": "   "})

        # Re-rendered modal (200 so htmx swaps it), org untouched, no email.
        assert resp.status_code == 200
        assert b"Please provide a reason" in resp.content
        test_org.refresh_from_db()
        assert test_org.is_active is True
        assert test_org.suspension_reason == ""
        assert len(mail.outbox) == 0

    def test_suspend_blocks_non_superadmin(self, client, tenant_user, test_org):
        client.force_login(tenant_user)
        resp = client.post(self._suspend_url(test_org), {"suspension_reason": "x"})
        assert resp.status_code == 302
        test_org.refresh_from_db()
        assert test_org.is_active is True
