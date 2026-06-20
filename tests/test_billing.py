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


def local_noon():
    """Noon today in the platform timezone (Africa/Lagos).

    The billing reminder tasks compute days_left as a *calendar-date* delta off
    ``timezone.localdate()`` (Lagos). Anchoring a fixture to ``timezone.now()``
    (UTC) makes that delta off-by-one whenever the suite runs in the ~23:00 UTC
    window, because Lagos (UTC+1) has already rolled to the next date. Anchoring
    on the local calendar date keeps ``days_left`` exactly N for ``+ N days``.
    """
    import datetime
    from django.utils import timezone
    return timezone.make_aware(
        datetime.datetime.combine(timezone.localdate(), datetime.time(12, 0))
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
            # Calendar-date based: anchor on the local date (see local_noon)
            # so day math is correct regardless of when tests run.
            plan_expires_at=local_noon() + timedelta(days=days),
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
        plan_expires_at=local_noon() + timedelta(days=3),
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
        plan_expires_at=local_noon() + timedelta(days=5),
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
        trial_ends_at=local_noon() + timedelta(days=7),
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
        trial_ends_at=local_noon() + timedelta(days=3),
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
        trial_ends_at=local_noon() + timedelta(days=1),
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
        trial_ends_at=local_noon() + timedelta(days=10),
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
        trial_ends_at=local_noon() + timedelta(days=7),
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

    # Trial ending today → days_left == 0, not in {7, 3, 1}.
    org = make_org(
        subdomain="trial0",
        owner_email="trial0@test.com",
        plan_tier="trial",
        trial_ends_at=local_noon(),
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
        trial_ends_at=local_noon() + timedelta(days=7),
    )

    send_trial_expiry_reminders()  # should not raise

    with set_tenant_context(org):
        assert not NotificationLog.objects.filter(
            org=org, event_type="trial_expiry_reminder"
        ).exists()


# ---------------------------------------------------------------------------
# Superadmin billing-manage lifecycle (grant_grace_period / extend_trial /
# change_subscription_status) — extracted from BillingManageOrgView (item g).
# ---------------------------------------------------------------------------

class TestBillingServiceLifecycle:

    def test_grant_grace_period_sets_fields(self, db):
        import datetime as dt
        from django.utils import timezone
        from apps.infrastructure.billing.services import BillingService

        org = make_org(
            subdomain="graceorg",
            is_active=False,
            subscription_status="past_due",
        )
        ends_at = timezone.make_aware(dt.datetime(2026, 12, 31, 12, 0, 0))

        BillingService.grant_grace_period(org, ends_at=ends_at)

        org.refresh_from_db()
        assert org.grace_period_ends_at == ends_at
        assert org.subscription_status == "active"
        assert org.is_active is True

    def test_grant_grace_period_logs(self, db):
        import datetime as dt
        from django.utils import timezone
        from structlog.testing import capture_logs
        from apps.infrastructure.billing.services import BillingService

        org = make_org(subdomain="gracelog")
        user = make_user(org)
        ends_at = timezone.make_aware(dt.datetime(2026, 11, 30, 12, 0, 0))

        with capture_logs() as logs:
            BillingService.grant_grace_period(org, ends_at=ends_at, granted_by=user)

        assert any(
            e["event"] == "billing.grace_period_granted"
            and e["org_id"] == str(org.pk)
            and e["granted_by"] == str(user.pk)
            for e in logs
        )

    def test_extend_trial_from_existing_end(self, db):
        import datetime as dt
        from datetime import timedelta
        from django.utils import timezone
        from apps.infrastructure.billing.services import BillingService

        start = timezone.make_aware(dt.datetime(2026, 7, 1, 12, 0, 0))
        org = make_org(subdomain="trialext", plan_tier="trial", trial_ends_at=start)

        BillingService.extend_trial(org, days=7)

        org.refresh_from_db()
        assert org.trial_ends_at == start + timedelta(days=7)
        assert org.subscription_status == "trial"

    def test_extend_trial_from_now_when_unset(self, db):
        from datetime import timedelta
        from django.utils import timezone
        from apps.infrastructure.billing.services import BillingService

        org = make_org(subdomain="trialnew", plan_tier="trial", trial_ends_at=None)
        before = timezone.now()

        BillingService.extend_trial(org, days=14)

        org.refresh_from_db()
        assert org.trial_ends_at is not None
        # Within a few seconds of now + 14 days.
        assert org.trial_ends_at >= before + timedelta(days=14) - timedelta(seconds=10)
        assert org.subscription_status == "trial"

    def test_extend_trial_logs(self, db):
        from structlog.testing import capture_logs
        from apps.infrastructure.billing.services import BillingService

        org = make_org(subdomain="triallog", plan_tier="trial")
        user = make_user(org)

        with capture_logs() as logs:
            BillingService.extend_trial(org, days=5, extended_by=user)

        assert any(
            e["event"] == "billing.trial_extended"
            and e["org_id"] == str(org.pk)
            and e["days"] == 5
            and e["extended_by"] == str(user.pk)
            for e in logs
        )

    def test_change_status_offline_notifies_owner(self, db):
        from apps.infrastructure.billing.services import BillingService

        org = make_org(subdomain="statusoff", is_active=True)
        make_user(org, email="owner@statusoff.com")

        with patch("apps.infrastructure.tenants.services.EmailService") as mock_email:
            BillingService.change_subscription_status(org, "past_due")

        org.refresh_from_db()
        assert org.subscription_status == "past_due"
        assert org.is_active is False
        mock_email.send_suspension.assert_called_once()

    def test_change_status_active_does_not_email(self, db):
        from apps.infrastructure.billing.services import BillingService

        org = make_org(
            subdomain="statuson",
            is_active=False,
            subscription_status="suspended",
        )
        make_user(org, email="owner@statuson.com")

        with patch("apps.infrastructure.tenants.services.EmailService") as mock_email:
            BillingService.change_subscription_status(org, "active")

        org.refresh_from_db()
        assert org.subscription_status == "active"
        assert org.is_active is True
        mock_email.send_suspension.assert_not_called()
        mock_email.send_reactivation.assert_not_called()


class TestBillingManagePanelRegression:
    """Regression: the superadmin billing-manage panel still mutates org state
    correctly now that it routes through BillingService."""

    def test_grace_period_action(self, client, super_admin_user, tenant_user):
        from django.utils import timezone
        org = tenant_user.org
        client.force_login(super_admin_user)
        resp = client.post(f'/superadmin/billing/{org.pk}/manage/', {
            'action': 'grace_period',
            'grace_end_date': '2026-12-31',
        })
        assert resp.status_code == 204
        org.refresh_from_db()
        assert org.grace_period_ends_at is not None
        assert (timezone.localtime(org.grace_period_ends_at).date().isoformat()
                == '2026-12-31')
        assert org.subscription_status == 'active'
        assert org.is_active is True

    def test_extend_trial_action(self, client, super_admin_user, tenant_user):
        org = tenant_user.org
        org.trial_ends_at = None
        org.save()
        client.force_login(super_admin_user)
        resp = client.post(f'/superadmin/billing/{org.pk}/manage/', {
            'action': 'extend_trial',
            'days': '10',
        })
        assert resp.status_code == 204
        org.refresh_from_db()
        assert org.trial_ends_at is not None
        assert org.subscription_status == 'trial'

    def test_change_status_action_offline(self, client, super_admin_user, tenant_user):
        org = tenant_user.org
        client.force_login(super_admin_user)
        with patch("apps.infrastructure.tenants.services.EmailService"):
            resp = client.post(f'/superadmin/billing/{org.pk}/manage/', {
                'action': 'change_status',
                'status': 'past_due',
            })
        assert resp.status_code == 204
        org.refresh_from_db()
        assert org.subscription_status == 'past_due'
        assert org.is_active is False

    def test_change_plan_action_no_regression(self, client, super_admin_user, tenant_user):
        """change_plan (SuperAdminTenantActionView) still activates via
        BillingService after the import was hoisted to module level."""
        org = tenant_user.org
        client.force_login(super_admin_user)
        resp = client.post(f'/superadmin/tenants/{org.pk}/action/', {
            'action': 'change_plan',
            'plan_tier': 'yearly',
        })
        assert resp.status_code == 204
        org.refresh_from_db()
        assert org.plan_tier == 'yearly'


# ---------------------------------------------------------------------------
# Signup → Paystack checkout (post email-verification) + dashboard trial banner
# ---------------------------------------------------------------------------

class TestSignupCheckoutView:
    """FIX 3 — GET /billing/checkout/?plan= initializes Paystack for a paid
    plan picked at signup, reusing BillingService.request_upgrade."""

    def _login(self, client, org):
        user = make_user(org, role="owner", email=f"owner@{org.subdomain}.com")
        client.force_login(user)
        return user

    @patch("apps.infrastructure.billing.services.BillingService.request_upgrade")
    def test_valid_plan_redirects_to_paystack(self, mock_upgrade):
        mock_upgrade.return_value = {
            "method": "paystack",
            "authorization_url": "https://checkout.paystack.com/abc123",
            "reference": "FIQ-TEST",
        }
        org = make_org(subdomain="chk1", plan_tier="trial",
                       subscription_status="trial")
        make_plan(plan_tier="monthly", amount_kobo=500000)
        client = Client()
        self._login(client, org)
        resp = client.get("/billing/checkout/?plan=monthly")
        assert resp.status_code == 302
        assert resp["Location"] == "https://checkout.paystack.com/abc123"
        mock_upgrade.assert_called_once()

    def test_paid_plan_not_in_db_redirects_billing(self):
        org = make_org(subdomain="chk2", plan_tier="trial",
                       subscription_status="trial")
        # No BillingPlan rows — 'yearly' is a valid tier but unavailable.
        client = Client()
        self._login(client, org)
        resp = client.get("/billing/checkout/?plan=yearly")
        assert resp.status_code == 302
        assert resp["Location"] == "/billing/"

    def test_trial_plan_redirects_home(self):
        org = make_org(subdomain="chk3", plan_tier="trial",
                       subscription_status="trial")
        client = Client()
        self._login(client, org)
        resp = client.get("/billing/checkout/?plan=trial")
        assert resp.status_code == 302
        assert resp["Location"] == "/"

    def test_unauthenticated_redirects_to_login(self):
        resp = Client().get("/billing/checkout/?plan=monthly")
        assert resp.status_code == 302
        assert "/login/" in resp["Location"]


class TestDashboardTrialBanner:
    """FIX 5 — the dashboard renders a trial countdown banner for trial orgs
    and omits it for active/paid orgs."""

    def _login(self, org):
        user = make_user(org, role="owner", email=f"owner@{org.subdomain}.com")
        user.email_verified = True
        user.save(update_fields=["email_verified"])
        client = Client()
        client.force_login(user)
        return client

    def test_trial_org_sees_banner(self):
        from datetime import timedelta
        from django.utils import timezone
        org = make_org(
            subdomain="trialbnr", plan_tier="trial",
            subscription_status="trial", onboarding_complete=True,
            trial_ends_at=timezone.now() + timedelta(days=10),
        )
        resp = self._login(org).get("/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert 'id="trial-banner"' in content
        assert "Upgrade Now" in content
        assert "/billing/" in content

    def test_active_org_no_banner(self):
        org = make_org(
            subdomain="activebnr", plan_tier="monthly",
            subscription_status="active", onboarding_complete=True,
        )
        resp = self._login(org).get("/")
        assert resp.status_code == 200
        assert 'id="trial-banner"' not in resp.content.decode()
