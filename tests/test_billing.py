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

    # A successful charge promotes a trial org to an active subscription.
    org.refresh_from_db()
    assert org.subscription_status == "active"


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


# ---------------------------------------------------------------------------
# 10. trial_status context processor — drives the global trial banner
# ---------------------------------------------------------------------------

def _request_for(user):
    from django.test import RequestFactory

    request = RequestFactory().get("/")
    request.user = user
    return request


def test_trial_status_expired_trial():
    from datetime import timedelta
    from django.utils import timezone
    from apps.infrastructure.billing.context_processors import trial_status

    org = make_org(
        subdomain="trialexpired",
        plan_tier="trial",
        trial_ends_at=timezone.now() - timedelta(days=1),
    )
    user = make_user(org)

    ctx = trial_status(_request_for(user))
    assert ctx["trial_expired"] is True
    assert ctx["on_trial"] is False
    assert ctx["trial_days_remaining"] == 0


def test_trial_status_active_trial_counts_down():
    from datetime import timedelta
    from django.utils import timezone
    from apps.infrastructure.billing.context_processors import trial_status

    org = make_org(
        subdomain="trialactive",
        plan_tier="trial",
        trial_ends_at=timezone.now() + timedelta(days=3, hours=1),
    )
    user = make_user(org)

    ctx = trial_status(_request_for(user))
    assert ctx["trial_expired"] is False
    assert ctx["on_trial"] is True
    assert ctx["trial_days_remaining"] == 3


def test_trial_status_super_admin_sees_nothing():
    from apps.infrastructure.billing.context_processors import trial_status

    org = make_org(subdomain="trialsuper", plan_tier="trial")
    user = make_user(org, role="super_admin", email="super@trialsuper.com")

    ctx = trial_status(_request_for(user))
    assert ctx["trial_expired"] is False
    assert ctx["on_trial"] is False


def test_trial_status_paid_org_sees_nothing():
    from apps.infrastructure.billing.context_processors import trial_status

    org = make_org(subdomain="trialpaid", plan_tier="monthly")
    user = make_user(org)

    ctx = trial_status(_request_for(user))
    assert ctx["trial_expired"] is False
    assert ctx["on_trial"] is False


def test_trial_status_anonymous_user_sees_nothing():
    from django.contrib.auth.models import AnonymousUser
    from apps.infrastructure.billing.context_processors import trial_status

    ctx = trial_status(_request_for(AnonymousUser()))
    assert ctx["trial_expired"] is False
    assert ctx["on_trial"] is False


# ---------------------------------------------------------------------------
# Subscription lifecycle — activate_plan()
# ---------------------------------------------------------------------------

def test_activate_plan_sets_expiry_30_days_from_now():
    from datetime import timedelta
    from django.utils import timezone
    from apps.infrastructure.billing.services import BillingService
    from apps.infrastructure.core.rls import set_tenant_context

    org = make_org(subdomain="actexpiry", plan_tier="trial")
    make_user(org)  # owner
    make_plan(plan_tier="monthly")

    with set_tenant_context(org):
        applied = BillingService(org).activate_plan(plan_tier="monthly")

    assert applied is True
    org.refresh_from_db()
    assert org.plan_tier == "monthly"
    assert org.subscription_status == "active"
    assert org.plan_expires_at is not None
    delta = org.plan_expires_at - timezone.now()
    assert timedelta(days=29, hours=23) < delta <= timedelta(days=30)


def test_activate_plan_emails_owner():
    from django.core import mail
    from apps.infrastructure.billing.services import BillingService
    from apps.infrastructure.core.rls import set_tenant_context

    org = make_org(subdomain="actemail", plan_tier="trial")
    owner = make_user(org)
    make_plan(plan_tier="monthly")

    mail.outbox = []
    with set_tenant_context(org):
        BillingService(org).activate_plan(plan_tier="monthly")

    assert any(owner.email in m.to for m in mail.outbox)


def test_activate_plan_creates_owner_in_app_notification():
    from apps.infrastructure.billing.services import BillingService
    from apps.infrastructure.core.rls import set_tenant_context
    from apps.infrastructure.notifications.models import NotificationLog

    org = make_org(subdomain="actnotif", plan_tier="trial")
    owner = make_user(org)
    make_plan(plan_tier="monthly")

    with set_tenant_context(org):
        BillingService(org).activate_plan(plan_tier="monthly")
        assert NotificationLog.objects.filter(
            org=org, recipient=owner, event_type="billing_plan_activated"
        ).exists()


def test_activate_plan_notifies_superadmin():
    from apps.infrastructure.accounts.models import CustomUser
    from apps.infrastructure.billing.services import BillingService
    from apps.infrastructure.core.rls import set_tenant_context
    from apps.infrastructure.notifications.models import AdminNotification

    su = CustomUser.objects.create_superuser(email="su_act@flock.com", password="x")
    org = make_org(subdomain="actsuper", plan_tier="trial")
    make_user(org)
    make_plan(plan_tier="monthly")

    before = AdminNotification.objects.filter(recipient=su).count()
    with set_tenant_context(org):
        BillingService(org).activate_plan(plan_tier="monthly")

    assert AdminNotification.objects.filter(recipient=su).count() == before + 1


def test_activate_plan_is_idempotent_on_payment_reference():
    from apps.infrastructure.billing.models import PaymentRecord
    from apps.infrastructure.billing.services import BillingService
    from apps.infrastructure.core.rls import set_tenant_context

    org = make_org(subdomain="actidem", plan_tier="trial")
    make_user(org)
    make_plan(plan_tier="monthly")

    with set_tenant_context(org):
        first = BillingService(org).activate_plan(
            plan_tier="monthly", payment_reference="REF_IDEM_1"
        )
        second = BillingService(org).activate_plan(
            plan_tier="monthly", payment_reference="REF_IDEM_1"
        )
        count = PaymentRecord.objects.filter(reference="REF_IDEM_1").count()

    assert first is True
    assert second is False  # duplicate reference → no-op
    assert count == 1


# ---------------------------------------------------------------------------
# Admin manual upgrade routes through activate_plan()
# ---------------------------------------------------------------------------

def test_admin_change_plan_uses_activate_plan():
    from apps.infrastructure.accounts.models import CustomUser
    from apps.infrastructure.tenants.models import Organization

    su = CustomUser.objects.create_superuser(email="su_admin@flock.com", password="x")
    org = make_org(subdomain="adminup", plan_tier="trial")
    make_user(org)
    make_plan(plan_tier="yearly", billing_interval="annually", amount_kobo=5000000)

    client = Client()
    client.force_login(su)
    url = reverse("superadmin:tenant_action", kwargs={"pk": org.id})
    resp = client.post(url, {"action": "change_plan", "plan_tier": "yearly"})

    assert resp.status_code in (200, 204)
    org = Organization.objects.get(pk=org.pk)
    assert org.plan_tier == "yearly"
    # A direct field set would leave this None — its presence proves activate_plan ran.
    assert org.plan_expires_at is not None


# ---------------------------------------------------------------------------
# Paystack webhook routes a plan charge through activate_plan()
# ---------------------------------------------------------------------------

def test_webhook_charge_success_with_plan_metadata_activates_plan():
    from django.test.utils import override_settings
    from apps.infrastructure.billing.models import PaymentRecord
    from apps.infrastructure.core.rls import set_tenant_context

    org = make_org(subdomain="whact", owner_email="whact@test.com", plan_tier="trial")
    make_user(org, email="owner@whact.com")
    make_plan(plan_tier="monthly")

    payload_data = {
        "event": "charge.success",
        "data": {
            "reference": "REF_wh_act",
            "amount": 500000,
            "channel": "card",
            "id": 12345,
            "customer": {"email": "whact@test.com"},
            "authorization": {"authorization_code": "AUTH_x"},
            "metadata": {"plan_tier": "monthly"},
        },
    }
    payload = json.dumps(payload_data).encode()
    sig = _webhook_signature(payload, "test_secret")

    with override_settings(PAYSTACK_WEBHOOK_SECRET="test_secret"):
        resp = Client().post(
            "/billing/webhook/paystack/",
            data=payload,
            content_type="application/json",
            HTTP_X_PAYSTACK_SIGNATURE=sig,
        )

    assert resp.status_code == 200
    org.refresh_from_db()
    assert org.plan_tier == "monthly"
    assert org.plan_expires_at is not None
    with set_tenant_context(org):
        assert PaymentRecord.objects.filter(reference="REF_wh_act").exists()


# ---------------------------------------------------------------------------
# Expiry reminder Celery task
# ---------------------------------------------------------------------------

def test_expiry_reminder_fires_at_7_3_1_days():
    from datetime import timedelta
    from django.utils import timezone
    from apps.infrastructure.billing.tasks import send_subscription_expiry_reminders
    from apps.infrastructure.core.rls import set_tenant_context
    from apps.infrastructure.notifications.models import NotificationLog
    from apps.infrastructure.tenants.models import Organization

    for days in (7, 3, 1):
        org = make_org(
            subdomain=f"exp{days}",
            owner_email=f"exp{days}@test.com",
            plan_tier="monthly",
            plan_expires_at=timezone.now() + timedelta(days=days, hours=2),
        )
        make_user(org, email=f"owner@exp{days}.com")

    send_subscription_expiry_reminders()

    for days in (7, 3, 1):
        org = Organization.objects.get(subdomain=f"exp{days}")
        with set_tenant_context(org):
            assert NotificationLog.objects.filter(
                org=org, event_type="billing_expiry_reminder"
            ).exists(), f"expected reminder for {days}-day org"


def test_expiry_reminder_does_not_fire_for_trial_orgs():
    from datetime import timedelta
    from django.utils import timezone
    from apps.infrastructure.billing.tasks import send_subscription_expiry_reminders
    from apps.infrastructure.core.rls import set_tenant_context
    from apps.infrastructure.notifications.models import NotificationLog

    org = make_org(
        subdomain="exptrial",
        owner_email="exptrial@test.com",
        plan_tier="trial",
        plan_expires_at=timezone.now() + timedelta(days=3, hours=2),
    )
    make_user(org, email="owner@exptrial.com")

    send_subscription_expiry_reminders()

    with set_tenant_context(org):
        assert not NotificationLog.objects.filter(
            org=org, event_type="billing_expiry_reminder"
        ).exists()


def test_expiry_reminder_skips_non_reminder_day():
    from datetime import timedelta
    from django.utils import timezone
    from apps.infrastructure.billing.tasks import send_subscription_expiry_reminders
    from apps.infrastructure.core.rls import set_tenant_context
    from apps.infrastructure.notifications.models import NotificationLog

    org = make_org(
        subdomain="exp5",
        owner_email="exp5@test.com",
        plan_tier="monthly",
        plan_expires_at=timezone.now() + timedelta(days=5, hours=2),
    )
    make_user(org, email="owner@exp5.com")

    send_subscription_expiry_reminders()

    with set_tenant_context(org):
        assert not NotificationLog.objects.filter(
            org=org, event_type="billing_expiry_reminder"
        ).exists()


# ---------------------------------------------------------------------------
# Trial expiry reminder Celery task
# ---------------------------------------------------------------------------

def test_trial_reminder_7_days_sends_email_and_notification():
    from datetime import timedelta
    from django.core import mail
    from django.utils import timezone
    from apps.infrastructure.billing.tasks import send_trial_expiry_reminders
    from apps.infrastructure.core.rls import set_tenant_context
    from apps.infrastructure.notifications.models import NotificationLog

    org = make_org(
        subdomain="trial7",
        owner_email="trial7@test.com",
        plan_tier="trial",
        trial_ends_at=timezone.now() + timedelta(days=7, hours=2),
    )
    owner = make_user(org, email="owner@trial7.com")

    mail.outbox = []
    send_trial_expiry_reminders()

    assert any(owner.email in m.to for m in mail.outbox)
    with set_tenant_context(org):
        assert NotificationLog.objects.filter(
            org=org, recipient=owner, event_type="trial_expiry_reminder"
        ).exists()


def test_trial_reminder_3_days_notification_is_warning():
    from datetime import timedelta
    from django.utils import timezone
    from apps.infrastructure.billing.tasks import send_trial_expiry_reminders
    from apps.infrastructure.core.rls import set_tenant_context
    from apps.infrastructure.notifications.models import NotificationLog

    org = make_org(
        subdomain="trial3",
        owner_email="trial3@test.com",
        plan_tier="trial",
        trial_ends_at=timezone.now() + timedelta(days=3, hours=2),
    )
    make_user(org, email="owner@trial3.com")

    send_trial_expiry_reminders()

    with set_tenant_context(org):
        note = NotificationLog.objects.get(
            org=org, event_type="trial_expiry_reminder"
        )
        assert note.severity == "warning"


def test_trial_reminder_1_day_urgency_is_today():
    from datetime import timedelta
    from django.utils import timezone
    from apps.infrastructure.billing.tasks import send_trial_expiry_reminders
    from apps.infrastructure.core.rls import set_tenant_context
    from apps.infrastructure.notifications.models import NotificationLog

    org = make_org(
        subdomain="trial1",
        owner_email="trial1@test.com",
        plan_tier="trial",
        trial_ends_at=timezone.now() + timedelta(days=1, hours=2),
    )
    make_user(org, email="owner@trial1.com")

    send_trial_expiry_reminders()

    with set_tenant_context(org):
        note = NotificationLog.objects.get(
            org=org, event_type="trial_expiry_reminder"
        )
        assert "today" in note.title


def test_trial_reminder_skips_non_reminder_day():
    from datetime import timedelta
    from django.core import mail
    from django.utils import timezone
    from apps.infrastructure.billing.tasks import send_trial_expiry_reminders
    from apps.infrastructure.core.rls import set_tenant_context
    from apps.infrastructure.notifications.models import NotificationLog

    org = make_org(
        subdomain="trial10",
        owner_email="trial10@test.com",
        plan_tier="trial",
        trial_ends_at=timezone.now() + timedelta(days=10, hours=2),
    )
    make_user(org, email="owner@trial10.com")

    mail.outbox = []
    send_trial_expiry_reminders()

    assert not any("trial10@test.com" in m.to or "owner@trial10.com" in m.to
                   for m in mail.outbox)
    with set_tenant_context(org):
        assert not NotificationLog.objects.filter(
            org=org, event_type="trial_expiry_reminder"
        ).exists()


def test_trial_reminder_ignores_paid_orgs():
    from datetime import timedelta
    from django.utils import timezone
    from apps.infrastructure.billing.tasks import send_trial_expiry_reminders
    from apps.infrastructure.core.rls import set_tenant_context
    from apps.infrastructure.notifications.models import NotificationLog

    # Paid org sitting exactly on a reminder day — must still be ignored
    # because the task filters plan_tier='trial'.
    org = make_org(
        subdomain="paidnot",
        owner_email="paidnot@test.com",
        plan_tier="monthly",
        trial_ends_at=timezone.now() + timedelta(days=7, hours=2),
    )
    make_user(org, email="owner@paidnot.com")

    send_trial_expiry_reminders()

    with set_tenant_context(org):
        assert not NotificationLog.objects.filter(
            org=org, event_type="trial_expiry_reminder"
        ).exists()


def test_trial_reminder_skips_expired_trial():
    from datetime import timedelta
    from django.utils import timezone
    from apps.infrastructure.billing.tasks import send_trial_expiry_reminders
    from apps.infrastructure.core.rls import set_tenant_context
    from apps.infrastructure.notifications.models import NotificationLog

    # Trial ending within the day → days_left == 0, not in {7, 3, 1}.
    org = make_org(
        subdomain="trial0",
        owner_email="trial0@test.com",
        plan_tier="trial",
        trial_ends_at=timezone.now() + timedelta(hours=2),
    )
    make_user(org, email="owner@trial0.com")

    send_trial_expiry_reminders()

    with set_tenant_context(org):
        assert not NotificationLog.objects.filter(
            org=org, event_type="trial_expiry_reminder"
        ).exists()


def test_trial_reminder_no_owner_does_not_error():
    from datetime import timedelta
    from django.utils import timezone
    from apps.infrastructure.billing.tasks import send_trial_expiry_reminders
    from apps.infrastructure.core.rls import set_tenant_context
    from apps.infrastructure.notifications.models import NotificationLog

    # Org on a reminder day but with no owner user — must skip gracefully.
    org = make_org(
        subdomain="trialnoowner",
        owner_email="trialnoowner@test.com",
        plan_tier="trial",
        trial_ends_at=timezone.now() + timedelta(days=7, hours=2),
    )

    send_trial_expiry_reminders()  # should not raise

    with set_tenant_context(org):
        assert not NotificationLog.objects.filter(
            org=org, event_type="trial_expiry_reminder"
        ).exists()
