"""
DRF API endpoint tests using APIClient.force_authenticate to bypass JWT.
Covers flocks, farms, health, finance, analytics, billing API views.
"""
import pytest
from datetime import date
from rest_framework.test import APIClient


pytestmark = pytest.mark.django_db


# ── Farm API Views ─────────────────────────────────────────────────────────────

class TestFarmAPIViews:

    def test_farm_list_api_unauthenticated_returns_401(self):
        client = APIClient()
        response = client.get("/api/v1/farms/")
        assert response.status_code == 401

    def test_farm_list_api_returns_200(self, api_client):
        response = api_client.get("/api/v1/farms/")
        assert response.status_code == 200
        assert "data" in response.json()

    def test_farm_list_api_shows_created_farm(self, api_client, test_farm):
        response = api_client.get("/api/v1/farms/")
        assert response.status_code == 200
        names = [f["name"] for f in response.json()["data"]]
        assert test_farm.name in names

    def test_farm_detail_api_returns_200(self, api_client, test_farm):
        response = api_client.get(f"/api/v1/farms/{test_farm.pk}/")
        assert response.status_code == 200
        assert response.json()["data"]["name"] == test_farm.name

    def test_farm_detail_api_404_for_missing(self, api_client):
        import uuid
        response = api_client.get(f"/api/v1/farms/{uuid.uuid4()}/")
        assert response.status_code == 404

    def test_farm_dashboard_api_returns_200(self, api_client, test_farm):
        response = api_client.get(f"/api/v1/farms/{test_farm.pk}/dashboard/")
        assert response.status_code == 200


# ── Flock API Views ────────────────────────────────────────────────────────────

class TestBatchAPIViews:

    def test_batch_list_api_unauthenticated_returns_401(self):
        client = APIClient()
        response = client.get("/api/v1/flocks/batches/")
        assert response.status_code == 401

    def test_batch_list_api_returns_200(self, api_client):
        response = api_client.get("/api/v1/flocks/batches/")
        assert response.status_code == 200
        assert "data" in response.json()

    def test_batch_list_api_status_filter(self, api_client, test_batch):
        response = api_client.get("/api/v1/flocks/batches/?status=active")
        assert response.status_code == 200

    def test_batch_detail_api_returns_200(self, api_client, test_batch):
        response = api_client.get(f"/api/v1/flocks/batches/{test_batch.pk}/")
        assert response.status_code == 200

    def test_batch_detail_api_404_for_missing(self, api_client):
        import uuid
        response = api_client.get(f"/api/v1/flocks/batches/{uuid.uuid4()}/")
        assert response.status_code == 404

    def test_batch_create_api_valid(self, api_client, test_farm, test_house):
        response = api_client.post(
            "/api/v1/flocks/batches/",
            {
                "farm_id": str(test_farm.pk),
                "house_id": str(test_house.pk),
                "batch_name": "API Batch",
                "bird_type": "layer",
                "placement_date": date.today().isoformat(),
                "initial_count": 50,
            },
            format="json",
        )
        assert response.status_code == 201

    def test_batch_create_api_invalid_returns_400(self, api_client):
        response = api_client.post("/api/v1/flocks/batches/", {}, format="json")
        assert response.status_code == 400

    def test_batch_create_api_no_org_returns_403(self, super_admin_user):
        client = APIClient()
        client.force_authenticate(user=super_admin_user)
        response = client.post("/api/v1/flocks/batches/", {}, format="json")
        assert response.status_code == 403


class TestMortalityAPIView:

    def test_mortality_api_valid_post(self, api_client, test_batch):
        response = api_client.post(
            f"/api/v1/flocks/batches/{test_batch.pk}/mortality/",
            {"count": 2, "cause": "disease", "date": date.today().isoformat()},
            format="json",
        )
        assert response.status_code == 201

    def test_mortality_api_invalid_returns_400(self, api_client, test_batch):
        response = api_client.post(
            f"/api/v1/flocks/batches/{test_batch.pk}/mortality/",
            {},
            format="json",
        )
        assert response.status_code == 400

    def test_mortality_api_batch_not_found_returns_404(self, api_client):
        import uuid
        response = api_client.post(
            f"/api/v1/flocks/batches/{uuid.uuid4()}/mortality/",
            {"count": 1, "cause": "disease"},
            format="json",
        )
        assert response.status_code == 404

    def test_mortality_api_no_org_returns_403(self, super_admin_user, test_batch):
        client = APIClient()
        client.force_authenticate(user=super_admin_user)
        response = client.post(
            f"/api/v1/flocks/batches/{test_batch.pk}/mortality/",
            {"count": 1, "cause": "disease"},
            format="json",
        )
        assert response.status_code == 403


class TestBatchCloseAPIView:

    def test_batch_close_api(self, api_client, test_batch):
        response = api_client.post(
            f"/api/v1/flocks/batches/{test_batch.pk}/close/",
            {"notes": "Cycle complete"},
            format="json",
        )
        assert response.status_code == 200

    def test_batch_close_api_not_found(self, api_client):
        import uuid
        response = api_client.post(
            f"/api/v1/flocks/batches/{uuid.uuid4()}/close/",
            {},
            format="json",
        )
        assert response.status_code in (404, 422)

    def test_batch_close_already_closed_returns_422(self, api_client, test_batch):
        # Close once
        api_client.post(
            f"/api/v1/flocks/batches/{test_batch.pk}/close/",
            {"notes": "First close"},
            format="json",
        )
        # Close again → 422
        response = api_client.post(
            f"/api/v1/flocks/batches/{test_batch.pk}/close/",
            {"notes": "Second close"},
            format="json",
        )
        assert response.status_code == 422


# ── Health API Views ───────────────────────────────────────────────────────────

class TestHealthAPIViews:

    def test_vaccination_api_returns_200(self, api_client, test_batch):
        response = api_client.get("/api/v1/health/vaccinations/")
        assert response.status_code == 200
        assert "data" in response.json()

    def test_vaccination_complete_api(self, api_client, test_batch, test_org):
        from apps.health.health.models import VaccinationSchedule
        from apps.infrastructure.core.rls import set_tenant_context
        with set_tenant_context(test_org):
            vacc = VaccinationSchedule.objects.filter(
                batch=test_batch, status="scheduled"
            ).first()
        if vacc is None:
            pytest.skip("No scheduled vaccination")
        response = api_client.post(
            f"/api/v1/health/vaccinations/{vacc.pk}/complete/",
            {},
            format="json",
        )
        assert response.status_code == 200

    def test_medication_api_post_missing_fields_returns_400(self, api_client):
        # MedicationAPIView is POST-only
        response = api_client.post("/api/v1/health/medications/", {}, format="json")
        assert response.status_code == 400

    def test_symptom_api_post_missing_fields_returns_400(self, api_client):
        # SymptomAPIView is POST-only
        response = api_client.post("/api/v1/health/symptoms/", {}, format="json")
        assert response.status_code == 400


# ── Finance API Views ──────────────────────────────────────────────────────────

class TestFinanceAPIViews:

    def test_finance_summary_api_requires_batch_id(self, api_client):
        # batch_id param is required → 400 without it
        response = api_client.get("/api/v1/finance/summary/")
        assert response.status_code == 400

    def test_finance_summary_api_returns_200_with_batch(self, api_client, test_batch):
        response = api_client.get(f"/api/v1/finance/summary/?batch_id={test_batch.pk}")
        assert response.status_code == 200

    def test_sales_api_returns_200(self, api_client):
        response = api_client.get("/api/v1/finance/sales/")
        assert response.status_code == 200

    def test_breakeven_api_returns_200(self, api_client, test_batch):
        response = api_client.get(f"/api/v1/finance/breakeven/{test_batch.pk}/")
        assert response.status_code == 200

    def test_expense_api_returns_200(self, api_client):
        response = api_client.get("/api/v1/expenses/")
        assert response.status_code == 200


# ── Analytics API Views ────────────────────────────────────────────────────────

class TestAnalyticsAPIViews:

    def test_alert_list_api_returns_200(self, api_client):
        response = api_client.get("/api/v1/analytics/alerts/")
        assert response.status_code == 200

    def test_forecast_api_returns_200(self, api_client, test_batch):
        response = api_client.get(f"/api/v1/analytics/forecast/{test_batch.pk}/")
        assert response.status_code == 200

    def test_theft_api_returns_200(self, api_client, test_batch):
        response = api_client.get(f"/api/v1/analytics/theft/{test_batch.pk}/")
        assert response.status_code == 200

    def test_sale_timing_api_returns_200(self, api_client, test_batch):
        response = api_client.get(f"/api/v1/analytics/sale-timing/{test_batch.pk}/")
        assert response.status_code == 200


# ── Billing Views ──────────────────────────────────────────────────────────────

class TestBillingViews:

    def test_billing_page_requires_login(self, client):
        response = client.get("/billing/")
        assert response.status_code in (301, 302)

    def test_billing_page_returns_200(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get("/billing/")
        assert response.status_code == 200

    def test_billing_api_returns_200(self, api_client):
        response = api_client.get("/api/v1/billing/summary/")
        assert response.status_code == 200

    def test_paystack_webhook_invalid_sig_returns_400(self, client):
        import json
        response = client.post(
            "/billing/webhook/paystack/",
            data=json.dumps({"event": "charge.success"}),
            content_type="application/json",
            HTTP_X_PAYSTACK_SIGNATURE="invalidsig",
        )
        assert response.status_code == 400

    def test_paystack_webhook_no_sig_returns_400(self, client):
        import json
        response = client.post(
            "/billing/webhook/paystack/",
            data=json.dumps({"event": "test"}),
            content_type="application/json",
        )
        assert response.status_code == 400
