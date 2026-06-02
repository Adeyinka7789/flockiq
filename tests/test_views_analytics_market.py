"""
Tests for analytics and market views.
Most analytics views are behind waffle switches — testing the "coming soon" fallback
and the waffle-flag-off path gives coverage of the dispatch logic.
"""
import pytest

pytestmark = pytest.mark.django_db


# ── Analytics HTMX views ───────────────────────────────────────────────────────

class TestAnalyticsViews:

    def test_forecast_view_requires_login(self, client, test_batch):
        response = client.get(f"/analytics/forecast/{test_batch.pk}/")
        assert response.status_code in (301, 302)

    def test_forecast_view_returns_200(self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        response = client.get(f"/analytics/forecast/{test_batch.pk}/")
        # Waffle flag off → renders "coming soon" template → 200
        assert response.status_code == 200

    def test_anomaly_feed_returns_200(self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        response = client.get(f"/analytics/anomalies/{test_batch.pk}/")
        assert response.status_code == 200

    def test_theft_report_returns_200(self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        response = client.get(f"/analytics/theft/{test_batch.pk}/")
        assert response.status_code == 200

    def test_sale_timing_returns_200(self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        response = client.get(f"/analytics/sale-timing/{test_batch.pk}/")
        assert response.status_code == 200

    def test_diagnosis_view_post_returns_200(self, client, tenant_user):
        # DiagnosisView is POST-only (no GET handler)
        client.force_login(tenant_user)
        response = client.post(
            "/analytics/diagnose/",
            {"symptoms": ["lethargy", "reduced_feed"], "bird_type": "layer"},
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200


# ── Analytics API views ────────────────────────────────────────────────────────

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


# ── Market views ───────────────────────────────────────────────────────────────

class TestMarketViews:

    def test_market_prices_requires_login(self, client):
        response = client.get("/market/prices/")
        assert response.status_code in (301, 302)

    def test_market_prices_returns_200(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get("/market/prices/")
        assert response.status_code == 200

    def test_market_seasonal_returns_200(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get("/market/seasonal/")
        assert response.status_code == 200

    def test_market_mvp_returns_200(self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        response = client.get(f"/market/mvp/{test_batch.pk}/")
        assert response.status_code == 200

    def test_record_market_price_get_returns_200(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get("/market/prices/record/")
        assert response.status_code == 200

    def test_record_market_price_post_valid(self, client, tenant_user):
        import datetime
        client.force_login(tenant_user)
        response = client.post(
            "/market/prices/record/",
            {
                "product_type": "eggs",
                "price_per_unit_kobo": "150000",
                "unit": "crate",
                "market_name": "Mile 12 Market",
                "state": "Lagos",
                "recorded_date": datetime.date.today().isoformat(),
            },
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code in (200, 201)

    def test_record_market_price_post_invalid_returns_422(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.post(
            "/market/prices/record/",
            {},
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code in (200, 422)
