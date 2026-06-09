"""
Tests for Farm Credit Score — CreditScoringService, model, views, PDF.
"""

import datetime
from decimal import Decimal

import pytest

from django.utils import timezone

pytestmark = pytest.mark.django_db


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_org(subdomain="credittest"):
    from apps.infrastructure.tenants.models import Organization
    return Organization.objects.create(
        name="Credit Test Farm",
        subdomain=subdomain,
        plan_tier="monthly",
        subscription_status="active",
        is_active=True,
        onboarding_complete=True,
    )


def _make_farm(org):
    from apps.farm.farms.models import Farm
    from apps.infrastructure.core.rls import set_tenant_context
    farm = Farm(
        org=org, name="Credit Farm", location="Lagos",
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
        return House.objects.create(
            org=org, farm=farm, name="House A", capacity=5000, house_type="broiler"
        )


def _make_closed_batch(org, farm, house, offset_days=40, n_batches=1):
    """Create n closed batches, returning a list."""
    from apps.farm.flocks.models import Batch
    from apps.infrastructure.core.rls import set_tenant_context
    batches = []
    for i in range(n_batches):
        with set_tenant_context(org):
            b = Batch.objects.create(
                org=org, farm=farm, house=house,
                batch_name=f"Closed Batch {i}",
                bird_type="broiler",
                placement_date=datetime.date.today() - datetime.timedelta(days=offset_days + i),
                initial_count=1000,
                current_count=960,
                status="closed",
                closed_at=timezone.now() - datetime.timedelta(days=i),
            )
        batches.append(b)
    return batches


# ── compute() returns None for 0 closed batches ───────────────────────────────

def test_compute_returns_none_for_no_closed_batches():
    from apps.infrastructure.core.credit_scoring import CreditScoringService
    from apps.infrastructure.core.rls import set_tenant_context

    org = _make_org("noclosed")
    with set_tenant_context(org):
        result = CreditScoringService(org).compute()
    assert result is None


# ── compute() returns score for 1 closed batch (early confidence) ─────────────

def test_compute_returns_early_confidence_for_one_batch():
    from apps.infrastructure.core.credit_scoring import CreditScoringService
    from apps.infrastructure.core.rls import set_tenant_context

    org = _make_org("onebatch")
    farm = _make_farm(org)
    house = _make_house(org, farm)
    _make_closed_batch(org, farm, house)

    with set_tenant_context(org):
        cs = CreditScoringService(org).compute()

    assert cs is not None
    assert cs.confidence == "early"
    assert 0 <= cs.score <= 100


# ── established confidence for 6+ batches ────────────────────────────────────

def test_compute_returns_established_confidence_for_six_batches():
    from apps.infrastructure.core.credit_scoring import CreditScoringService
    from apps.infrastructure.core.rls import set_tenant_context

    org = _make_org("sixbatches")
    farm = _make_farm(org)

    for i in range(6):
        from apps.farm.farms.models import House
        with set_tenant_context(org):
            house = House.objects.create(
                org=org, farm=farm, name=f"H{i}", capacity=5000, house_type="broiler"
            )
        _make_closed_batch(org, farm, house, offset_days=50 + i * 2)

    with set_tenant_context(org):
        cs = CreditScoringService(org).compute()

    assert cs.confidence == "established"


# ── financial health score uses BatchFinancialSummary ────────────────────────

def test_financial_health_score_uses_batch_financial_summary():
    from apps.finance.finance.models import BatchFinancialSummary
    from apps.infrastructure.core.credit_scoring import CreditScoringService
    from apps.infrastructure.core.rls import set_tenant_context

    org = _make_org("financial")
    farm = _make_farm(org)
    house = _make_house(org, farm)
    (batch,) = _make_closed_batch(org, farm, house)

    with set_tenant_context(org):
        BatchFinancialSummary.objects.create(
            org=org,
            batch=batch,
            total_revenue_kobo=1_000_000,
            total_expenses_kobo=700_000,
            gross_profit_kobo=300_000,
            profit_margin_pct=Decimal("30.00"),
        )
        svc = CreditScoringService(org)
        score = svc._score_financial_health([batch])

    assert score == 100


# ── mortality score: <2% = 100, 2-5% = 80, >15% = 20 ────────────────────────

def test_mortality_score_low():
    from apps.farm.flocks.models import Batch, MortalityLog
    from apps.infrastructure.core.credit_scoring import CreditScoringService
    from apps.infrastructure.core.rls import set_tenant_context

    org = _make_org("mort-low")
    farm = _make_farm(org)
    house = _make_house(org, farm)

    with set_tenant_context(org):
        batch = Batch.objects.create(
            org=org, farm=farm, house=house,
            batch_name="Mort Low",
            bird_type="broiler",
            placement_date=datetime.date.today() - datetime.timedelta(days=40),
            initial_count=1000,
            current_count=990,
            status="active",
        )
        MortalityLog.objects.create(
            org=org, batch=batch, farm=farm,
            date=datetime.date.today(), count=10, cause="unknown",
        )
        batch.status = "closed"
        batch.closed_at = timezone.now()
        batch.save()
        score = CreditScoringService(org)._score_mortality_management([batch])

    assert score == 100  # 10/1000 = 1% < 2%


def test_mortality_score_high():
    from apps.farm.flocks.models import Batch, MortalityLog
    from apps.infrastructure.core.credit_scoring import CreditScoringService
    from apps.infrastructure.core.rls import set_tenant_context

    org = _make_org("mort-high")
    farm = _make_farm(org)
    house = _make_house(org, farm)

    with set_tenant_context(org):
        batch = Batch.objects.create(
            org=org, farm=farm, house=house,
            batch_name="Mort High",
            bird_type="broiler",
            placement_date=datetime.date.today() - datetime.timedelta(days=40),
            initial_count=1000,
            current_count=800,
            status="active",
        )
        MortalityLog.objects.create(
            org=org, batch=batch, farm=farm,
            date=datetime.date.today(), count=200, cause="disease",
        )
        batch.status = "closed"
        batch.closed_at = timezone.now()
        batch.save()
        score = CreditScoringService(org)._score_mortality_management([batch])

    assert score == 20  # 200/1000 = 20% > 15%


# ── grade A+ for score >= 90 ──────────────────────────────────────────────────

def test_score_to_grade():
    from apps.infrastructure.core.credit_scoring import CreditScoringService

    assert CreditScoringService._score_to_grade(95) == "A+"
    assert CreditScoringService._score_to_grade(85) == "A"
    assert CreditScoringService._score_to_grade(75) == "B"
    assert CreditScoringService._score_to_grade(65) == "C"
    assert CreditScoringService._score_to_grade(55) == "D"
    assert CreditScoringService._score_to_grade(30) == "F"


# ── score recomputed after batch close ───────────────────────────────────────

def test_score_recomputed_on_batch_close():
    from apps.farm.flocks.models import Batch
    from apps.farm.flocks.services import BatchService
    from apps.finance.finance.models import FarmCreditScore
    from apps.infrastructure.core.rls import set_tenant_context

    org = _make_org("batchclose")
    farm = _make_farm(org)
    house = _make_house(org, farm)

    with set_tenant_context(org):
        batch = Batch.objects.create(
            org=org, farm=farm, house=house,
            batch_name="Close Me",
            bird_type="broiler",
            placement_date=datetime.date.today() - datetime.timedelta(days=40),
            initial_count=500,
            current_count=480,
            status="active",
        )

    before_count = FarmCreditScore.objects.filter(org=org).count()
    assert before_count == 0

    with set_tenant_context(org):
        BatchService(org).close_batch(str(batch.id), notes="Test close")

    with set_tenant_context(org):
        assert FarmCreditScore.objects.filter(org=org).count() >= 1


# ── PDF view returns application/pdf content type ────────────────────────────

def test_credit_score_pdf_view(client):
    import uuid
    from apps.infrastructure.accounts.models import CustomUser
    from apps.infrastructure.core.credit_scoring import CreditScoringService
    from apps.infrastructure.core.rls import set_tenant_context

    org = _make_org(f"pdftest-{uuid.uuid4().hex[:6]}")
    farm = _make_farm(org)
    house = _make_house(org, farm)
    _make_closed_batch(org, farm, house)

    with set_tenant_context(org):
        CreditScoringService(org).compute()

    user = CustomUser.objects.create_user(
        username=f"pdfuser-{org.subdomain}",
        email=f"pdf@{org.subdomain}.com",
        password="testpass123",
        org=org,
        role="owner",
        email_verified=True,
    )
    client.force_login(user)
    response = client.get("/finance/credit-score/pdf/")
    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"


# ── dashboard shows credit score card when available ─────────────────────────

def test_dashboard_shows_credit_score_when_available(client):
    import uuid
    from apps.infrastructure.accounts.models import CustomUser
    from apps.infrastructure.core.credit_scoring import CreditScoringService
    from apps.infrastructure.core.rls import set_tenant_context

    org = _make_org(f"dashscore-{uuid.uuid4().hex[:6]}")
    org.onboarding_complete = True
    org.save()

    farm = _make_farm(org)
    house = _make_house(org, farm)
    _make_closed_batch(org, farm, house)

    with set_tenant_context(org):
        CreditScoringService(org).compute()

    user = CustomUser.objects.create_user(
        username=f"dashuser-{org.subdomain}",
        email=f"dash@{org.subdomain}.com",
        password="testpass123",
        org=org,
        role="owner",
        email_verified=True,
    )
    client.force_login(user)

    # Create a minimal active batch so onboarding check passes
    from apps.farm.flocks.models import Batch
    with set_tenant_context(org):
        Batch.objects.create(
            org=org, farm=farm, house=house,
            batch_name="Active",
            bird_type="broiler",
            placement_date=datetime.date.today() - datetime.timedelta(days=5),
            initial_count=100,
            current_count=100,
            status="active",
        )

    response = client.get("/billing/")
    assert response.status_code == 200
    assert b"Farm Credit Score" in response.content


# ── score history on detail page ─────────────────────────────────────────────

def test_credit_score_detail_shows_history(client):
    import uuid
    from apps.infrastructure.accounts.models import CustomUser
    from apps.finance.finance.models import FarmCreditScore
    from apps.infrastructure.core.rls import set_tenant_context

    org = _make_org(f"histtest-{uuid.uuid4().hex[:6]}")
    farm = _make_farm(org)
    house = _make_house(org, farm)
    _make_closed_batch(org, farm, house)

    with set_tenant_context(org):
        for _ in range(3):
            FarmCreditScore.objects.create(
                org=org,
                score=72,
                grade="B",
                confidence="early",
                financial_health_score=70,
                operational_consistency_score=70,
                mortality_management_score=80,
                feed_efficiency_score=70,
                platform_engagement_score=80,
                payment_history_score=80,
                batches_analysed=1,
                total_birds_managed=1000,
                months_on_platform=3,
            )

    user = CustomUser.objects.create_user(
        username=f"histuser-{org.subdomain}",
        email=f"hist@{org.subdomain}.com",
        password="testpass123",
        org=org,
        role="owner",
        email_verified=True,
    )
    client.force_login(user)
    response = client.get("/finance/credit-score/")
    assert response.status_code == 200
    assert b"72" in response.content
