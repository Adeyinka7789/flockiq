# Skill: Testing Strategy for FlockIQ

## Testing Philosophy
1. RLS isolation tests are NON-NEGOTIABLE — run before every deploy
2. Auto-calculation tests ensure breed logic is correct
3. API tests ensure mobile-readiness
4. Minimum 80% coverage before merge to main

## Setup
```python
# pytest.ini
[pytest]
DJANGO_SETTINGS_MODULE = config.settings.development
python_files = tests/test_*.py tests/**/test_*.py
python_classes = Test*
python_functions = test_*
addopts = --tb=short -v --cov=apps --cov-report=term-missing

# conftest.py
import pytest
from django.db import connection

@pytest.fixture
def org_a(db):
    from apps.tenants.models import Organization
    return Organization.objects.create(name="Farm Corp A", slug="org-a")

@pytest.fixture
def org_b(db):
    from apps.tenants.models import Organization
    return Organization.objects.create(name="Farm Corp B", slug="org-b")

@pytest.fixture
def set_rls(db):
    """Context manager to set RLS context in tests."""
    def _set(org_id):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT set_config('app.current_tenant_id', %s, true)",
                [str(org_id)]
            )
    return _set
```

---

## 1. RLS Isolation Tests (MANDATORY)

```python
# tests/test_rls.py

@pytest.mark.django_db
def test_farms_isolated(org_a, org_b, set_rls):
    from apps.farms.models import Farm
    Farm.objects.create(org=org_a, name="A Farm", latitude=7.5, longitude=4.5)
    Farm.objects.create(org=org_b, name="B Farm", latitude=8.0, longitude=5.0)

    set_rls(org_a.id)
    farms = list(Farm.objects.all())
    assert len(farms) == 1
    assert farms[0].name == "A Farm"


@pytest.mark.django_db
def test_mortality_logs_isolated(org_a, org_b, set_rls):
    from apps.farms.models import Farm, House
    from apps.flocks.models import Batch, MortalityLog
    from datetime import date

    farm_a = Farm.objects.create(org=org_a, name="A", latitude=7.5, longitude=4.5)
    house_a = House.objects.create(org=org_a, farm=farm_a, name="H1", house_type='layer', capacity=1000)
    batch_a = Batch.objects.create(org=org_a, farm=farm_a, house=house_a,
        batch_number='B-A-01', bird_type='layer',
        placement_date=date.today(), initial_count=500, current_count=500)

    farm_b = Farm.objects.create(org=org_b, name="B", latitude=8.0, longitude=5.0)
    house_b = House.objects.create(org=org_b, farm=farm_b, name="H1", house_type='broiler', capacity=1000)
    batch_b = Batch.objects.create(org=org_b, farm=farm_b, house=house_b,
        batch_number='B-B-01', bird_type='broiler',
        placement_date=date.today(), initial_count=500, current_count=500)

    # Create mortality as superuser (bypasses RLS)
    MortalityLog.objects.create(org=org_a, batch=batch_a, farm=farm_a, count=5, cause='disease')
    MortalityLog.objects.create(org=org_b, batch=batch_b, farm=farm_b, count=3, cause='culling')

    set_rls(org_a.id)
    logs = list(MortalityLog.objects.all())
    assert len(logs) == 1
    assert logs[0].count == 5


@pytest.mark.django_db
def test_cross_tenant_insert_blocked(org_a, org_b, set_rls):
    """RLS WITH CHECK blocks writing wrong org_id."""
    from apps.farms.models import Farm
    import pytest

    set_rls(org_a.id)
    with pytest.raises(Exception):
        Farm.objects.create(org=org_b, name="Evil Farm", latitude=7.5, longitude=4.5)


@pytest.mark.django_db
def test_all_tenant_tables_have_rls(db):
    """Ensures no tenant table was accidentally created without RLS."""
    TENANT_TABLES = [
        'farms', 'houses', 'batches', 'mortality_logs', 'weight_records',
        'egg_production_logs', 'crate_inventory',
        'feed_consumption_logs', 'feed_stock', 'water_consumption_logs',
        'waste_logs', 'expense_records',
        'vaccination_schedules', 'medication_logs', 'symptom_logs', 'symptom_diagnoses',
        'sale_records', 'anomaly_alerts', 'forecast_results',
        'weather_alerts', 'market_season_alerts', 'tasks', 'notifications',
    ]
    with connection.cursor() as cursor:
        for table in TENANT_TABLES:
            cursor.execute(
                "SELECT rowsecurity FROM pg_tables WHERE tablename = %s", [table])
            row = cursor.fetchone()
            assert row is not None, f"Table {table} does not exist"
            assert row[0] is True, f"Table {table} does NOT have RLS enabled!"
```

---

## 2. Auto-Calculation Tests

```python
# tests/test_auto_calc.py

@pytest.mark.django_db
def test_hen_day_pct_calculated_on_save(org_a, set_rls):
    """hen_day_pct = total_eggs / live_hen_count * 100"""
    set_rls(org_a.id)
    from apps.production.models import EggProductionLog
    # ... setup batch ...
    log = EggProductionLog.objects.create(
        org=org_a, batch=batch, farm=farm,
        record_date=date.today(),
        total_eggs=1800, live_hen_count=2000,
        grade_a=1700, grade_b=80, cracked=15, dirty=5
    )
    assert float(log.hen_day_pct) == 90.0
    assert float(log.crates) == 60.0  # 1800 / 30


@pytest.mark.django_db
def test_mortality_decrements_current_count(org_a, set_rls):
    """Mortality log save should auto-decrement batch.current_count."""
    set_rls(org_a.id)
    # ... setup batch with current_count=500 ...
    MortalityLog.objects.create(org=org_a, batch=batch, farm=farm, count=10, cause='disease')
    batch.refresh_from_db()
    assert batch.current_count == 490


@pytest.mark.django_db
def test_water_auto_requirement_calculated(org_a, set_rls):
    """Water requirement auto-calculated from age/count reference table."""
    set_rls(org_a.id)
    # ... setup broiler batch at day 35 with 200 birds ...
    log = WaterConsumptionLog.objects.create(
        org=org_a, batch=batch, farm=farm,
        record_date=date.today(),
        litres_consumed=38.0
    )
    # At day 35, 200 birds: 200 * avg(200-250)ml = ~45 litres
    assert log.auto_requirement_litres is not None
    assert float(log.auto_requirement_litres) > 30


@pytest.mark.django_db
def test_withdrawal_date_calculated(org_a, set_rls):
    """safe_to_sell_date = start + duration + withdrawal."""
    set_rls(org_a.id)
    from datetime import date, timedelta
    log = MedicationLog.objects.create(
        org=org_a, batch=batch,
        drug_name='Oxytetracycline', drug_type='antibiotic',
        quantity_used=50, unit='g', cost=1500,
        start_date=date(2025, 3, 1),
        duration_days=5, withdrawal_period_days=7,
        reason='reactive'
    )
    expected = date(2025, 3, 1) + timedelta(days=5+7)
    assert log.safe_to_sell_date == expected


@pytest.mark.django_db
def test_fcr_calculation(org_a, set_rls):
    """FCR = total_feed_kg / total_weight_gained_kg"""
    from apps.feed.services import calculate_fcr
    set_rls(org_a.id)
    # ... setup broiler batch, add feed logs totaling 50kg, weight from 42g to 1200g ...
    fcr = calculate_fcr(batch)
    assert fcr is not None
    assert 1.5 <= fcr <= 2.5  # reasonable range
```

---

## 3. Breed Logic Tests

```python
# tests/test_breed_logic.py

def test_broiler_stage_auto_advances():
    from apps.flocks.models import Batch
    from unittest.mock import patch

    # Day 0-13: starter
    with patch.object(Batch, 'age_days', new_callable=property) as mock_age:
        mock_age.return_value = 10
        batch = Batch(bird_type='broiler')
        batch.update_stage()
        assert batch.stage == 'starter'

    # Day 14-27: grower
    with patch.object(Batch, 'age_days', new_callable=property) as mock_age:
        mock_age.return_value = 20
        batch = Batch(bird_type='broiler')
        batch.update_stage()
        assert batch.stage == 'grower'


def test_layer_expected_laying_pct():
    from apps.production.services import get_expected_laying_pct
    assert get_expected_laying_pct(20) == (20, 30)   # coming into lay
    assert get_expected_laying_pct(28) == (90, 95)   # peak
    assert get_expected_laying_pct(65) == (70, 85)   # declining


def test_theft_detection_threshold():
    from apps.analytics.services import run_theft_detection
    from unittest.mock import MagicMock

    batch = MagicMock()
    batch.initial_count = 1000
    batch.current_count = 850

    with patch('MortalityLog.objects.filter') as mock_mort, \
         patch('SaleRecord.objects.filter') as mock_sale:
        mock_mort.return_value.aggregate.return_value = {'total': 0}
        mock_sale.return_value.aggregate.return_value = {'total': 0}

        # 850 accounted (current) + 0 mortality + 0 sold = 850
        # unaccounted = 1000 - 850 = 150 = 15% — should flag
        result = run_theft_detection(batch)
        assert result['theft_suspected'] is True
        assert result['unaccounted_birds'] == 150
```

---

## 4. API Tests

```python
# tests/test_api.py

@pytest.mark.django_db
def test_api_requires_auth(client):
    response = client.get('/api/v1/farms/')
    assert response.status_code == 401


@pytest.mark.django_db
def test_api_returns_only_tenant_farms(api_client_org_a, org_a, org_b):
    """API should only return the authenticated tenant's farms."""
    from apps.farms.models import Farm
    Farm.objects.create(org=org_a, name="A Farm", latitude=7.5, longitude=4.5)
    Farm.objects.create(org=org_b, name="B Farm", latitude=8.0, longitude=5.0)

    response = api_client_org_a.get('/api/v1/farms/')
    assert response.status_code == 200
    assert response.data['success'] is True
    assert len(response.data['data']) == 1
    assert response.data['data'][0]['name'] == "A Farm"
```

---

## Running Tests
```bash
# Full test suite
pytest

# RLS tests only (run before every deploy)
pytest tests/test_rls.py -v

# Auto-calc tests
pytest tests/test_auto_calc.py -v

# With coverage report
pytest --cov=apps --cov-report=html

# Specific app
pytest tests/apps/test_flocks*.py -v
```
