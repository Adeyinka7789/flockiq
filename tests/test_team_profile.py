import uuid

import pytest

pytestmark = pytest.mark.django_db


class TestProfilePage:
    def test_profile_returns_200(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get("/profile/")
        assert response.status_code == 200

    def test_profile_shows_real_member_since(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get("/profile/")
        assert response.status_code == 200
        assert b"January 2023" not in response.content

    def test_profile_shows_user_email(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get("/profile/")
        assert tenant_user.email.encode() in response.content

    def test_profile_shows_org_name(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get("/profile/")
        assert tenant_user.org.name.encode() in response.content

    def test_profile_no_fake_devices(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get("/profile/")
        assert b"MacBook Pro" not in response.content
        assert b"iPhone 15" not in response.content
        assert b"Samsung Galaxy Tab" not in response.content

    def test_profile_no_fake_bio(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get("/profile/")
        assert b"Precision livestock specialist" not in response.content

    def test_profile_shows_bio_when_set(self, client, tenant_user):
        tenant_user.bio = "Farm manager based in Lagos."
        tenant_user.save()
        client.force_login(tenant_user)
        response = client.get("/profile/")
        assert b"Farm manager based in Lagos." in response.content

    def test_profile_shows_default_bio_when_empty(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get("/profile/")
        assert b"No bio added yet." in response.content

    def test_edit_profile_updates_bio(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.post(
            "/profile/edit/",
            {
                "first_name": "Michael",
                "last_name": "Adeniran",
                "phone": "+2348012345678",
                "bio": "Poultry farm manager based in Lagos.",
            },
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        tenant_user.refresh_from_db()
        assert tenant_user.bio == "Poultry farm manager based in Lagos."

    def test_edit_profile_updates_name_and_phone(self, client, tenant_user):
        client.force_login(tenant_user)
        client.post(
            "/profile/edit/",
            {"first_name": "Ada", "last_name": "Okafor", "phone": "+2348099999999", "bio": ""},
            HTTP_HX_REQUEST="true",
        )
        tenant_user.refresh_from_db()
        assert tenant_user.first_name == "Ada"
        assert tenant_user.phone == "+2348099999999"

    def test_profile_requires_login(self, client):
        response = client.get("/profile/")
        assert response.status_code == 302

    def test_change_password_correct(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.post(
            "/profile/change-password/",
            {
                "old_password": "testpass123",
                "new_password": "NewSecure456!",
                "confirm_password": "NewSecure456!",
            },
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        tenant_user.refresh_from_db()
        assert tenant_user.check_password("NewSecure456!")

    def test_change_password_wrong_old(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.post(
            "/profile/change-password/",
            {
                "old_password": "wrongpass",
                "new_password": "NewSecure456!",
                "confirm_password": "NewSecure456!",
            },
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        assert b"incorrect" in response.content.lower()


class TestTeamPage:
    def test_team_returns_200(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get("/team/")
        assert response.status_code == 200

    def test_team_requires_login(self, client):
        response = client.get("/team/")
        assert response.status_code == 302

    def test_team_shows_active_count(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get("/team/")
        assert response.status_code == 200
        assert b"Active members" in response.content

    def test_team_shows_member_email(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get("/team/")
        assert tenant_user.email.encode() in response.content

    def test_team_search_returns_partial(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get(
            "/team/?q=owner", HTTP_HX_REQUEST="true", HTTP_HX_TARGET="members-list"
        )
        assert response.status_code == 200
        assert b"<!DOCTYPE" not in response.content

    def test_team_search_filters_by_email(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get("/team/?q=owner", HTTP_HX_REQUEST="true")
        assert response.status_code == 200
        assert tenant_user.email.encode() in response.content

    def test_team_search_no_match_shows_empty(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get("/team/?q=zzznomatch", HTTP_HX_REQUEST="true")
        assert response.status_code == 200
        assert b"No team members found." in response.content

    def test_team_search_full_page_without_htmx(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get("/team/?q=owner")
        assert response.status_code == 200
        assert b"<!DOCTYPE" in response.content or b"Team Members" in response.content

    def test_team_no_dead_ui(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get("/team/")
        assert b"Manage permissions" not in response.content
        assert b"Bulk upload" not in response.content
        assert b"Download template" not in response.content

    def test_invite_member_get(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get("/team/invite/", HTTP_HX_REQUEST="true")
        assert response.status_code == 200

    def test_invite_member_post_valid(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.post(
            "/team/invite/",
            {
                "first_name": "Test",
                "last_name": "Worker",
                "email": "worker@testfarm.com",
                "role": "data_entry",
            },
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        from apps.infrastructure.accounts.models import CustomUser

        assert CustomUser.objects.filter(email="worker@testfarm.com").exists()

    def test_invite_duplicate_email_rejected(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.post(
            "/team/invite/",
            {
                "first_name": tenant_user.first_name,
                "last_name": tenant_user.last_name,
                "email": tenant_user.email,
                "role": "manager",
            },
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        assert b"already exists" in response.content

    def test_deactivate_member(self, client, tenant_user):
        from apps.infrastructure.accounts.models import CustomUser

        member = CustomUser.objects.create_user(
            username=f"member_{uuid.uuid4().hex[:8]}",
            email=f"member_{uuid.uuid4().hex[:8]}@test.com",
            password="testpass123",
            org=tenant_user.org,
            role="data_entry",
        )
        client.force_login(tenant_user)
        response = client.post(f"/team/{member.pk}/deactivate/", HTTP_HX_REQUEST="true")
        assert response.status_code == 200
        member.refresh_from_db()
        assert member.is_active is False

    def test_reactivate_member(self, client, tenant_user):
        from apps.infrastructure.accounts.models import CustomUser

        member = CustomUser.objects.create_user(
            username=f"member_{uuid.uuid4().hex[:8]}",
            email=f"member_{uuid.uuid4().hex[:8]}@test.com",
            password="testpass123",
            org=tenant_user.org,
            role="data_entry",
            is_active=False,
        )
        client.force_login(tenant_user)
        response = client.post(f"/team/{member.pk}/reactivate/", HTTP_HX_REQUEST="true")
        assert response.status_code == 200
        member.refresh_from_db()
        assert member.is_active is True

    def test_change_member_role(self, client, tenant_user):
        from apps.infrastructure.accounts.models import CustomUser

        member = CustomUser.objects.create_user(
            username=f"member_{uuid.uuid4().hex[:8]}",
            email=f"member_{uuid.uuid4().hex[:8]}@test.com",
            password="testpass123",
            org=tenant_user.org,
            role="data_entry",
        )
        client.force_login(tenant_user)
        response = client.post(
            f"/team/{member.pk}/role/", {"role": "supervisor"}, HTTP_HX_REQUEST="true"
        )
        assert response.status_code == 200
        member.refresh_from_db()
        assert member.role == "supervisor"

    def test_non_owner_cannot_invite(self, client, tenant_user):
        tenant_user.role = "data_entry"
        tenant_user.save()
        client.force_login(tenant_user)
        response = client.post(
            "/team/invite/",
            {"email": "new@test.com", "first_name": "New", "last_name": "User", "role": "manager"},
        )
        assert response.status_code == 403

    def test_cannot_deactivate_self(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.post(f"/team/{tenant_user.pk}/deactivate/", HTTP_HX_REQUEST="true")
        assert response.status_code == 200
        tenant_user.refresh_from_db()
        assert tenant_user.is_active is True
