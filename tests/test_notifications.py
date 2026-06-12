"""
Phase 1E — Notifications engine tests.

Conventions:
- All tests use pytest-django (pytestmark = pytest.mark.django_db)
- No fixture files: each test builds its own objects to be self-contained
- Providers are tested with mocked external calls
"""

import uuid
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_org(subdomain="testfarm", **kwargs):
    from apps.infrastructure.tenants.models import Organization
    defaults = {"name": "Test Farm", "subdomain": subdomain, "owner_email": f"{subdomain}@test.com"}
    defaults.update(kwargs)
    return Organization.objects.create(**defaults)


def make_user(org, role="owner", email=None, phone="+2348012345678"):
    from apps.infrastructure.accounts.models import CustomUser
    if email is None:
        email = f"{role}@{org.subdomain}.com"
    return CustomUser.objects.create_user(
        email=email,
        username=email,
        password="pass1234",
        role=role,
        org=org,
        phone=phone,
    )


# ---------------------------------------------------------------------------
# 1. AlertRules seeded on Org creation
# ---------------------------------------------------------------------------

def test_alert_rules_seeded_on_org_creation():
    from apps.infrastructure.notifications.models import AlertRule, DEFAULT_ALERT_RULES
    from apps.infrastructure.core.rls import set_tenant_context
    org = make_org(subdomain="seedtest")
    with set_tenant_context(org):
        count = AlertRule.objects.filter(org=org).count()
    assert count == len(DEFAULT_ALERT_RULES)


# ---------------------------------------------------------------------------
# 2. Cooldown prevents duplicate OutboxEvents
# ---------------------------------------------------------------------------

def test_cooldown_prevents_duplicate_outbox_events():
    from apps.infrastructure.notifications.models import AlertRule, OutboxEvent
    from apps.infrastructure.notifications.services import NotificationService
    from apps.infrastructure.core.rls import set_tenant_context

    org = make_org(subdomain="cooldowntest")
    make_user(org, role="owner")

    with set_tenant_context(org):
        AlertRule.objects.filter(org=org, event_type="water_drop").update(cooldown_minutes=60)

        svc = NotificationService(org)
        svc.send("water_drop", {"farm_name": "Test Farm", "value": "50"})

        OutboxEvent.objects.filter(org_id=org.id, event_type="water_drop").update(
            status="delivered",
            delivered_at=timezone.now(),
        )

        before_count = OutboxEvent.objects.filter(org_id=org.id, event_type="water_drop").count()
        svc.send("water_drop", {"farm_name": "Test Farm", "value": "50"})
        after_count = OutboxEvent.objects.filter(org_id=org.id, event_type="water_drop").count()

    assert before_count == after_count


# ---------------------------------------------------------------------------
# 3. Only correct roles receive notifications
# ---------------------------------------------------------------------------

def test_only_correct_roles_get_notified():
    from apps.infrastructure.notifications.models import AlertRule, OutboxEvent
    from apps.infrastructure.notifications.services import NotificationService
    from apps.infrastructure.core.rls import set_tenant_context

    org = make_org(subdomain="roletest")
    owner = make_user(org, role="owner", email="owner@roletest.com")
    make_user(org, role="data_entry", email="de@roletest.com")

    with set_tenant_context(org):
        AlertRule.objects.filter(org=org, event_type="theft_suspected").update(
            notify_roles=["owner"], cooldown_minutes=0
        )

        svc = NotificationService(org)
        svc.send("theft_suspected", {"farm_name": "Test Farm", "batch_name": "B1", "count": "5"})

        events = OutboxEvent.objects.filter(org_id=org.id, event_type="theft_suspected")
        recipient_ids = set(str(e.recipient_user_id) for e in events)

    assert str(owner.id) in recipient_ids
    assert all(str(r_id) == str(owner.id) for r_id in recipient_ids)


# ---------------------------------------------------------------------------
# 4. Idempotency key is unique per user/channel/day
# ---------------------------------------------------------------------------

def test_outbox_event_has_unique_idempotency_key():
    from apps.infrastructure.notifications.models import AlertRule, OutboxEvent
    from apps.infrastructure.notifications.services import NotificationService
    from apps.infrastructure.core.rls import set_tenant_context
    from datetime import date

    org = make_org(subdomain="idemptest")
    user = make_user(org, role="owner", email="owner@idemptest.com")

    with set_tenant_context(org):
        AlertRule.objects.filter(org=org, event_type="batch_closed").update(cooldown_minutes=0)
        svc = NotificationService(org)
        svc.send("batch_closed", {"farm_name": "F", "batch_name": "B1", "date": str(date.today())})

        events = OutboxEvent.objects.filter(org_id=org.id, event_type="batch_closed")
        keys = [e.idempotency_key for e in events]

    assert len(keys) == len(set(keys)), "Idempotency keys must be unique"
    for key in keys:
        assert str(user.id) in key
        assert str(org.id) in key


# ---------------------------------------------------------------------------
# 5. TermiiProvider returns DeliveryResult on success
# ---------------------------------------------------------------------------

def test_termii_provider_returns_delivery_result_on_success():
    from apps.infrastructure.notifications.providers.termii import TermiiProvider
    from apps.infrastructure.notifications.providers.base import NotificationPayload

    payload = NotificationPayload(
        recipient_id="user-1",
        recipient_phone="+2348012345678",
        recipient_email="",
        subject="",
        body="Test SMS body",
        body_html="",
        channel="sms",
        idempotency_key="mortality_spike:org1:user1:2026-01-01:sms",
        org_id="org-1",
    )

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"code": "ok", "message_id": "abc123"}

    with patch("apps.infrastructure.notifications.providers.termii.requests.post", return_value=mock_response):
        result = TermiiProvider().send(payload)

    assert result.success is True
    assert result.provider == "termii"
    assert result.external_id == "abc123"


# ---------------------------------------------------------------------------
# 6. TermiiProvider returns should_retry=True on timeout
# ---------------------------------------------------------------------------

def test_termii_provider_returns_retry_on_timeout():
    import requests as req
    from apps.infrastructure.notifications.providers.termii import TermiiProvider
    from apps.infrastructure.notifications.providers.base import NotificationPayload

    payload = NotificationPayload(
        recipient_id="user-1",
        recipient_phone="+2348012345678",
        recipient_email="",
        subject="",
        body="Test SMS",
        body_html="",
        channel="sms",
        idempotency_key="test:org:user:2026-01-01:sms",
        org_id="org-1",
    )

    with patch("apps.infrastructure.notifications.providers.termii.requests.post", side_effect=req.Timeout):
        result = TermiiProvider().send(payload)

    assert result.success is False
    assert result.should_retry is True
    assert result.error_code == "timeout"


# ---------------------------------------------------------------------------
# 7. SMTPProvider sends email
# ---------------------------------------------------------------------------

def test_smtp_provider_sends_email():
    from apps.infrastructure.notifications.providers.smtp import SMTPProvider
    from apps.infrastructure.notifications.providers.base import NotificationPayload

    payload = NotificationPayload(
        recipient_id="user-1",
        recipient_phone="",
        recipient_email="owner@testfarm.com",
        subject="Weekly Summary",
        body="Your weekly summary.",
        body_html="<p>Your weekly summary.</p>",
        channel="email",
        idempotency_key="weekly_summary:org:user:2026-01-01:email",
        org_id="org-1",
    )

    with patch("apps.infrastructure.notifications.providers.smtp.EmailMultiAlternatives") as mock_email_cls:
        mock_msg = MagicMock()
        mock_email_cls.return_value = mock_msg
        result = SMTPProvider().send(payload)

    assert result.success is True
    mock_msg.send.assert_called_once()


# ---------------------------------------------------------------------------
# 8. InAppProvider returns success
# ---------------------------------------------------------------------------

def test_inapp_provider_returns_success():
    from apps.infrastructure.notifications.providers.inapp import InAppProvider
    from apps.infrastructure.notifications.providers.base import NotificationPayload

    payload = NotificationPayload(
        recipient_id="user-1",
        recipient_phone="",
        recipient_email="",
        subject="Mortality Spike Detected",
        body="3 deaths at Test Farm",
        body_html="",
        channel="in_app",
        idempotency_key="mortality_spike:org:user:2026-01-01:in_app",
        org_id="org-1",
    )

    result = InAppProvider().send(payload)

    assert result.success is True
    assert result.provider == "inapp"


# ---------------------------------------------------------------------------
# 9. process_outbox delivers pending events
# ---------------------------------------------------------------------------

def test_process_outbox_delivers_pending_events():
    import uuid
    from apps.infrastructure.notifications.models import OutboxEvent
    from apps.infrastructure.notifications.tasks import process_outbox

    org = make_org(subdomain="outboxtest")
    user = make_user(org, role="owner", email="owner@outboxtest.com")

    event = OutboxEvent.objects.create(
        org_id=org.id,
        event_type="batch_closed",
        recipient_user_id=user.id,
        recipient_phone=user.phone,
        recipient_email=user.email,
        subject="Batch Closed",
        body="Your batch was closed.",
        channel="in_app",
        idempotency_key=f"batch_closed:{org.id}:{user.id}:2026-01-01:in_app",
        status="pending",
    )

    with patch("apps.infrastructure.notifications.tasks._create_notification_log") as mock_log:
        process_outbox()

    event.refresh_from_db()
    assert event.status == "delivered"
    mock_log.assert_called_once()


# ---------------------------------------------------------------------------
# 10. process_outbox skips locked rows (no double-processing)
# ---------------------------------------------------------------------------

def test_process_outbox_skips_locked_rows():
    import uuid
    from apps.infrastructure.notifications.models import OutboxEvent
    from apps.infrastructure.notifications.tasks import process_outbox

    org = make_org(subdomain="lockedtest")
    user = make_user(org, role="owner", email="owner@lockedtest.com")

    OutboxEvent.objects.create(
        org_id=org.id,
        event_type="batch_closed",
        recipient_user_id=user.id,
        recipient_email=user.email,
        subject="Batch Closed",
        body="Closed.",
        channel="in_app",
        idempotency_key=f"batch_closed:{org.id}:{user.id}:2026-01-02:in_app",
        status="processing",
        attempts=1,
    )

    with patch("apps.infrastructure.notifications.tasks._deliver_event") as mock_deliver:
        process_outbox()

    mock_deliver.assert_not_called()


# ---------------------------------------------------------------------------
# 11. mark_read updates is_read
# ---------------------------------------------------------------------------

def test_mark_read_updates_is_read():
    from apps.infrastructure.notifications.models import NotificationLog
    from apps.infrastructure.notifications.services import NotificationService
    from apps.infrastructure.core.rls import set_tenant_context

    org = make_org(subdomain="markreadtest")
    user = make_user(org, role="owner", email="owner@markreadtest.com")

    with set_tenant_context(org):
        notif = NotificationLog.objects.create(
            org=org,
            event_type="batch_closed",
            title="Test",
            body="Test body",
            severity="info",
            channel="in_app",
            recipient=user,
        )
        svc = NotificationService(org)
        svc.mark_read(notif.id, user)
        notif.refresh_from_db()

    assert notif.is_read is True
    assert notif.read_at is not None


# ---------------------------------------------------------------------------
# 12. get_unread_count returns correct integer
# ---------------------------------------------------------------------------

def test_unread_count_returns_correct_integer():
    from apps.infrastructure.notifications.models import NotificationLog
    from apps.infrastructure.notifications.services import NotificationService
    from apps.infrastructure.core.rls import set_tenant_context

    org = make_org(subdomain="unreadtest")
    user = make_user(org, role="owner", email="owner@unreadtest.com")

    with set_tenant_context(org):
        for i in range(3):
            NotificationLog.objects.create(
                org=org,
                event_type="water_drop",
                title=f"Alert {i}",
                body="Body",
                severity="warning",
                channel="in_app",
                recipient=user,
            )
        NotificationLog.objects.create(
            org=org,
            event_type="water_drop",
            title="Already read",
            body="Body",
            severity="info",
            channel="in_app",
            recipient=user,
            is_read=True,
        )

        svc = NotificationService(org)
        count = svc.get_unread_count(user)

    assert count == 3


# ---------------------------------------------------------------------------
# 13. NotificationLog RLS isolation (org_b cannot see org_a notifications)
# ---------------------------------------------------------------------------

def test_notification_log_rls_isolated():
    from apps.infrastructure.notifications.models import NotificationLog
    from apps.infrastructure.core.rls import set_tenant_context

    org_a = make_org(subdomain="rlsa")
    org_b = make_org(subdomain="rlsb")
    user_a = make_user(org_a, role="owner", email="owner@rlsa.com")
    user_b = make_user(org_b, role="owner", email="owner@rlsb.com")

    with set_tenant_context(org_a):
        NotificationLog.objects.create(
            org=org_a,
            event_type="theft_suspected",
            title="Theft at A",
            body="Body",
            severity="critical",
            channel="in_app",
            recipient=user_a,
        )

    with set_tenant_context(org_b):
        logs = NotificationLog.objects.filter(event_type="theft_suspected")
        titles = list(logs.values_list("title", flat=True))

    assert "Theft at A" not in titles


# ---------------------------------------------------------------------------
# 14. TermiiProvider — permanent failure on 400/422
# ---------------------------------------------------------------------------

def test_termii_provider_permanent_failure_on_400():
    from apps.infrastructure.notifications.providers.termii import TermiiProvider
    from apps.infrastructure.notifications.providers.base import NotificationPayload

    payload = NotificationPayload(
        recipient_id="user-1",
        recipient_phone="+2348099999999",
        recipient_email="",
        subject="",
        body="Test SMS",
        body_html="",
        channel="sms",
        idempotency_key="test:org:user:2026-01-01:sms",
        org_id="org-1",
    )

    mock_response = MagicMock()
    mock_response.status_code = 400
    mock_response.text = "Bad Request"

    with patch("apps.infrastructure.notifications.providers.termii.requests.post",
               return_value=mock_response):
        result = TermiiProvider().send(payload)

    assert result.success is False
    assert result.should_retry is False
    assert result.error_code == "400"


def test_termii_provider_permanent_failure_on_422():
    from apps.infrastructure.notifications.providers.termii import TermiiProvider
    from apps.infrastructure.notifications.providers.base import NotificationPayload

    payload = NotificationPayload(
        recipient_id="user-1",
        recipient_phone="+2348099999998",
        recipient_email="",
        subject="",
        body="Test SMS",
        body_html="",
        channel="sms",
        idempotency_key="test:org:user:2026-01-02:sms",
        org_id="org-1",
    )

    mock_response = MagicMock()
    mock_response.status_code = 422
    mock_response.text = "Unprocessable"

    with patch("apps.infrastructure.notifications.providers.termii.requests.post",
               return_value=mock_response):
        result = TermiiProvider().send(payload)

    assert result.success is False
    assert result.should_retry is False


def test_termii_provider_unexpected_response_retries():
    from apps.infrastructure.notifications.providers.termii import TermiiProvider
    from apps.infrastructure.notifications.providers.base import NotificationPayload

    payload = NotificationPayload(
        recipient_id="user-1",
        recipient_phone="+2348099999997",
        recipient_email="",
        subject="",
        body="Test SMS",
        body_html="",
        channel="sms",
        idempotency_key="test:org:user:2026-01-03:sms",
        org_id="org-1",
    )

    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.text = "Internal Server Error"
    mock_response.json.return_value = {}

    with patch("apps.infrastructure.notifications.providers.termii.requests.post",
               return_value=mock_response):
        result = TermiiProvider().send(payload)

    assert result.success is False
    assert result.should_retry is True


def test_termii_provider_request_exception_retries():
    import requests as req
    from apps.infrastructure.notifications.providers.termii import TermiiProvider
    from apps.infrastructure.notifications.providers.base import NotificationPayload

    payload = NotificationPayload(
        recipient_id="user-1",
        recipient_phone="+2348099999996",
        recipient_email="",
        subject="",
        body="Test SMS",
        body_html="",
        channel="sms",
        idempotency_key="test:org:user:2026-01-04:sms",
        org_id="org-1",
    )

    with patch("apps.infrastructure.notifications.providers.termii.requests.post",
               side_effect=req.RequestException("connection refused")):
        result = TermiiProvider().send(payload)

    assert result.success is False
    assert result.should_retry is True
    assert result.error_code == "request_error"


# ---------------------------------------------------------------------------
# 15. SMTPProvider — exception handling
# ---------------------------------------------------------------------------

def test_smtp_provider_exception_returns_retry():
    from apps.infrastructure.notifications.providers.smtp import SMTPProvider
    from apps.infrastructure.notifications.providers.base import NotificationPayload

    payload = NotificationPayload(
        recipient_id="user-1",
        recipient_phone="",
        recipient_email="fail@test.com",
        subject="Test",
        body="Body",
        body_html="<p>Body</p>",
        channel="email",
        idempotency_key="test:org:user:2026-01-01:email",
        org_id="org-1",
    )

    with patch("apps.infrastructure.notifications.providers.smtp.EmailMultiAlternatives",
               side_effect=Exception("SMTP connection failed")):
        result = SMTPProvider().send(payload)

    assert result.success is False
    assert result.should_retry is True
    assert "SMTP connection failed" in (result.error_detail or "")


# ---------------------------------------------------------------------------
# 16. _get_provider — unknown channel returns None
# ---------------------------------------------------------------------------

def test_get_provider_unknown_channel_returns_none():
    from apps.infrastructure.notifications.tasks import _get_provider
    result = _get_provider("push")
    assert result is None


def test_get_provider_sms_returns_termii():
    from apps.infrastructure.notifications.tasks import _get_provider
    provider = _get_provider("sms")
    assert provider is not None
    assert provider.provider_name == "termii"


def test_get_provider_email_returns_smtp():
    from apps.infrastructure.notifications.tasks import _get_provider
    provider = _get_provider("email")
    assert provider is not None
    assert provider.provider_name == "smtp"


def test_get_provider_in_app_returns_inapp():
    from apps.infrastructure.notifications.tasks import _get_provider
    provider = _get_provider("in_app")
    assert provider is not None
    assert provider.provider_name == "inapp"


# ---------------------------------------------------------------------------
# 17. _mark_failed — retry vs permanent failure
# ---------------------------------------------------------------------------

def test_mark_failed_with_retry_sets_pending():
    from apps.infrastructure.notifications.models import OutboxEvent
    from apps.infrastructure.notifications.tasks import _mark_failed

    org = make_org(subdomain=f"markfailed-{uuid.uuid4().hex[:6]}")
    user = make_user(org, role="owner")

    event = OutboxEvent.objects.create(
        org_id=org.id,
        event_type="batch_closed",
        recipient_user_id=user.id,
        recipient_email=user.email,
        subject="Test",
        body="Test",
        channel="in_app",
        idempotency_key=f"test:{org.id}:{user.id}:retry:{uuid.uuid4().hex}",
        status="processing",
        attempts=1,
    )

    _mark_failed(event, "timeout", "Request timed out", retry=True)
    event.refresh_from_db()

    assert event.status == "pending"
    assert "timeout" in event.error_detail


def test_mark_failed_without_retry_sets_failed():
    from apps.infrastructure.notifications.models import OutboxEvent
    from apps.infrastructure.notifications.tasks import _mark_failed
    import uuid as _uuid

    org = make_org(subdomain=f"permfail-{_uuid.uuid4().hex[:6]}")
    user = make_user(org, role="owner")

    event = OutboxEvent.objects.create(
        org_id=org.id,
        event_type="batch_closed",
        recipient_user_id=user.id,
        recipient_email=user.email,
        subject="Test",
        body="Test",
        channel="sms",
        idempotency_key=f"test:{org.id}:{user.id}:perm:{_uuid.uuid4().hex}",
        status="processing",
        attempts=3,
    )

    _mark_failed(event, "400", "Bad phone number", retry=False)
    event.refresh_from_db()

    assert event.status == "failed"


# ---------------------------------------------------------------------------
# 18. _deliver_event — no provider → marks failed permanently
# ---------------------------------------------------------------------------

def test_deliver_event_no_provider_marks_failed():
    from apps.infrastructure.notifications.models import OutboxEvent
    from apps.infrastructure.notifications.tasks import _deliver_event
    import uuid as _uuid

    org = make_org(subdomain=f"noprovider-{_uuid.uuid4().hex[:6]}")
    user = make_user(org, role="owner")

    event = OutboxEvent.objects.create(
        org_id=org.id,
        event_type="batch_closed",
        recipient_user_id=user.id,
        recipient_email=user.email,
        subject="Test",
        body="Test",
        channel="push",   # no provider supports "push"
        idempotency_key=f"test:{org.id}:{user.id}:push:{_uuid.uuid4().hex}",
        status="pending",
        attempts=0,
    )

    _deliver_event(event.id)
    event.refresh_from_db()

    assert event.status == "failed"
    assert "no_provider" in (event.error_detail or "")


# ---------------------------------------------------------------------------
# 19. _deliver_event — provider fails with no retry → status=failed
# ---------------------------------------------------------------------------

def test_deliver_event_failure_no_retry_marks_failed():
    from apps.infrastructure.notifications.models import OutboxEvent
    from apps.infrastructure.notifications.tasks import _deliver_event
    from apps.infrastructure.notifications.providers.base import DeliveryResult
    import uuid as _uuid

    org = make_org(subdomain=f"failnoretry-{_uuid.uuid4().hex[:6]}")
    user = make_user(org, role="owner")

    event = OutboxEvent.objects.create(
        org_id=org.id,
        event_type="batch_closed",
        recipient_user_id=user.id,
        recipient_phone="+2348099999990",
        recipient_email=user.email,
        subject="Test",
        body="Test",
        channel="sms",
        idempotency_key=f"test:{org.id}:{user.id}:fail:{_uuid.uuid4().hex}",
        status="pending",
        max_attempts=3,
        attempts=0,
    )

    failed_result = DeliveryResult(
        success=False,
        provider="termii",
        error_code="400",
        error_detail="Bad number",
        should_retry=False,
    )

    with patch("apps.infrastructure.notifications.tasks._get_provider") as mock_provider_fn:
        mock_provider = MagicMock()
        mock_provider.send.return_value = failed_result
        mock_provider_fn.return_value = mock_provider

        _deliver_event(event.id)

    event.refresh_from_db()
    assert event.status == "failed"


# ---------------------------------------------------------------------------
# 20. _deliver_event — already processed (DoesNotExist) returns early
# ---------------------------------------------------------------------------

def test_deliver_event_already_processed_is_noop():
    from apps.infrastructure.notifications.tasks import _deliver_event
    import uuid as _uuid

    non_existent_id = _uuid.uuid4()
    _deliver_event(non_existent_id)  # must not raise


# ---------------------------------------------------------------------------
# 21. _create_notification_log — missing org logs error gracefully
# ---------------------------------------------------------------------------

def test_create_notification_log_missing_org_does_not_raise():
    from apps.infrastructure.notifications.tasks import _create_notification_log
    from apps.infrastructure.notifications.models import OutboxEvent
    import uuid as _uuid

    org = make_org(subdomain=f"logcreate-{_uuid.uuid4().hex[:6]}")
    user = make_user(org, role="owner")

    event = OutboxEvent.objects.create(
        org_id=_uuid.uuid4(),  # Non-existent org_id
        event_type="batch_closed",
        recipient_user_id=user.id,
        recipient_email=user.email,
        subject="Test",
        body="Test",
        channel="in_app",
        idempotency_key=f"test:noorg:{_uuid.uuid4().hex}",
        status="delivered",
    )

    _create_notification_log(event)  # must not raise


# ---------------------------------------------------------------------------
# 22. process_outbox — no pending events returns early (no _deliver_event calls)
# ---------------------------------------------------------------------------

def test_process_outbox_empty_queue_does_not_call_deliver():
    from apps.infrastructure.notifications.models import OutboxEvent
    from apps.infrastructure.notifications.tasks import process_outbox

    OutboxEvent.objects.all().delete()

    with patch("apps.infrastructure.notifications.tasks._deliver_event") as mock_deliver:
        process_outbox()

    mock_deliver.assert_not_called()


# ---------------------------------------------------------------------------
# 23. NotificationService — no rule returns 0
# ---------------------------------------------------------------------------

def test_notification_service_no_rule_returns_zero():
    from apps.infrastructure.notifications.models import AlertRule
    from apps.infrastructure.notifications.services import NotificationService
    from apps.infrastructure.core.rls import set_tenant_context
    import uuid as _uuid

    org = make_org(subdomain=f"norule-{_uuid.uuid4().hex[:6]}")

    with set_tenant_context(org):
        AlertRule.objects.filter(org=org, event_type="mortality_spike").delete()
        svc = NotificationService(org)
        result = svc.send("mortality_spike", {"farm_name": "F", "count": "5", "normal": "1"})

    assert result == 0


# ---------------------------------------------------------------------------
# 24. NotificationService._render_message — fallback for missing key
# ---------------------------------------------------------------------------

def test_render_message_unknown_event_type_fallback():
    from apps.infrastructure.notifications.services import NotificationService
    import uuid as _uuid

    org = make_org(subdomain=f"renderfb-{_uuid.uuid4().hex[:6]}")
    svc = NotificationService(org)

    # Unknown event type — should fall back gracefully
    subject, body, html = svc._render_message("unknown_event_xyz", "sms", {})
    assert isinstance(subject, str)
    assert isinstance(body, str)


def test_render_message_sms_channel():
    from apps.infrastructure.notifications.services import NotificationService
    import uuid as _uuid

    org = make_org(subdomain=f"rendersms-{_uuid.uuid4().hex[:6]}")
    svc = NotificationService(org)

    subject, body, html = svc._render_message(
        "mortality_spike", "sms",
        {"farm_name": "Farm A", "count": "5", "normal": "2"}
    )
    assert subject == ""
    assert "Farm A" in body
    assert html == ""


def test_render_message_email_channel():
    from apps.infrastructure.notifications.services import NotificationService
    import uuid as _uuid

    org = make_org(subdomain=f"renderemail-{_uuid.uuid4().hex[:6]}")
    svc = NotificationService(org)

    subject, body, html = svc._render_message(
        "vaccination_due", "email",
        {"farm_name": "Farm B", "batch_name": "B1", "date": "2026-06-10"}
    )
    assert "Vaccination" in subject
    assert "Farm B" in body
    assert "<p>" in html


def test_render_message_in_app_channel():
    from apps.infrastructure.notifications.services import NotificationService
    import uuid as _uuid

    org = make_org(subdomain=f"renderinapp-{_uuid.uuid4().hex[:6]}")
    svc = NotificationService(org)

    subject, body, html = svc._render_message(
        "heat_stress", "in_app",
        {"farm_name": "Farm C", "value": "38"}
    )
    assert "Heat Stress" in subject or subject != ""
    assert "Farm C" in body


# ---------------------------------------------------------------------------
# 25. get_notifications service method
# ---------------------------------------------------------------------------

def test_get_notifications_returns_queryset():
    from apps.infrastructure.notifications.models import NotificationLog
    from apps.infrastructure.notifications.services import NotificationService
    from apps.infrastructure.core.rls import set_tenant_context
    import uuid as _uuid

    org = make_org(subdomain=f"getnotif-{_uuid.uuid4().hex[:6]}")
    user = make_user(org, role="owner")

    with set_tenant_context(org):
        for i in range(3):
            NotificationLog.objects.create(
                org=org,
                event_type="batch_closed",
                title=f"Notif {i}",
                body="Body",
                severity="info",
                channel="in_app",
                recipient=user,
            )

        svc = NotificationService(org)
        notifs = svc.get_notifications(user, limit=10)

    assert len(notifs) == 3


# ---------------------------------------------------------------------------
# 26. NotificationService.notify() — gated direct in-app notifications
#
# notify() is the sanctioned replacement for direct NotificationLog.objects
# .create() at targeted call sites. It must apply the same _should_receive gate
# (RBAC floor + preference mute + always-deliver floor) that send() applies.
# ---------------------------------------------------------------------------

import uuid as _uuid

from apps.infrastructure.core.rls import set_tenant_context as _stc


def _org():
    return make_org(subdomain=f"notify-{_uuid.uuid4().hex[:6]}")


def _logs(org, recipient):
    from apps.infrastructure.notifications.models import NotificationLog
    return NotificationLog.objects.filter(org=org, recipient=recipient)


def test_notify_creates_log_for_allowed_recipient():
    from apps.infrastructure.notifications.services import NotificationService
    org = _org()
    owner = make_user(org, role="owner")
    with _stc(org):
        log = NotificationService(org).notify(
            recipient=owner,
            event_type="billing_plan_activated",
            title="Plan upgraded",
            body="Your plan is active.",
            severity="info",
            action_url="/billing/",
        )
        assert log is not None
        assert log.recipient_id == owner.id
        assert log.channel == "in_app"
        assert log.action_url == "/billing/"
        assert _logs(org, owner).count() == 1


def test_notify_returns_none_and_creates_nothing_when_muted():
    """A muteable financial event must NOT be written for an owner who muted
    the financial-reports category."""
    from apps.infrastructure.notifications.services import NotificationService
    org = _org()
    owner = make_user(org, role="owner")
    owner.notify_financial_reports = False
    owner.save(update_fields=["notify_financial_reports"])
    with _stc(org):
        log = NotificationService(org).notify(
            recipient=owner,
            event_type="billing_plan_activated",
            title="Plan upgraded",
            body="Body",
        )
        assert log is None
        assert _logs(org, owner).count() == 0


def test_notify_respects_rbac_floor_for_financial_event():
    """A financial event routed at a restricted recipient creates nothing."""
    from apps.infrastructure.notifications.services import NotificationService
    org = _org()
    de = make_user(org, role="data_entry", email="de@x.com")
    with _stc(org):
        log = NotificationService(org).notify(
            recipient=de,
            event_type="payment_failed",
            title="Payment failed",
            body="Body",
        )
        assert log is None
        assert _logs(org, de).count() == 0


def test_notify_always_delivers_payment_failed_to_muted_owner():
    """Account-critical events bypass the preference mute (but not RBAC)."""
    from apps.infrastructure.notifications.services import NotificationService
    org = _org()
    owner = make_user(org, role="owner")
    owner.notify_financial_reports = False
    owner.save(update_fields=["notify_financial_reports"])
    with _stc(org):
        for event_type in ("payment_failed", "billing_expiry_reminder", "trial_expiry_reminder"):
            log = NotificationService(org).notify(
                recipient=owner,
                event_type=event_type,
                title="Account notice",
                body="Body",
            )
            assert log is not None, f"{event_type} must always deliver to owner"
        assert _logs(org, owner).count() == 3


def test_notify_delivers_ai_anomaly_despite_all_mutes():
    """ai_anomaly is uncategorised — reaches owner/manager regardless of prefs."""
    from apps.infrastructure.notifications.services import NotificationService
    org = _org()
    owner = make_user(org, role="owner")
    owner.notify_health_alerts = False
    owner.notify_production_insights = False
    owner.save(update_fields=["notify_health_alerts", "notify_production_insights"])
    with _stc(org):
        log = NotificationService(org).notify(
            recipient=owner,
            event_type="ai_anomaly",
            title="Mortality anomaly",
            body="Body",
            batch_reference="batch-1",
        )
        assert log is not None
        assert log.batch_reference == "batch-1"


def test_notify_support_reply_reaches_data_entry_submitter():
    """support_reply is not financial and not categorised — a data_entry user
    who filed a ticket must still receive the reply."""
    from apps.infrastructure.notifications.services import NotificationService
    org = _org()
    de = make_user(org, role="data_entry", email="de2@x.com")
    with _stc(org):
        log = NotificationService(org).notify(
            recipient=de,
            event_type="support_reply",
            title="Ticket update",
            body="Admin replied",
        )
        assert log is not None
        assert _logs(org, de).count() == 1
