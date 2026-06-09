"""
Tests for the in-app support ticket modal — authenticated users only.
"""
import pytest
from unittest.mock import patch

pytestmark = pytest.mark.django_db


def make_org():
    from apps.infrastructure.tenants.models import Organization
    import uuid
    return Organization.objects.create(
        name="Support Test Farm",
        subdomain=f"supportfarm-{uuid.uuid4().hex[:8]}",
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
    return CustomUser.objects.create_user(
        username="sadmin",
        email="sadmin@flockiq.com",
        password="pass1234",
        org=None,
        role="super_admin",
        is_staff=True,
        is_superuser=True,
    )


# ─── Unauthenticated ──────────────────────────────────────────────────────────

def test_unauthenticated_post_redirects(client):
    """Unauthenticated POST → 302 redirect to login."""
    resp = client.post("/support/ticket/submit/", {
        "subject": "Help",
        "message": "Stuck on batch setup",
        "priority": "medium",
    })
    assert resp.status_code == 302
    assert "/login/" in resp["Location"]


def test_unauthenticated_form_get_redirects(client):
    """Unauthenticated GET of form → 302 redirect to login."""
    resp = client.get("/support/ticket/form/")
    assert resp.status_code == 302


# ─── Validation ───────────────────────────────────────────────────────────────

def test_missing_subject_returns_422(client):
    org = make_org()
    user = make_user(org)
    client.force_login(user)

    resp = client.post("/support/ticket/submit/", {
        "subject": "",
        "message": "Something went wrong",
        "priority": "high",
    })
    assert resp.status_code == 422

    from apps.infrastructure.notifications.models import SupportTicket
    assert SupportTicket.objects.count() == 0


def test_missing_message_returns_422(client):
    org = make_org()
    user = make_user(org)
    client.force_login(user)

    resp = client.post("/support/ticket/submit/", {
        "subject": "Cannot log yields",
        "message": "",
        "priority": "low",
    })
    assert resp.status_code == 422

    from apps.infrastructure.notifications.models import SupportTicket
    assert SupportTicket.objects.count() == 0


# ─── Happy path ───────────────────────────────────────────────────────────────

def test_valid_post_creates_ticket(client):
    org = make_org()
    user = make_user(org)
    su = make_superuser()
    client.force_login(user)

    with patch("apps.infrastructure.core.email_service.EmailService.send_support_ticket"):
        resp = client.post("/support/ticket/submit/", {
            "subject": "Batch weight missing",
            "message": "The weight field does not save.",
            "priority": "high",
        })

    assert resp.status_code == 200

    from apps.infrastructure.notifications.models import SupportTicket
    ticket = SupportTicket.objects.get(subject="Batch weight missing")
    assert ticket.org == org
    assert ticket.submitted_by == user
    assert ticket.priority == "high"
    assert ticket.status == "open"
    assert ticket.is_read_by_admin is False


def test_valid_post_sends_email(client):
    org = make_org()
    user = make_user(org)
    make_superuser()
    client.force_login(user)

    with patch(
        "apps.infrastructure.core.email_service.EmailService.send_support_ticket"
    ) as mock_send_email:
        client.post("/support/ticket/submit/", {
            "subject": "Feed calculation wrong",
            "message": "Numbers are off.",
            "priority": "medium",
        })

    mock_send_email.assert_called_once()
    _, kwargs = mock_send_email.call_args
    assert kwargs.get("subject") == "Feed calculation wrong"
    assert kwargs.get("priority") == "medium"


def test_valid_post_notifies_superusers(client):
    org = make_org()
    user = make_user(org)
    su = make_superuser()
    client.force_login(user)

    with patch("apps.infrastructure.core.email_service.EmailService.send_support_ticket"):
        client.post("/support/ticket/submit/", {
            "subject": "Cannot view reports",
            "message": "Page errors out.",
            "priority": "low",
        })

    from apps.infrastructure.notifications.models import AdminNotification
    notifs = AdminNotification.objects.filter(recipient=su)
    assert notifs.count() == 1
    assert "Cannot view reports" in notifs.first().title


def test_org_auto_captured_from_request_not_form(client):
    """Tenant must come from request.user.org, never from POST data."""
    org = make_org()
    user = make_user(org)

    other_org = make_org()
    client.force_login(user)

    with patch("apps.infrastructure.core.email_service.EmailService.send_support_ticket"):
        client.post("/support/ticket/submit/", {
            "subject": "Tenant spoof test",
            "message": "Attempting to spoof org",
            "priority": "low",
            "org": str(other_org.pk),
        })

    from apps.infrastructure.notifications.models import SupportTicket
    ticket = SupportTicket.objects.get(subject="Tenant spoof test")
    assert ticket.org == org
    assert ticket.org != other_org


# ─── Superadmin list ──────────────────────────────────────────────────────────

def test_superadmin_support_tickets_list_200(client):
    su = make_superuser()
    client.force_login(su)

    resp = client.get("/superadmin/support-tickets/")
    assert resp.status_code == 200


def test_non_superadmin_support_tickets_list_redirects(client):
    org = make_org()
    user = make_user(org)
    client.force_login(user)

    resp = client.get("/superadmin/support-tickets/")
    assert resp.status_code == 302


def test_superadmin_mark_read_toggles(client):
    org = make_org()
    user = make_user(org)
    su = make_superuser()

    from apps.infrastructure.notifications.models import SupportTicket
    ticket = SupportTicket.objects.create(
        org=org,
        submitted_by=user,
        subject="Toggle test",
        message="Testing read toggle.",
        priority="low",
    )
    assert ticket.is_read_by_admin is False

    client.force_login(su)
    resp = client.post(f"/superadmin/support-tickets/{ticket.pk}/mark-read/")
    assert resp.status_code == 200

    ticket.refresh_from_db()
    assert ticket.is_read_by_admin is True

    resp = client.post(f"/superadmin/support-tickets/{ticket.pk}/mark-read/")
    ticket.refresh_from_db()
    assert ticket.is_read_by_admin is False
