"""
Phase 1 security-audit fixes — billing.

Covers:
  Bug 1A — Organization.is_lapsed is purely date-based (status no longer
           consulted, so a stale 'active' status cannot grant free access)
  Bug 1B — billing.mark_lapsed_orgs flips expired orgs' subscription_status
  Bug 2  — Paystack subscription renewal charges (no FlockIQ metadata)
           extend plan_expires_at via the Paystack plan code
  Bug 3  — webhook returns 503 when PAYSTACK_WEBHOOK_SECRET is empty
  Bug 5  — webhook returns 500 on processing failure so Paystack retries
  Bug 6  — org resolved from metadata.org_id before customer email
  Bug 7  — verify_and_activate rejects mismatched org and insufficient amount
  Bug 8  — failed payment creates a payment_failed notification, never
           disease_outbreak
"""

import json
import uuid
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.infrastructure.billing.models import (
    BillingPlan,
    PaymentRecord,
    PaystackWebhookLog,
)
from apps.infrastructure.billing.views import PaystackWebhookView
from apps.infrastructure.core.rls import set_tenant_context

pytestmark = pytest.mark.django_db

WEBHOOK_URL = reverse("billing:webhook")

VERIFY_SIG = (
    "apps.infrastructure.billing.services."
    "PaystackService.verify_webhook_signature"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_org(**kwargs):
    from apps.infrastructure.tenants.models import Organization
    subdomain = f"audit-{uuid.uuid4().hex[:8]}"
    defaults = {
        "name": "Audit Farm",
        "subdomain": subdomain,
        "owner_email": f"{subdomain}@test.com",
        "plan_tier": "monthly",
        "subscription_status": "active",
        "is_active": True,
    }
    defaults.update(kwargs)
    return Organization.objects.create(**defaults)


def make_plan(plan_tier="monthly", amount_kobo=500000, **kwargs):
    defaults = {
        "name": f"{plan_tier.title()} Plan",
        "plan_tier": plan_tier,
        "paystack_plan_code": f"PLN_{uuid.uuid4().hex[:10]}",
        "amount_kobo": amount_kobo,
        "billing_interval": "monthly",
        "is_active": True,
    }
    defaults.update(kwargs)
    return BillingPlan.objects.create(**defaults)


def post_webhook(client, payload):
    return client.post(
        WEBHOOK_URL, data=json.dumps(payload),
        content_type="application/json",
    )


# ---------------------------------------------------------------------------
# Bug 1A — is_lapsed is purely date-based
# ---------------------------------------------------------------------------

class TestIsLapsedDateBased:
    def test_lapsed_true_when_expired_even_with_active_status(self):
        # THE audit bug: status stuck on 'active' used to grant free access
        # forever after one payment.
        org = make_org(
            subscription_status="active",
            plan_expires_at=timezone.now() - timedelta(days=2),
        )
        assert org.is_lapsed is True

    def test_lapsed_false_when_expiry_in_future(self):
        org = make_org(
            subscription_status="active",
            plan_expires_at=timezone.now() + timedelta(days=10),
        )
        assert org.is_lapsed is False

    def test_lapsed_false_for_trial_org(self):
        org = make_org(
            plan_tier="trial",
            subscription_status="trial",
            plan_expires_at=timezone.now() - timedelta(days=2),
        )
        assert org.is_lapsed is False

    def test_expired_org_loses_write_access(self):
        from apps.infrastructure.billing.features import can_write_data
        org = make_org(
            subscription_status="active",
            plan_expires_at=timezone.now() - timedelta(days=1),
        )
        assert can_write_data(org) is False


# ---------------------------------------------------------------------------
# Bug 1B — mark_lapsed_orgs beat task
# ---------------------------------------------------------------------------

class TestMarkLapsedOrgsTask:
    def test_flips_expired_active_orgs_only(self):
        from apps.infrastructure.billing.tasks import mark_lapsed_orgs

        expired = make_org(
            subscription_status="active",
            plan_expires_at=timezone.now() - timedelta(days=1),
        )
        current = make_org(
            subscription_status="active",
            plan_expires_at=timezone.now() + timedelta(days=20),
        )
        trial = make_org(
            plan_tier="trial",
            subscription_status="trial",
            plan_expires_at=timezone.now() - timedelta(days=1),
        )

        mark_lapsed_orgs()

        expired.refresh_from_db()
        current.refresh_from_db()
        trial.refresh_from_db()
        assert expired.subscription_status == "lapsed"
        assert current.subscription_status == "active"
        assert trial.subscription_status == "trial"


# ---------------------------------------------------------------------------
# Bug 3 — webhook fails closed without a secret
# ---------------------------------------------------------------------------

class TestWebhookSecretGuard:
    def test_503_when_secret_empty(self, client, settings):
        settings.PAYSTACK_WEBHOOK_SECRET = ""
        resp = post_webhook(client, {"event": "charge.success", "data": {}})
        assert resp.status_code == 503
        # Nothing logged or processed — the request is refused outright.
        assert PaystackWebhookLog.objects.count() == 0

    def test_system_check_errors_in_production_mode(self, settings):
        from apps.infrastructure.billing.checks import (
            check_paystack_webhook_secret,
        )
        settings.PAYSTACK_WEBHOOK_SECRET = ""
        settings.DEBUG = False
        errors = check_paystack_webhook_secret(None)
        assert len(errors) == 1
        assert errors[0].id == "billing.E001"

    def test_system_check_passes_when_secret_set(self, settings):
        from apps.infrastructure.billing.checks import (
            check_paystack_webhook_secret,
        )
        settings.PAYSTACK_WEBHOOK_SECRET = "sk_test_xxx"
        assert check_paystack_webhook_secret(None) == []


# ---------------------------------------------------------------------------
# Bug 5 — processing failure returns 500 so Paystack retries
# ---------------------------------------------------------------------------

class TestWebhookRetryOnFailure:
    @patch(VERIFY_SIG, return_value=True)
    def test_500_on_processing_error(self, mock_verify, client):
        payload = {
            "event": "charge.success",
            "data": {"id": 55001, "reference": "ref_fail_1"},
        }
        with patch.object(
            PaystackWebhookView, "_dispatch", side_effect=RuntimeError("db down")
        ):
            resp = post_webhook(client, payload)

        assert resp.status_code == 500
        log = PaystackWebhookLog.objects.get(event_id="55001")
        assert log.processed is False
        assert "db down" in log.error

    @patch(VERIFY_SIG, return_value=True)
    def test_retry_after_failure_is_processed(self, mock_verify, client):
        # A failed delivery must NOT be treated as a duplicate on retry.
        payload = {
            "event": "charge.success",
            "data": {"id": 55002, "reference": "ref_fail_2"},
        }
        with patch.object(
            PaystackWebhookView, "_dispatch", side_effect=RuntimeError("boom")
        ):
            first = post_webhook(client, payload)
        with patch.object(PaystackWebhookView, "_dispatch") as ok_dispatch:
            second = post_webhook(client, payload)

        assert first.status_code == 500
        assert second.status_code == 200
        assert ok_dispatch.call_count == 1

    @patch(VERIFY_SIG, return_value=True)
    def test_unknown_event_type_still_returns_200(self, mock_verify, client):
        resp = post_webhook(
            client,
            {"event": "transfer.success", "data": {"id": 55003}},
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Bug 2 + 6 — charge.success org resolution and renewals
# ---------------------------------------------------------------------------

class TestChargeSuccess:
    @patch(VERIFY_SIG, return_value=True)
    def test_org_resolved_by_metadata_org_id(self, mock_verify, client):
        plan = make_plan("monthly")
        org = make_org(owner_email="real-owner@test.com")
        decoy = make_org(owner_email="decoy@test.com")

        payload = {
            "event": "charge.success",
            "data": {
                "id": 66001,
                "reference": "ref_orgid_1",
                "amount": plan.amount_kobo,
                # Email points at the WRONG org — metadata must win.
                "customer": {"email": "decoy@test.com"},
                "metadata": {"org_id": str(org.id), "plan_tier": "monthly"},
            },
        }
        resp = post_webhook(client, payload)
        assert resp.status_code == 200

        org.refresh_from_db()
        decoy.refresh_from_db()
        assert org.plan_expires_at is not None
        assert org.plan_expires_at > timezone.now()
        assert decoy.plan_expires_at is None

    @patch(VERIFY_SIG, return_value=True)
    def test_renewal_without_metadata_extends_plan(self, mock_verify, client):
        # Paystack-initiated subscription renewals carry no FlockIQ metadata,
        # only the Paystack plan object. They must still extend the plan.
        plan = make_plan("monthly")
        org = make_org(
            subscription_status="active",
            plan_expires_at=timezone.now() + timedelta(days=1),
        )

        payload = {
            "event": "charge.success",
            "data": {
                "id": 66002,
                "reference": "ref_renewal_1",
                "amount": plan.amount_kobo,
                "customer": {"email": org.owner_email},
                "plan": {"plan_code": plan.paystack_plan_code},
            },
        }
        resp = post_webhook(client, payload)
        assert resp.status_code == 200

        org.refresh_from_db()
        assert org.plan_expires_at > timezone.now() + timedelta(days=25)
        assert org.subscription_status == "active"
        with set_tenant_context(org):
            record = PaymentRecord.objects.get(reference="ref_renewal_1")
        assert record.status == "success"

    @patch(VERIFY_SIG, return_value=True)
    def test_renewal_reactivates_lapsed_org(self, mock_verify, client):
        plan = make_plan("monthly")
        org = make_org(
            subscription_status="lapsed",
            plan_expires_at=timezone.now() - timedelta(days=3),
        )
        assert org.is_lapsed is True

        payload = {
            "event": "charge.success",
            "data": {
                "id": 66003,
                "reference": "ref_renewal_2",
                "amount": plan.amount_kobo,
                "customer": {"email": org.owner_email},
                "plan": {"plan_code": plan.paystack_plan_code},
            },
        }
        post_webhook(client, payload)

        org.refresh_from_db()
        assert org.is_lapsed is False
        assert org.subscription_status == "active"

    @patch(VERIFY_SIG, return_value=True)
    def test_unmatched_charge_recorded_without_plan_change(
        self, mock_verify, client
    ):
        org = make_org(
            subscription_status="active",
            plan_expires_at=timezone.now() + timedelta(days=5),
        )
        before = org.plan_expires_at

        payload = {
            "event": "charge.success",
            "data": {
                "id": 66004,
                "reference": "ref_unmatched_1",
                "amount": 100000,
                "customer": {"email": org.owner_email},
                # No metadata, no recognisable plan code.
                "plan": {"plan_code": "PLN_unknown"},
            },
        }
        resp = post_webhook(client, payload)
        assert resp.status_code == 200

        org.refresh_from_db()
        assert org.plan_expires_at == before
        with set_tenant_context(org):
            assert PaymentRecord.objects.filter(
                reference="ref_unmatched_1"
            ).exists()


# ---------------------------------------------------------------------------
# Bug 7 — verify_and_activate validates org and amount
# ---------------------------------------------------------------------------

class TestVerifyAndActivate:
    def _paystack_response(self, **data_overrides):
        data = {
            "status": "success",
            "amount": 500000,
            "id": 77001,
            "channel": "card",
            "metadata": {},
        }
        data.update(data_overrides)
        return {"status": True, "data": data}

    def test_rejects_mismatched_org_id(self):
        from apps.infrastructure.billing.services import BillingService

        make_plan("monthly", amount_kobo=500000)
        org = make_org()
        other_org_id = str(uuid.uuid4())

        with patch(
            "apps.infrastructure.billing.services."
            "PaystackService.verify_transaction",
            return_value=self._paystack_response(
                metadata={"org_id": other_org_id, "plan_tier": "monthly"},
            ),
        ):
            with set_tenant_context(org):
                ok = BillingService(org).verify_and_activate("ref_steal_1")

        assert ok is False
        org.refresh_from_db()
        assert org.plan_expires_at is None

    def test_rejects_insufficient_amount(self):
        from apps.infrastructure.billing.services import BillingService

        make_plan("monthly", amount_kobo=500000)
        org = make_org()

        with patch(
            "apps.infrastructure.billing.services."
            "PaystackService.verify_transaction",
            return_value=self._paystack_response(
                amount=100,  # paid ₦1 for a ₦5,000 plan
                metadata={"org_id": str(org.id), "plan_tier": "monthly"},
            ),
        ):
            with set_tenant_context(org):
                ok = BillingService(org).verify_and_activate("ref_cheap_1")

        assert ok is False
        org.refresh_from_db()
        assert org.plan_expires_at is None

    def test_activates_on_valid_org_and_amount(self):
        from apps.infrastructure.billing.services import BillingService

        make_plan("monthly", amount_kobo=500000)
        org = make_org()

        with patch(
            "apps.infrastructure.billing.services."
            "PaystackService.verify_transaction",
            return_value=self._paystack_response(
                metadata={"org_id": str(org.id), "plan_tier": "monthly"},
            ),
        ):
            with set_tenant_context(org):
                ok = BillingService(org).verify_and_activate("ref_valid_1")

        assert ok is True
        org.refresh_from_db()
        assert org.plan_expires_at > timezone.now()


# ---------------------------------------------------------------------------
# Bug 8 — failed payment notification uses a billing event type
# ---------------------------------------------------------------------------

class TestPaymentFailedNotification:
    @patch(VERIFY_SIG, return_value=True)
    def test_creates_payment_failed_not_disease_outbreak(
        self, mock_verify, client
    ):
        from apps.infrastructure.accounts.models import CustomUser
        from apps.infrastructure.notifications.models import NotificationLog

        org = make_org()
        CustomUser.objects.create_user(
            username=f"owner-{org.subdomain}",
            email=org.owner_email,
            password="testpass123",
            org=org,
            role="owner",
        )

        payload = {
            "event": "invoice.payment_failed",
            "data": {
                "id": 88001,
                "customer": {"email": org.owner_email},
            },
        }
        resp = post_webhook(client, payload)
        assert resp.status_code == 200

        with set_tenant_context(org):
            assert NotificationLog.objects.filter(
                event_type="payment_failed"
            ).exists()
            assert not NotificationLog.objects.filter(
                event_type="disease_outbreak"
            ).exists()
            note = NotificationLog.objects.get(event_type="payment_failed")
        assert note.severity == "warning"
        assert note.action_url == "/billing/"
