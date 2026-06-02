"""
Additional flock view tests targeting weight recording, farm summary card,
and HTMX-specific response paths not covered in test_views_flocks.py.
"""
import pytest
from datetime import date

pytestmark = pytest.mark.django_db


@pytest.fixture
def broiler_batch(db, test_org, test_farm):
    from apps.farm.farms.models import House
    from apps.farm.flocks.models import Batch
    from apps.infrastructure.core.rls import set_tenant_context
    with set_tenant_context(test_org):
        house = House.objects.create(
            org=test_org, farm=test_farm,
            name="Broiler House", capacity=1000, house_type="broiler",
        )
        return Batch.objects.create(
            org=test_org, farm=test_farm, house=house,
            batch_name="Broiler Batch", bird_type="broiler",
            placement_date=date.today(), initial_count=500, current_count=500,
            status="active",
        )


class TestWeightRecordView:

    def test_weight_record_requires_login(self, client, test_batch):
        response = client.post(f"/batches/{test_batch.pk}/weight/")
        assert response.status_code in (301, 302)

    def test_weight_record_layer_batch_rejected(self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        response = client.post(
            f"/batches/{test_batch.pk}/weight/",
            {"sample_size": 10, "avg_weight_kg": "1.8", "sample_date": date.today().isoformat()},
            HTTP_HX_REQUEST="true",
        )
        # Layer batch raises ValueError → 422
        assert response.status_code == 422

    def test_weight_record_invalid_form_returns_422(self, client, tenant_user, broiler_batch):
        client.force_login(tenant_user)
        response = client.post(
            f"/batches/{broiler_batch.pk}/weight/",
            {},
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 422

    def test_weight_record_valid_broiler_post(self, client, tenant_user, broiler_batch):
        client.force_login(tenant_user)
        response = client.post(
            f"/batches/{broiler_batch.pk}/weight/",
            {
                "sample_size": 10,
                "avg_weight_kg": "1.800",
                "sample_date": date.today().isoformat(),
                "notes": "Normal growth",
            },
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        assert "HX-Trigger" in response.headers

    def test_weight_record_with_min_max(self, client, tenant_user, broiler_batch):
        client.force_login(tenant_user)
        response = client.post(
            f"/batches/{broiler_batch.pk}/weight/",
            {
                "sample_size": 20,
                "avg_weight_kg": "2.100",
                "min_weight_kg": "1.900",
                "max_weight_kg": "2.300",
                "sample_date": date.today().isoformat(),
            },
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200


class TestFarmSummaryCard:

    def test_summary_card_returns_200(self, client, tenant_user, test_farm):
        client.force_login(tenant_user)
        response = client.get(f"/farms/{test_farm.pk}/summary-card/")
        assert response.status_code == 200

    def test_summary_card_requires_login(self, client, test_farm):
        response = client.get(f"/farms/{test_farm.pk}/summary-card/")
        assert response.status_code in (301, 302)


class TestMortalityRecentViewExtra:

    def test_mortality_recent_with_logs(self, client, tenant_user, test_batch, test_org, test_farm):
        from apps.farm.flocks.models import MortalityLog
        from apps.infrastructure.core.rls import set_tenant_context
        client.force_login(tenant_user)
        with set_tenant_context(test_org):
            MortalityLog.objects.create(
                org=test_org,
                batch=test_batch,
                farm=test_farm,
                count=3,
                cause="disease",
                date=date.today(),
            )
        response = client.get(f"/batches/{test_batch.pk}/mortality/recent/")
        assert response.status_code == 200


class TestBatchCreateViewExtra:

    def test_batch_create_get_with_house_preselected(self, client, tenant_user, test_farm, test_house):
        client.force_login(tenant_user)
        response = client.get(
            f"/farms/{test_farm.pk}/batches/create/?house={test_house.pk}"
        )
        assert response.status_code == 200

    def test_batch_create_non_htmx_success_redirects(self, client, tenant_user, test_farm, test_house):
        client.force_login(tenant_user)
        response = client.post(
            f"/farms/{test_farm.pk}/batches/create/",
            {
                "batch_name": "Non-HTMX Batch",
                "bird_type": "layer",
                "house_id": str(test_house.pk),
                "placement_date": date.today().isoformat(),
                "initial_count": 50,
            },
        )
        assert response.status_code in (302, 204)
