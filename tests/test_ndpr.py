"""NDPR compliance — data export + account deletion (Phase 2)."""
import json
from unittest.mock import patch

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


@pytest.fixture
def non_owner_user(db, test_org):
    """A data-entry team member belonging to the same org as ``tenant_user``."""
    from apps.infrastructure.accounts.models import CustomUser

    return CustomUser.objects.create_user(
        username=f"staff-{test_org.subdomain}",
        email=f"staff@{test_org.subdomain}.com",
        password="testpass123",
        org=test_org,
        role="data_entry",
        first_name="Staff",
        last_name="Member",
        email_verified=True,
    )


# ── Data export ──────────────────────────────────────────────────────────────

class TestDataExport:

    def test_export_requires_login(self, client):
        response = client.get(reverse("accounts:export_data"))
        assert response.status_code in (301, 302)

    def test_export_returns_json_file(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get(reverse("accounts:export_data"))
        assert response.status_code == 200
        assert response["Content-Type"] == "application/json"
        assert "attachment" in response["Content-Disposition"]
        assert ".json" in response["Content-Disposition"]

    def test_export_includes_user_data(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get(reverse("accounts:export_data"))
        data = json.loads(response.content)
        assert data["user"]["email"] == tenant_user.email

    def test_export_includes_org_data_for_owner(self, client, tenant_user, test_farm):
        client.force_login(tenant_user)
        response = client.get(reverse("accounts:export_data"))
        data = json.loads(response.content)
        assert "organisation" in data
        assert "farms" in data
        assert len(data["farms"]) == 1

    def test_export_excludes_org_data_for_non_owner(self, client, non_owner_user):
        client.force_login(non_owner_user)
        response = client.get(reverse("accounts:export_data"))
        data = json.loads(response.content)
        assert "user" in data
        assert "organisation" not in data
        assert "farms" not in data

    def test_export_rate_limited_to_once_per_24h(self, client, tenant_user):
        client.force_login(tenant_user)
        first = client.get(reverse("accounts:export_data"))
        assert first.status_code == 200
        second = client.get(reverse("accounts:export_data"))
        assert second.status_code == 429


# ── Account deletion ─────────────────────────────────────────────────────────

class TestDeleteAccount:

    def test_delete_requires_login(self, client):
        response = client.get(reverse("accounts:delete_account"))
        assert response.status_code in (301, 302)

    def test_get_shows_confirmation_page(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get(reverse("accounts:delete_account"))
        assert response.status_code == 200
        assert b"DELETE" in response.content

    def test_delete_requires_correct_password(self, client, tenant_user):
        from apps.infrastructure.accounts.models import CustomUser

        client.force_login(tenant_user)
        response = client.post(reverse("accounts:delete_account"), {
            "password": "wrongpassword",
            "confirmation": "DELETE",
        })
        assert response.status_code == 200
        assert b"Incorrect password" in response.content
        assert CustomUser.objects.filter(pk=tenant_user.pk).exists()

    def test_delete_requires_typing_delete(self, client, tenant_user):
        from apps.infrastructure.accounts.models import CustomUser

        client.force_login(tenant_user)
        response = client.post(reverse("accounts:delete_account"), {
            "password": "testpass123",
            "confirmation": "nope",
        })
        assert response.status_code == 200
        assert CustomUser.objects.filter(pk=tenant_user.pk).exists()

    @patch("apps.infrastructure.core.email_service.EmailService.send_account_deleted")
    def test_owner_deletion_cascades_to_org(self, _mail, client, tenant_user, test_batch):
        from apps.infrastructure.accounts.models import CustomUser
        from apps.farm.farms.models import Farm
        from apps.infrastructure.tenants.models import Organization

        org_id = tenant_user.org_id
        client.force_login(tenant_user)
        response = client.post(reverse("accounts:delete_account"), {
            "password": "testpass123",
            "confirmation": "DELETE",
        })
        assert response.status_code == 302
        assert response["Location"] == "/?deleted=1"
        assert not Organization.objects.filter(pk=org_id).exists()
        assert not CustomUser.objects.filter(pk=tenant_user.pk).exists()
        assert not Farm.objects.unscoped().filter(org_id=org_id).exists()

    @patch("apps.infrastructure.core.email_service.EmailService.send_account_deleted")
    def test_non_owner_deletion_removes_only_user(self, _mail, client, non_owner_user):
        from apps.infrastructure.accounts.models import CustomUser
        from apps.infrastructure.tenants.models import Organization

        org_id = non_owner_user.org_id
        client.force_login(non_owner_user)
        response = client.post(reverse("accounts:delete_account"), {
            "password": "testpass123",
            "confirmation": "DELETE",
        })
        assert response.status_code == 302
        assert not CustomUser.objects.filter(pk=non_owner_user.pk).exists()
        assert Organization.objects.filter(pk=org_id).exists()

    @patch("apps.infrastructure.core.email_service.EmailService.send_account_deleted")
    def test_superadmin_notified_on_org_deletion(self, _mail, client, tenant_user, super_admin_user):
        from apps.infrastructure.notifications.models import AdminNotification

        client.force_login(tenant_user)
        client.post(reverse("accounts:delete_account"), {
            "password": "testpass123",
            "confirmation": "DELETE",
        })
        assert AdminNotification.objects.filter(recipient=super_admin_user).exists()

    def test_farewell_email_sent_on_deletion(self, client, tenant_user):
        client.force_login(tenant_user)
        with patch(
            "apps.infrastructure.core.email_service.EmailService.send_account_deleted"
        ) as mock_email:
            client.post(reverse("accounts:delete_account"), {
                "password": "testpass123",
                "confirmation": "DELETE",
            })
        assert mock_email.called
