import pytest
from datetime import date

pytestmark = pytest.mark.django_db


class TestVaccinationCalendarView:

    def test_calendar_requires_login(self, client):
        response = client.get("/health/vaccinations/")
        assert response.status_code in (301, 302)

    def test_calendar_returns_200(self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        response = client.get("/health/vaccinations/")
        assert response.status_code == 200

    def test_calendar_days_ahead_param(self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        response = client.get("/health/vaccinations/?days_ahead=14")
        assert response.status_code == 200


class TestVaccinationCompleteView:

    def test_vaccination_complete_post(self, client, tenant_user, test_batch, test_org):
        from apps.health.health.models import VaccinationSchedule
        from apps.infrastructure.core.rls import set_tenant_context
        client.force_login(tenant_user)
        with set_tenant_context(test_org):
            vacc = VaccinationSchedule.objects.filter(
                batch=test_batch, status="scheduled"
            ).first()
        if vacc is None:
            pytest.skip("No scheduled vaccination available")
        response = client.post(
            f"/health/vaccinations/{vacc.pk}/complete/",
            {"notes": "Administered on time"},
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200

    def test_vaccination_complete_returns_hx_trigger(self, client, tenant_user, test_batch, test_org):
        from apps.health.health.models import VaccinationSchedule
        from apps.infrastructure.core.rls import set_tenant_context
        client.force_login(tenant_user)
        with set_tenant_context(test_org):
            vacc = VaccinationSchedule.objects.filter(
                batch=test_batch, status="scheduled"
            ).first()
        if vacc is None:
            pytest.skip("No scheduled vaccination available")
        response = client.post(
            f"/health/vaccinations/{vacc.pk}/complete/",
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        assert "HX-Trigger" in response.headers


class TestMedicationLogView:

    def test_medication_log_get_returns_200(self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        response = client.get(f"/health/medications/{test_batch.pk}/log/")
        assert response.status_code == 200

    def test_medication_log_post_valid(self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        response = client.post(
            f"/health/medications/{test_batch.pk}/log/",
            {
                "drug_name": "Tetracycline",
                "drug_type": "antibiotic",
                "start_date": date.today().isoformat(),
                "duration_days": 5,
                "withdrawal_period_days": 7,
                "dosage": "1ml per litre",
                "quantity_used": "500",
                "unit": "ml",
            },
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code in (200, 201)

    def test_medication_log_post_missing_fields_shows_error(self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        response = client.post(
            f"/health/medications/{test_batch.pk}/log/",
            {},
            HTTP_HX_REQUEST="true",
        )
        # View renders the form with an error message, not 422
        assert response.status_code == 200
        assert b"required" in response.content.lower()

    def test_medication_list_returns_200(self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        response = client.get(f"/health/medications/{test_batch.pk}/list/")
        assert response.status_code == 200


class TestSymptomLogView:

    def test_symptom_log_get_returns_200(self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        response = client.get(f"/health/symptoms/{test_batch.pk}/log/")
        assert response.status_code == 200

    def test_symptom_log_post_valid(self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        response = client.post(
            f"/health/symptoms/{test_batch.pk}/log/",
            {
                "affected_count": 5,
                "symptoms": ["lethargy", "reduced_feed"],
                "severity": "mild",
                "notes": "Observed morning",
            },
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code in (200, 201)

    def test_symptom_log_post_missing_count_shows_error(self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        response = client.post(
            f"/health/symptoms/{test_batch.pk}/log/",
            {},
            HTTP_HX_REQUEST="true",
        )
        # View renders form with error, not 422
        assert response.status_code == 200
        assert b"required" in response.content.lower()


class TestHealthSummaryView:

    def test_health_summary_returns_200(self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        response = client.get(f"/health/summary/{test_batch.pk}/")
        assert response.status_code == 200


class TestOutbreakAlertView:

    def test_outbreaks_requires_login(self, client):
        response = client.get("/health/outbreaks/")
        assert response.status_code in (301, 302)

    def test_outbreaks_returns_200(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get("/health/outbreaks/")
        assert response.status_code == 200
