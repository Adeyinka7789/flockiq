"""
Tests for the Loss Documentation Report feature.

Covers:
  - LossDocumentationReportView role gating (owner/manager/supervisor only)
  - data_entry / vet_advisor get 403
  - GET renders the form modal
  - POST with a valid form returns a PDF (application/pdf)
  - POST with an invalid form re-renders the modal with errors (422)
  - generate_loss_documentation_pdf includes batch name, cause of death,
    mortality timeline and the vaccination compliance section
"""
import datetime
from decimal import Decimal

import pytest

pytestmark = pytest.mark.django_db


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_org(subdomain="loss-test"):
    from apps.infrastructure.tenants.models import Organization
    return Organization.objects.create(
        name="Loss Test Org",
        subdomain=subdomain,
        plan_tier="monthly",
        subscription_status="active",
        onboarding_complete=True,
        is_active=True,
    )


def _make_user(org, role="owner"):
    from apps.infrastructure.accounts.models import CustomUser
    return CustomUser.objects.create_user(
        username=f"{role}-{org.subdomain}",
        email=f"{role}@{org.subdomain}.com",
        password="testpass123",
        org=org, role=role, email_verified=True,
    )


def _make_farm(org):
    from apps.farm.farms.models import Farm
    from apps.infrastructure.core.rls import set_tenant_context
    with set_tenant_context(org):
        farm = Farm(
            org=org, name="Loss Farm", location="Lagos",
            latitude=Decimal("6.5244"), longitude=Decimal("3.3792"),
            farm_type="broiler",
        )
        farm.clean()
        farm.save()
    return farm


def _make_house(org, farm):
    from apps.farm.farms.models import House
    from apps.infrastructure.core.rls import set_tenant_context
    with set_tenant_context(org):
        return House.objects.create(
            org=org, farm=farm, name="House A", capacity=1000, house_type="broiler",
        )


def _make_batch(org, farm, house, name="LossBatch001"):
    from apps.farm.flocks.models import Batch
    from apps.infrastructure.core.rls import set_tenant_context
    with set_tenant_context(org):
        return Batch.objects.create(
            org=org, farm=farm, house=house,
            batch_name=name,
            bird_type="broiler",
            breed_name="Cobb 500",
            placement_date=datetime.date.today() - datetime.timedelta(days=30),
            initial_count=500,
            current_count=350,
            status="active",
        )


def _valid_post_data():
    return {
        "cause_of_death": "heat_stress",
        "incident_date": datetime.date.today().isoformat(),
        "birds_affected": "150",
        "additional_notes": "Power outage during a heatwave.",
    }


# ── View: role gating ──────────────────────────────────────────────────────────

class TestLossReportRBAC:

    def _setup(self):
        org = _make_org(f"loss-rbac-{datetime.datetime.now().timestamp()}")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house)
        return org, batch

    @pytest.mark.parametrize("role", ["owner", "manager", "supervisor"])
    def test_allowed_roles_can_open_form(self, client, role):
        org, batch = self._setup()
        user = _make_user(org, role)
        client.force_login(user)
        resp = client.get(f"/batches/{batch.pk}/loss-report/")
        assert resp.status_code == 200
        assert b"Generate Loss Report" in resp.content

    @pytest.mark.parametrize("role", ["data_entry", "vet_advisor"])
    def test_forbidden_roles_get_403(self, client, role):
        org, batch = self._setup()
        user = _make_user(org, role)
        client.force_login(user)
        resp = client.get(f"/batches/{batch.pk}/loss-report/")
        assert resp.status_code == 403


# ── View: POST behaviour ───────────────────────────────────────────────────────

class TestLossReportPost:

    def _setup(self, subdomain):
        org = _make_org(subdomain)
        user = _make_user(org, "owner")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house)
        return org, user, batch

    def test_valid_post_returns_pdf(self, client):
        org, user, batch = self._setup("loss-post-1")
        client.force_login(user)
        resp = client.post(f"/batches/{batch.pk}/loss-report/", data=_valid_post_data())
        assert resp.status_code == 200
        assert resp["Content-Type"] == "application/pdf"
        assert resp.content[:4] == b"%PDF"
        assert "attachment" in resp["Content-Disposition"]

    def test_invalid_post_rerenders_with_errors(self, client):
        org, user, batch = self._setup("loss-post-2")
        client.force_login(user)
        data = _valid_post_data()
        del data["cause_of_death"]  # required field missing
        resp = client.post(f"/batches/{batch.pk}/loss-report/", data=data)
        assert resp.status_code == 422
        assert resp["Content-Type"].startswith("text/html")
        assert b"Generate Loss Report" in resp.content

    def test_future_incident_date_rejected(self, client):
        org, user, batch = self._setup("loss-post-3")
        client.force_login(user)
        data = _valid_post_data()
        data["incident_date"] = (
            datetime.date.today() + datetime.timedelta(days=5)
        ).isoformat()
        resp = client.post(f"/batches/{batch.pk}/loss-report/", data=data)
        assert resp.status_code == 422


# ── PDF generator content ──────────────────────────────────────────────────────

class TestLossReportPdfContent:

    def test_pdf_includes_key_sections(self):
        from reportlab import rl_config
        from apps.farm.flocks.models import MortalityLog
        from apps.health.health.models import VaccinationSchedule
        from apps.infrastructure.core.exports import generate_loss_documentation_pdf
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.infrastructure.core.valuation import FlockValuationService

        org = _make_org("loss-pdf-1")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house, name="LossBatchPDF")

        with set_tenant_context(org):
            MortalityLog.objects.create(
                org=org, batch=batch, farm=farm,
                date=datetime.date.today(), count=150, cause="disease",
                notes="Sudden spike",
            )
            VaccinationSchedule.objects.create(
                org=org, batch=batch, farm=farm,
                vaccine_name="Newcastle", due_date=datetime.date.today(),
                status="completed",
            )
            mortality_logs = list(MortalityLog.objects.filter(batch=batch))
            vaccinations = list(VaccinationSchedule.objects.filter(batch=batch))
            valuation = FlockValuationService(batch).estimate_value()

        loss_details = {
            "cause_of_death": "heat_stress",
            "incident_date": datetime.date.today(),
            "birds_affected": 150,
            "additional_notes": "Heatwave incident.",
        }

        # Disable PDF stream compression so we can search the raw bytes for text.
        original = rl_config.pageCompression
        rl_config.pageCompression = 0
        try:
            pdf = generate_loss_documentation_pdf(
                batch=batch,
                loss_details=loss_details,
                mortality_logs=mortality_logs,
                feed_logs=[],
                vaccinations=vaccinations,
                valuation=valuation,
            )
        finally:
            rl_config.pageCompression = original

        assert pdf[:4] == b"%PDF"
        text = pdf.decode("latin-1")
        # Batch name (single token), cause label, section headings.
        assert "LossBatchPDF" in text
        assert "Heat" in text and "Stress" in text
        assert "Mortality" in text and "Timeline" in text
        assert "Vaccination" in text
        assert "Newcastle" in text
