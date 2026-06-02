import pytest

pytestmark = pytest.mark.django_db


class TestProfileViews:

    def test_profile_requires_login(self, client):
        response = client.get("/profile/")
        assert response.status_code in (301, 302)

    def test_profile_returns_200(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get("/profile/")
        assert response.status_code == 200

    def test_edit_profile_get_returns_form(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get("/profile/edit/")
        assert response.status_code == 200

    def test_edit_profile_post_updates_name(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.post(
            "/profile/edit/",
            {"first_name": "Updated", "last_name": "Name", "phone": "+2348012345678"},
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        tenant_user.refresh_from_db()
        assert tenant_user.first_name == "Updated"

    def test_edit_profile_post_sets_hx_trigger(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.post(
            "/profile/edit/",
            {"first_name": "X", "last_name": "Y", "phone": ""},
        )
        assert response.status_code == 200
        assert "HX-Trigger" in response.headers

    def test_edit_profile_requires_login(self, client):
        response = client.post("/profile/edit/", {"first_name": "X"})
        assert response.status_code in (301, 302)


class TestChangePasswordView:

    def test_change_password_wrong_old_returns_error(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.post(
            "/profile/change-password/",
            {"old_password": "wrongpass", "new_password": "newpass123", "confirm_password": "newpass123"},
        )
        assert response.status_code == 200
        assert b"incorrect" in response.content.lower()

    def test_change_password_too_short_returns_error(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.post(
            "/profile/change-password/",
            {"old_password": "testpass123", "new_password": "short", "confirm_password": "short"},
        )
        assert response.status_code == 200
        assert b"8" in response.content

    def test_change_password_mismatch_returns_error(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.post(
            "/profile/change-password/",
            {"old_password": "testpass123", "new_password": "newpass123", "confirm_password": "different123"},
        )
        assert response.status_code == 200
        assert b"match" in response.content.lower()

    def test_change_password_success(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.post(
            "/profile/change-password/",
            {"old_password": "testpass123", "new_password": "newpass123!", "confirm_password": "newpass123!"},
        )
        assert response.status_code == 200

    def test_change_password_requires_login(self, client):
        response = client.post("/profile/change-password/", {})
        assert response.status_code in (301, 302)


class TestLogoutView:

    def test_logout_get_redirects(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get("/logout/")
        assert response.status_code == 302

    def test_logout_post_redirects(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.post("/logout/")
        assert response.status_code == 302

    def test_logout_clears_session(self, client, tenant_user):
        client.force_login(tenant_user)
        client.get("/logout/")
        response = client.get("/profile/")
        assert response.status_code in (301, 302)


class TestForgotPasswordView:

    def test_forgot_password_get_returns_200(self, client):
        response = client.get("/forgot-password/")
        assert response.status_code == 200

    def test_forgot_password_post_unknown_email_still_200(self, client):
        response = client.post(
            "/forgot-password/",
            {"email": "nobody@example.com"},
        )
        assert response.status_code == 200

    def test_forgot_password_post_known_email_200(self, client, tenant_user):
        response = client.post(
            "/forgot-password/",
            {"email": tenant_user.email},
        )
        assert response.status_code == 200


class TestResetPasswordView:

    def test_reset_password_no_token_redirects(self, client):
        response = client.get("/reset-password/")
        assert response.status_code == 302

    def test_reset_password_invalid_token_shows_error(self, client):
        response = client.get("/reset-password/?token=invalid-token-xyz")
        assert response.status_code == 200
        assert b"expired" in response.content.lower() or b"invalid" in response.content.lower()

    def test_reset_password_valid_token_shows_form(self, client, tenant_user):
        from django.core.cache import cache
        import secrets
        token = secrets.token_urlsafe(32)
        cache.set(f"pwd_reset:{token}", tenant_user.email, timeout=3600)
        response = client.get(f"/reset-password/?token={token}")
        assert response.status_code == 200
        cache.delete(f"pwd_reset:{token}")

    def test_reset_password_post_expired_token(self, client):
        response = client.post(
            "/reset-password/",
            {"token": "expired-token", "new_password": "newpass123", "confirm_password": "newpass123"},
        )
        assert response.status_code == 200
        assert b"expired" in response.content.lower() or b"link" in response.content.lower()

    def test_reset_password_post_too_short(self, client, tenant_user):
        from django.core.cache import cache
        import secrets
        token = secrets.token_urlsafe(32)
        cache.set(f"pwd_reset:{token}", tenant_user.email, timeout=3600)
        response = client.post(
            "/reset-password/",
            {"token": token, "new_password": "short", "confirm_password": "short"},
        )
        assert response.status_code == 200
        assert b"8" in response.content
        cache.delete(f"pwd_reset:{token}")

    def test_reset_password_post_mismatch(self, client, tenant_user):
        from django.core.cache import cache
        import secrets
        token = secrets.token_urlsafe(32)
        cache.set(f"pwd_reset:{token}", tenant_user.email, timeout=3600)
        response = client.post(
            "/reset-password/",
            {"token": token, "new_password": "newpass123", "confirm_password": "different123"},
        )
        assert response.status_code == 200
        assert b"match" in response.content.lower()
        cache.delete(f"pwd_reset:{token}")

    def test_reset_password_post_success_redirects(self, client, tenant_user):
        from django.core.cache import cache
        import secrets
        token = secrets.token_urlsafe(32)
        cache.set(f"pwd_reset:{token}", tenant_user.email, timeout=3600)
        response = client.post(
            "/reset-password/",
            {"token": token, "new_password": "validpass123!", "confirm_password": "validpass123!"},
        )
        assert response.status_code == 302
        assert "/login/" in response["Location"]
