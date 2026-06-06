"""
Tests for the public contact form — Task 2B.
"""
import pytest
from unittest.mock import patch

pytestmark = pytest.mark.django_db


def make_superuser(email="admin@flockiq.com"):
    from apps.infrastructure.accounts.models import CustomUser
    return CustomUser.objects.create_user(
        username=email,
        email=email,
        password="pass1234",
        org=None,
        role="super_admin",
        is_staff=True,
        is_superuser=True,
    )


def test_contact_success_creates_message_and_notification(client):
    """
    POST to /contact/ with valid data:
    - creates a ContactMessage record
    - sends an email to ADMIN_EMAIL
    - creates an AdminNotification for every superuser
    """
    su = make_superuser()

    from apps.infrastructure.notifications.models import AdminNotification, ContactMessage

    with patch("config.views.send_mail") as mock_mail:
        resp = client.post("/contact/", {
            "name": "Adebayo",
            "email": "adebayo@farm.com",
            "subject": "Need help with batch setup",
            "message": "How do I register my first batch?",
        })

    assert resp.status_code == 200

    msg = ContactMessage.objects.get(subject="Need help with batch setup")
    assert msg.email == "adebayo@farm.com"
    assert msg.is_read is False

    mock_mail.assert_called_once()
    call_kwargs = mock_mail.call_args
    assert "Need help with batch setup" in call_kwargs[1]["subject"] or "Need help with batch setup" in call_kwargs[0][0]

    notifs = AdminNotification.objects.filter(recipient=su)
    assert notifs.count() == 1
    assert "Need help with batch setup" in notifs.first().title


def test_contact_missing_fields_returns_400(client):
    """
    POST to /contact/ without required subject/message returns 400.
    """
    from apps.infrastructure.notifications.models import ContactMessage

    resp = client.post("/contact/", {
        "name": "Test",
        "email": "test@example.com",
        "subject": "",
        "message": "",
    })

    assert resp.status_code == 400
    assert ContactMessage.objects.count() == 0
