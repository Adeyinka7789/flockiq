"""
Unit tests for SupportTicketService.add_reply — the single authoritative path
for support ticket replies shared by the tenant-side and superadmin-side views.

Covers reply creation, notification fan-out (superadmins vs tenant submitter),
channel selection (bell/email/AdminNotification), status transitions, atomicity,
and notification-body truncation.
"""
import uuid
from unittest.mock import patch

import pytest
from django.core import mail
from django.test import override_settings

pytestmark = pytest.mark.django_db


# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_org():
    from apps.infrastructure.tenants.models import Organization
    return Organization.objects.create(
        name="Service Test Farm",
        subdomain=f"svcfarm-{uuid.uuid4().hex[:8]}",
        plan_tier="monthly",
        subscription_status="active",
        onboarding_complete=True,
        is_active=True,
    )


def make_user(org, role="owner"):
    from apps.infrastructure.accounts.models import CustomUser
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


def make_ticket(org, user, subject="Test Ticket", message="Needs help.",
                status="open"):
    from apps.infrastructure.notifications.models import SupportTicket
    return SupportTicket.objects.create(
        org=org,
        submitted_by=user,
        subject=subject,
        message=message,
        priority="medium",
        status=status,
    )


def add_reply(**kwargs):
    from apps.infrastructure.notifications.ticket_service import (
        SupportTicketService,
    )
    return SupportTicketService.add_reply(**kwargs)


# ─── Tenant-side replies ──────────────────────────────────────────────────────

def test_tenant_reply_creates_reply():
    from apps.infrastructure.notifications.models import SupportTicketReply

    org = make_org()
    user = make_user(org)
    ticket = make_ticket(org, user)

    reply = add_reply(ticket=ticket, author=user, message="Still broken.")

    assert reply.pk is not None
    assert reply.ticket_id == ticket.pk
    assert reply.author_id == user.pk
    assert reply.message == "Still broken."
    assert SupportTicketReply.objects.filter(ticket=ticket).count() == 1


def test_tenant_reply_notifies_all_superadmins():
    from apps.infrastructure.notifications.models import AdminNotification

    org = make_org()
    user = make_user(org)
    su1 = make_superuser()
    su2 = make_superuser()
    ticket = make_ticket(org, user, subject="Feeder jam")

    add_reply(ticket=ticket, author=user, message="Any update?")

    for su in (su1, su2):
        notifs = AdminNotification.objects.filter(recipient=su)
        assert notifs.count() == 1
        notif = notifs.first()
        assert "Feeder jam" in notif.title
        assert org.name in notif.title
        assert user.email in notif.body


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_tenant_reply_does_not_email_tenant():
    org = make_org()
    user = make_user(org)
    make_superuser()
    ticket = make_ticket(org, user)

    add_reply(ticket=ticket, author=user, message="Hello?")

    assert len(mail.outbox) == 0


def test_tenant_reply_does_not_change_status():
    from apps.infrastructure.notifications.models import SupportTicket

    org = make_org()
    user = make_user(org)
    make_superuser()
    ticket = make_ticket(org, user, status="open")

    # Tenant cannot drive a status transition even if new_status is passed.
    add_reply(ticket=ticket, author=user, message="Hi", new_status="resolved")

    ticket.refresh_from_db()
    assert ticket.status == "open"
    assert SupportTicket.objects.get(pk=ticket.pk).status == "open"


# ─── Superadmin-side replies ──────────────────────────────────────────────────

def test_superadmin_reply_creates_reply():
    from apps.infrastructure.notifications.models import SupportTicketReply

    org = make_org()
    user = make_user(org)
    su = make_superuser()
    ticket = make_ticket(org, user)

    reply = add_reply(ticket=ticket, author=su, message="Looking into it.")

    assert reply.pk is not None
    assert reply.author_id == su.pk
    assert SupportTicketReply.objects.filter(ticket=ticket).count() == 1


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_superadmin_reply_emails_submitter():
    org = make_org()
    user = make_user(org)
    su = make_superuser()
    ticket = make_ticket(org, user, subject="Mobile login bug")

    add_reply(ticket=ticket, author=su, message="Fixed in 2.1.")

    assert len(mail.outbox) == 1
    sent = mail.outbox[0]
    assert user.email in sent.to
    assert "Mobile login bug" in sent.subject


def test_superadmin_reply_creates_bell_notification_for_submitter():
    from apps.infrastructure.core.rls import set_tenant_context
    from apps.infrastructure.notifications.models import NotificationLog

    org = make_org()
    user = make_user(org)
    su = make_superuser()
    ticket = make_ticket(org, user, subject="Sensor firmware")

    add_reply(ticket=ticket, author=su, message="Patched the firmware.")

    with set_tenant_context(org):
        notifs = NotificationLog.objects.filter(
            recipient=user, event_type="support_reply",
        )
        assert notifs.count() == 1
        notif = notifs.first()
        assert "Sensor firmware" in notif.title
        assert "Patched the firmware." in notif.body


def test_superadmin_reply_changes_status_when_provided():
    org = make_org()
    user = make_user(org)
    su = make_superuser()
    ticket = make_ticket(org, user, status="open")

    add_reply(ticket=ticket, author=su, message="Done.", new_status="resolved")

    ticket.refresh_from_db()
    assert ticket.status == "resolved"


def test_superadmin_reply_keeps_status_when_new_status_none():
    org = make_org()
    user = make_user(org)
    su = make_superuser()
    ticket = make_ticket(org, user, status="in_progress")

    add_reply(ticket=ticket, author=su, message="Working on it.")

    ticket.refresh_from_db()
    assert ticket.status == "in_progress"


def test_superadmin_reply_ignores_invalid_status():
    org = make_org()
    user = make_user(org)
    su = make_superuser()
    ticket = make_ticket(org, user, status="open")

    add_reply(ticket=ticket, author=su, message="Hmm", new_status="bogus")

    ticket.refresh_from_db()
    assert ticket.status == "open"


# ─── Atomicity / resilience ───────────────────────────────────────────────────

@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_email_failure_does_not_roll_back_reply():
    from apps.infrastructure.core.rls import set_tenant_context
    from apps.infrastructure.notifications.models import (
        NotificationLog, SupportTicketReply,
    )

    org = make_org()
    user = make_user(org)
    su = make_superuser()
    ticket = make_ticket(org, user, status="open")

    with patch(
        "apps.infrastructure.core.email_service.EmailService.send_support_reply",
        side_effect=Exception("SMTP down"),
    ):
        # Must not raise — the email failure is caught and logged.
        reply = add_reply(
            ticket=ticket, author=su, message="Resolved.", new_status="resolved",
        )

    assert SupportTicketReply.objects.filter(pk=reply.pk).exists()
    ticket.refresh_from_db()
    assert ticket.status == "resolved"
    # Bell notification still written despite the email failure.
    with set_tenant_context(org):
        assert NotificationLog.objects.filter(
            recipient=user, event_type="support_reply",
        ).count() == 1


# ─── Truncation ───────────────────────────────────────────────────────────────

def test_notification_body_truncated_to_200_chars():
    from apps.infrastructure.notifications.models import AdminNotification

    org = make_org()
    user = make_user(org)
    su = make_superuser()
    ticket = make_ticket(org, user)

    long_message = "x" * 500
    reply = add_reply(ticket=ticket, author=user, message=long_message)

    # The stored reply keeps the full message...
    reply.refresh_from_db()
    assert reply.message == long_message

    # ...but the AdminNotification body truncates the message to 200 chars.
    notif = AdminNotification.objects.filter(recipient=su).first()
    assert ("x" * 200) in notif.body
    assert ("x" * 201) not in notif.body
