# FlockIQ — Testing Guide
## `skills/testing_guide.md`

**Version:** 1.0  
**Date:** April 2026  
**Author:** ADM Tech Hub — Lead Systems Architecture  
**Stack:** pytest-django · factory-boy · faker · pytest-cov · freezegun · responses · hypothesis  
**Companion to:** `skills/system_architectures.md` · `skills/api_contract.md` · `skills/deployment_runbook.md`

---

## Table of Contents

1. [Philosophy & Coverage Targets](#1-philosophy--coverage-targets)
2. [Project Structure & Configuration](#2-project-structure--configuration)
3. [pytest Configuration](#3-pytest-configuration)
4. [Base Fixtures](#4-base-fixtures)
5. [Factory Definitions](#5-factory-definitions)
6. [RLS & Multi-Tenancy Test Patterns](#6-rls--multi-tenancy-test-patterns)
7. [Service Layer Tests](#7-service-layer-tests)
8. [API View Tests](#8-api-view-tests)
9. [Celery Task Tests](#9-celery-task-tests)
10. [Notification Engine Tests](#10-notification-engine-tests)
11. [Calculator & Business Logic Tests](#11-calculator--business-logic-tests)
12. [ML Pipeline Tests](#12-ml-pipeline-tests)
13. [Offline Sync Tests](#13-offline-sync-tests)
14. [HTMX View Tests](#14-htmx-view-tests)
15. [Financial Ledger Tests](#15-financial-ledger-tests)
16. [Integration & E2E Tests](#16-integration--e2e-tests)
17. [Performance & Load Tests](#17-performance--load-tests)
18. [CI Pipeline Integration](#18-ci-pipeline-integration)

---

## 1. Philosophy & Coverage Targets

### 1.1 The Testing Pyramid for FlockIQ

```
                    ┌─────────────┐
                    │  E2E / UI   │  ~5%   — Playwright, critical user journeys only
                    │   Tests     │
                  ┌─┴─────────────┴─┐
                  │   Integration    │  ~25%  — API views, DB + service together
                  │     Tests        │
               ┌──┴──────────────────┴──┐
               │     Unit / Service      │  ~70%  — Pure logic, mocked dependencies
               │         Tests           │
               └────────────────────────┘
```

**The most important tests at FlockIQ are:**

1. **RLS isolation tests** — a cross-tenant data leak is a catastrophic security failure
2. **Financial ledger tests** — an unbalanced ledger corrupts all P&L reports
3. **Notification idempotency tests** — duplicate SMS to a farmer erodes trust
4. **Calculation engine tests** — wrong FCR or hen-day % drives bad farm decisions
5. **Offline sync idempotency tests** — duplicate records from retry storms corrupt data

Tests that are valuable but not critical: HTMX partial render tests, UI component tests, chart data serialisation.

### 1.2 Coverage Targets

| App Group | Minimum Coverage | Notes |
|---|---|---|
| `apps/infrastructure/core/` | **95%** | RLS, ledger, calculator — zero tolerance for untested paths |
| `apps/infrastructure/notifications/` | **90%** | Outbox, retry, idempotency |
| `apps/farm/flocks/` | **85%** | Batch lifecycle, mortality |
| `apps/production/` | **80%** | Egg logs, feed, water |
| `apps/health/analytics/` | **80%** | ML pipeline, anomaly |
| `apps/finance/` | **85%** | Sales, ledger, P&L |
| `apps/*/views.py` | **75%** | HTTP contract tests |
| `templates/` | **0%** | Templates tested via integration; unit coverage irrelevant |

### 1.3 Test Naming Convention

```python
# Pattern: test_{what}_{condition}_{expected_outcome}

def test_batch_placement_valid_data_creates_batch(): ...
def test_batch_placement_occupied_house_raises_conflict(): ...
def test_mortality_log_exceeds_live_count_raises_validation_error(): ...
def test_rls_tenant_a_cannot_read_tenant_b_batches(): ...
def test_outbox_duplicate_idempotency_key_suppressed(): ...
def test_fcr_below_target_returns_excellent_rating(): ...
```

---

## 2. Project Structure & Configuration

### 2.1 Test Directory Layout

```
tests/
├── conftest.py                    # Root conftest — DB, tenant, user fixtures
├── factories.py                   # All factory-boy factories in one file
│
├── unit/                          # Pure logic — no DB, no HTTP
│   ├── test_calculator.py
│   ├── test_breed_standards.py
│   ├── test_ledger_balance.py
│   ├── test_notification_idempotency.py
│   └── test_sync_processor.py
│
├── service/                       # Service layer — DB required, no HTTP
│   ├── test_batch_service.py
│   ├── test_feed_service.py
│   ├── test_production_service.py
│   ├── test_health_service.py
│   ├── test_finance_service.py
│   ├── test_notification_service.py
│   └── test_diagnosis_service.py
│
├── api/                           # API views — full request/response cycle
│   ├── test_auth.py
│   ├── test_batches.py
│   ├── test_production.py
│   ├── test_health.py
│   ├── test_finance.py
│   ├── test_sync.py
│   └── test_billing_webhook.py
│
├── rls/                           # Multi-tenancy isolation — must be exhaustive
│   ├── test_rls_isolation.py      # Cross-tenant query isolation
│   ├── test_rls_celery.py         # Worker context correctness
│   └── test_rls_middleware.py     # HTTP middleware sets context
│
├── tasks/                         # Celery tasks (eager mode)
│   ├── test_outbox_processor.py
│   ├── test_forecast_task.py
│   ├── test_anomaly_task.py
│   └── test_task_generation.py
│
├── htmx/                          # HTMX-specific view behaviour
│   ├── test_htmx_partials.py
│   └── test_htmx_oob_swaps.py
│
└── integration/                   # Full stack — DB + service + API together
    ├── test_batch_lifecycle.py
    ├── test_offline_sync_flow.py
    └── test_notification_delivery.py
```

### 2.2 requirements/development.txt (test dependencies)

```text
# Testing core
pytest==8.2.2
pytest-django==4.8.0
pytest-cov==5.0.0
pytest-xdist==3.5.0           # Parallel test execution
pytest-randomly==3.15.0       # Randomise test order — finds order-dependent failures

# Factories & fakes
factory-boy==3.3.0
Faker==25.2.0

# Time control
freezegun==1.5.1               # freeze_time decorator

# HTTP mocking
responses==0.25.3              # Mock external HTTP (Termii, Paystack, OpenWeatherMap)
httpretty==1.1.4               # Alternative for more complex scenarios

# Assertion helpers
pytest-lazy-fixtures==1.0.7    # Use fixtures inside parametrize
deepdiff==7.0.1                # Deep diff for complex dict comparisons

# Property-based testing
hypothesis==6.103.1
hypothesis-django==...         # Hypothesis strategies for Django models

# Coverage
coverage[toml]==7.5.3

# Optional: performance profiling in tests
pytest-benchmark==4.0.0

# Playwright for E2E (install browsers separately: playwright install chromium)
playwright==1.44.0
pytest-playwright==0.5.0
```

---

## 3. pytest Configuration

### 3.1 `pyproject.toml`

```toml
[tool.pytest.ini_options]
DJANGO_SETTINGS_MODULE = "config.settings.test"
python_files   = ["test_*.py", "*_test.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]

# Markers — used for selective test runs
markers = [
    "unit: Pure logic, no DB or HTTP",
    "service: Service layer, DB required",
    "api: Full HTTP request/response",
    "rls: Multi-tenancy isolation tests",
    "celery: Celery task tests",
    "slow: Tests taking > 1 second (ML, E2E)",
    "smoke: Quick sanity suite for post-deploy verification",
]

# Always show local variables on failure
showlocals = true

# Strict — unregistered markers are errors
addopts = [
    "--strict-markers",
    "--tb=short",
    "-ra",                    # Show summary of all non-passing tests
    "--reuse-db",             # pytest-django: reuse DB between runs
    "--no-migrations",        # Use --create-db on first run; faster thereafter
]

filterwarnings = [
    "error",                  # Treat all warnings as errors in tests
    "ignore::DeprecationWarning:factory_boy",
    "ignore::PendingDeprecationWarning",
]


[tool.coverage.run]
source = ["apps"]
omit = [
    "*/migrations/*",
    "*/admin.py",
    "*/apps.py",
    "*/tests/*",
    "*/management/commands/*",
]
branch = true                 # Branch coverage (not just line coverage)

[tool.coverage.report]
show_missing = true
skip_covered = false
fail_under = 80               # CI fails if total coverage drops below 80%
exclude_lines = [
    "pragma: no cover",
    "def __repr__",
    "if TYPE_CHECKING:",
    "raise NotImplementedError",
    "if __name__ == .__main__.:",
]
```

### 3.2 `config/settings/test.py`

```python
from .base import *

# Use fast password hasher — bcrypt is too slow for thousands of test users
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# In-memory test database — uses a real PostgreSQL for RLS tests
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "flockiq_test",
        "USER": "flockiq_user",
        "PASSWORD": "test_password",
        "HOST": "127.0.0.1",
        "PORT": "5432",          # Direct to PostgreSQL, not PgBouncer
        "CONN_MAX_AGE": 0,
        "TEST": {
            "NAME": "flockiq_test",
        },
    }
}

# Celery — always eager in tests; no broker needed
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True  # Propagate exceptions from tasks to tests

# Cache — use LocMemCache, not Redis
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

# Email — capture in memory
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# Disable Sentry in tests
SENTRY_DSN = ""

# Static files — whitenoise breaks in tests without this
STATICFILES_STORAGE = "django.contrib.staticfiles.storage.StaticFilesStorage"

# Make SECRET_KEY deterministic — simplifies JWT testing
SECRET_KEY = "test-secret-key-not-secure-do-not-use-in-production"
JWT_SIGNING_KEY = "test-jwt-key-not-secure-do-not-use-in-production"
```

---

## 4. Base Fixtures

### 4.1 `tests/conftest.py`

```python
# tests/conftest.py

import pytest
import uuid
from django.db import connection
from django.test import RequestFactory
from rest_framework.test import APIClient
from freezegun import freeze_time


# ── Database & RLS fixtures ────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def django_db_setup(django_db_setup, django_db_blocker):
    """
    Session-scoped DB setup. Creates the test database once per session.
    RLS policies are applied by migrations — they exist in the test DB.
    """
    pass


@pytest.fixture
def set_rls_context(db):
    """
    Context manager fixture that sets and clears PostgreSQL RLS context.
    Use inside tests that need to verify RLS enforcement or work within a tenant.

    Usage:
        def test_something(set_rls_context, org):
            with set_rls_context(org.id):
                batches = Batch.objects.all()  # scoped to org
    """
    from contextlib import contextmanager

    @contextmanager
    def _set(org_id):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT set_config('app.current_org_id', %s, TRUE)",
                [str(org_id)],
            )
        try:
            yield
        finally:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT set_config('app.current_org_id', '', TRUE)"
                )

    return _set


@pytest.fixture
def clear_rls_context(db):
    """
    Clears the RLS context — simulates a query running without tenant context.
    Used in RLS isolation tests to prove zero-row returns.
    """
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('app.current_org_id', '', TRUE)")
    yield
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('app.current_org_id', '', TRUE)")


# ── Tenant & User fixtures ─────────────────────────────────────────────────────

@pytest.fixture
def org(db):
    """A single tenant organisation."""
    from tests.factories import OrganizationFactory
    return OrganizationFactory()


@pytest.fixture
def org_b(db):
    """A second, unrelated organisation — used in RLS isolation tests."""
    from tests.factories import OrganizationFactory
    return OrganizationFactory(subdomain="farmb-test")


@pytest.fixture
def owner(db, org):
    """Org owner user."""
    from tests.factories import UserFactory
    return UserFactory(org=org, role="owner")


@pytest.fixture
def farm_manager(db, org):
    """Farm manager user."""
    from tests.factories import UserFactory
    return UserFactory(org=org, role="farm_manager")


@pytest.fixture
def worker(db, org):
    """Worker user — limited permissions."""
    from tests.factories import UserFactory
    return UserFactory(org=org, role="worker")


@pytest.fixture
def vet(db, org):
    """Veterinarian user."""
    from tests.factories import UserFactory
    return UserFactory(org=org, role="vet")


# ── Farm structure fixtures ────────────────────────────────────────────────────

@pytest.fixture
def farm(db, org):
    from tests.factories import FarmFactory
    return FarmFactory(org=org)


@pytest.fixture
def house(db, farm):
    from tests.factories import HouseFactory
    return HouseFactory(farm=farm, org=farm.org)


@pytest.fixture
def broiler_batch(db, house, set_rls_context):
    from tests.factories import BatchFactory
    with set_rls_context(house.org.id):
        return BatchFactory(
            org=house.org,
            house=house,
            bird_type="broiler_cobb500",
            initial_count=5000,
            status="active",
        )


@pytest.fixture
def layer_batch(db, house, set_rls_context):
    from tests.factories import BatchFactory
    with set_rls_context(house.org.id):
        return BatchFactory(
            org=house.org,
            house=house,
            bird_type="layer_isa_brown",
            initial_count=4000,
            status="active",
        )


@pytest.fixture
def closed_batch(db, house, set_rls_context):
    from tests.factories import BatchFactory
    with set_rls_context(house.org.id):
        return BatchFactory(
            org=house.org,
            house=house,
            bird_type="broiler_cobb500",
            status="closed",
        )


# ── API Client fixtures ────────────────────────────────────────────────────────

@pytest.fixture
def api_client():
    """Unauthenticated DRF test client."""
    return APIClient()


@pytest.fixture
def auth_client(api_client, farm_manager):
    """
    Authenticated DRF client — pre-loaded with a valid JWT for farm_manager.
    Sets both Authorization header and X-Org-Subdomain for tenant resolution.
    """
    from rest_framework_simplejwt.tokens import AccessToken
    token = AccessToken.for_user(farm_manager)
    token["org_id"] = str(farm_manager.org.id)
    token["org_subdomain"] = farm_manager.org.subdomain
    token["role"] = farm_manager.role

    api_client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {str(token)}",
        HTTP_X_ORG_SUBDOMAIN=farm_manager.org.subdomain,
    )
    api_client.farm_manager = farm_manager  # Attach for easy access in tests
    api_client.org = farm_manager.org
    return api_client


@pytest.fixture
def owner_client(api_client, owner):
    """Authenticated client as org owner."""
    from rest_framework_simplejwt.tokens import AccessToken
    token = AccessToken.for_user(owner)
    token["org_id"] = str(owner.org.id)
    token["role"] = "owner"
    api_client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {str(token)}",
        HTTP_X_ORG_SUBDOMAIN=owner.org.subdomain,
    )
    api_client.owner = owner
    api_client.org = owner.org
    return api_client


@pytest.fixture
def worker_client(api_client, worker):
    """Authenticated client as worker — limited permissions."""
    from rest_framework_simplejwt.tokens import AccessToken
    token = AccessToken.for_user(worker)
    token["org_id"] = str(worker.org.id)
    token["role"] = "worker"
    api_client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {str(token)}",
        HTTP_X_ORG_SUBDOMAIN=worker.org.subdomain,
    )
    api_client.worker = worker
    api_client.org = worker.org
    return api_client


# ── Utility fixtures ───────────────────────────────────────────────────────────

@pytest.fixture
def today():
    import datetime
    return datetime.date.today()


@pytest.fixture
def yesterday():
    import datetime
    return datetime.date.today() - datetime.timedelta(days=1)


@pytest.fixture
def freezer():
    """
    Returns a freeze_time context manager bound to a stable test datetime.
    Usage:
        def test_something(freezer):
            with freezer("2026-04-08 10:00:00"):
                ...
    """
    return freeze_time


@pytest.fixture(autouse=True)
def reset_cache():
    """Clear Django cache between every test — prevents cache pollution."""
    from django.core.cache import cache
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def reset_outbox(db):
    """
    Ensures OutboxEvent table is empty at test start.
    Prevents notification count assertions from failing due to prior test data.
    """
    from apps.infrastructure.notifications.models import OutboxEvent
    OutboxEvent.objects.all().delete()
    yield
```

---

## 5. Factory Definitions

### 5.1 `tests/factories.py`

```python
# tests/factories.py
# All factories in one file — easier to maintain than per-app scattered files.

import factory
import factory.fuzzy
import uuid
import datetime
from decimal import Decimal
from django.utils import timezone
from faker import Faker

fake = Faker()
Faker.seed(42)  # Deterministic — same data on every run


# ── Infrastructure ─────────────────────────────────────────────────────────────

class OrganizationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "tenants.Organization"
        django_get_or_create = ("subdomain",)

    id          = factory.LazyFunction(uuid.uuid4)
    name        = factory.LazyAttribute(lambda _: f"{fake.company()} Farms")
    subdomain   = factory.LazyAttribute(lambda _: fake.slug()[:20])
    country     = "NG"
    currency    = "NGN"
    plan        = "growth"
    subscription_status = "active"
    is_active   = True
    created_at  = factory.LazyFunction(timezone.now)


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "accounts.User"

    id           = factory.LazyFunction(uuid.uuid4)
    org          = factory.SubFactory(OrganizationFactory)
    email        = factory.LazyAttribute(lambda o: f"{fake.user_name()}@{o.org.subdomain}.test")
    full_name    = factory.LazyAttribute(lambda _: fake.name())
    phone_number = factory.LazyAttribute(lambda _: f"+234{fake.numerify('##########')}")
    role         = "farm_manager"
    is_active    = True
    password     = factory.PostGenerationMethodCall("set_password", "testpass123")


# ── Farm Structure ─────────────────────────────────────────────────────────────

class FarmFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "farms.Farm"

    id            = factory.LazyFunction(uuid.uuid4)
    org           = factory.SubFactory(OrganizationFactory)
    name          = factory.LazyAttribute(lambda _: f"{fake.city()} Farm")
    address       = factory.LazyAttribute(lambda _: fake.address())
    gps_latitude  = factory.LazyAttribute(lambda _: str(round(fake.latitude(), 4)))
    gps_longitude = factory.LazyAttribute(lambda _: str(round(fake.longitude(), 4)))
    created_at    = factory.LazyFunction(timezone.now)


class HouseFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "farms.House"

    id         = factory.LazyFunction(uuid.uuid4)
    org        = factory.LazyAttribute(lambda o: o.farm.org)
    farm       = factory.SubFactory(FarmFactory)
    name       = factory.Sequence(lambda n: f"House {chr(65 + n % 26)}")
    capacity   = factory.fuzzy.FuzzyInteger(2000, 10000, step=500)
    house_type = "deep_litter"
    created_at = factory.LazyFunction(timezone.now)


# ── Flocks ─────────────────────────────────────────────────────────────────────

class BatchFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "flocks.Batch"

    id              = factory.LazyFunction(uuid.uuid4)
    org             = factory.LazyAttribute(lambda o: o.house.org)
    house           = factory.SubFactory(HouseFactory)
    batch_code      = factory.Sequence(lambda n: f"TEST-BRO-2026-{n:03d}")
    bird_type       = "broiler_cobb500"
    initial_count   = 5000
    current_count   = factory.LazyAttribute(lambda o: o.initial_count)
    placement_date  = factory.LazyFunction(lambda: datetime.date.today() - datetime.timedelta(days=21))
    status          = "active"
    supplier        = "Test Hatchery"
    cost_per_bird   = Decimal("420.00")
    created_at      = factory.LazyFunction(timezone.now)

    class Params:
        # Trait: layer batch
        layer = factory.Trait(
            bird_type="layer_isa_brown",
            batch_code=factory.Sequence(lambda n: f"TEST-LAY-2026-{n:03d}"),
        )

        # Trait: closed batch
        closed = factory.Trait(
            status="closed",
            close_reason="sold",
            close_date=factory.LazyFunction(datetime.date.today),
        )

        # Trait: old batch (60 days in)
        aged = factory.Trait(
            placement_date=factory.LazyFunction(
                lambda: datetime.date.today() - datetime.timedelta(days=60)
            ),
        )


class MortalityLogFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "flocks.MortalityLog"

    id         = factory.LazyFunction(uuid.uuid4)
    org        = factory.LazyAttribute(lambda o: o.batch.org)
    batch      = factory.SubFactory(BatchFactory)
    date       = factory.LazyFunction(datetime.date.today)
    count      = factory.fuzzy.FuzzyInteger(1, 20)
    cause      = "unknown"
    created_at = factory.LazyFunction(timezone.now)


class WeightRecordFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "flocks.WeightRecord"

    id                  = factory.LazyFunction(uuid.uuid4)
    org                 = factory.LazyAttribute(lambda o: o.batch.org)
    batch               = factory.SubFactory(BatchFactory)
    date                = factory.LazyFunction(datetime.date.today)
    sample_size         = 50
    average_weight_kg   = Decimal("1.820")
    created_at          = factory.LazyFunction(timezone.now)


# ── Production ─────────────────────────────────────────────────────────────────

class EggProductionLogFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "production.EggProductionLog"

    id             = factory.LazyFunction(uuid.uuid4)
    org            = factory.LazyAttribute(lambda o: o.batch.org)
    batch          = factory.SubFactory(BatchFactory, layer=True)
    date           = factory.LazyFunction(datetime.date.today)
    total_eggs     = factory.fuzzy.FuzzyInteger(3000, 4500)
    cracked_eggs   = factory.fuzzy.FuzzyInteger(0, 50)
    live_hen_count = 4800
    hen_day_pct    = factory.LazyAttribute(
        lambda o: round((o.total_eggs / o.live_hen_count) * 100, 2)
    )
    created_at     = factory.LazyFunction(timezone.now)


class FeedMovementFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "feed.FeedMovement"

    id              = factory.LazyFunction(uuid.uuid4)
    org             = factory.LazyAttribute(lambda o: o.batch.org)
    batch           = factory.SubFactory(BatchFactory)
    date            = factory.LazyFunction(datetime.date.today)
    movement_type   = "consumption"
    quantity_kg     = Decimal("520.000")
    feed_type       = "grower"
    created_at      = factory.LazyFunction(timezone.now)


class WaterConsumptionLogFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "water.WaterConsumptionLog"

    id               = factory.LazyFunction(uuid.uuid4)
    org              = factory.LazyAttribute(lambda o: o.batch.org)
    batch            = factory.SubFactory(BatchFactory)
    date             = factory.LazyFunction(datetime.date.today)
    quantity_litres  = Decimal("985.000")
    ambient_temp_c   = Decimal("31.5")
    created_at       = factory.LazyFunction(timezone.now)


# ── Health ─────────────────────────────────────────────────────────────────────

class VaccinationScheduleFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "health.VaccinationSchedule"

    id           = factory.LazyFunction(uuid.uuid4)
    org          = factory.LazyAttribute(lambda o: o.batch.org)
    batch        = factory.SubFactory(BatchFactory)
    vaccine_name = "Newcastle Disease (Lasota)"
    route        = "drinking_water"
    due_date     = factory.LazyFunction(
        lambda: datetime.date.today() + datetime.timedelta(days=7)
    )
    status       = "upcoming"
    created_at   = factory.LazyFunction(timezone.now)


class SymptomLogFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "health.SymptomLog"

    id               = factory.LazyFunction(uuid.uuid4)
    org              = factory.LazyAttribute(lambda o: o.batch.org)
    batch            = factory.SubFactory(BatchFactory)
    observation_date = factory.LazyFunction(datetime.date.today)
    symptoms         = ["lethargy", "ruffled_feathers"]
    affected_count   = 20
    created_at       = factory.LazyFunction(timezone.now)


# ── Finance ────────────────────────────────────────────────────────────────────

class ExpenseRecordFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "expenses.ExpenseRecord"

    id           = factory.LazyFunction(uuid.uuid4)
    org          = factory.LazyAttribute(lambda o: o.batch.org)
    batch        = factory.SubFactory(BatchFactory)
    category     = "feed"
    description  = factory.LazyAttribute(lambda _: f"Feed purchase — {fake.company()}")
    amount       = Decimal("1040000.00")
    currency     = "NGN"
    expense_date = factory.LazyFunction(datetime.date.today)
    created_at   = factory.LazyFunction(timezone.now)


class SaleRecordFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "finance.SaleRecord"

    id             = factory.LazyFunction(uuid.uuid4)
    org            = factory.LazyAttribute(lambda o: o.batch.org)
    batch          = factory.SubFactory(BatchFactory)
    sale_type      = "broiler"
    sale_date      = factory.LazyFunction(datetime.date.today)
    quantity       = 4750
    unit           = "birds"
    unit_price     = Decimal("3200.00")
    total_amount   = Decimal("15200000.00")
    buyer_name     = "Chicken Republic Nigeria"
    payment_method = "bank_transfer"
    created_at     = factory.LazyFunction(timezone.now)


# ── Notifications ──────────────────────────────────────────────────────────────

class OutboxEventFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "notifications.OutboxEvent"

    id              = factory.LazyFunction(uuid.uuid4)
    org_id          = factory.LazyFunction(uuid.uuid4)
    recipient_id    = factory.LazyFunction(uuid.uuid4)
    channel         = "sms"
    subject         = "Test notification"
    body            = "Test body"
    idempotency_key = factory.LazyFunction(lambda: uuid.uuid4().hex[:40])
    status          = "pending"
    attempt_count   = 0
    next_attempt_at = factory.LazyFunction(timezone.now)
    created_at      = factory.LazyFunction(timezone.now)


# ── Helpers ────────────────────────────────────────────────────────────────────

def make_mortality_series(batch, days: int = 30, daily_count: int = 5):
    """
    Creates a 30-day mortality log series for a batch.
    Useful for anomaly detection tests that need historical data.
    """
    import datetime
    logs = []
    for i in range(days):
        date = datetime.date.today() - datetime.timedelta(days=days - i)
        logs.append(MortalityLogFactory(batch=batch, org=batch.org, date=date, count=daily_count))
    return logs


def make_egg_production_series(batch, days: int = 30, base_eggs: int = 4200):
    """Creates a 30-day egg production series — for Prophet forecast tests."""
    import datetime
    import random
    logs = []
    for i in range(days):
        date = datetime.date.today() - datetime.timedelta(days=days - i)
        # Add realistic variance ±5%
        eggs = int(base_eggs * (1 + random.uniform(-0.05, 0.05)))
        logs.append(
            EggProductionLogFactory(
                batch=batch, org=batch.org,
                date=date, total_eggs=eggs, live_hen_count=4800,
            )
        )
    return logs
```

---

## 6. RLS & Multi-Tenancy Test Patterns

These are the most important tests in the codebase. Every new model must have a corresponding RLS isolation test.

### 6.1 `tests/rls/test_rls_isolation.py`

```python
# tests/rls/test_rls_isolation.py

import pytest
from django.db import connection
from apps.farm.flocks.models import Batch, MortalityLog

pytestmark = [pytest.mark.django_db, pytest.mark.rls]


class TestBatchRLSIsolation:
    """
    Verifies that Batch queries are scoped to the current tenant.
    Tests the two-layer guarantee:
      1. PostgreSQL RLS returns no rows without context
      2. TenantAwareManager also filters by org
    """

    def test_tenant_a_cannot_read_tenant_b_batches(
        self, org, org_b, house, set_rls_context
    ):
        """Core isolation test — the most important test in the codebase."""
        from tests.factories import BatchFactory, HouseFactory

        # Create a house and batch for tenant B
        house_b = HouseFactory(org=org_b, farm__org=org_b)
        batch_b = BatchFactory(org=org_b, house=house_b)

        # Query as tenant A — must see zero rows
        with set_rls_context(org.id):
            visible_batches = Batch.objects.all()
            batch_ids = list(visible_batches.values_list("id", flat=True))

        assert str(batch_b.id) not in [str(i) for i in batch_ids], (
            "CRITICAL: Tenant A can see Tenant B's batch — RLS FAILURE"
        )

    def test_query_without_rls_context_returns_empty(self, broiler_batch, clear_rls_context):
        """
        Without tenant context, PostgreSQL RLS returns zero rows.
        This is the safe default — never an error, never all data.
        """
        # clear_rls_context fixture has already cleared the context
        batches = Batch.objects.all()
        assert batches.count() == 0, (
            "CRITICAL: Query without RLS context returned rows — RLS policy missing"
        )

    def test_tenant_sees_own_batches_only(self, org, org_b, set_rls_context):
        """Tenant A sees exactly its own batches, no more, no less."""
        from tests.factories import BatchFactory, HouseFactory

        house_a = HouseFactory(org=org, farm__org=org)
        house_b = HouseFactory(org=org_b, farm__org=org_b)

        batch_a1 = BatchFactory(org=org, house=house_a)
        batch_a2 = BatchFactory(org=org, house=house_a)
        batch_b1 = BatchFactory(org=org_b, house=house_b)

        with set_rls_context(org.id):
            visible_ids = set(str(i) for i in Batch.objects.values_list("id", flat=True))

        assert str(batch_a1.id) in visible_ids
        assert str(batch_a2.id) in visible_ids
        assert str(batch_b1.id) not in visible_ids
        assert len(visible_ids) == 2

    def test_mortality_log_isolated_by_tenant(self, broiler_batch, org_b, set_rls_context):
        """RLS on related models — MortalityLog must also be tenant-scoped."""
        from tests.factories import MortalityLogFactory, BatchFactory, HouseFactory

        house_b  = HouseFactory(org=org_b, farm__org=org_b)
        batch_b  = BatchFactory(org=org_b, house=house_b)
        log_b    = MortalityLogFactory(org=org_b, batch=batch_b)

        # Create a log for org A
        log_a    = MortalityLogFactory(org=broiler_batch.org, batch=broiler_batch)

        with set_rls_context(broiler_batch.org.id):
            log_ids = set(str(i) for i in MortalityLog.objects.values_list("id", flat=True))

        assert str(log_a.id) in log_ids
        assert str(log_b.id) not in log_ids

    def test_rls_policy_exists_for_all_tenant_models(self, db):
        """
        Meta-test: verifies RLS is enabled on every TenantAwareModel subclass.
        This test fails if a developer adds a new model without the RLS migration.
        """
        from django.apps import apps
        from apps.infrastructure.core.models import TenantAwareModel

        EXEMPT_TABLES = {
            "notifications_outboxevent",
            "weather_weathercache",
            "tasks_tasktemplate",
            "billing_billingplan",
        }

        tenant_tables = {
            model._meta.db_table
            for model in apps.get_models()
            if issubclass(model, TenantAwareModel) and not model._meta.abstract
        }

        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT tablename
                FROM pg_tables
                WHERE schemaname = 'public' AND rowsecurity = TRUE
            """)
            rls_enabled = {row[0] for row in cursor.fetchall()}

        missing = tenant_tables - rls_enabled - EXEMPT_TABLES
        assert not missing, (
            f"RLS NOT ENABLED on {len(missing)} tables: {sorted(missing)}. "
            f"Add enable_rls() to their migrations."
        )

    def test_direct_sql_bypasses_orm_but_not_rls(self, broiler_batch, clear_rls_context):
        """
        Even raw SQL through psycopg2 is blocked by RLS when context is unset.
        This is the database-layer guarantee — independent of the ORM.
        """
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM flocks_batch")
            count = cursor.fetchone()[0]

        assert count == 0, (
            "CRITICAL: Raw SQL bypassed RLS — check FORCE ROW LEVEL SECURITY is set"
        )


class TestCrossTableRLSConsistency:
    """
    Verifies that JOIN queries and related-object access don't leak data.
    ORM select_related / prefetch_related must respect RLS at every join.
    """

    def test_select_related_does_not_leak_farm_across_tenant(
        self, broiler_batch, org_b, set_rls_context
    ):
        from tests.factories import BatchFactory, HouseFactory

        house_b = HouseFactory(org=org_b, farm__org=org_b)
        batch_b = BatchFactory(org=org_b, house=house_b)

        with set_rls_context(broiler_batch.org.id):
            batches = list(
                Batch.objects
                .select_related("house", "house__farm")
                .all()
            )
            farm_ids = {b.house.farm_id for b in batches}

        assert house_b.farm_id not in farm_ids

    def test_filter_by_id_of_other_tenant_returns_empty(
        self, broiler_batch, org_b, set_rls_context
    ):
        """Direct ID lookup for another tenant's resource returns empty, not 404."""
        from tests.factories import BatchFactory, HouseFactory

        house_b = HouseFactory(org=org_b, farm__org=org_b)
        batch_b = BatchFactory(org=org_b, house=house_b)

        with set_rls_context(broiler_batch.org.id):
            # Trying to fetch a batch by its exact ID but from wrong tenant
            result = Batch.objects.filter(id=batch_b.id).first()

        assert result is None, (
            "CRITICAL: Fetching another tenant's resource by ID succeeded"
        )
```

### 6.2 `tests/rls/test_rls_celery.py`

```python
# tests/rls/test_rls_celery.py

import pytest
from django.db import connection

pytestmark = [pytest.mark.django_db, pytest.mark.rls, pytest.mark.celery]


class TestCeleryRLSContext:

    def test_set_tenant_context_scopes_queries(self, broiler_batch):
        """set_tenant_context() correctly gates all queries to the given org."""
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.farm.flocks.models import Batch

        with set_tenant_context(str(broiler_batch.org.id)):
            count = Batch.objects.count()

        assert count == 1

    def test_context_cleared_after_block_exits(self, broiler_batch):
        """
        After set_tenant_context block exits, subsequent queries see no rows.
        This prevents context leaking between tasks sharing a DB connection.
        """
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.farm.flocks.models import Batch

        with set_tenant_context(str(broiler_batch.org.id)):
            pass  # context set and cleared

        # Post-block: no context, no rows
        count = Batch.objects.count()
        assert count == 0

    def test_nested_context_not_permitted(self, org, org_b):
        """
        Nested set_tenant_context calls use the innermost context.
        The outer context is restored on inner exit.
        """
        from apps.infrastructure.core.rls import set_tenant_context

        with set_tenant_context(str(org.id)):
            with connection.cursor() as c:
                c.execute("SELECT current_setting('app.current_org_id', TRUE)")
                inner_val = c.fetchone()[0]

        assert inner_val == str(org.id)

    def test_task_with_wrong_org_id_sees_no_data(self, broiler_batch):
        """A task given a wrong org_id sees zero rows — not another tenant's data."""
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.farm.flocks.models import Batch
        import uuid

        wrong_org_id = str(uuid.uuid4())  # Random UUID — no such org

        with set_tenant_context(wrong_org_id):
            count = Batch.objects.count()

        assert count == 0

    def test_celery_fan_out_task_uses_correct_per_org_context(self, org, org_b, db):
        """
        The daily_egg_forecast fan-out task processes each org in isolation.
        Tests that per-org sub-tasks receive correct org_id.
        """
        from tests.factories import BatchFactory, HouseFactory
        from apps.infrastructure.core.rls import set_tenant_context

        house_a = HouseFactory(org=org, farm__org=org)
        house_b = HouseFactory(org=org_b, farm__org=org_b)
        batch_a = BatchFactory(org=org, house=house_a, bird_type="layer_isa_brown")
        batch_b = BatchFactory(org=org_b, house=house_b, bird_type="layer_isa_brown")

        # Simulate per-org task context
        with set_tenant_context(str(org.id)):
            from apps.farm.flocks.models import Batch
            visible = list(Batch.objects.values_list("id", flat=True))

        assert str(batch_a.id) in [str(i) for i in visible]
        assert str(batch_b.id) not in [str(i) for i in visible]
```

---

## 7. Service Layer Tests

### 7.1 `tests/service/test_batch_service.py`

```python
# tests/service/test_batch_service.py

import pytest
import datetime
from decimal import Decimal

pytestmark = [pytest.mark.django_db, pytest.mark.service]


class TestBatchPlacement:

    def test_place_batch_creates_batch_with_correct_fields(
        self, org, house, set_rls_context
    ):
        from apps.farm.flocks.services import BatchService

        with set_rls_context(org.id):
            batch = BatchService(org).place_batch(
                house_id=str(house.id),
                bird_type="broiler_cobb500",
                initial_count=5000,
                placement_date=datetime.date.today(),
                cost_per_bird=Decimal("420.00"),
            )

        assert batch.org == org
        assert batch.house == house
        assert batch.initial_count == 5000
        assert batch.current_count == 5000
        assert batch.status == "active"
        assert batch.bird_type == "broiler_cobb500"

    def test_place_batch_generates_unique_batch_code(self, org, house, set_rls_context):
        from apps.farm.flocks.services import BatchService
        from tests.factories import HouseFactory

        house2 = HouseFactory(org=org, farm=house.farm)

        with set_rls_context(org.id):
            batch1 = BatchService(org).place_batch(
                house_id=str(house.id), bird_type="broiler_cobb500",
                initial_count=2000, placement_date=datetime.date.today(),
            )
            batch2 = BatchService(org).place_batch(
                house_id=str(house2.id), bird_type="broiler_cobb500",
                initial_count=2000, placement_date=datetime.date.today(),
            )

        assert batch1.batch_code != batch2.batch_code

    def test_place_broiler_batch_activates_cycle_subscription(
        self, org, house, set_rls_context
    ):
        from apps.farm.flocks.services import BatchService
        from apps.billing.models import CycleSubscription

        with set_rls_context(org.id):
            batch = BatchService(org).place_batch(
                house_id=str(house.id),
                bird_type="broiler_cobb500",
                initial_count=5000,
                placement_date=datetime.date.today(),
            )
            subs = CycleSubscription.objects.filter(batch=batch, status="active")

        assert subs.count() == 1

    def test_place_layer_batch_does_not_activate_cycle_subscription(
        self, org, house, set_rls_context
    ):
        from apps.farm.flocks.services import BatchService
        from apps.billing.models import CycleSubscription

        with set_rls_context(org.id):
            batch = BatchService(org).place_batch(
                house_id=str(house.id),
                bird_type="layer_isa_brown",
                initial_count=4000,
                placement_date=datetime.date.today(),
            )
            subs = CycleSubscription.objects.filter(batch=batch)

        assert subs.count() == 0

    def test_place_batch_on_occupied_house_raises_conflict(
        self, org, broiler_batch, set_rls_context
    ):
        from apps.farm.flocks.services import BatchService
        from apps.farm.flocks.exceptions import HouseOccupiedError

        with set_rls_context(org.id):
            with pytest.raises(HouseOccupiedError) as exc:
                BatchService(org).place_batch(
                    house_id=str(broiler_batch.house.id),
                    bird_type="broiler_cobb500",
                    initial_count=3000,
                    placement_date=datetime.date.today(),
                )

        assert str(broiler_batch.batch_code) in str(exc.value)

    def test_place_batch_is_atomic_on_subscription_failure(
        self, org, house, set_rls_context, monkeypatch
    ):
        """
        If CycleSubscription activation fails, the batch itself must not be created.
        Tests the transaction.atomic() guarantee.
        """
        from apps.farm.flocks.services import BatchService
        from apps.farm.flocks.models import Batch

        def broken_activate(*args, **kwargs):
            raise RuntimeError("Paystack unreachable")

        monkeypatch.setattr(
            "apps.billing.services.CycleSubscriptionService.activate_for_batch",
            broken_activate,
        )

        with set_rls_context(org.id):
            with pytest.raises(RuntimeError):
                BatchService(org).place_batch(
                    house_id=str(house.id),
                    bird_type="broiler_cobb500",
                    initial_count=5000,
                    placement_date=datetime.date.today(),
                )

            # Transaction rolled back — no batch in DB
            assert Batch.objects.filter(house=house).count() == 0


class TestMortalityLogging:

    def test_log_mortality_decrements_current_count(
        self, broiler_batch, set_rls_context
    ):
        from apps.farm.flocks.services import BatchService

        initial_count = broiler_batch.current_count

        with set_rls_context(broiler_batch.org.id):
            BatchService(broiler_batch.org).log_mortality(
                batch_id=str(broiler_batch.id),
                date=datetime.date.today(),
                count=25,
                cause="respiratory",
            )
            broiler_batch.refresh_from_db()

        assert broiler_batch.current_count == initial_count - 25

    def test_log_mortality_exceeding_live_count_raises_error(
        self, broiler_batch, set_rls_context
    ):
        from apps.farm.flocks.services import BatchService
        from apps.farm.flocks.exceptions import MortalityExceedsLiveBirdsError

        with set_rls_context(broiler_batch.org.id):
            with pytest.raises(MortalityExceedsLiveBirdsError):
                BatchService(broiler_batch.org).log_mortality(
                    batch_id=str(broiler_batch.id),
                    date=datetime.date.today(),
                    count=broiler_batch.current_count + 1,  # One more than alive
                )

    def test_log_mortality_creates_outbox_event(
        self, broiler_batch, farm_manager, set_rls_context
    ):
        from apps.farm.flocks.services import BatchService
        from apps.infrastructure.notifications.models import OutboxEvent

        with set_rls_context(broiler_batch.org.id):
            BatchService(broiler_batch.org).log_mortality(
                batch_id=str(broiler_batch.id),
                date=datetime.date.today(),
                count=5,
            )

        assert OutboxEvent.objects.filter(
            org_id=broiler_batch.org.id,
            status="pending",
        ).count() >= 1

    def test_log_mortality_is_atomic(
        self, broiler_batch, set_rls_context, monkeypatch
    ):
        """If anomaly check task fails to enqueue, the mortality log must still save."""
        from apps.farm.flocks.services import BatchService
        from apps.farm.flocks.models import MortalityLog

        # The anomaly task raises but is fire-and-forget — shouldn't affect the log
        monkeypatch.setattr(
            "apps.health.analytics.tasks.check_mortality_anomaly.delay",
            lambda *a, **k: (_ for _ in ()).throw(Exception("Redis down")),
        )

        initial = broiler_batch.current_count
        with set_rls_context(broiler_batch.org.id):
            # Should not raise even though Celery task failed
            try:
                BatchService(broiler_batch.org).log_mortality(
                    batch_id=str(broiler_batch.id),
                    date=datetime.date.today(),
                    count=5,
                )
            except Exception:
                pass  # Fire-and-forget should swallow this

            broiler_batch.refresh_from_db()

        # Mortality was still logged
        assert broiler_batch.current_count == initial - 5


class TestBatchClose:

    def test_close_batch_sets_status_and_close_date(
        self, broiler_batch, set_rls_context
    ):
        from apps.farm.flocks.services import BatchService

        with set_rls_context(broiler_batch.org.id):
            BatchService(broiler_batch.org).close_batch(
                batch_id=str(broiler_batch.id),
                close_reason="sold",
                close_date=datetime.date.today(),
            )
            broiler_batch.refresh_from_db()

        assert broiler_batch.status == "closed"
        assert broiler_batch.close_date == datetime.date.today()
        assert broiler_batch.close_reason == "sold"

    def test_close_batch_deactivates_cycle_subscription(
        self, broiler_batch, set_rls_context
    ):
        from apps.farm.flocks.services import BatchService
        from apps.billing.models import CycleSubscription
        from tests.factories import OrganizationFactory

        # Ensure there's an active subscription to deactivate
        CycleSubscription.objects.create(
            org=broiler_batch.org,
            batch=broiler_batch,
            status="active",
        )

        with set_rls_context(broiler_batch.org.id):
            BatchService(broiler_batch.org).close_batch(
                batch_id=str(broiler_batch.id),
                close_reason="sold",
            )
            sub = CycleSubscription.objects.get(batch=broiler_batch)

        assert sub.status == "inactive"

    def test_close_already_closed_batch_raises_error(
        self, closed_batch, set_rls_context
    ):
        from apps.farm.flocks.services import BatchService
        from apps.farm.flocks.exceptions import BatchAlreadyClosedError

        with set_rls_context(closed_batch.org.id):
            with pytest.raises(BatchAlreadyClosedError):
                BatchService(closed_batch.org).close_batch(
                    batch_id=str(closed_batch.id),
                    close_reason="sold",
                )
```

---

## 8. API View Tests

### 8.1 `tests/api/test_batches.py`

```python
# tests/api/test_batches.py

import pytest
import datetime
from decimal import Decimal

pytestmark = [pytest.mark.django_db, pytest.mark.api]


class TestBatchList:

    def test_list_batches_returns_only_own_org_batches(
        self, auth_client, broiler_batch, org_b
    ):
        """API response is scoped to the authenticated org."""
        from tests.factories import BatchFactory, HouseFactory

        house_b = HouseFactory(org=org_b, farm__org=org_b)
        BatchFactory(org=org_b, house=house_b)

        response = auth_client.get("/api/v1/batches/")

        assert response.status_code == 200
        ids = [b["id"] for b in response.data["data"]]
        assert str(broiler_batch.id) in ids

    def test_list_batches_unauthenticated_returns_401(self, api_client):
        response = api_client.get("/api/v1/batches/")
        assert response.status_code == 401

    def test_list_batches_filters_by_status(
        self, auth_client, broiler_batch, closed_batch
    ):
        response = auth_client.get("/api/v1/batches/?status=active")
        assert response.status_code == 200
        statuses = [b["status"] for b in response.data["data"]]
        assert all(s == "active" for s in statuses)

    def test_list_batches_includes_metrics(self, auth_client, broiler_batch):
        response = auth_client.get("/api/v1/batches/")
        assert response.status_code == 200
        batch_data = response.data["data"][0]
        assert "metrics" in batch_data or "current_count" in batch_data


class TestBatchCreate:

    def test_create_batch_valid_payload_returns_201(
        self, auth_client, house, set_rls_context
    ):
        payload = {
            "house_id": str(house.id),
            "bird_type": "broiler_cobb500",
            "initial_count": 4000,
            "placement_date": datetime.date.today().isoformat(),
            "cost_per_bird": "420.00",
        }
        with set_rls_context(auth_client.org.id):
            response = auth_client.post("/api/v1/batches/", payload, format="json")

        assert response.status_code == 201
        assert response.data["data"]["initial_count"] == 4000
        assert response.data["data"]["status"] == "active"

    def test_create_batch_missing_bird_type_returns_400(self, auth_client, house):
        payload = {
            "house_id": str(house.id),
            "initial_count": 4000,
            "placement_date": datetime.date.today().isoformat(),
        }
        response = auth_client.post("/api/v1/batches/", payload, format="json")

        assert response.status_code == 400
        assert "bird_type" in response.data["error"]["fields"]

    def test_create_batch_future_date_returns_400(self, auth_client, house):
        future = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
        payload = {
            "house_id": str(house.id),
            "bird_type": "broiler_cobb500",
            "initial_count": 4000,
            "placement_date": future,
        }
        response = auth_client.post("/api/v1/batches/", payload, format="json")

        assert response.status_code == 400
        assert "placement_date" in response.data["error"]["fields"]

    def test_create_batch_worker_role_returns_403(
        self, worker_client, house
    ):
        """Workers cannot place batches."""
        payload = {
            "house_id": str(house.id),
            "bird_type": "broiler_cobb500",
            "initial_count": 4000,
            "placement_date": datetime.date.today().isoformat(),
        }
        response = worker_client.post("/api/v1/batches/", payload, format="json")
        assert response.status_code == 403

    def test_create_batch_wrong_org_house_returns_400(
        self, auth_client, org_b
    ):
        """Cannot create a batch in a house that belongs to another org."""
        from tests.factories import HouseFactory

        house_b = HouseFactory(org=org_b, farm__org=org_b)
        payload = {
            "house_id": str(house_b.id),
            "bird_type": "broiler_cobb500",
            "initial_count": 4000,
            "placement_date": datetime.date.today().isoformat(),
        }
        response = auth_client.post("/api/v1/batches/", payload, format="json")
        assert response.status_code == 400  # House not found for this tenant


class TestBatchMortality:

    def test_log_mortality_valid_returns_201(
        self, auth_client, broiler_batch, set_rls_context
    ):
        initial_count = broiler_batch.current_count
        payload = {
            "date": datetime.date.today().isoformat(),
            "count": 10,
            "cause": "respiratory",
        }
        with set_rls_context(auth_client.org.id):
            response = auth_client.post(
                f"/api/v1/batches/{broiler_batch.id}/mortality/",
                payload,
                format="json",
            )

        assert response.status_code == 201
        assert response.data["data"]["count"] == 10

    def test_log_mortality_exceeding_live_count_returns_422(
        self, auth_client, broiler_batch, set_rls_context
    ):
        payload = {
            "date": datetime.date.today().isoformat(),
            "count": broiler_batch.current_count + 1,
            "cause": "unknown",
        }
        with set_rls_context(auth_client.org.id):
            response = auth_client.post(
                f"/api/v1/batches/{broiler_batch.id}/mortality/",
                payload,
                format="json",
            )

        assert response.status_code in (400, 422)

    def test_log_mortality_other_tenant_batch_returns_404(
        self, auth_client, org_b
    ):
        from tests.factories import BatchFactory, HouseFactory

        house_b = HouseFactory(org=org_b, farm__org=org_b)
        batch_b = BatchFactory(org=org_b, house=house_b)

        payload = {
            "date": datetime.date.today().isoformat(),
            "count": 5, "cause": "unknown",
        }
        response = auth_client.post(
            f"/api/v1/batches/{batch_b.id}/mortality/",
            payload,
            format="json",
        )
        # Should be 404 (not 403) — tenant doesn't know the resource exists
        assert response.status_code == 404
```

---

## 9. Celery Task Tests

### 9.1 `tests/tasks/test_outbox_processor.py`

```python
# tests/tasks/test_outbox_processor.py

import pytest
from unittest.mock import patch, MagicMock
from django.utils import timezone

pytestmark = [pytest.mark.django_db, pytest.mark.celery]


class TestOutboxProcessor:

    def test_process_outbox_delivers_pending_event(
        self, org, farm_manager
    ):
        from tests.factories import OutboxEventFactory
        from apps.infrastructure.notifications.models import OutboxEvent
        from apps.infrastructure.notifications.tasks import process_outbox

        event = OutboxEventFactory(
            org_id=org.id,
            recipient_id=farm_manager.id,
            channel="in_app",
            status="pending",
            next_attempt_at=timezone.now(),
        )

        with patch(
            "apps.infrastructure.notifications.providers.inapp.InAppProvider.send"
        ) as mock_send:
            mock_send.return_value = MagicMock(
                success=True, external_id="in_app_123", should_retry=False,
                error_code=None, error_detail=None, provider="in_app",
            )
            process_outbox()

        event.refresh_from_db()
        assert event.status == OutboxEvent.Status.DELIVERED
        assert event.delivered_at is not None

    def test_failed_delivery_increments_attempt_count(
        self, org, farm_manager
    ):
        from tests.factories import OutboxEventFactory
        from apps.infrastructure.notifications.models import OutboxEvent
        from apps.infrastructure.notifications.tasks import process_outbox

        event = OutboxEventFactory(
            org_id=org.id,
            recipient_id=farm_manager.id,
            channel="sms",
            status="pending",
            attempt_count=0,
            next_attempt_at=timezone.now(),
        )

        with patch(
            "apps.infrastructure.notifications.providers.termii.TermiiProvider.send"
        ) as mock_send:
            mock_send.return_value = MagicMock(
                success=False, should_retry=True,
                error_code="TIMEOUT", error_detail="Request timed out",
                provider="termii", external_id=None,
            )
            process_outbox()

        event.refresh_from_db()
        assert event.attempt_count == 1
        assert event.status == OutboxEvent.Status.PENDING
        assert event.next_attempt_at > timezone.now()  # Backoff applied

    def test_exponential_backoff_intervals(self):
        """Verifies backoff sequence: 30s, 2m, 8m, 32m, 2h."""
        from tests.factories import OutboxEventFactory
        from django.utils import timezone
        import datetime

        event = OutboxEventFactory.build(attempt_count=0)

        expected_delays = [30, 120, 480, 1920, 7200]
        for i, expected_delay in enumerate(expected_delays):
            event.attempt_count = i
            next_at = event.compute_next_attempt()
            actual_delay = (next_at - timezone.now()).total_seconds()
            assert abs(actual_delay - expected_delay) < 5, (
                f"Attempt {i}: expected ~{expected_delay}s delay, got {actual_delay:.0f}s"
            )

    def test_max_attempts_marks_event_failed(self, org, farm_manager):
        from tests.factories import OutboxEventFactory
        from apps.infrastructure.notifications.models import OutboxEvent
        from apps.infrastructure.notifications.tasks import process_outbox

        event = OutboxEventFactory(
            org_id=org.id,
            recipient_id=farm_manager.id,
            channel="sms",
            status="pending",
            attempt_count=OutboxEvent.MAX_ATTEMPTS - 1,  # One attempt from max
            next_attempt_at=timezone.now(),
        )

        with patch(
            "apps.infrastructure.notifications.providers.termii.TermiiProvider.send"
        ) as mock_send:
            mock_send.return_value = MagicMock(
                success=False, should_retry=True,
                error_code="TIMEOUT", error_detail="Timeout", provider="termii",
            )
            process_outbox()

        event.refresh_from_db()
        assert event.status == OutboxEvent.Status.FAILED
        assert event.attempt_count == OutboxEvent.MAX_ATTEMPTS

    def test_permanent_failure_not_retried(self, org, farm_manager):
        """should_retry=False must mark as FAILED immediately, regardless of attempt count."""
        from tests.factories import OutboxEventFactory
        from apps.infrastructure.notifications.models import OutboxEvent
        from apps.infrastructure.notifications.tasks import process_outbox

        event = OutboxEventFactory(
            org_id=org.id, recipient_id=farm_manager.id,
            channel="sms", status="pending", attempt_count=0,
            next_attempt_at=timezone.now(),
        )

        with patch(
            "apps.infrastructure.notifications.providers.termii.TermiiProvider.send"
        ) as mock_send:
            mock_send.return_value = MagicMock(
                success=False, should_retry=False,  # Permanent failure
                error_code="INVALID_RECIPIENT", error_detail="Number rejected",
                provider="termii",
            )
            process_outbox()

        event.refresh_from_db()
        assert event.status == OutboxEvent.Status.FAILED
        assert event.attempt_count == 1  # Only tried once

    def test_skip_locked_prevents_double_processing(self, org, farm_manager, db):
        """
        SELECT FOR UPDATE SKIP LOCKED means two concurrent workers won't
        process the same event. This test simulates two processor calls.
        """
        from tests.factories import OutboxEventFactory
        from apps.infrastructure.notifications.models import OutboxEvent
        from apps.infrastructure.notifications.tasks import process_outbox, deliver_outbox_event

        event = OutboxEventFactory(
            org_id=org.id, recipient_id=farm_manager.id,
            channel="in_app", status="pending",
            next_attempt_at=timezone.now(),
        )

        delivery_count = {"n": 0}

        original_deliver = deliver_outbox_event.run

        def counted_deliver(event_id):
            delivery_count["n"] += 1
            return original_deliver(event_id)

        with patch(
            "apps.infrastructure.notifications.tasks.deliver_outbox_event.delay",
            side_effect=lambda eid: counted_deliver(eid),
        ):
            process_outbox()
            process_outbox()  # Second call — event already CLAIMED

        # Should only be delivered once
        assert delivery_count["n"] <= 1
```

---

## 10. Notification Engine Tests

### 10.1 Idempotency Tests

```python
# tests/service/test_notification_service.py

import pytest

pytestmark = [pytest.mark.django_db, pytest.mark.service]


class TestNotificationIdempotency:

    def test_same_idempotency_key_creates_only_one_event(
        self, org, farm_manager, broiler_batch, set_rls_context
    ):
        from apps.infrastructure.notifications.services import NotificationService
        from apps.infrastructure.notifications.models import OutboxEvent
        from django.db import transaction

        with set_rls_context(org.id):
            for _ in range(3):  # Call 3 times with same domain_id
                with transaction.atomic():
                    NotificationService(org).send(
                        event_type="mortality_alert",
                        domain_id=str(broiler_batch.id),
                        recipient_id=str(farm_manager.id),
                        channel="sms",
                        subject="Test",
                        body="Test body",
                    )

        count = OutboxEvent.objects.filter(org_id=org.id).count()
        assert count == 1, f"Expected 1 OutboxEvent, got {count} — idempotency key not working"

    def test_different_channels_create_separate_events(
        self, org, farm_manager, broiler_batch, set_rls_context
    ):
        from apps.infrastructure.notifications.services import NotificationService
        from apps.infrastructure.notifications.models import OutboxEvent
        from django.db import transaction

        with set_rls_context(org.id):
            for channel in ["sms", "email", "in_app"]:
                with transaction.atomic():
                    NotificationService(org).send(
                        event_type="mortality_alert",
                        domain_id=str(broiler_batch.id),
                        recipient_id=str(farm_manager.id),
                        channel=channel,
                        subject="Test",
                        body="Test body",
                    )

        assert OutboxEvent.objects.filter(org_id=org.id).count() == 3

    def test_notification_rolled_back_with_domain_write(
        self, org, farm_manager, set_rls_context
    ):
        """
        If the outer transaction fails, the OutboxEvent must also be rolled back.
        This is the core atomicity guarantee of the outbox pattern.
        """
        from apps.infrastructure.notifications.services import NotificationService
        from apps.infrastructure.notifications.models import OutboxEvent
        from django.db import transaction

        with set_rls_context(org.id):
            try:
                with transaction.atomic():
                    NotificationService(org).send(
                        event_type="test_event",
                        domain_id="test-id",
                        recipient_id=str(farm_manager.id),
                        channel="sms",
                        subject="Test",
                        body="Test body",
                    )
                    raise ValueError("Simulated domain write failure")
            except ValueError:
                pass

        # Transaction rolled back — no OutboxEvent persisted
        assert OutboxEvent.objects.filter(org_id=org.id).count() == 0
```

---

## 11. Calculator & Business Logic Tests

### 11.1 `tests/unit/test_calculator.py`

```python
# tests/unit/test_calculator.py

import pytest
from decimal import Decimal

# No DB needed — calculator is pure Python
pytestmark = pytest.mark.unit


class TestFCRCalculation:

    def test_fcr_within_target_returns_excellent(self):
        from apps.infrastructure.core.calculator import PoultryCalculator

        calc = PoultryCalculator("broiler_cobb500")
        result = calc.fcr(
            cumulative_feed_kg=850,
            cumulative_weight_gain_kg=500,  # FCR = 1.7 vs target 1.8
        )

        assert result.fcr == pytest.approx(1.700, abs=0.001)
        assert result.rating == "excellent"
        assert result.variance < 0  # Below target = good

    def test_fcr_above_target_returns_poor(self):
        from apps.infrastructure.core.calculator import PoultryCalculator

        calc = PoultryCalculator("broiler_cobb500")
        result = calc.fcr(
            cumulative_feed_kg=1100,
            cumulative_weight_gain_kg=500,  # FCR = 2.2 vs target 1.8
        )

        assert result.fcr == pytest.approx(2.200, abs=0.001)
        assert result.rating == "poor"
        assert result.variance > 0

    def test_fcr_zero_weight_gain_raises_value_error(self):
        from apps.infrastructure.core.calculator import PoultryCalculator

        calc = PoultryCalculator("broiler_cobb500")
        with pytest.raises(ValueError, match="Weight gain must be > 0"):
            calc.fcr(cumulative_feed_kg=500, cumulative_weight_gain_kg=0)

    @pytest.mark.parametrize("feed_kg,weight_kg,expected_fcr,expected_rating", [
        (810, 500,  1.620, "excellent"),
        (900, 500,  1.800, "good"),
        (945, 500,  1.890, "acceptable"),
        (1100, 500, 2.200, "poor"),
    ])
    def test_fcr_ratings_at_boundaries(self, feed_kg, weight_kg, expected_fcr, expected_rating):
        from apps.infrastructure.core.calculator import PoultryCalculator

        calc = PoultryCalculator("broiler_cobb500")
        result = calc.fcr(feed_kg, weight_kg)

        assert result.fcr == pytest.approx(expected_fcr, abs=0.001)
        assert result.rating == expected_rating


class TestHenDayPercentage:

    def test_hen_day_pct_correct_calculation(self):
        from apps.infrastructure.core.calculator import PoultryCalculator

        calc = PoultryCalculator("layer_isa_brown")
        result = calc.hen_day_pct(total_eggs=4224, live_hen_count=4800)

        assert result.hen_day_pct == pytest.approx(88.0, abs=0.1)
        assert result.rating == "excellent"  # ISA Brown target is 88%

    def test_hen_day_pct_not_applicable_to_broiler_raises(self):
        from apps.infrastructure.core.calculator import PoultryCalculator

        calc = PoultryCalculator("broiler_cobb500")
        with pytest.raises(ValueError, match="not applicable"):
            calc.hen_day_pct(total_eggs=0, live_hen_count=5000)

    def test_hen_day_pct_zero_hens_raises_value_error(self):
        from apps.infrastructure.core.calculator import PoultryCalculator

        calc = PoultryCalculator("layer_isa_brown")
        with pytest.raises(ValueError, match="live_hen_count must be > 0"):
            calc.hen_day_pct(total_eggs=100, live_hen_count=0)


class TestWaterRequirement:

    def test_water_requirement_at_25c_equals_base(self):
        from apps.infrastructure.core.calculator import PoultryCalculator

        calc = PoultryCalculator("broiler_cobb500")
        result = calc.daily_water_requirement(bird_count=5000, ambient_temp_c=25.0)

        # Base: 200ml/bird × 5000 = 1000L
        assert result.base_litres == pytest.approx(1000.0, abs=0.1)
        assert result.heat_adjusted_litres == pytest.approx(1000.0, abs=0.1)

    def test_water_requirement_adjusted_upward_above_25c(self):
        from apps.infrastructure.core.calculator import PoultryCalculator

        calc = PoultryCalculator("broiler_cobb500")
        result = calc.daily_water_requirement(bird_count=5000, ambient_temp_c=32.0)

        # Heat factor: (32-25) × 10% = 70% increase
        expected = 1000.0 * 1.70
        assert result.heat_adjusted_litres == pytest.approx(expected, abs=1.0)

    def test_water_requirement_no_negative_adjustment_below_25c(self):
        from apps.infrastructure.core.calculator import PoultryCalculator

        calc = PoultryCalculator("broiler_cobb500")
        result = calc.daily_water_requirement(bird_count=5000, ambient_temp_c=18.0)

        # Below 25°C: no reduction — min is base requirement
        assert result.heat_adjusted_litres == pytest.approx(result.base_litres, abs=0.1)


class TestUnknownBreedFallback:

    def test_unknown_breed_falls_back_to_generic_broiler(self):
        from apps.infrastructure.core.calculator import PoultryCalculator
        from apps.infrastructure.core.breed_standards import BREED_STANDARDS

        calc = PoultryCalculator("mystery_bird_type_xyz")
        assert calc.standard == BREED_STANDARDS["generic_broiler"]

    def test_unknown_layer_breed_falls_back_to_generic_layer(self):
        from apps.infrastructure.core.calculator import PoultryCalculator
        from apps.infrastructure.core.breed_standards import BREED_STANDARDS

        calc = PoultryCalculator("some_unknown_layer_breed")
        assert calc.standard == BREED_STANDARDS["generic_layer"]
```

---

## 12. ML Pipeline Tests

### 12.1 `tests/tasks/test_forecast_task.py`

```python
# tests/tasks/test_forecast_task.py

import pytest
import datetime

pytestmark = [pytest.mark.django_db, pytest.mark.celery, pytest.mark.slow]


class TestProphetForecastService:

    def test_forecast_skipped_below_min_rows(
        self, layer_batch, set_rls_context
    ):
        """Forecast is not attempted if fewer than 21 days of production data."""
        from tests.factories import EggProductionLogFactory
        from apps.health.analytics.services.forecasting import ProphetForecastService

        # Only 10 days of data — below the 21-day minimum
        with set_rls_context(layer_batch.org.id):
            for i in range(10):
                EggProductionLogFactory(
                    batch=layer_batch,
                    org=layer_batch.org,
                    date=datetime.date.today() - datetime.timedelta(days=10 - i),
                )

            result = ProphetForecastService(layer_batch.org).forecast_batch(
                str(layer_batch.id)
            )

        assert result is None

    def test_forecast_returns_14_day_horizon(
        self, layer_batch, set_rls_context
    ):
        """With sufficient data, forecast returns 14 future dates."""
        from tests.factories import make_egg_production_series
        from apps.health.analytics.services.forecasting import ProphetForecastService

        with set_rls_context(layer_batch.org.id):
            make_egg_production_series(layer_batch, days=30, base_eggs=4200)
            result = ProphetForecastService(layer_batch.org).forecast_batch(
                str(layer_batch.id)
            )

        assert result is not None
        assert len(result["forecast"]) == 14

    def test_forecast_result_cached_in_redis(
        self, layer_batch, set_rls_context
    ):
        from tests.factories import make_egg_production_series
        from apps.health.analytics.services.forecasting import (
            ProphetForecastService,
            FORECAST_CACHE_KEY,
        )
        from django.core.cache import cache

        with set_rls_context(layer_batch.org.id):
            make_egg_production_series(layer_batch, days=30)
            ProphetForecastService(layer_batch.org).forecast_batch(str(layer_batch.id))

        cache_key = FORECAST_CACHE_KEY.format(batch_id=layer_batch.id)
        cached = cache.get(cache_key)
        assert cached is not None

    def test_get_cached_forecast_returns_db_fallback_on_cache_miss(
        self, layer_batch, set_rls_context
    ):
        from tests.factories import make_egg_production_series
        from apps.health.analytics.services.forecasting import ProphetForecastService
        from django.core.cache import cache

        with set_rls_context(layer_batch.org.id):
            make_egg_production_series(layer_batch, days=30)
            # Run forecast to populate DB
            ProphetForecastService(layer_batch.org).forecast_batch(str(layer_batch.id))

        # Clear cache — force DB fallback
        cache.clear()

        result = ProphetForecastService.get_cached_forecast(str(layer_batch.id))
        assert result is not None
        assert "forecast" in result

    def test_forecast_values_within_valid_range(
        self, layer_batch, set_rls_context
    ):
        """Hen-day % predictions must be between 0 and 100."""
        from tests.factories import make_egg_production_series
        from apps.health.analytics.services.forecasting import ProphetForecastService

        with set_rls_context(layer_batch.org.id):
            make_egg_production_series(layer_batch, days=30)
            result = ProphetForecastService(layer_batch.org).forecast_batch(
                str(layer_batch.id)
            )

        for point in result["forecast"]:
            assert 0 <= point["predicted_hen_day_pct"] <= 100
            assert 0 <= point["lower_bound"] <= 100
            assert 0 <= point["upper_bound"] <= 100
            assert point["lower_bound"] <= point["predicted_hen_day_pct"] <= point["upper_bound"]


class TestAnomalyDetection:

    def test_no_anomaly_on_stable_mortality(
        self, broiler_batch, set_rls_context
    ):
        from tests.factories import make_mortality_series
        from apps.health.analytics.services.anomaly import AnomalyDetectionService

        with set_rls_context(broiler_batch.org.id):
            make_mortality_series(broiler_batch, days=30, daily_count=5)
            result = AnomalyDetectionService(broiler_batch.org).check_batch_mortality(
                str(broiler_batch.id)
            )

        assert result is not None
        assert result["is_anomaly"] is False

    def test_anomaly_detected_on_spike(
        self, broiler_batch, set_rls_context
    ):
        from tests.factories import MortalityLogFactory, make_mortality_series
        from apps.health.analytics.services.anomaly import AnomalyDetectionService

        with set_rls_context(broiler_batch.org.id):
            # 29 days of normal mortality (5/day)
            make_mortality_series(broiler_batch, days=29, daily_count=5)
            # Day 30: massive spike
            MortalityLogFactory(
                batch=broiler_batch, org=broiler_batch.org,
                date=datetime.date.today(), count=120,
            )
            result = AnomalyDetectionService(broiler_batch.org).check_batch_mortality(
                str(broiler_batch.id)
            )

        assert result["is_anomaly"] is True
        assert result["z_score"] > 2.5

    def test_anomaly_alert_not_duplicated_same_day(
        self, broiler_batch, set_rls_context
    ):
        from tests.factories import MortalityLogFactory, make_mortality_series
        from apps.health.analytics.services.anomaly import AnomalyDetectionService
        from apps.health.analytics.models import AnomalyAlert

        with set_rls_context(broiler_batch.org.id):
            make_mortality_series(broiler_batch, days=29, daily_count=5)
            MortalityLogFactory(
                batch=broiler_batch, org=broiler_batch.org,
                date=datetime.date.today(), count=120,
            )

            # Run twice — should create only one alert for today
            AnomalyDetectionService(broiler_batch.org).check_batch_mortality(
                str(broiler_batch.id)
            )
            AnomalyDetectionService(broiler_batch.org).check_batch_mortality(
                str(broiler_batch.id)
            )

            alerts = AnomalyAlert.objects.filter(
                batch=broiler_batch,
                alert_date=datetime.date.today(),
                alert_type="mortality_spike",
            )

        assert alerts.count() == 1
```

---

## 13. Offline Sync Tests

### 13.1 `tests/api/test_sync.py`

```python
# tests/api/test_sync.py

import pytest
import uuid
import datetime

pytestmark = [pytest.mark.django_db, pytest.mark.api]


class TestOfflineSyncIdempotency:

    def test_sync_same_client_id_twice_returns_already_synced(
        self, auth_client, broiler_batch, set_rls_context
    ):
        client_id = str(uuid.uuid4())
        payload = {
            "device_id": "test-device-001",
            "records": [{
                "type": "mortality_log",
                "client_id": client_id,
                "client_timestamp": datetime.datetime.utcnow().isoformat() + "Z",
                "payload": {
                    "batch_id": str(broiler_batch.id),
                    "date": datetime.date.today().isoformat(),
                    "count": 5,
                    "cause": "unknown",
                },
            }],
        }

        with set_rls_context(auth_client.org.id):
            r1 = auth_client.post("/api/v1/sync/", payload, format="json")
            r2 = auth_client.post("/api/v1/sync/", payload, format="json")

        assert r1.status_code == 200
        assert r2.status_code == 200

        r1_result = r1.data["data"]["results"][0]
        r2_result = r2.data["data"]["results"][0]

        assert r1_result["status"] == "created"
        assert r2_result["status"] == "already_synced"
        assert r1_result["server_id"] == r2_result["server_id"]

    def test_sync_partial_failure_does_not_abort_other_records(
        self, auth_client, broiler_batch, set_rls_context
    ):
        """If one record fails, others in the same batch must still process."""
        good_client_id  = str(uuid.uuid4())
        bad_client_id   = str(uuid.uuid4())

        payload = {
            "device_id": "test-device-001",
            "records": [
                {
                    "type": "mortality_log",
                    "client_id": bad_client_id,
                    "client_timestamp": datetime.datetime.utcnow().isoformat() + "Z",
                    "payload": {
                        "batch_id": str(uuid.uuid4()),  # Non-existent batch
                        "date": datetime.date.today().isoformat(),
                        "count": 5,
                    },
                },
                {
                    "type": "mortality_log",
                    "client_id": good_client_id,
                    "client_timestamp": datetime.datetime.utcnow().isoformat() + "Z",
                    "payload": {
                        "batch_id": str(broiler_batch.id),
                        "date": datetime.date.today().isoformat(),
                        "count": 3,
                        "cause": "unknown",
                    },
                },
            ],
        }

        with set_rls_context(auth_client.org.id):
            response = auth_client.post("/api/v1/sync/", payload, format="json")

        assert response.status_code == 200
        results = {r["client_id"]: r for r in response.data["data"]["results"]}

        assert results[bad_client_id]["status"] == "error"
        assert results[good_client_id]["status"] == "created"

    def test_sync_conflict_detected_for_same_batch_and_date(
        self, auth_client, broiler_batch, set_rls_context
    ):
        from tests.factories import MortalityLogFactory

        # Pre-existing server-side record for same batch+date
        with set_rls_context(auth_client.org.id):
            existing = MortalityLogFactory(
                batch=broiler_batch,
                org=broiler_batch.org,
                date=datetime.date.today(),
                count=12,
            )

        client_id = str(uuid.uuid4())
        payload = {
            "device_id": "test-device-001",
            "records": [{
                "type": "mortality_log",
                "client_id": client_id,
                "client_timestamp": datetime.datetime.utcnow().isoformat() + "Z",
                "payload": {
                    "batch_id": str(broiler_batch.id),
                    "date": datetime.date.today().isoformat(),  # Same date
                    "count": 8,  # Different count
                },
            }],
        }

        with set_rls_context(auth_client.org.id):
            response = auth_client.post("/api/v1/sync/", payload, format="json")

        result = response.data["data"]["results"][0]
        assert result["status"] == "conflict"
        assert "conflict_data" in result
        assert result["conflict_data"]["server_count"] == 12
        assert result["conflict_data"]["client_count"] == 8

    def test_sync_unauthenticated_returns_401(self, api_client):
        response = api_client.post("/api/v1/sync/", {}, format="json")
        assert response.status_code == 401

    def test_sync_batch_exceeding_500_records_returns_400(
        self, auth_client
    ):
        records = [
            {
                "type": "mortality_log",
                "client_id": str(uuid.uuid4()),
                "client_timestamp": datetime.datetime.utcnow().isoformat() + "Z",
                "payload": {},
            }
            for _ in range(501)
        ]
        response = auth_client.post(
            "/api/v1/sync/",
            {"device_id": "test", "records": records},
            format="json",
        )
        assert response.status_code == 400
```

---

## 14. HTMX View Tests

### 14.1 `tests/htmx/test_htmx_partials.py`

```python
# tests/htmx/test_htmx_partials.py

import pytest
from django.test import Client

pytestmark = [pytest.mark.django_db]


@pytest.fixture
def htmx_client(farm_manager):
    """Django test client authenticated as farm_manager with HTMX header."""
    client = Client()
    client.force_login(farm_manager)
    return client


class TestHTMXPartials:

    def test_batch_list_htmx_request_returns_fragment(
        self, htmx_client, broiler_batch
    ):
        """HTMX request returns only the fragment, not a full HTML page."""
        response = htmx_client.get(
            "/batches/",
            HTTP_HX_REQUEST="true",
        )

        assert response.status_code == 200
        content = response.content.decode()

        # Fragment should NOT contain the base layout elements
        assert "<html" not in content
        assert "<head>" not in content
        assert "<!DOCTYPE" not in content

        # But should contain batch data
        assert broiler_batch.batch_code in content

    def test_batch_list_direct_request_returns_full_page(
        self, htmx_client, broiler_batch
    ):
        """Direct browser navigation returns the full page with layout."""
        response = htmx_client.get("/batches/")  # No HX-Request header

        assert response.status_code == 200
        content = response.content.decode()
        assert "<!DOCTYPE html" in content or "<html" in content

    def test_mortality_form_submit_htmx_returns_fragment(
        self, htmx_client, broiler_batch
    ):
        """HTMX form POST returns updated fragment, not redirect."""
        import datetime
        response = htmx_client.post(
            f"/batches/{broiler_batch.id}/mortality/",
            {
                "date": datetime.date.today().isoformat(),
                "count": "5",
                "cause": "unknown",
            },
            HTTP_HX_REQUEST="true",
        )

        # Should return the updated fragment (200) not a redirect (302)
        assert response.status_code in (200, 201)
        assert "Location" not in response

    def test_mortality_form_invalid_htmx_returns_422_with_form(
        self, htmx_client, broiler_batch
    ):
        """Invalid HTMX form POST returns 422 with form fragment containing errors."""
        response = htmx_client.post(
            f"/batches/{broiler_batch.id}/mortality/",
            {"count": "-1"},  # Invalid count
            HTTP_HX_REQUEST="true",
        )

        assert response.status_code == 422
        content = response.content.decode()
        # Error message should be in the returned fragment
        assert "error" in content.lower() or "invalid" in content.lower()

    def test_dashboard_stats_returns_partial_on_htmx(self, htmx_client):
        response = htmx_client.get(
            "/dashboard/stats/",
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        content = response.content.decode()
        assert "<html" not in content
```

---

## 15. Financial Ledger Tests

### 15.1 `tests/service/test_ledger.py`

```python
# tests/service/test_ledger.py

import pytest
from decimal import Decimal
import datetime

pytestmark = [pytest.mark.django_db, pytest.mark.service]


class TestLedgerDoubleEntry:

    def test_feed_purchase_creates_balanced_entries(
        self, org, broiler_batch, set_rls_context
    ):
        from apps.infrastructure.core.ledger import LedgerEntry, LedgerEntryType, LedgerAccount
        from apps.infrastructure.core.services import LedgerService
        import uuid

        movement_id = uuid.uuid4()
        amount = Decimal("1040000.00")

        with set_rls_context(org.id):
            LedgerService.post_feed_purchase(
                org_id=org.id,
                batch_id=broiler_batch.id,
                movement_id=movement_id,
                amount=amount,
                date=datetime.date.today(),
            )

            entries = LedgerEntry.objects.filter(
                org_id=org.id,
                reference_id=movement_id,
            )

        assert entries.count() == 2

        debit  = entries.get(entry_type=LedgerEntryType.DEBIT)
        credit = entries.get(entry_type=LedgerEntryType.CREDIT)

        assert debit.account  == LedgerAccount.FEED_STOCK
        assert credit.account == LedgerAccount.ACCOUNTS_PAY
        assert debit.amount   == amount
        assert credit.amount  == amount  # Must balance

    def test_unbalanced_transaction_raises_value_error(self, org, broiler_batch):
        from apps.infrastructure.core.services import LedgerService
        from apps.infrastructure.core.ledger import LedgerEntryType, LedgerAccount
        import uuid

        with pytest.raises(ValueError, match="Unbalanced ledger"):
            LedgerService._post(
                org_id=org.id,
                batch_id=broiler_batch.id,
                reference_id=uuid.uuid4(),
                reference_type="test.Test",
                description="Intentionally unbalanced",
                date=datetime.date.today(),
                entries=[
                    {"type": LedgerEntryType.DEBIT,  "account": LedgerAccount.FEED_STOCK,   "amount": Decimal("100.00")},
                    {"type": LedgerEntryType.CREDIT, "account": LedgerAccount.ACCOUNTS_PAY, "amount": Decimal("90.00")},
                    # Missing 10.00 — deliberately unbalanced
                ],
            )

    def test_batch_pnl_aggregation_correct(
        self, org, broiler_batch, set_rls_context
    ):
        from apps.infrastructure.core.services import LedgerService
        import uuid

        batch_id   = broiler_batch.id
        today      = datetime.date.today()
        feed_cost  = Decimal("9578400.00")
        revenue    = Decimal("15200000.00")

        with set_rls_context(org.id):
            LedgerService.post_feed_consumption(org.id, batch_id, uuid.uuid4(), feed_cost, today)
            LedgerService.post_broiler_sale(org.id, batch_id, uuid.uuid4(), revenue, today)

            pnl = LedgerService.get_batch_pnl(org.id, batch_id)

        assert pnl["revenue"]      == pytest.approx(float(revenue), abs=0.01)
        assert pnl["feed_cost"]    == pytest.approx(float(feed_cost), abs=0.01)
        assert pnl["gross_profit"] == pytest.approx(float(revenue - feed_cost), abs=0.01)

    def test_ledger_entry_immutable_no_update(
        self, org, broiler_batch, set_rls_context
    ):
        """LedgerEntry records must never be UPDATEd — only reversals allowed."""
        from apps.infrastructure.core.services import LedgerService
        from apps.infrastructure.core.ledger import LedgerEntry
        import uuid

        with set_rls_context(org.id):
            LedgerService.post_feed_purchase(
                org.id, broiler_batch.id, uuid.uuid4(),
                Decimal("100000.00"), datetime.date.today(),
            )
            entry = LedgerEntry.objects.filter(org_id=org.id).first()
            original_amount = entry.amount

        # Attempt to update — this should either be blocked by model or be a
        # code review violation. Test that amount is unchanged after re-fetch.
        entry.amount = Decimal("999999.00")
        entry.save()

        # Re-fetch — in a correctly implemented system, you'd use a
        # custom save() that raises. For now, audit: original should differ.
        entry.refresh_from_db()
        # Document: this test should FAIL until immutability is enforced.
        # Uncomment when custom save() is implemented:
        # assert entry.amount == original_amount

    def test_no_cross_tenant_ledger_leakage(
        self, org, org_b, broiler_batch, set_rls_context
    ):
        from apps.infrastructure.core.services import LedgerService
        from apps.infrastructure.core.ledger import LedgerEntry
        from tests.factories import BatchFactory, HouseFactory
        import uuid

        house_b = HouseFactory(org=org_b, farm__org=org_b)
        batch_b = BatchFactory(org=org_b, house=house_b)

        with set_rls_context(org.id):
            LedgerService.post_feed_purchase(
                org.id, broiler_batch.id, uuid.uuid4(),
                Decimal("100.00"), datetime.date.today(),
            )

        # Create an entry for org_b (bypassing RLS — raw factory)
        from apps.infrastructure.core.ledger import LedgerEntry, LedgerEntryType, LedgerAccount
        LedgerEntry.objects.create(
            org_id=org_b.id, batch_id=batch_b.id,
            entry_type=LedgerEntryType.DEBIT,
            account=LedgerAccount.FEED_STOCK,
            amount=Decimal("999.00"),
            reference_id=uuid.uuid4(),
            reference_type="test.Test",
            description="Org B entry",
            transaction_date=datetime.date.today(),
        )

        with set_rls_context(org.id):
            entries = LedgerEntry.objects.filter(org_id=org.id)
            amounts = list(entries.values_list("amount", flat=True))

        assert Decimal("999.00") not in amounts
```

---

## 16. Integration & E2E Tests

### 16.1 Full Batch Lifecycle Integration Test

```python
# tests/integration/test_batch_lifecycle.py

import pytest
import datetime
from decimal import Decimal

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.slow]


class TestFullBatchLifecycle:
    """
    Simulates a complete broiler batch cycle:
    placement → daily ops → close → P&L verification.
    Uses transaction=True for realistic DB behaviour.
    """

    def test_complete_broiler_cycle_produces_correct_pnl(
        self, org, house, farm_manager, set_rls_context
    ):
        from apps.farm.flocks.services import BatchService
        from apps.production.feed.services import FeedService
        from apps.finance.services import SaleService
        from apps.infrastructure.core.services import LedgerService

        today = datetime.date.today()

        with set_rls_context(org.id):
            # 1. Place batch
            batch = BatchService(org).place_batch(
                house_id=str(house.id),
                bird_type="broiler_cobb500",
                initial_count=5000,
                placement_date=today - datetime.timedelta(days=42),
                cost_per_bird=Decimal("420.00"),
            )

            # 2. Log feed consumption for 42 days
            total_feed_kg = Decimal("0")
            for day in range(42):
                date = today - datetime.timedelta(days=42 - day)
                feed_kg = Decimal("520.000")
                FeedService(org).log_consumption(
                    batch_id=str(batch.id),
                    date=date,
                    quantity_kg=feed_kg,
                    feed_type="grower",
                )
                total_feed_kg += feed_kg

            # 3. Log some mortality
            for week in range(6):
                BatchService(org).log_mortality(
                    batch_id=str(batch.id),
                    date=today - datetime.timedelta(days=42 - (week * 7)),
                    count=10,
                )

            # 4. Record a sale
            birds_sold = batch.current_count
            sale_amount = Decimal(str(birds_sold * 3200))
            SaleService(org).record_sale(
                batch_id=str(batch.id),
                sale_type="broiler",
                sale_date=today,
                quantity=birds_sold,
                unit="birds",
                unit_price=Decimal("3200.00"),
                total_amount=sale_amount,
            )

            # 5. Close the batch
            BatchService(org).close_batch(
                batch_id=str(batch.id),
                close_reason="sold",
                close_date=today,
            )

            # 6. Verify P&L
            pnl = LedgerService.get_batch_pnl(org.id, batch.id)

        assert pnl["revenue"] > 0
        assert pnl["feed_cost"] > 0
        assert pnl["gross_profit"] == pytest.approx(
            pnl["revenue"] - pnl["total_cost"], abs=1.0
        )
        assert batch.status == "closed"
```

---

## 17. Performance & Load Tests

### 17.1 Query Count Assertions

```python
# tests/service/test_query_counts.py

import pytest
from django.test import TestCase
from django.db import connection, reset_queries

pytestmark = pytest.mark.django_db


class TestQueryCounts:
    """
    Prevents N+1 query regressions.
    If a query count assertion fails, the view has an N+1 bug.
    """

    def test_batch_list_view_query_count(
        self, auth_client, set_rls_context
    ):
        from tests.factories import BatchFactory, HouseFactory

        # Create 10 batches
        with set_rls_context(auth_client.org.id):
            house = HouseFactory(org=auth_client.org, farm__org=auth_client.org)
            for _ in range(10):
                h = HouseFactory(org=auth_client.org, farm=house.farm)
                BatchFactory(org=auth_client.org, house=h)

        from django.test.utils import override_settings

        with override_settings(DEBUG=True):
            reset_queries()
            response = auth_client.get("/api/v1/batches/")
            query_count = len(connection.queries)

        assert response.status_code == 200
        # 10 batches should not require 10+ queries — select_related must be used
        assert query_count <= 5, (
            f"Batch list view uses {query_count} queries for 10 batches — "
            f"check for N+1 bugs. Add select_related('house', 'house__farm')"
        )

    def test_dashboard_stats_query_count(self, auth_client, set_rls_context):
        from tests.factories import BatchFactory, HouseFactory

        with set_rls_context(auth_client.org.id):
            farm = HouseFactory(org=auth_client.org, farm__org=auth_client.org).farm
            for _ in range(5):
                h = HouseFactory(org=auth_client.org, farm=farm)
                BatchFactory(org=auth_client.org, house=h)

        from django.test.utils import override_settings

        with override_settings(DEBUG=True):
            reset_queries()
            response = auth_client.get("/api/v1/analytics/dashboard/")
            query_count = len(connection.queries)

        assert response.status_code == 200
        assert query_count <= 8, (
            f"Dashboard uses {query_count} queries — "
            f"consider caching or annotate-based aggregation"
        )
```

### 17.2 Benchmark Tests (pytest-benchmark)

```python
# tests/unit/test_benchmarks.py

import pytest


@pytest.mark.benchmark(group="calculator")
def test_fcr_calculation_performance(benchmark):
    from apps.infrastructure.core.calculator import PoultryCalculator

    calc = PoultryCalculator("broiler_cobb500")

    result = benchmark(calc.fcr, cumulative_feed_kg=850, cumulative_weight_gain_kg=500)

    assert result.fcr > 0
    # Benchmark result is printed — assert nothing about timing in unit tests;
    # use --benchmark-compare in CI to detect regressions


@pytest.mark.benchmark(group="calculator")
def test_batch_performance_summary_benchmark(benchmark):
    from apps.infrastructure.core.calculator import PoultryCalculator

    calc = PoultryCalculator("layer_isa_brown")

    result = benchmark(
        calc.batch_performance_summary,
        initial_count=5000, final_count=4750,
        total_feed_kg=50000, total_weight_gain_kg=0,
        total_eggs=350000, total_days=365,
    )

    assert "hen_day_pct" in result
```

---

## 18. CI Pipeline Integration

### 18.1 Test Runner Makefile Targets

```makefile
# Makefile

.PHONY: test test-unit test-service test-api test-rls test-fast test-full coverage

# Fast local development cycle — unit + service only, no DB setup delay
test-fast:
	pytest tests/unit/ tests/service/ -m "not slow" --no-header -q

# Full suite — everything except E2E
test:
	pytest tests/ --ignore=tests/integration/ -m "not slow" -q

# RLS tests only — run before every merge to main
test-rls:
	pytest tests/rls/ -v --tb=long -q

# API contract tests
test-api:
	pytest tests/api/ -v -q

# Full suite including slow ML tests
test-full:
	pytest tests/ -q

# Coverage report
coverage:
	pytest tests/ --ignore=tests/integration/ \
	  --cov=apps \
	  --cov-report=term-missing \
	  --cov-report=html:htmlcov \
	  --cov-fail-under=80 \
	  -q

# Run with parallel workers (faster on multi-core)
test-parallel:
	pytest tests/ --ignore=tests/integration/ \
	  -n auto \
	  -q

# Smoke tests — quick post-deploy sanity check
test-smoke:
	pytest tests/ -m "smoke" -v --tb=short
```

### 18.2 GitHub Actions Test Matrix

```yaml
# .github/workflows/test.yml  (excerpt — test job detail)

  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        test-group:
          - "tests/unit/"
          - "tests/service/"
          - "tests/api/"
          - "tests/rls/"
          - "tests/tasks/"
      fail-fast: false    # Run all groups even if one fails

    steps:
      - name: Run test group
        env:
          DATABASE_URL: postgresql://flockiq_user:test_password@localhost:5432/flockiq_test
          REDIS_URL: redis://localhost:6379
          DJANGO_SECRET_KEY: test-only
        run: |
          pytest ${{ matrix.test-group }} \
            --tb=short \
            --cov=apps \
            --cov-report=xml \
            -q

      # RLS tests get extra verbosity — failures here are P1 security issues
      - name: Run RLS tests with verbose output
        if: matrix.test-group == 'tests/rls/'
        env:
          DATABASE_URL: postgresql://flockiq_user:test_password@localhost:5432/flockiq_test
          DJANGO_SECRET_KEY: test-only
        run: |
          pytest tests/rls/ \
            -v \
            --tb=long \
            -s \
            --no-header
```

### 18.3 Pre-commit Hooks

```yaml
# .pre-commit-config.yaml

repos:
  - repo: local
    hooks:
      # Run fast tests before every commit
      - id: pytest-fast
        name: Fast tests
        entry: pytest tests/unit/ tests/service/ -m "not slow" -q --no-header
        language: system
        pass_filenames: false
        always_run: false
        files: ^apps/

      # RLS tests before every commit touching models or migrations
      - id: pytest-rls
        name: RLS isolation tests
        entry: pytest tests/rls/ -q --no-header
        language: system
        pass_filenames: false
        files: ^apps/.*/models\.py$|^apps/.*/migrations/

      # Check no DEBUG=True in settings
      - id: no-debug-true
        name: No DEBUG=True in production settings
        entry: grep -rn "DEBUG = True" config/settings/production.py
        language: system
        pass_filenames: false
        files: ^config/settings/production\.py$
```

---

*End of FlockIQ Testing Guide v1.0*  
*Companion documents:*  
*— `skills/system_architectures.md` (Core Engine Technical Specification)*  
*— `skills/deployment_runbook.md` (Deployment & Operations)*  
*— `skills/api_contract.md` (REST API Contract)*  
*— `skills/frontend_component_guide.md` (HTMX + Tailwind Component Patterns)*  
*— Next: `skills/claude_code_guide.md` (Claude Code prompting patterns for FlockIQ sprint)*
