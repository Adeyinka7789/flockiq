"""
Phase 5 — Finance app tests (SalesRecord, BatchFinancialSummary, P&L, break-even, ROI).
"""

import datetime
from decimal import Decimal

import pytest

pytestmark = pytest.mark.django_db


# ── Helpers ──────────────────────────────────────────────────────────────────────

def _make_org(subdomain):
    from apps.infrastructure.tenants.models import Organization
    return Organization.objects.create(name="Finance Org", subdomain=subdomain)


def _make_user(org, email=None):
    from apps.infrastructure.accounts.models import CustomUser
    email = email or f"user_{org.subdomain}@example.com"
    return CustomUser.objects.create_user(email=email, password="testpass123", username=email, org=org)


def _make_farm(org):
    from apps.farm.farms.models import Farm
    from apps.infrastructure.core.rls import set_tenant_context
    farm = Farm(
        org=org, name="Finance Farm", location="Lagos",
        latitude=Decimal("6.5244"), longitude=Decimal("3.3792"),
        farm_type="broiler",
    )
    farm.clean()
    with set_tenant_context(org):
        farm.save()
    return farm


def _make_house(org, farm):
    from apps.farm.farms.models import House
    from apps.infrastructure.core.rls import set_tenant_context
    with set_tenant_context(org):
        return House.objects.create(org=org, farm=farm, name="House A", capacity=5000, house_type="broiler")


def _make_batch(org, farm, house, count=5000):
    from apps.farm.flocks.models import Batch
    from apps.infrastructure.core.rls import set_tenant_context
    with set_tenant_context(org):
        return Batch.objects.create(
            org=org, farm=farm, house=house,
            batch_name="Finance Batch",
            bird_type="broiler",
            placement_date=datetime.date.today() - datetime.timedelta(days=40),
            initial_count=count,
            current_count=count,
            status="active",
        )


def _record_expense(org, farm, batch, amount_kobo, category="feed"):
    from apps.finance.expenses.services import ExpenseService
    return ExpenseService(org).record_expense(
        farm_id=str(farm.id),
        category=category,
        amount_kobo=amount_kobo,
        description="Test expense",
        batch_id=str(batch.id),
    )


def _record_sale(org, batch, product_type="live_birds", quantity=4000, unit_price_kobo=350000):
    from apps.finance.finance.services import FinanceService
    return FinanceService(org).record_sale(
        batch_id=str(batch.id),
        sale_date=datetime.date.today(),
        product_type=product_type,
        quantity=quantity,
        unit="birds",
        unit_price_kobo=unit_price_kobo,
        buyer_name="Test Buyer",
    )


# ── Tests ─────────────────────────────────────────────────────────────────────────

class TestSalesRecord:

    def test_sale_revenue_auto_calculated(self):
        org = _make_org("fin_auto_rev")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house)
        from apps.infrastructure.core.rls import set_tenant_context
        with set_tenant_context(org):
            record = _record_sale(org, batch, quantity=100, unit_price_kobo=300000)

        assert record.total_revenue_kobo == 100 * 300000

    def test_sales_record_auditlog_registered(self):
        from auditlog.registry import auditlog
        from apps.finance.finance.models import SalesRecord
        assert SalesRecord in auditlog.get_models()

    def test_sale_total_revenue_naira_property(self):
        org = _make_org("fin_naira_prop")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house)
        from apps.infrastructure.core.rls import set_tenant_context
        with set_tenant_context(org):
            record = _record_sale(org, batch, quantity=10, unit_price_kobo=100000)
        assert record.total_revenue_naira == 10000.0


class TestBatchFinancialSummary:

    def test_financial_summary_updated_on_sale(self):
        org = _make_org("fin_summ_sale")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house)
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.finance.finance.models import BatchFinancialSummary
        with set_tenant_context(org):
            _record_sale(org, batch, quantity=1000, unit_price_kobo=350000)
            summary = BatchFinancialSummary.objects.filter(batch=batch, org=org).first()

        assert summary is not None
        assert summary.total_revenue_kobo == 1000 * 350000

    def test_financial_summary_updated_on_expense(self):
        org = _make_org("fin_summ_exp")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house)
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.finance.finance.models import BatchFinancialSummary
        with set_tenant_context(org):
            _record_sale(org, batch, quantity=1000, unit_price_kobo=350000)
            _record_expense(org, farm, batch, amount_kobo=100000000)
            summary = BatchFinancialSummary.objects.filter(batch=batch, org=org).first()

        assert summary.total_expenses_kobo == 100000000

    def test_financial_summary_rls_isolation(self):
        org_a = _make_org("fin_rls_a")
        org_b = _make_org("fin_rls_b")
        farm_a = _make_farm(org_a)
        farm_b = _make_farm(org_b)
        house_a = _make_house(org_a, farm_a)
        house_b = _make_house(org_b, farm_b)
        batch_a = _make_batch(org_a, farm_a, house_a)
        batch_b = _make_batch(org_b, farm_b, house_b)
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.finance.finance.models import BatchFinancialSummary
        with set_tenant_context(org_a):
            _record_sale(org_a, batch_a)
        with set_tenant_context(org_b):
            _record_sale(org_b, batch_b)

        with set_tenant_context(org_a):
            count = BatchFinancialSummary.objects.filter(org=org_a).count()
        assert count == 1


class TestPLSummary:

    def test_pl_summary_returns_profit(self):
        org = _make_org("fin_pl_profit")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house, count=5000)
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.finance.finance.services import FinanceService
        with set_tenant_context(org):
            _record_expense(org, farm, batch, amount_kobo=100000000)
            _record_sale(org, batch, quantity=4500, unit_price_kobo=350000)
            summary = FinanceService(org).get_pl_summary(str(batch.id))

        assert summary["gross_profit_naira"] > 0
        assert summary["profit_margin_pct"] > 0
        assert summary["total_revenue_naira"] > summary["total_expenses_naira"]

    def test_pl_summary_returns_loss_correctly(self):
        org = _make_org("fin_pl_loss")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house, count=5000)
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.finance.finance.services import FinanceService
        with set_tenant_context(org):
            _record_expense(org, farm, batch, amount_kobo=200000000)
            _record_sale(org, batch, quantity=100, unit_price_kobo=10000)
            summary = FinanceService(org).get_pl_summary(str(batch.id))

        assert summary["gross_profit_naira"] < 0
        assert summary["profit_margin_pct"] < 0


class TestBreakEven:

    def test_break_even_calculation(self):
        org = _make_org("fin_be")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house, count=5000)
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.finance.finance.services import FinanceService
        with set_tenant_context(org):
            _record_expense(org, farm, batch, amount_kobo=150000000)
            _record_sale(org, batch, quantity=100, unit_price_kobo=350000)
            result = FinanceService(org).calculate_break_even(str(batch.id))

        assert result["total_expenses_kobo"] == 150000000
        assert result["break_even_quantity"] > 0
        assert result["avg_unit_price_kobo"] == 350000


class TestROI:

    def test_roi_calculation(self):
        org = _make_org("fin_roi")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house, count=5000)
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.finance.finance.services import FinanceService
        with set_tenant_context(org):
            _record_expense(org, farm, batch, amount_kobo=100000000)
            _record_sale(org, batch, quantity=4500, unit_price_kobo=350000)
            pl = FinanceService(org).get_pl_summary(str(batch.id))

        assert "roi_pct" in pl
        assert isinstance(pl["roi_pct"], float)

    def test_roi_calculator_data_has_scenarios(self):
        org = _make_org("fin_roi_scen")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house, count=5000)
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.finance.finance.services import FinanceService
        with set_tenant_context(org):
            _record_expense(org, farm, batch, amount_kobo=100000000)
            data = FinanceService(org).get_roi_calculator_data(str(batch.id))

        assert "scenarios" in data
        assert len(data["scenarios"]) == 5
        for scenario in data["scenarios"]:
            assert "roi_pct" in scenario
            assert "price_per_unit_naira" in scenario
