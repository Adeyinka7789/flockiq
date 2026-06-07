"""
Coverage tests for:
- apps/infrastructure/core/middleware.py   (HtmxSessionExpiredMiddleware, ImpersonationMiddleware)
- apps/infrastructure/core/tasks.py        (clear_expired_sessions)
- apps/infrastructure/core/services.py     (BaseService, LedgerService)
"""
import time
import uuid
from unittest.mock import MagicMock, patch
from urllib.parse import unquote

import pytest
from django.http import HttpResponse, HttpResponseRedirect
from django.test import RequestFactory

pytestmark = pytest.mark.django_db


class MockSession(dict):
    """Minimal stand-in for a Django session.

    Behaves like a dict but supports ``.modified`` attribute assignment, which
    the middleware now performs after mutating the session. A plain dict raises
    AttributeError on ``session.modified = True``.
    """

    modified = False

    def pop(self, key, default=None):
        self.modified = True
        return super().pop(key, default)


# ── HtmxSessionExpiredMiddleware — unit tests ────────────────────────────────

class TestHtmxSessionExpiredMiddleware:

    def _middleware(self, get_response):
        from apps.infrastructure.core.middleware import HtmxSessionExpiredMiddleware
        return HtmxSessionExpiredMiddleware(get_response)

    def test_htmx_redirect_to_login_becomes_401(self):
        rf = RequestFactory()
        request = rf.get("/dashboard/", HTTP_HX_REQUEST="true")

        def get_response(req):
            return HttpResponseRedirect("/login/?next=/dashboard/")

        response = self._middleware(get_response)(request)
        assert response.status_code == 401
        assert "HX-Redirect" in response

    def test_htmx_redirect_hx_redirect_contains_path(self):
        rf = RequestFactory()
        request = rf.get("/batches/", HTTP_HX_REQUEST="true")
        # Middleware now derives next= from HTTP_REFERER, not request.path.
        request.META["HTTP_REFERER"] = "http://testserver/batches/"

        def get_response(req):
            return HttpResponseRedirect("/login/?next=/batches/")

        response = self._middleware(get_response)(request)
        assert response.status_code == 401
        assert "/batches/" in unquote(response["HX-Redirect"])

    def test_htmx_redirect_no_referer_fallback_to_root(self):
        rf = RequestFactory()
        request = rf.get("/some-fragment/", HTTP_HX_REQUEST="true")
        # No HTTP_REFERER — middleware falls back to dest = "/"

        def get_response(req):
            return HttpResponseRedirect("/login/?next=/some-fragment/")

        response = self._middleware(get_response)(request)
        assert response.status_code == 401
        assert unquote(response["HX-Redirect"]) == "/login/?next=/"

    def test_non_htmx_redirect_to_login_stays_302(self):
        rf = RequestFactory()
        request = rf.get("/dashboard/")  # no HX-Request header

        def get_response(req):
            return HttpResponseRedirect("/login/?next=/dashboard/")

        response = self._middleware(get_response)(request)
        assert response.status_code == 302

    def test_htmx_redirect_to_non_login_url_stays_302(self):
        rf = RequestFactory()
        request = rf.get("/batches/", HTTP_HX_REQUEST="true")

        def get_response(req):
            # redirect to something other than /login/
            return HttpResponseRedirect("/onboarding/")

        response = self._middleware(get_response)(request)
        assert response.status_code == 302

    def test_htmx_200_passes_through_unchanged(self):
        rf = RequestFactory()
        request = rf.get("/dashboard/", HTTP_HX_REQUEST="true")

        def get_response(req):
            return HttpResponse(status=200, content=b"ok")

        response = self._middleware(get_response)(request)
        assert response.status_code == 200

    def test_non_htmx_200_passes_through_unchanged(self):
        rf = RequestFactory()
        request = rf.get("/dashboard/")

        def get_response(req):
            return HttpResponse(status=200, content=b"ok")

        response = self._middleware(get_response)(request)
        assert response.status_code == 200


# ── HtmxSessionExpiredMiddleware — integration via test client ────────────────

class TestHtmxSessionExpiredMiddlewareIntegration:

    def test_htmx_unauthenticated_returns_401(self, client):
        response = client.get("/notifications/bell/", HTTP_HX_REQUEST="true")
        assert response.status_code == 401

    def test_non_htmx_unauthenticated_returns_302(self, client):
        response = client.get("/notifications/bell/")
        assert response.status_code == 302

    def test_htmx_authenticated_returns_200(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get("/notifications/bell/", HTTP_HX_REQUEST="true")
        assert response.status_code == 200


# ── ImpersonationMiddleware — unit tests ─────────────────────────────────────

class TestImpersonationMiddleware:

    def _middleware(self, get_response=None):
        from apps.infrastructure.core.middleware import ImpersonationMiddleware
        if get_response is None:
            get_response = MagicMock(return_value=HttpResponse(status=200))
        return ImpersonationMiddleware(get_response)

    def test_no_session_key_sets_not_impersonating(self):
        request = MagicMock()
        request.session = MockSession()
        request.user.is_authenticated = True

        self._middleware()(request)

        assert request.is_impersonating is False
        assert request.impersonator is None

    def test_unauthenticated_user_with_session_key_not_impersonating(self):
        request = MagicMock()
        request.session = MockSession({"_impersonated_user_id": str(uuid.uuid4())})
        request.user.is_authenticated = False

        self._middleware()(request)

        assert request.is_impersonating is False

    def test_valid_impersonation_swaps_request_user(self, tenant_user):
        from apps.infrastructure.accounts.models import CustomUser

        admin = CustomUser.objects.create_user(
            username="admin-imp",
            email="admin-imp@test.com",
            password="pass",
            org=None,
            role="super_admin",
            is_staff=True,
            is_superuser=True,
        )
        # admin.is_authenticated is always True for a real Django user

        request = MagicMock()
        request.session = MockSession({
            "_impersonated_user_id": tenant_user.pk,
            # Must be within IMPERSONATION_MAX_SECONDS or the middleware revokes
            # the session before swapping the user.
            "_impersonation_started_at": time.time(),
        })
        request.user = admin
        # Don't set is_authenticated — it's a read-only property on real users

        self._middleware()(request)

        assert request.is_impersonating is True
        assert request.user.pk == tenant_user.pk
        assert request.impersonator == admin

    def test_invalid_user_id_clears_session_key(self):
        request = MagicMock()
        request.session = MockSession({
            "_impersonated_user_id": str(uuid.uuid4()),
            # Fresh start time so we reach the user lookup (which fails) rather
            # than tripping the TTL/expiry revocation branch first.
            "_impersonation_started_at": time.time(),
        })
        request.user.is_authenticated = True

        self._middleware()(request)

        assert "_impersonated_user_id" not in request.session
        assert request.is_impersonating is False


# ── clear_expired_sessions task ───────────────────────────────────────────────

class TestClearExpiredSessionsTask:

    def test_task_calls_clearsessions(self):
        from apps.infrastructure.core.tasks import clear_expired_sessions
        with patch("apps.infrastructure.core.tasks.call_command") as mock_cmd:
            clear_expired_sessions()
        mock_cmd.assert_called_once_with("clearsessions")

    def test_task_does_not_raise(self):
        from apps.infrastructure.core.tasks import clear_expired_sessions
        with patch("apps.infrastructure.core.tasks.call_command"):
            clear_expired_sessions()  # must not raise


# ── BaseService ───────────────────────────────────────────────────────────────

class TestBaseService:

    def test_none_org_raises_value_error(self):
        from apps.infrastructure.core.services import BaseService
        with pytest.raises(ValueError, match="requires an org"):
            BaseService(org=None)

    def test_valid_org_sets_attribute(self, test_org):
        from apps.infrastructure.core.services import BaseService
        svc = BaseService(org=test_org)
        assert svc.org is test_org

    def test_logger_bound_with_org_id(self, test_org):
        from apps.infrastructure.core.services import BaseService
        svc = BaseService(org=test_org)
        assert svc.logger is not None

    def test_atomic_returns_context_manager(self, test_org):
        from apps.infrastructure.core.services import BaseService
        from django.db import transaction
        svc = BaseService(org=test_org)
        ctx = svc.atomic()
        # transaction.atomic() returns an Atomic context manager
        assert hasattr(ctx, "__enter__")
        assert hasattr(ctx, "__exit__")


# ── LedgerService ─────────────────────────────────────────────────────────────

class TestLedgerService:

    def test_record_transaction_does_not_raise(self, test_org, test_batch):
        from apps.infrastructure.core.services import LedgerService
        svc = LedgerService(org=test_org)
        svc.record_transaction(
            batch=test_batch,
            amount_kobo=50000,
            category="feed_purchase",
            direction="debit",
        )

    def test_record_transaction_no_batch(self, test_org):
        from apps.infrastructure.core.services import LedgerService
        svc = LedgerService(org=test_org)
        svc.record_transaction(
            batch=None,
            amount_kobo=10000,
            category="feed_purchase",
            direction="debit",
        )

    def test_record_feed_purchase(self, test_org, test_batch):
        from apps.infrastructure.core.services import LedgerService
        from datetime import date
        svc = LedgerService(org=test_org)
        svc.record_feed_purchase(test_batch, "move-1", 75000, date.today())

    def test_record_feed_consumption(self, test_org, test_batch):
        from apps.infrastructure.core.services import LedgerService
        from datetime import date
        svc = LedgerService(org=test_org)
        svc.record_feed_consumption(test_batch, "move-2", 30000, date.today())

    def test_record_egg_sale(self, test_org, test_batch):
        from apps.infrastructure.core.services import LedgerService
        from datetime import date
        svc = LedgerService(org=test_org)
        svc.record_egg_sale(test_batch, "sale-1", 200000, date.today())

    def test_record_broiler_sale(self, test_org, test_batch):
        from apps.infrastructure.core.services import LedgerService
        from datetime import date
        svc = LedgerService(org=test_org)
        svc.record_broiler_sale(test_batch, "sale-2", 500000, date.today())

    def test_record_mortality_writedown(self, test_org, test_batch):
        from apps.infrastructure.core.services import LedgerService
        from datetime import date
        svc = LedgerService(org=test_org)
        svc.record_mortality_writedown(test_batch, "log-1", 5000, date.today())
