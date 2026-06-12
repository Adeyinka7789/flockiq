"""
Fixtures for the cross-tenant RLS isolation suite.

Two orgs are created; ONE instance of every tenant-scoped model is created
for org_a (inside set_tenant_context, as production code does). org_b gets
nothing — every isolation test then asserts org_b's context cannot reach
org_a's rows through any layer (ORM manager, unscoped escape hatch, raw SQL).
"""
import datetime
import uuid
from decimal import Decimal

import pytest

from apps.infrastructure.core.rls import set_tenant_context


@pytest.fixture
def two_orgs(db):
    """Two separate active orgs for cross-tenant testing."""
    from apps.infrastructure.tenants.models import Organization

    suffix = uuid.uuid4().hex[:8]
    org_a = Organization.objects.create(
        name="RLS Test Org A",
        subdomain=f"rlstest-a-{suffix}",
        plan_tier="monthly",
        subscription_status="active",
        onboarding_complete=True,
        is_active=True,
    )
    org_b = Organization.objects.create(
        name="RLS Test Org B",
        subdomain=f"rlstest-b-{suffix}",
        plan_tier="monthly",
        subscription_status="active",
        onboarding_complete=True,
        is_active=True,
    )
    return org_a, org_b


@pytest.fixture
def org_a_user(db, two_orgs):
    """User in org_a — required by NotificationLog.recipient (NOT NULL FK)."""
    from apps.infrastructure.accounts.models import CustomUser

    org_a, _ = two_orgs
    return CustomUser.objects.create_user(
        username=f"rls-owner-{org_a.subdomain}",
        email=f"owner@{org_a.subdomain}.com",
        password="testpass123",
        org=org_a,
        role="owner",
        email_verified=True,
    )


@pytest.fixture
def org_a_full_dataset(db, two_orgs, org_a_user):
    """
    One instance of EVERY tenant-scoped model for org_a, created inside
    set_tenant_context(org_a) exactly like production code paths.

    Returns dict of (app_label, ModelName) -> instance so tests can grab a
    known PK without re-querying.

    Creation notes:
      - The batch is layer/active so MortalityLog (active-batch save guard)
        and EggProductionLog (layer-only clean) are both valid.
      - SalesRecord/ExpenseRecord post_save signals may upsert
        BatchFinancialSummary, so it is get_or_create'd afterwards.
      - BillingPlan is global (RLS disabled) — created outside any org.
    """
    org_a, _ = two_orgs
    today = datetime.date.today()
    instances = {}

    from apps.infrastructure.billing.models import BillingPlan

    plan = BillingPlan.objects.create(
        name="RLS Test Plan",
        plan_tier="monthly",
        amount_kobo=500000,
        billing_interval="monthly",
    )

    with set_tenant_context(org_a):
        # ── farm structure (FK roots) ───────────────────────────────────
        from apps.farm.farms.models import Farm, House

        farm = Farm.objects.create(
            org=org_a,
            name="RLS Farm A",
            location="Lagos",
            latitude=Decimal("6.5244"),
            longitude=Decimal("3.3792"),
            farm_type="layer",
        )
        house = House.objects.create(
            org=org_a, farm=farm, name="House 1", capacity=500,
            house_type="layer",
        )
        instances[("farms", "Farm")] = farm
        instances[("farms", "House")] = house

        from apps.farm.flocks.models import (
            Batch, MortalityLog, StockReconciliation, WeightRecord,
        )

        batch = Batch.objects.create(
            org=org_a, farm=farm, house=house,
            batch_name="RLS Batch", bird_type="layer",
            placement_date=today - datetime.timedelta(days=30),
            initial_count=200, current_count=200, status="active",
        )
        instances[("flocks", "Batch")] = batch
        instances[("flocks", "MortalityLog")] = MortalityLog.objects.create(
            org=org_a, batch=batch, farm=farm, count=1, cause="unknown",
        )
        instances[("flocks", "StockReconciliation")] = (
            StockReconciliation.objects.create(
                org=org_a, batch=batch, date=today,
                expected_count=199, actual_count=199,
                variance=0, variance_pct=Decimal("0"),
            )
        )
        instances[("flocks", "WeightRecord")] = WeightRecord.objects.create(
            org=org_a, batch=batch, sample_date=today,
            sample_size=10, avg_weight_kg=Decimal("1.500"),
        )

        from apps.farm.tasks.models import FarmTask

        instances[("tasks", "FarmTask")] = FarmTask.objects.create(
            org=org_a, farm=farm, batch=batch, title="RLS task",
        )

        from apps.farm.weather.models import WeatherAlert

        instances[("weather", "WeatherAlert")] = WeatherAlert.objects.create(
            org=org_a, farm=farm, alert_type="heat_stress",
            severity="warning", description="RLS weather alert",
        )

        # ── production logs ─────────────────────────────────────────────
        from apps.production.feed.models import FeedLog, FeedStock

        instances[("feed", "FeedLog")] = FeedLog.objects.create(
            org=org_a, batch=batch, farm=farm,
            quantity_kg=Decimal("25.00"), feed_type="layer_mash",
        )
        instances[("feed", "FeedStock")] = FeedStock.objects.create(
            org=org_a, farm=farm, feed_type="starter",
            quantity_kg=Decimal("100.00"),
        )

        from apps.production.production.models import (
            CrateInventory, EggProductionLog,
        )

        instances[("production", "EggProductionLog")] = (
            EggProductionLog.objects.create(
                org=org_a, batch=batch, farm=farm, house=house,
                total_eggs=150,
            )
        )
        # The EggProductionLog post_save signal upserts today's
        # CrateInventory row — reuse it instead of colliding with the
        # (org, farm, date) unique constraint.
        crates, _ = CrateInventory.objects.get_or_create(org=org_a, farm=farm)
        instances[("production", "CrateInventory")] = crates

        from apps.production.water.models import WaterLog

        instances[("water", "WaterLog")] = WaterLog.objects.create(
            org=org_a, batch=batch, farm=farm,
            litres_consumed=Decimal("40.00"),
        )

        from apps.production.waste.models import WasteLog

        instances[("waste", "WasteLog")] = WasteLog.objects.create(
            org=org_a, farm=farm, waste_type="litter",
            quantity_kg=Decimal("5.00"),
        )

        # ── health ──────────────────────────────────────────────────────
        from apps.health.health.models import (
            MedicationRecord, OutbreakAlert, SymptomLog, VaccinationSchedule,
        )

        instances[("health", "VaccinationSchedule")] = (
            VaccinationSchedule.objects.create(
                org=org_a, batch=batch, farm=farm,
                vaccine_name="Newcastle", due_date=today,
            )
        )
        instances[("health", "MedicationRecord")] = (
            MedicationRecord.objects.create(
                org=org_a, batch=batch, farm=farm,
                drug_name="Amoxicillin", start_date=today,
                duration_days=5, dosage="10ml/L",
                quantity_used=Decimal("10.00"),
            )
        )
        instances[("health", "SymptomLog")] = SymptomLog.objects.create(
            org=org_a, batch=batch, farm=farm,
            affected_count=3, symptoms=["coughing"],
        )
        instances[("health", "OutbreakAlert")] = OutbreakAlert.objects.create(
            org=org_a, farm=farm, disease_name="Newcastle",
            severity="warning",
        )

        # ── analytics ───────────────────────────────────────────────────
        from apps.health.analytics.models import (
            AIDailyBrief, AnomalyRecord, FarmBaseline, ForecastResult,
            SaleTimingRecommendation, TheftFlag,
        )

        instances[("analytics", "ForecastResult")] = (
            ForecastResult.objects.create(
                org=org_a, batch=batch, forecast_type="egg",
                forecast_date=today, predicted_value=Decimal("150.00"),
            )
        )
        instances[("analytics", "AnomalyRecord")] = (
            AnomalyRecord.objects.create(
                org=org_a, batch=batch, anomaly_type="mortality_spike",
                severity="warning", description="RLS anomaly",
            )
        )
        instances[("analytics", "SaleTimingRecommendation")] = (
            SaleTimingRecommendation.objects.create(
                org=org_a, batch=batch, message="RLS recommendation",
            )
        )
        instances[("analytics", "AIDailyBrief")] = AIDailyBrief.objects.create(
            org=org_a, brief_date=today, headline="RLS brief",
        )
        instances[("analytics", "FarmBaseline")] = FarmBaseline.objects.create(
            org=org_a, bird_type="layer",
        )
        instances[("analytics", "TheftFlag")] = TheftFlag.objects.create(
            org=org_a, batch=batch, unaccounted_birds=2,
            variance_pct=Decimal("1.00"), initial_count=200,
            total_mortality=1, total_sold=0, current_count=197,
        )

        # ── finance ─────────────────────────────────────────────────────
        from apps.finance.expenses.models import ExpenseRecord
        from apps.finance.finance.models import (
            BatchFinancialSummary, FarmCreditScore, SalesRecord,
        )

        instances[("finance", "SalesRecord")] = SalesRecord.objects.create(
            org=org_a, batch=batch, farm=farm, product_type="eggs",
            quantity=Decimal("10.00"), unit_price_kobo=5000,
            total_revenue_kobo=50000,
        )
        instances[("expenses", "ExpenseRecord")] = ExpenseRecord.objects.create(
            org=org_a, farm=farm, batch=batch, category="feed",
            amount_kobo=100000, description="RLS expense",
        )
        # Sales/expense post_save signals may already have upserted this
        # OneToOne row — get_or_create instead of create.
        summary, _ = BatchFinancialSummary.objects.get_or_create(
            org=org_a, batch=batch,
        )
        instances[("finance", "BatchFinancialSummary")] = summary
        instances[("finance", "FarmCreditScore")] = (
            FarmCreditScore.objects.create(
                org=org_a, score=70, grade="B", confidence="early",
                financial_health_score=70, operational_consistency_score=70,
                mortality_management_score=70, feed_efficiency_score=70,
                platform_engagement_score=70, payment_history_score=70,
                batches_analysed=1,
            )
        )

        from apps.finance.market.models import MarketPrice

        instances[("market", "MarketPrice")] = MarketPrice.objects.create(
            org=org_a, product_type="eggs", price_per_unit_kobo=450000,
            unit="crate", market_name="Mile 12",
        )

        # ── infrastructure ──────────────────────────────────────────────
        from apps.infrastructure.billing.models import (
            CycleSubscription, PaymentRecord,
        )

        instances[("billing", "CycleSubscription")] = (
            CycleSubscription.objects.create(
                org=org_a, plan=plan, batch_id=batch.id,
            )
        )
        instances[("billing", "PaymentRecord")] = PaymentRecord.objects.create(
            org=org_a, reference=f"rlstest-{uuid.uuid4().hex[:12]}",
            amount_kobo=500000, status="success", plan=plan,
        )

        from apps.infrastructure.notifications.models import (
            AlertRule, NotificationLog,
        )

        # Default alert rules are seeded when the org is created — reuse
        # rather than colliding with the (org, event_type) unique.
        rule, _ = AlertRule.objects.get_or_create(
            org=org_a, event_type="mortality_spike",
        )
        instances[("notifications", "AlertRule")] = rule
        instances[("notifications", "NotificationLog")] = (
            NotificationLog.objects.create(
                org=org_a, recipient=org_a_user,
                event_type="mortality_spike", title="RLS notification",
                body="RLS test", severity="info", channel="in_app",
            )
        )

    return instances
