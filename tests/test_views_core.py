import pytest

pytestmark = pytest.mark.django_db


class TestCoreViews:

    def test_landing_shown_to_unauthenticated(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert b"FlockIQ" in response.content

    def test_dashboard_shown_to_authenticated(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get("/")
        assert response.status_code == 200

    def test_super_admin_sees_platform_dashboard(self, client, super_admin_user):
        client.force_login(super_admin_user)
        response = client.get("/")
        assert response.status_code == 200
        content = response.content.lower()
        assert b"tenant" in content or b"platform" in content or b"organisation" in content

    def test_login_page_returns_200(self, client):
        response = client.get("/login/")
        assert response.status_code == 200

    def test_login_page_redirects_authenticated_user(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get("/login/")
        assert response.status_code == 302

    def test_signup_page_returns_200(self, client):
        response = client.get("/signup/")
        assert response.status_code == 200

    def test_signup_page_redirects_authenticated_user(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get("/signup/")
        assert response.status_code == 302

    def test_forgot_password_page_returns_200(self, client):
        response = client.get("/forgot-password/")
        assert response.status_code == 200

    def test_login_post_invalid_credentials_rerenders(self, client):
        response = client.post("/login/", {"email": "nobody@example.com", "password": "wrong"})
        assert response.status_code == 200
        assert b"Invalid" in response.content or b"error" in response.content.lower()

    def test_login_post_valid_credentials_redirects(self, client, tenant_user):
        response = client.post("/login/", {"email": tenant_user.email, "password": "testpass123"})
        assert response.status_code == 302
