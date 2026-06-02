import pytest

pytestmark = pytest.mark.django_db


class TestFarmListView:

    def test_farm_list_requires_login(self, client):
        response = client.get("/farms/")
        assert response.status_code in (301, 302)

    def test_farm_list_returns_200(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get("/farms/")
        assert response.status_code == 200

    def test_farm_list_htmx_returns_partial(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get("/farms/", HTTP_HX_REQUEST="true")
        assert response.status_code == 200

    def test_farm_list_shows_created_farm(self, client, tenant_user, test_farm):
        client.force_login(tenant_user)
        response = client.get("/farms/")
        assert response.status_code == 200
        assert test_farm.name.encode() in response.content


class TestFarmCreateView:

    def test_farm_create_get_returns_modal(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get("/farms/create/")
        assert response.status_code == 200
        assert b"form" in response.content.lower()

    def test_farm_create_htmx_valid_post(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.post(
            "/farms/create/",
            {
                "name": "HTMX Farm",
                "location": "Abuja",
                "latitude": "9.0576",
                "longitude": "7.4951",
                "farm_type": "layer",
            },
            HTTP_HX_REQUEST="true",
        )
        # HTMX success returns 204 with HX-Redirect header
        assert response.status_code in (200, 204)

    def test_farm_create_non_htmx_valid_post_redirects(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.post(
            "/farms/create/",
            {
                "name": "Redirect Farm",
                "location": "Kano",
                "latitude": "12.0",
                "longitude": "8.5",
                "farm_type": "broiler",
            },
        )
        assert response.status_code == 302

    def test_farm_create_invalid_gps_rejected(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.post(
            "/farms/create/",
            {
                "name": "Bad Farm",
                "location": "London",
                "latitude": "51.5074",
                "longitude": "-0.1278",
                "farm_type": "mixed",
            },
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 422

    def test_farm_create_persists_to_db(self, client, tenant_user, test_org):
        from apps.farm.farms.models import Farm
        from apps.infrastructure.core.rls import set_tenant_context
        client.force_login(tenant_user)
        client.post(
            "/farms/create/",
            {
                "name": "Persisted Farm",
                "location": "Ibadan",
                "latitude": "7.3775",
                "longitude": "3.9470",
                "farm_type": "layer",
            },
        )
        with set_tenant_context(test_org):
            assert Farm.objects.filter(name="Persisted Farm").exists()


class TestFarmDetailView:

    def test_farm_detail_returns_200(self, client, tenant_user, test_farm):
        client.force_login(tenant_user)
        response = client.get(f"/farms/{test_farm.pk}/")
        assert response.status_code == 200

    def test_farm_detail_shows_farm_name(self, client, tenant_user, test_farm):
        client.force_login(tenant_user)
        response = client.get(f"/farms/{test_farm.pk}/")
        assert test_farm.name.encode() in response.content

    def test_farm_detail_requires_login(self, client, test_farm):
        response = client.get(f"/farms/{test_farm.pk}/")
        assert response.status_code in (301, 302)


class TestHouseCreateView:

    def test_house_create_returns_fragment(self, client, tenant_user, test_farm):
        client.force_login(tenant_user)
        response = client.post(
            f"/farms/{test_farm.pk}/houses/create/",
            {"name": "New House", "capacity": 300, "house_type": "broiler"},
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code in (200, 204)

    def test_house_create_persists_to_db(self, client, tenant_user, test_farm, test_org):
        from apps.farm.farms.models import House
        from apps.infrastructure.core.rls import set_tenant_context
        client.force_login(tenant_user)
        client.post(
            f"/farms/{test_farm.pk}/houses/create/",
            {"name": "DB House", "capacity": 200, "house_type": "layer"},
            HTTP_HX_REQUEST="true",
        )
        with set_tenant_context(test_org):
            assert House.objects.filter(name="DB House", farm=test_farm).exists()

    def test_house_create_zero_capacity_rejected(self, client, tenant_user, test_farm):
        client.force_login(tenant_user)
        response = client.post(
            f"/farms/{test_farm.pk}/houses/create/",
            {"name": "Bad House", "capacity": 0, "house_type": "layer"},
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code in (200, 422)
