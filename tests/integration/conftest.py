"""
Shared fixtures for the end-to-end integration suite.

These exercise the full request/response cycle (middleware → view → signals →
email → cache → RLS). They deliberately use the Django test client's default
``testserver`` host: ``TenantMiddleware`` treats that host as a dev host and
resolves the active tenant from ``request.user.org`` (and runs the suspension
kick-out there). Overriding HTTP_HOST to ``<sub>.localhost`` produces a 2-part
host that the middleware treats as a tenant-less root domain — so we do NOT do
that here.
"""
import datetime

import pytest
from django.test import Client

from apps.infrastructure.accounts.models import CustomUser
from apps.infrastructure.billing.models import BillingPlan
from apps.infrastructure.core.rls import set_tenant_context
from apps.farm.farms.models import Farm, House
from apps.farm.flocks.models import Batch
from apps.infrastructure.tenants.models import Organization


# Map each plan tier to a valid BillingPlan.billing_interval choice.
_PLAN_INTERVAL = {
    "trial": "monthly",
    "monthly": "monthly",
    "cycle": "per_cycle",
    "yearly": "annually",
}


@pytest.fixture
def billing_plans(db):
    """Ensure a BillingPlan row exists for each tier (keyed by plan_tier)."""
    plans = {}
    for tier in ["trial", "monthly", "cycle", "yearly"]:
        plan, _ = BillingPlan.objects.get_or_create(
            plan_tier=tier,
            defaults={
                "name": tier.title(),
                "amount_kobo": 0 if tier == "trial" else 500000,
                "billing_interval": _PLAN_INTERVAL[tier],
            },
        )
        plans[tier] = plan
    return plans


@pytest.fixture
def make_org(db):
    """Factory: create org + owner user."""
    def _make(name="Test Farm", subdomain="testfarm",
              plan="trial", is_active=True):
        from django.utils import timezone
        org = Organization.objects.create(
            name=name,
            subdomain=subdomain,
            plan_tier=plan,
            is_active=is_active,
            onboarding_complete=False,
            trial_ends_at=timezone.now() + datetime.timedelta(days=14),
        )
        user = CustomUser.objects.create_user(
            email=f"owner@{subdomain}.com",
            username=f"owner@{subdomain}.com",
            password="TestPass123!",
            org=org,
            role="owner",
            email_verified=True,
        )
        return org, user
    return _make


@pytest.fixture
def make_farm(db):
    """Factory: create farm + house + batch for an org."""
    def _make(org, bird_type="broiler"):
        with set_tenant_context(org):
            farm = Farm.objects.create(
                org=org,
                name="Integration Farm",
                location="Lagos, Nigeria",
                farm_type=bird_type,
                latitude=6.5244,
                longitude=3.3792,
            )
            house = House.objects.create(
                org=org,
                farm=farm,
                name="House A",
                capacity=500,
                house_type=bird_type,
            )
            batch = Batch.objects.create(
                org=org,
                farm=farm,
                house=house,
                batch_name="Integration Batch",
                bird_type=bird_type,
                initial_count=500,
                current_count=500,
                breed_name="Arbor Acres",
                placement_date=datetime.date.today(),
                status="active",
            )
            return farm, house, batch
    return _make


@pytest.fixture
def superadmin(db):
    """Create a superuser for admin tests."""
    return CustomUser.objects.create_superuser(
        email="admin@flockiq.com",
        password="SuperAdmin123!",
    )


@pytest.fixture
def tenant_client(db, make_org):
    """Authenticated client for a tenant user (default testserver host)."""
    org, user = make_org()
    org.onboarding_complete = True
    org.save()
    client = Client()
    client.force_login(user)
    return client, org, user


@pytest.fixture
def superadmin_client(db, superadmin):
    """Authenticated client for superadmin."""
    client = Client()
    client.force_login(superadmin)
    return client, superadmin
