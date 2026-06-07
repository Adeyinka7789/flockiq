import pytest
from datetime import date

pytestmark = pytest.mark.django_db


class TestPLSummaryView:

    def test_pl_summary_requires_login(self, client, test_batch):
        response = client.get(f"/finance/pl/{test_batch.pk}/")
        assert response.status_code in (301, 302)

    def test_pl_summary_returns_200(self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        response = client.get(f"/finance/pl/{test_batch.pk}/")
        assert response.status_code == 200


class TestSaleLogView:

    def test_sale_log_get_returns_form(self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        response = client.get(f"/finance/sales/{test_batch.pk}/log/")
        assert response.status_code == 200

    def test_sale_log_post_missing_fields_returns_422(self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        response = client.post(
            f"/finance/sales/{test_batch.pk}/log/",
            {},
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 422

    def test_sale_log_post_invalid_amount_returns_422(self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        response = client.post(
            f"/finance/sales/{test_batch.pk}/log/",
            {"product_type": "eggs", "quantity": "abc", "unit": "crates", "unit_price": "bad"},
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 422

    def test_sale_log_post_valid(self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        response = client.post(
            f"/finance/sales/{test_batch.pk}/log/",
            {
                "product_type": "eggs",
                "quantity": "10",
                "unit": "crates",
                "unit_price": "1500",
                "sale_date": date.today().isoformat(),
                "buyer_name": "Market",
            },
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code in (200, 201)


class TestSaleTableView:

    def test_sale_table_returns_200(self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        response = client.get(f"/finance/sales/{test_batch.pk}/table/")
        assert response.status_code == 200


class TestBreakEvenView:

    def test_breakeven_returns_200(self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        response = client.get(f"/finance/breakeven/{test_batch.pk}/")
        assert response.status_code == 200


class TestROICalculatorView:

    def test_roi_returns_200(self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        response = client.get(f"/finance/roi/{test_batch.pk}/")
        assert response.status_code == 200


class TestExpenseLogView:

    def test_expense_log_missing_fields_returns_422(self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        response = client.post(
            f"/finance/expenses/{test_batch.pk}/log/",
            {},
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 422

    def test_expense_log_invalid_amount_returns_422(self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        response = client.post(
            f"/finance/expenses/{test_batch.pk}/log/",
            {"category": "feed", "amount": "notanumber", "description": "Feed purchase"},
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 422

    def test_expense_log_valid_post(self, client, tenant_user, test_batch, test_farm):
        client.force_login(tenant_user)
        response = client.post(
            f"/finance/expenses/{test_batch.pk}/log/",
            {
                "category": "feed",
                "amount": "5000",
                "description": "Feed purchase",
                "expense_date": date.today().isoformat(),
                "farm_id": str(test_farm.pk),
            },
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code in (200, 201)


class TestExpenseTableView:

    def test_expense_table_returns_200(self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        response = client.get(f"/finance/expenses/{test_batch.pk}/table/")
        assert response.status_code == 200


class TestExpenseBreakdownView:

    def test_expense_breakdown_returns_200(self, client, tenant_user, test_batch):
        client.force_login(tenant_user)
        response = client.get(f"/finance/expenses/{test_batch.pk}/breakdown/")
        assert response.status_code == 200


class TestExpenseFarmSummaryView:

    def test_expense_farm_summary_returns_200(self, client, tenant_user, test_farm):
        client.force_login(tenant_user)
        response = client.get(f"/finance/expenses/farm/{test_farm.pk}/summary/")
        assert response.status_code == 200
