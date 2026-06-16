import pytest
from django.test import RequestFactory
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_org(**kwargs):
    from apps.infrastructure.tenants.models import Organization
    defaults = {
        "name": "Test Farm",
        "subdomain": "testfarm",
        "owner_email": "owner@testfarm.com",
    }
    defaults.update(kwargs)
    return Organization.objects.create(**defaults)


def make_user(org=None, role="data_entry", email="user@testfarm.com", password="pass1234"):
    from apps.infrastructure.accounts.models import CustomUser
    return CustomUser.objects.create_user(
        email=email,
        username=email,
        password=password,
        role=role,
        org=org,
    )


# ── Model tests ───────────────────────────────────────────────────────────────

def test_custom_user_str():
    org = make_org(subdomain="strtest")
    user = make_user(org=org, role="owner", email="str@test.com")
    assert "str@test.com" in str(user)
    assert "owner" in str(user)


def test_owner_role_property():
    org = make_org(subdomain="ownerprop")
    user = make_user(org=org, role="owner", email="ownerp@test.com")
    assert user.is_owner is True
    assert user.is_manager is False


def test_supervisor_or_above_includes_manager():
    org = make_org(subdomain="suprop")
    manager = make_user(org=org, role="manager", email="mgr@test.com")
    supervisor = make_user(org=org, role="supervisor", email="sup@test.com")
    data_entry = make_user(org=org, role="data_entry", email="de@test.com")

    assert manager.is_supervisor_or_above is True
    assert supervisor.is_supervisor_or_above is True
    assert data_entry.is_supervisor_or_above is False


def test_super_admin_has_no_org():
    from apps.infrastructure.accounts.models import CustomUser
    admin = CustomUser.objects.create_user(
        email="superadmin@flockiq.com",
        username="superadmin@flockiq.com",
        password="pass1234",
        role="super_admin",
        org=None,
    )
    assert admin.org is None
    assert admin.role == "super_admin"


# ── Auth endpoint tests ────────────────────────────────────────────────────────

def test_login_returns_tokens_and_profile():
    org = make_org(subdomain="logintest")
    make_user(org=org, role="owner", email="login@test.com", password="pass1234")

    client = APIClient()
    response = client.post(
        "/api/v1/auth/login/",
        {"email": "login@test.com", "password": "pass1234"},
        format="json",
    )

    assert response.status_code == 200
    data = response.data["data"]
    assert "access" in data
    assert "refresh" in data
    assert data["user"]["email"] == "login@test.com"
    assert data["user"]["role"] == "owner"


def test_login_wrong_password_returns_401():
    org = make_org(subdomain="wrongpass")
    make_user(org=org, email="wp@test.com", password="correct")

    client = APIClient()
    response = client.post(
        "/api/v1/auth/login/",
        {"email": "wp@test.com", "password": "wrong"},
        format="json",
    )
    assert response.status_code == 401


def test_login_lockout_after_5_attempts():
    """django-axes locks the IP after AXES_FAILURE_LIMIT failed attempts."""
    org = make_org(subdomain="locktest")
    make_user(org=org, email="lock@test.com", password="correct")

    client = APIClient()
    for _ in range(5):
        client.post(
            "/api/v1/auth/login/",
            {"email": "lock@test.com", "password": "wrong"},
            format="json",
            REMOTE_ADDR="10.0.0.1",
        )

    # 6th attempt should be locked out (axes returns 403)
    response = client.post(
        "/api/v1/auth/login/",
        {"email": "lock@test.com", "password": "correct"},
        format="json",
        REMOTE_ADDR="10.0.0.1",
    )
    assert response.status_code in (403, 429)


def test_jwt_payload_contains_org_id_and_role():
    from rest_framework_simplejwt.tokens import AccessToken
    from apps.infrastructure.accounts.serializers import CustomTokenObtainPairSerializer

    org = make_org(subdomain="jwttest")
    user = make_user(org=org, role="manager", email="jwt@test.com")

    token = CustomTokenObtainPairSerializer.get_token(user)
    access = token.access_token

    assert str(access["org_id"]) == str(org.id)
    assert access["role"] == "manager"


# ── User management tests ─────────────────────────────────────────────────────

def test_user_create_requires_manager_or_above():
    org = make_org(subdomain="ucreate")
    data_entry = make_user(org=org, role="data_entry", email="de2@test.com")

    client = APIClient()
    client.force_authenticate(user=data_entry)
    response = client.post(
        "/api/v1/users/create/",
        {"email": "new@test.com", "role": "supervisor"},
        format="json",
    )
    assert response.status_code == 403


def test_user_cannot_see_other_org_users():
    org_a = make_org(subdomain="orga")
    org_b = make_org(subdomain="orgb")
    manager_a = make_user(org=org_a, role="manager", email="mgra@test.com")
    make_user(org=org_b, role="data_entry", email="de_b@test.com")

    client = APIClient()
    client.force_authenticate(user=manager_a)
    # Hit the request on org_a's tenant subdomain so TenantMiddleware resolves
    # the tenant by subdomain and sets the RLS context for the view. (JWT auth
    # via force_authenticate runs at the DRF view layer, after the middleware,
    # so request.user is anonymous at middleware time and cannot establish the
    # tenant context on a non-subdomain host.)
    response = client.get("/api/v1/users/", HTTP_HOST="orga.flockiq.com")

    assert response.status_code == 200
    emails = [u["email"] for u in response.data["data"]]
    assert "de_b@test.com" not in emails
    assert "mgra@test.com" in emails


# ── Onboarding tests ───────────────────────────────────────────────────────────

def test_onboarding_creates_org_and_owner_atomically():
    from apps.infrastructure.tenants.models import Organization
    from apps.infrastructure.accounts.models import CustomUser

    client = APIClient()
    response = client.post(
        "/api/v1/onboarding/",
        {
            "name": "Atomic Farm",
            "subdomain": "atomicfarm",
            "owner_name": "Adeniran Test",
            "owner_phone": "+2348012345678",
            "owner_email": "atomic@test.com",
        },
        format="json",
    )

    assert response.status_code == 201
    assert Organization.objects.filter(subdomain="atomicfarm").exists()
    assert CustomUser.objects.filter(email="atomic@test.com", role="owner").exists()

    data = response.data["data"]
    assert "access" in data
    assert "refresh" in data
    assert data["user"]["role"] == "owner"


def test_reserved_subdomain_rejected_at_onboarding():
    client = APIClient()
    response = client.post(
        "/api/v1/onboarding/",
        {
            "name": "Admin Farm",
            "subdomain": "admin",
            "owner_name": "Test",
            "owner_phone": "+2348012345678",
            "owner_email": "reserved@test.com",
        },
        format="json",
    )
    assert response.status_code == 400


# ── Staff onboarding tour ─────────────────────────────────────────────────────

from django.test import Client


def _staff_page_org(subdomain):
    """An org configured so middleware lets an authenticated staff page render."""
    import datetime
    from django.utils import timezone
    org = make_org(subdomain=subdomain)
    org.onboarding_complete = True
    org.trial_ends_at = timezone.now() + datetime.timedelta(days=14)
    org.save()
    return org


def _logged_in_staff(org, role, email):
    user = make_user(org=org, role=role, email=email)
    user.email_verified = True
    user.save()
    client = Client()
    client.force_login(user)
    return client, user


def test_has_seen_staff_onboarding_defaults_false():
    org = make_org(subdomain="onbdefault")
    user = make_user(org=org, role="manager", email="onbdef@test.com")
    assert user.has_seen_staff_onboarding is False


@pytest.mark.parametrize("role", ["manager", "supervisor", "data_entry", "vet_advisor"])
def test_staff_sees_onboarding_modal(role):
    org = _staff_page_org(f"onbshow{role[:4]}")
    client, _ = _logged_in_staff(org, role, f"onbshow-{role}@test.com")
    response = client.get("/profile/")
    assert response.status_code == 200
    assert b"Welcome to the Team!" in response.content


def test_owner_does_not_see_onboarding_modal():
    org = _staff_page_org("onbowner")
    client, _ = _logged_in_staff(org, "owner", "onbowner-user@test.com")
    response = client.get("/profile/")
    assert response.status_code == 200
    assert b"Welcome to the Team!" not in response.content


def test_superuser_does_not_see_onboarding_modal():
    from apps.infrastructure.accounts.models import CustomUser
    admin = CustomUser.objects.create_superuser(
        email="onbsuper@flockiq.com",
        username="onbsuper@flockiq.com",
        password="pass1234",
    )
    admin.email_verified = True
    admin.save()
    client = Client()
    client.force_login(admin)
    response = client.get("/profile/")
    assert response.status_code == 200
    assert b"Welcome to the Team!" not in response.content


def test_dismissed_staff_does_not_see_onboarding_modal():
    org = _staff_page_org("onbdone")
    client, user = _logged_in_staff(org, "data_entry", "onbdone-user@test.com")
    user.has_seen_staff_onboarding = True
    user.save()
    response = client.get("/profile/")
    assert response.status_code == 200
    assert b"Welcome to the Team!" not in response.content


def test_dismiss_endpoint_sets_flag_and_returns_204():
    org = _staff_page_org("onbdismiss")
    client, user = _logged_in_staff(org, "supervisor", "onbdismiss-user@test.com")
    assert user.has_seen_staff_onboarding is False
    response = client.post("/onboarding/staff/dismiss/")
    assert response.status_code == 204
    user.refresh_from_db()
    assert user.has_seen_staff_onboarding is True


def test_dismiss_endpoint_requires_login():
    client = Client()
    response = client.post("/onboarding/staff/dismiss/")
    assert response.status_code == 302
    assert "/login/" in response["Location"]
