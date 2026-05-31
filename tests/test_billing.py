"""
Phase 1F — Billing engine tests.

Paystack HTTP calls are mocked with unittest.mock.patch on requests.post/get.
Tests run against the dev SQLite DB (same pattern as other test files).
"""

import hashlib
import hmac
import json
import uuid
from unittest.mock import MagicMock, patch

import pytest
from django.test import Client
from django.urls import reverse

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_org(subdomain="billingtest", **kwargs):
    from apps.infrastructure.tenants.models import Organization
    defaults = {
        "name": "Billing Farm",
        "subdomain": subdomain,
        "owner_email": f"{subdomain}@test.com",
        "plan_tier": "monthly",
    }
    defaults.update(kwargs)
    return Organization.objects.create(**defaults)


def make_user(org, role="owner", email=None, password="pass1234"):
    from apps.infrastructure.accounts.models import CustomUser
    email = email or f"{role}@{org.subdomain}.com"
    return CustomUser.objects.create_user(
        email=email, username=email, password=password, role=role, org=org,
    )


def make_plan(**kwargs):
    from apps.infrastructure.billing.models import BillingPlan
    defaults = {
        "name": "Monthly Plan",
        "plan_tier": "monthly",
        "paystack_plan_code": "PLN_test123",
        "amount_kobo": 500000,
        "billing_interval": "monthly",
    }
    defaults.update(kwargs)
    return BillingPlan.objects.create(**defaults)


def _webhook_signature(payload: bytes, secret: str = "test_secret") -> str:
    return hmac.new(secret.encode(), payload, hashlib.sha512).hexdigest()


# ---------------------------------------------------------------------------
# 1. Webhook signature valid
# ---------------------------------------------------------------------------

def test_webhook_signature_valid():
    from apps.infrastructure.billing.services import PaystackService
    from django.test.utils import override_settings

    payload = b'{"event":"charge.success","data":{}}'
    sig = _webhook_signature(payload, "mysecret")

    with override_settings(PAYSTACK_WEBHOOK_SECRET="mysecret"):
        assert PaystackService.verify_webhook_signature(payload, sig) is True


# ---------------------------------------------------------------------------
# 2. Invalid signature returns 400
# ---------------------------------------------------------------------------

def test_webhook_signature_invalid_returns_400():
    from django.test.utils import override_settings

    client = Client()
    payload = b'{"event":"charge.success","data":{}}'

    with override_settings(PAYSTACK_WEBHOOK_SECRET="real_secret"):
        response = client.post(
            "/billing/webhook/paystack/",
            data=payload,
            content_type="application/json",
            HTTP_X_PAYSTACK_SIGNATURE="totally_wrong_signature",
        )

    assert response.status_code == 400


# ---------------------------------------------------------------------------
# 3. Every webhook is logged regardless of signature validity
# ---------------------------------------------------------------------------

def test_webhook_logged_regardless_of_validity():
    from apps.infrastructure.billing.models import PaystackWebhookLog
    from django.test.utils import override_settings

    client = Client()
    payload = json.dumps({"event": "charge.success", "data": {}}).encode()

    before_count = PaystackWebhookLog.objects.count()

    with override_settings(PAYSTACK_WEBHOOK_SECRET="real_secret"):
        # Send with wrong signature
        client.post(
            "/billing/webhook/paystack/",
            data=payload,
            content_type="application/json",
            HTTP_X_PAYSTACK_SIGNATURE="bad_sig",
        )

    assert PaystackWebhookLog.objects.count() == before_count + 1
    log = PaystackWebhookLog.objects.order_by("-received_at").first()
    assert log.signature_valid is False


# ---------------------------------------------------------------------------
# 4. charge.success creates a PaymentRecord
# ---------------------------------------------------------------------------

def test_charge_success_creates_payment_record():
    from apps.infrastructure.billing.models import PaymentRecord
    from apps.infrastructure.core.rls import set_tenant_context
    from django.test.utils import override_settings

    org = make_org(subdomain="chargetest", owner_email="chargetest@test.com")
    make_plan()

    payload_data = {
        "event": "charge.success",
        "data": {
            "reference": "REF_charge_001",
            "amount": 500000,
            "channel": "card",
            "id": 99999,
            "customer": {"email": "chargetest@test.com"},
            "authorization": {"authorization_code": "AUTH_abc"},
        },
    }
    payload = json.dumps(payload_data).encode()
    sig = _webhook_signature(payload, "test_secret")

    with override_settings(PAYSTACK_WEBHOOK_SECRET="test_secret"):
        client = Client()
        response = client.post(
            "/billing/webhook/paystack/",
            data=payload,
            content_type="application/json",
            HTTP_X_PAYSTACK_SIGNATURE=sig,
        )

    assert response.status_code == 200

    with set_tenant_context(org):
        records = PaymentRecord.objects.filter(reference="REF_charge_001")
        assert records.count() == 1
        rec = records.first()
        assert rec.status == "success"
        assert rec.amount_kobo == 500000
        assert rec.authorization_code == "AUTH_abc"


# ---------------------------------------------------------------------------
# 5. CycleSubscription created via BillingService.activate_cycle_subscription
# ---------------------------------------------------------------------------

def test_cycle_subscription_created_on_batch_placement():
    from apps.infrastructure.billing.models import CycleSubscription
    from apps.infrastructure.billing.services import BillingService
    from apps.infrastructure.core.rls import set_tenant_context

    org = make_org(subdomain="cycletest", plan_tier="cycle")
    plan = make_plan(plan_tier="cycle", billing_interval="per_cycle", paystack_plan_code="PLN_cycle")
    batch_id = uuid.uuid4()

    mock_ps_response = {"status": True, "data": {"subscription_code": "SUB_001", "email_token": "TOKEN_001"}}

    with set_tenant_context(org):
        with patch("apps.infrastructure.billing.services.requests.post") as mock_post:
            mock_post.return_value = MagicMock(json=lambda: mock_ps_response)
            svc = BillingService(org)
            sub = svc.activate_cycle_subscription(batch_id)

    assert sub is not None
    assert str(sub.batch_id) == str(batch_id)
    assert sub.status in ("active", "pending")

    with set_tenant_context(org):
        assert CycleSubscription.objects.filter(batch_id=batch_id, org=org).exists()


# ---------------------------------------------------------------------------
# 6. CycleSubscription cancelled via BillingService.deactivate_cycle_subscription
# ---------------------------------------------------------------------------

def test_cycle_subscription_cancelled_on_batch_closure():
    from apps.infrastructure.billing.models import BillingPlan, CycleSubscription
    from apps.infrastructure.billing.services import BillingService
    from apps.infrastructure.core.rls import set_tenant_context

    org = make_org(subdomain="canceltest", plan_tier="cycle")
    plan = make_plan(plan_tier="cycle", billing_interval="per_cycle")
    batch_id = uuid.uuid4()

    with set_tenant_context(org):
        sub = CycleSubscription.objects.create(
            org=org,
            batch_id=batch_id,
            plan=plan,
            status="active",
            paystack_subscription_code="SUB_cancel_001",
            paystack_email_token="TOKEN_cancel",
        )

    mock_cancel_response = {"status": True, "message": "Subscription disabled"}

    with set_tenant_context(org):
        with patch("apps.infrastructure.billing.services.requests.post") as mock_post:
            mock_post.return_value = MagicMock(json=lambda: mock_cancel_response)
            svc = BillingService(org)
            svc.deactivate_cycle_subscription(batch_id)

        sub.refresh_from_db()

    assert sub.status == "cancelled"
    assert sub.deactivated_at is not None


# ---------------------------------------------------------------------------
# 7. BillingPlan table has RLS disabled (readable without tenant context)
# ---------------------------------------------------------------------------

def test_billing_plan_rls_disabled():
    from apps.infrastructure.billing.models import BillingPlan

    plan = make_plan()
    # No set_tenant_context — should still return the plan
    found = BillingPlan.objects.filter(id=plan.id).first()
    assert found is not None
    assert found.id == plan.id


# ---------------------------------------------------------------------------
# 8. PaymentRecord is tenant-scoped via RLS
# ---------------------------------------------------------------------------

def test_payment_record_rls_enabled():
    from apps.infrastructure.billing.models import PaymentRecord
    from apps.infrastructure.core.rls import set_tenant_context

    org_a = make_org(subdomain="prls_a")
    org_b = make_org(subdomain="prls_b")
    plan = make_plan()

    with set_tenant_context(org_a):
        PaymentRecord.objects.create(
            org=org_a, reference="REF_RLS_A", amount_kobo=100000, status="success",
        )

    with set_tenant_context(org_b):
        refs = list(PaymentRecord.objects.values_list("reference", flat=True))

    assert "REF_RLS_A" not in refs


# ---------------------------------------------------------------------------
# 9. get_billing_summary returns the correct plan
# ---------------------------------------------------------------------------

def test_billing_summary_returns_correct_plan():
    from apps.infrastructure.billing.services import BillingService
    from apps.infrastructure.core.rls import set_tenant_context

    org = make_org(subdomain="summarytest", plan_tier="monthly")
    plan = make_plan(plan_tier="monthly")

    with set_tenant_context(org):
        svc = BillingService(org)
        summary = svc.get_billing_summary()

    assert summary["plan"] is not None
    assert summary["plan"].plan_tier == "monthly"
    assert summary["org"].subdomain == "summarytest"
