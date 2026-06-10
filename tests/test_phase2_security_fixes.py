"""
Phase 2 security-audit fixes — concurrency, Redis separation, idempotency,
JWT throttling.

Covers:
  Bug 4  — verify flow split: activate_from_verified_data does no network I/O
           and the callback view pre-fetches before the tenant context
  Bug 9  — Redis DB separation in production settings (broker 0, cache 1,
           sessions 2, results 3)
  Bug 10 — PaymentRecord.reference unique constraint + activate_plan
           idempotency under repeated delivery
  Bug 19 — JWT login endpoint throttled at the 'login' scope (10/h → 429)

mark_lapsed_orgs coverage lives in
tests/test_billing_security_fixes.py::TestMarkLapsedOrgsTask (Phase 1).
"""

import importlib
import uuid
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from apps.infrastructure.billing.models import BillingPlan, PaymentRecord
from apps.infrastructure.billing.services import BillingService
from apps.infrastructure.core.rls import set_tenant_context

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_org(**kwargs):
    from apps.infrastructure.tenants.models import Organization
    subdomain = f"p2-{uuid.uuid4().hex[:8]}"
    defaults = {
        "name": "Phase2 Farm",
        "subdomain": subdomain,
        "owner_email": f"{subdomain}@test.com",
        "plan_tier": "monthly",
        "subscription_status": "active",
        "is_active": True,
    }
    defaults.update(kwargs)
    return Organization.objects.create(**defaults)


def make_plan(plan_tier="monthly", amount_kobo=500000):
    return BillingPlan.objects.create(
        name=f"{plan_tier.title()} Plan",
        plan_tier=plan_tier,
        paystack_plan_code=f"PLN_{uuid.uuid4().hex[:10]}",
        amount_kobo=amount_kobo,
        billing_interval="monthly",
        is_active=True,
    )


# ---------------------------------------------------------------------------
# Bug 10 — PaymentRecord unique constraint + idempotent activation
# ---------------------------------------------------------------------------

class TestPaymentIdempotency:
    def test_duplicate_reference_rejected_at_db_level(self):
        org_a = make_org()
        org_b = make_org()

        with set_tenant_context(org_a):
            PaymentRecord.objects.create(
                org=org_a, reference="ref_dup_db",
                amount_kobo=1000, status="success",
            )

        # Globally unique — even a different org cannot reuse a reference.
        with pytest.raises(IntegrityError):
            with set_tenant_context(org_b):
                PaymentRecord.objects.create(
                    org=org_b, reference="ref_dup_db",
                    amount_kobo=1000, status="success",
                )

    def test_activate_plan_second_delivery_is_noop(self):
        # Simulates webhook + callback both delivering the same reference:
        # the second activation must not extend the plan or record a second
        # payment.
        make_plan("monthly")
        org = make_org()

        with set_tenant_context(org):
            svc = BillingService(org)
            first = svc.activate_plan(
                plan_tier="monthly",
                payment_reference="ref_idem_1",
                activated_by="paystack",
                amount_kobo=500000,
            )
        org.refresh_from_db()
        expiry_after_first = org.plan_expires_at

        with set_tenant_context(org):
            second = svc.activate_plan(
                plan_tier="monthly",
                payment_reference="ref_idem_1",
                activated_by="paystack",
                amount_kobo=500000,
            )

        org.refresh_from_db()
        assert first is True
        assert second is False
        assert org.plan_expires_at == expiry_after_first
        with set_tenant_context(org):
            assert PaymentRecord.objects.filter(
                reference="ref_idem_1"
            ).count() == 1


# ---------------------------------------------------------------------------
# Bug 4 — verify flow split (no HTTP inside the activation transaction)
# ---------------------------------------------------------------------------

class TestVerifySplit:
    def test_activate_from_verified_data_handles_none(self):
        # The callback view passes None when the Paystack fetch failed —
        # activation must decline gracefully, not crash.
        org = make_org()
        with set_tenant_context(org):
            ok = BillingService(org).activate_from_verified_data(
                None, "ref_none"
            )
        assert ok is False

    def test_verify_and_activate_delegates_to_activation(self):
        make_plan("monthly", amount_kobo=500000)
        org = make_org()
        response = {
            "status": True,
            "data": {
                "status": "success",
                "amount": 500000,
                "id": 90001,
                "channel": "card",
                "metadata": {"org_id": str(org.id), "plan_tier": "monthly"},
            },
        }
        with patch(
            "apps.infrastructure.billing.services."
            "PaystackService.verify_transaction",
            return_value=response,
        ) as mock_verify:
            with set_tenant_context(org):
                ok = BillingService(org).verify_and_activate("ref_split_1")

        assert ok is True
        mock_verify.assert_called_once_with("ref_split_1")
        org.refresh_from_db()
        assert org.plan_expires_at > timezone.now()

    def test_callback_view_fetches_before_tenant_context(
        self, client, tenant_user
    ):
        # The view must call verify_transaction exactly once and pass the
        # result into activate_from_verified_data — no second HTTP call
        # inside the tenant context.
        make_plan("monthly", amount_kobo=500000)
        org = tenant_user.org
        response = {
            "status": True,
            "data": {
                "status": "success",
                "amount": 500000,
                "id": 90002,
                "channel": "card",
                "metadata": {"org_id": str(org.id), "plan_tier": "monthly"},
            },
        }
        client.force_login(tenant_user)
        with patch(
            "apps.infrastructure.billing.services."
            "PaystackService.verify_transaction",
            return_value=response,
        ) as mock_verify:
            resp = client.get("/billing/verify/", {"reference": "ref_cb_1"})

        assert mock_verify.call_count == 1
        assert resp.status_code == 302
        assert "upgraded=1" in resp["Location"]
        org.refresh_from_db()
        assert org.plan_expires_at > timezone.now()


# ---------------------------------------------------------------------------
# Bug 9 — Redis DB separation in production settings
# ---------------------------------------------------------------------------

class TestRedisDbSeparation:
    def test_broker_sessions_cache_results_on_distinct_dbs(self, monkeypatch):
        # production.py requires these at import time.
        monkeypatch.setenv("SECRET_KEY", "test-secret")
        monkeypatch.setenv("DB_NAME", "test_db")
        monkeypatch.setenv("DB_USER", "test_user")
        monkeypatch.setenv("DB_PASSWORD", "test_pass")
        monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6379")
        monkeypatch.delenv("CELERY_BROKER_URL", raising=False)
        monkeypatch.delenv("CELERY_RESULT_BACKEND", raising=False)
        monkeypatch.delenv("REDIS_SESSION_URL", raising=False)

        prod = importlib.import_module("config.settings.production")
        prod = importlib.reload(prod)

        broker = prod.CELERY_BROKER_URL
        results = prod.CELERY_RESULT_BACKEND
        cache = prod.CACHES["default"]["LOCATION"]
        sessions = prod.CACHES["sessions"]["LOCATION"]

        assert broker.endswith("/0")
        assert cache.endswith("/1")
        assert sessions.endswith("/2")
        assert results.endswith("/3")
        # The original bug: broker and sessions shared DB 2.
        assert broker != sessions
        assert len({broker, results, cache, sessions}) == 4

    def test_base_broker_default_not_on_cache_db(self):
        # Dev/base default must also keep the broker off the cache DB.
        from django.conf import settings
        assert settings.CELERY_BROKER_URL != settings.CACHES["default"]["LOCATION"]


# ---------------------------------------------------------------------------
# Bug 19 — JWT login throttle
# ---------------------------------------------------------------------------

class TestJwtLoginThrottle:
    def test_jwt_login_returns_429_after_limit(self, client, settings):
        # Deterministic cache for throttle counters (the dev Redis cache
        # ignores exceptions, which would silently disable throttling), and
        # axes disabled so its 5-failure IP lockout doesn't 403 first.
        settings.AXES_ENABLED = False
        settings.CACHES = {
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                "LOCATION": "jwt-throttle-test",
            },
            "sessions": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                "LOCATION": "jwt-throttle-test-sessions",
            },
        }
        from django.core.cache import cache
        cache.clear()

        url = reverse("token_obtain_pair")
        payload = {
            "username": "nobody@example.com",
            "email": "nobody@example.com",
            "password": "wrong-password",
        }

        # Login scope is 10/hour (DEFAULT_THROTTLE_RATES["login"]).
        responses = [client.post(url, payload) for _ in range(11)]

        for resp in responses[:10]:
            assert resp.status_code in (400, 401), (
                f"expected auth failure, got {resp.status_code}"
            )
        assert responses[10].status_code == 429
