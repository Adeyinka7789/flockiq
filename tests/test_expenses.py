"""
Phase 5 — Expenses app tests.
"""

import datetime
from decimal import Decimal

import pytest

pytestmark = pytest.mark.django_db


# ── Helpers ──────────────────────────────────────────────────────────────────────

def _make_org(subdomain):
    from apps.infrastructure.tenants.models import Organization
    return Organization.objects.create(name="Test Org", subdomain=subdomain)


def _make_user(org, email=None):
    from apps.infrastructure.accounts.models import CustomUser
    email = email or f"user_{org.subdomain}@example.com"
    return CustomUser.objects.create_user(email=email, password="testpass123", username=email, org=org)


def _make_farm(org):
    from apps.farm.farms.models import Farm
    farm = Farm(
        org=org, name="Test Farm", location="Lagos",
        latitude=Decimal("6.5244"), longitude=Decimal("3.3792"),
        farm_type="broiler",
    )
    farm.clean()
    farm.save()
    return farm


def _make_house(org, farm):
    from apps.farm.farms.models import House
    return House.objects.create(org=org, farm=farm, name="House A", capacity=5000, house_type="broiler")


def _make_batch(org, farm, house):
    from apps.farm.flocks.models import Batch
    return Batch.objects.create(
        org=org, farm=farm, house=house,
        batch_name="Test Batch",
        bird_type="broiler",
        placement_date=datetime.date.today() - datetime.timedelta(days=30),
        initial_count=5000,
        current_count=5000,
        status="active",
    )


def _make_expense(org, farm, batch=None, amount_kobo=104000000, category="feed"):
    from apps.infrastructure.core.rls import set_tenant_context
    from apps.finance.expenses.services import ExpenseService
    with set_tenant_context(org):
        return ExpenseService(org).record_expense(
            farm_id=str(farm.id),
            category=category,
            amount_kobo=amount_kobo,
            description="Test expense",
            batch_id=str(batch.id) if batch else None,
        )


# ── Tests ─────────────────────────────────────────────────────────────────────────

class TestExpenseRecord:

    def test_expense_created_in_kobo(self):
        org = _make_org("exp_kobo")
        farm = _make_farm(org)
        from apps.infrastructure.core.rls import set_tenant_context
        with set_tenant_context(org):
            expense = _make_expense(org, farm, amount_kobo=50000000)
        assert expense.amount_kobo == 50000000

    def test_amount_naira_property(self):
        org = _make_org("exp_naira")
        farm = _make_farm(org)
        from apps.infrastructure.core.rls import set_tenant_context
        with set_tenant_context(org):
            expense = _make_expense(org, farm, amount_kobo=100000)
        assert expense.amount_naira == 1000.0

    def test_expense_breakdown_by_category(self):
        org = _make_org("exp_breakdown")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house)
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.finance.expenses.services import ExpenseService
        with set_tenant_context(org):
            _make_expense(org, farm, batch, amount_kobo=50000000, category="feed")
            _make_expense(org, farm, batch, amount_kobo=20000000, category="medication")
            breakdown = ExpenseService(org).get_expense_breakdown(batch_id=str(batch.id))

        assert len(breakdown["labels"]) == 2
        assert breakdown["total_kobo"] == 70000000
        assert "Feed" in breakdown["labels"] or "feed" in [l.lower() for l in breakdown["labels"]]

    def test_total_cost_of_production(self):
        org = _make_org("exp_total")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        batch = _make_batch(org, farm, house)
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.finance.expenses.services import ExpenseService
        with set_tenant_context(org):
            _make_expense(org, farm, batch, amount_kobo=30000000)
            _make_expense(org, farm, batch, amount_kobo=20000000)
            total = ExpenseService(org).get_total_cost_of_production(str(batch.id))

        assert total == 50000000

    def test_expense_rls_isolation(self):
        org_a = _make_org("exp_rls_a")
        org_b = _make_org("exp_rls_b")
        farm_a = _make_farm(org_a)
        farm_b = _make_farm(org_b)
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.finance.expenses.models import ExpenseRecord
        with set_tenant_context(org_a):
            _make_expense(org_a, farm_a, amount_kobo=10000000)
        with set_tenant_context(org_b):
            _make_expense(org_b, farm_b, amount_kobo=10000000)

        with set_tenant_context(org_a):
            count = ExpenseRecord.objects.filter(org=org_a).count()
        assert count == 1

        with set_tenant_context(org_b):
            count_b = ExpenseRecord.objects.filter(org=org_b).count()
        assert count_b == 1

    def test_expense_with_no_batch_allowed(self):
        org = _make_org("exp_no_batch")
        farm = _make_farm(org)
        from apps.infrastructure.core.rls import set_tenant_context
        with set_tenant_context(org):
            expense = _make_expense(org, farm, batch=None, amount_kobo=5000000)
        assert expense.batch is None
        assert expense.amount_kobo == 5000000
