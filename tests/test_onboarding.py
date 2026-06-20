"""Country selection during signup/onboarding + Organization.country backfill."""

import uuid

import pytest

pytestmark = pytest.mark.django_db


# ── Organization.country field ────────────────────────────────────────────────

class TestOrganizationCountry:

    def test_country_defaults_to_nigeria(self):
        from apps.infrastructure.tenants.models import Organization
        org = Organization.objects.create(name="Default Co", subdomain="defaultco")
        assert org.country == "Nigeria"

    def test_country_can_be_set(self):
        from apps.infrastructure.tenants.models import Organization
        org = Organization.objects.create(
            name="Ghana Co", subdomain="ghanaco", country="Ghana",
        )
        org.refresh_from_db()
        assert org.country == "Ghana"


# ── Data migration backfill ────────────────────────────────────────────────────

class TestCountryBackfill:
    """Exercises the 0009 data migration's backfill function against the live
    schema — copies the owner's CustomUser.country onto the org."""

    def _run_backfill(self):
        import importlib
        from django.apps import apps as django_apps

        # Module name begins with a digit, so import_module (not `import`).
        module = importlib.import_module(
            "apps.infrastructure.tenants.migrations.0009_organization_country"
        )
        module.backfill_country_from_owner(django_apps, None)

    def test_backfill_copies_owner_country(self):
        from apps.infrastructure.tenants.models import Organization
        from apps.infrastructure.accounts.models import CustomUser

        org = Organization.objects.create(name="Backfill Co", subdomain="backfillco")
        # Simulate a pre-migration row: default 'Nigeria' even though owner is Kenyan.
        org.country = "Nigeria"
        org.save(update_fields=["country"])
        CustomUser.objects.create_user(
            username="owner-bf", email="owner@bf.com", password="x",
            org=org, role="owner", country="Kenya",
        )

        self._run_backfill()
        org.refresh_from_db()
        assert org.country == "Kenya"

    def test_backfill_falls_back_to_nigeria_when_owner_has_no_country(self):
        from apps.infrastructure.tenants.models import Organization
        from apps.infrastructure.accounts.models import CustomUser

        org = Organization.objects.create(name="NoCountry Co", subdomain="nocountryco")
        CustomUser.objects.create_user(
            username="owner-nc", email="owner@nc.com", password="x",
            org=org, role="owner", country="",
        )

        self._run_backfill()
        org.refresh_from_db()
        assert org.country == "Nigeria"


# ── Signup wires org.country from the user's selection ─────────────────────────

class TestSignupCountry:

    def _signup_payload(self, **overrides):
        sub = f"signup{uuid.uuid4().hex[:8]}"
        payload = {
            "org_name": "Signup Farm",
            "owner_name": "Ama Mensah",
            "email": f"{sub}@example.com",
            "phone": "+233200000000",
            "subdomain": sub,
            "country": "Ghana",
            "state_region": "Greater Accra",
            "password": "supersecret123",
            "confirm_password": "supersecret123",
        }
        payload.update(overrides)
        return payload

    def test_signup_sets_org_country_from_selection(self, client):
        from django.core.cache import cache
        from apps.infrastructure.tenants.models import Organization

        cache.clear()  # reset the per-IP signup throttle bucket
        payload = self._signup_payload(country="Ghana")
        resp = client.post("/signup/", payload)
        assert resp.status_code == 302, getattr(resp, "content", b"")

        org = Organization.objects.get(subdomain=payload["subdomain"])
        assert org.country == "Ghana"
        # Phone is collected at signup too.
        assert org.owner_phone == payload["phone"]

    def test_signup_nigeria_org_country(self, client):
        from django.core.cache import cache
        from apps.infrastructure.tenants.models import Organization

        cache.clear()  # reset the per-IP signup throttle bucket
        payload = self._signup_payload(country="Nigeria", phone="+2348012345678")
        resp = client.post("/signup/", payload)
        assert resp.status_code == 302

        org = Organization.objects.get(subdomain=payload["subdomain"])
        assert org.country == "Nigeria"


# ── API onboarding wires org.country from request.data (Step 4 bug fix) ────────

class TestOnboardingApiCountry:
    """POST /api/v1/onboarding/ now reads country from request.data instead of
    silently defaulting every international API signup to Nigeria."""

    def _payload(self, **overrides):
        sub = f"api{uuid.uuid4().hex[:8]}"
        payload = {
            "name": "API Farm",
            "subdomain": sub,
            "owner_name": "Kwame Asante",
            "owner_phone": "+233200000000",
            "owner_email": f"{sub}@example.com",
        }
        payload.update(overrides)
        return payload

    def test_onboarding_creates_org_and_owner(self, client):
        from apps.infrastructure.tenants.models import Organization
        from apps.infrastructure.accounts.models import CustomUser

        payload = self._payload()
        resp = client.post("/api/v1/onboarding/", payload, content_type="application/json")
        assert resp.status_code == 201, resp.content
        body = resp.json()["data"]
        assert body["user"]["role"] == "owner"
        assert body["temp_password"]  # generated password surfaced to caller
        assert body["access"] and body["refresh"]

        org = Organization.objects.get(subdomain=payload["subdomain"])
        owner = CustomUser.objects.get(email=payload["owner_email"])
        assert owner.role == "owner"
        assert owner.org_id == org.id

    def test_onboarding_sets_country_from_request(self, client):
        from apps.infrastructure.tenants.models import Organization

        payload = self._payload(country="Ghana")
        resp = client.post("/api/v1/onboarding/", payload, content_type="application/json")
        assert resp.status_code == 201, resp.content

        org = Organization.objects.get(subdomain=payload["subdomain"])
        assert org.country == "Ghana"
        # User country must match the org's so market data scopes correctly.
        assert org.users.get(role="owner").country == "Ghana"

    def test_onboarding_defaults_country_to_nigeria(self, client):
        from apps.infrastructure.tenants.models import Organization

        payload = self._payload()  # no country key
        resp = client.post("/api/v1/onboarding/", payload, content_type="application/json")
        assert resp.status_code == 201, resp.content

        org = Organization.objects.get(subdomain=payload["subdomain"])
        assert org.country == "Nigeria"
