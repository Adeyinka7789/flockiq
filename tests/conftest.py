import uuid
import pytest
from django.test import TestCase  # noqa: F401
from rest_framework.test import APIClient


# ── Shared fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def test_org(db):
    from apps.infrastructure.tenants.models import Organization
    return Organization.objects.create(
        name="Test Farm Ltd",
        subdomain=f"testfarm-{uuid.uuid4().hex[:8]}",
        plan_tier="monthly",
        subscription_status="active",
        onboarding_complete=True,
        is_active=True,
    )


@pytest.fixture
def tenant_user(db, test_org):
    from apps.infrastructure.accounts.models import CustomUser
    return CustomUser.objects.create_user(
        username=f"owner-{test_org.subdomain}",
        email=f"owner@{test_org.subdomain}.com",
        password="testpass123",
        org=test_org,
        role="owner",
        first_name="Test",
        last_name="Owner",
        email_verified=True,
    )


@pytest.fixture
def super_admin_user(db):
    from apps.infrastructure.accounts.models import CustomUser
    return CustomUser.objects.create_user(
        username="superadmin",
        email="admin@flockiq.com",
        password="testpass123",
        org=None,
        role="super_admin",
        is_staff=True,
        is_superuser=True,
    )


@pytest.fixture
def test_farm(db, test_org):
    from apps.farm.farms.models import Farm
    from apps.infrastructure.core.rls import set_tenant_context
    from decimal import Decimal
    with set_tenant_context(test_org):
        farm = Farm(
            org=test_org,
            name="Test Farm",
            location="Lagos",
            latitude=Decimal("6.5244"),
            longitude=Decimal("3.3792"),
            farm_type="mixed",
        )
        farm.clean()
        farm.save()
    return farm


@pytest.fixture
def test_house(db, test_org, test_farm):
    from apps.farm.farms.models import House
    from apps.infrastructure.core.rls import set_tenant_context
    with set_tenant_context(test_org):
        return House.objects.create(
            org=test_org,
            farm=test_farm,
            name="House A",
            capacity=500,
            house_type="layer",
        )


@pytest.fixture
def test_batch(db, test_org, test_farm, test_house):
    from apps.farm.flocks.models import Batch
    from apps.infrastructure.core.rls import set_tenant_context
    from datetime import date
    with set_tenant_context(test_org):
        return Batch.objects.create(
            org=test_org,
            farm=test_farm,
            house=test_house,
            batch_name="Batch 001",
            bird_type="layer",
            placement_date=date.today(),
            initial_count=200,
            current_count=200,
            status="active",
        )


@pytest.fixture
def api_client(tenant_user):
    """DRF APIClient with force_authenticate — bypasses JWT for API endpoint tests."""
    client = APIClient()
    client.force_authenticate(user=tenant_user)
    return client


@pytest.fixture
def test_notification(db, test_org, tenant_user):
    from apps.infrastructure.notifications.models import NotificationLog
    from apps.infrastructure.core.rls import set_tenant_context
    with set_tenant_context(test_org):
        return NotificationLog.objects.create(
            org=test_org,
            recipient=tenant_user,
            event_type="mortality_spike",
            title="Test Alert",
            body="Test notification body",
            severity="warning",
            channel="in_app",
            is_read=False,
        )
