import pytest
from datetime import date

pytestmark = pytest.mark.django_db


class TestBatchListView:

    def test_batch_list_requires_login(self, client):
        response = client.get("/batches/")
        assert response.status_code in (301, 302)

    def test_batch_list_returns_200(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get("/batches/")
        assert response.status_code == 200

    def test_batch_list_htmx_returns_partial(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get("/batches/", HTTP_HX_REQUEST="true")
        assert response.status_code == 200

    def test_batch_list_shows_existing_batch(self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        response = client.get("/batches/")
        assert response.status_code == 200
        assert test_batch.batch_name.encode() in response.content


class TestBatchDetailView:

    def test_batch_detail_requires_login(self, client, test_batch):
        response = client.get(f"/batches/{test_batch.pk}/")
        assert response.status_code in (301, 302)

    def test_batch_detail_returns_200(self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        response = client.get(f"/batches/{test_batch.pk}/")
        assert response.status_code == 200

    def test_batch_detail_has_tabs(self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        response = client.get(f"/batches/{test_batch.pk}/")
        content = response.content.decode()
        assert "overview" in content.lower()
        assert "health" in content.lower()
        assert "finance" in content.lower()

    def test_batch_detail_shows_batch_name(self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        response = client.get(f"/batches/{test_batch.pk}/")
        assert test_batch.batch_name.encode() in response.content


class TestMortalityLogView:

    def test_mortality_get_returns_modal(self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        response = client.get(f"/batches/{test_batch.pk}/mortality/")
        assert response.status_code == 200

    def test_mortality_log_htmx_post(self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        response = client.post(
            f"/batches/{test_batch.pk}/mortality/",
            {"count": 2, "cause": "disease", "date": date.today().isoformat()},
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        assert len(response.content) > 0

    def test_mortality_decrements_batch_count(self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        initial = test_batch.current_count
        client.post(
            f"/batches/{test_batch.pk}/mortality/",
            {"count": 5, "cause": "disease", "date": date.today().isoformat()},
            HTTP_HX_REQUEST="true",
        )
        test_batch.refresh_from_db()
        assert test_batch.current_count == initial - 5

    def test_mortality_exceeds_count_returns_422(self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        response = client.post(
            f"/batches/{test_batch.pk}/mortality/",
            {"count": 9999, "cause": "disease", "date": date.today().isoformat()},
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 422

    def test_mortality_invalid_form_returns_422(self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        response = client.post(
            f"/batches/{test_batch.pk}/mortality/",
            {"count": "", "cause": "", "date": ""},
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 422


class TestMortalityRecentView:

    def test_mortality_recent_returns_200(self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        response = client.get(f"/batches/{test_batch.pk}/mortality/recent/")
        assert response.status_code == 200


class TestBatchMetricsCardView:

    def test_batch_metrics_card_returns_200(self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        response = client.get(f"/batches/{test_batch.pk}/metrics/")
        assert response.status_code == 200


class TestBatchCloseView:

    def test_batch_close_get_returns_modal(self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        response = client.get(f"/batches/{test_batch.pk}/close/")
        assert response.status_code == 200

    def test_batch_close_htmx_post(self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        response = client.post(
            f"/batches/{test_batch.pk}/close/",
            {"notes": "End of cycle"},
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        test_batch.refresh_from_db()
        assert test_batch.status == "closed"


class TestBatchCreateView:

    def test_batch_create_get_returns_modal(self, client, tenant_user, test_farm):
        client.force_login(tenant_user)
        response = client.get(f"/farms/{test_farm.pk}/batches/create/")
        assert response.status_code == 200

    def test_batch_create_htmx_valid_post(self, client, tenant_user, test_farm, test_house):
        client.force_login(tenant_user)
        response = client.post(
            f"/farms/{test_farm.pk}/batches/create/",
            {
                "batch_name": "New Batch",
                "bird_type": "broiler",
                "house_id": str(test_house.pk),
                "placement_date": date.today().isoformat(),
                "initial_count": 100,
            },
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code in (200, 204)

    def test_batch_create_invalid_form_returns_422(self, client, tenant_user, test_farm):
        client.force_login(tenant_user)
        response = client.post(
            f"/farms/{test_farm.pk}/batches/create/",
            {"batch_name": "", "bird_type": "", "house_id": "", "placement_date": "", "initial_count": ""},
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 422
