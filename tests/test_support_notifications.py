"""
Fix 4 — Notification tests for support ticket submit and admin reply flows.

Covers:
  1. Superuser gets AdminNotification on ticket submission
  2. Tenant user gets NotificationLog when superadmin replies
  3. Email sent to ADMIN_EMAIL on ticket submission (locmem backend)
  4. Email sent to tenant user when superadmin replies (locmem backend)
"""
import pytest
from django.core import mail
from django.test import override_settings

pytestmark = pytest.mark.django_db


# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_org():
    from apps.infrastructure.tenants.models import Organization
    import uuid
    return Organization.objects.create(
        name="Notify Test Farm",
        subdomain=f"notifyfarm-{uuid.uuid4().hex[:8]}",
        plan_tier="monthly",
        subscription_status="active",
        onboarding_complete=True,
        is_active=True,
    )


def make_user(org, role="owner"):
    from apps.infrastructure.accounts.models import CustomUser
    import uuid
    slug = uuid.uuid4().hex[:8]
    return CustomUser.objects.create_user(
        username=f"{role}-{slug}",
        email=f"{role}-{slug}@farm.com",
        password="pass1234",
        org=org,
        role=role,
        first_name="Test",
        last_name="User",
    )


def make_superuser():
    from apps.infrastructure.accounts.models import CustomUser
    import uuid
    slug = uuid.uuid4().hex[:6]
    return CustomUser.objects.create_user(
        username=f"sadmin-{slug}",
        email=f"sadmin-{slug}@flockiq.com",
        password="pass1234",
        org=None,
        role="super_admin",
        is_staff=True,
        is_superuser=True,
    )


def make_ticket(org, user, subject="Test Ticket", message="Needs help."):
    from apps.infrastructure.notifications.models import SupportTicket
    return SupportTicket.objects.create(
        org=org,
        submitted_by=user,
        subject=subject,
        message=message,
        priority="medium",
    )


# ─── Test 1: Superuser gets AdminNotification on ticket submission ─────────────

def test_superuser_gets_admin_notification_on_ticket_submit(client):
    """Submitting a ticket creates an AdminNotification for every superuser."""
    from unittest.mock import patch

    org = make_org()
    user = make_user(org)
    su = make_superuser()
    client.force_login(user)

    with patch("apps.infrastructure.notifications.views.send_mail"):
        resp = client.post("/support/ticket/submit/", {
            "subject": "Feeder broken",
            "message": "The automatic feeder stopped working.",
            "priority": "high",
        })

    assert resp.status_code == 200

    from apps.infrastructure.notifications.models import AdminNotification
    notifs = AdminNotification.objects.filter(recipient=su)
    assert notifs.count() == 1
    notif = notifs.first()
    assert "Feeder broken" in notif.title
    assert org.name in notif.title


# ─── Test 2: Tenant user gets NotificationLog when superadmin replies ──────────

@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_tenant_user_gets_notification_log_on_admin_reply(client):
    """When a superadmin replies to a ticket, the submitting user gains a
    NotificationLog record with event_type='support_reply'."""
    org = make_org()
    user = make_user(org)
    su = make_superuser()
    ticket = make_ticket(org, user, subject="Water level sensor")
    client.force_login(su)

    resp = client.post(f"/superadmin/support-tickets/{ticket.pk}/reply/", {
        "message": "We have fixed the sensor firmware.",
        "status": "resolved",
    })

    assert resp.status_code == 200

    from apps.infrastructure.notifications.models import NotificationLog
    from apps.infrastructure.core.rls import set_tenant_context

    with set_tenant_context(org):
        notifs = NotificationLog.objects.filter(
            recipient=user,
            event_type="support_reply",
        )
        assert notifs.count() == 1
        notif = notifs.first()
        assert "Water level sensor" in notif.title
        assert "We have fixed the sensor firmware." in notif.body


# ─── Test 3: Email sent to ADMIN_EMAIL on ticket submission ───────────────────

@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    ADMIN_EMAIL="admin@flockiq.com",
)
def test_email_sent_to_admin_on_ticket_submit(client):
    """Submitting a ticket delivers a real email to ADMIN_EMAIL (locmem backend)."""
    org = make_org()
    user = make_user(org)
    make_superuser()
    client.force_login(user)

    resp = client.post("/support/ticket/submit/", {
        "subject": "Cannot export PDF",
        "message": "PDF export button does nothing.",
        "priority": "low",
    })

    assert resp.status_code == 200
    assert len(mail.outbox) == 1
    sent = mail.outbox[0]
    assert "admin@flockiq.com" in sent.to
    assert "Cannot export PDF" in sent.subject


# ─── Test 4: Email sent to tenant user when superadmin replies ────────────────

@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
def test_email_sent_to_tenant_user_on_admin_reply(client):
    """When a superadmin replies, the ticket submitter receives an email."""
    org = make_org()
    user = make_user(org)
    su = make_superuser()
    ticket = make_ticket(org, user, subject="Login error on mobile")
    client.force_login(su)

    resp = client.post(f"/superadmin/support-tickets/{ticket.pk}/reply/", {
        "message": "This has been fixed in version 2.1.",
        "status": "resolved",
    })

    assert resp.status_code == 200
    assert len(mail.outbox) == 1
    sent = mail.outbox[0]
    assert user.email in sent.to
    assert "Login error on mobile" in sent.subject
