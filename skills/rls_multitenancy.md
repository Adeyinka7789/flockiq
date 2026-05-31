# Skill: PostgreSQL Row-Level Security (RLS) for FlockIQ

## The Pattern in One Sentence
Middleware sets `app.current_tenant_id` in a transaction-local PostgreSQL session variable.
RLS policies on every tenant table read that variable. No WHERE clauses needed in application code.

---

## Step-by-Step: Adding RLS to a New Table

### Step 1 — Model (with required fields)
```python
# Every tenant model inherits this base
import uuid
from django.db import models

class TenantModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey('tenants.Organization', on_delete=models.CASCADE, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        unique_together = [('org', 'id')]  # REQUIRED for composite FK references
        indexes = [models.Index(fields=['org'])]  # REQUIRED for RLS performance
```

### Step 2 — Schema Migration (auto-generated)
```bash
python manage.py makemigrations <app_name>
```

### Step 3 — RLS Data Migration (always create this after schema migration)
```python
# apps/<app>/migrations/000X_add_rls_<table>.py
from django.db import migrations

class Migration(migrations.Migration):
    dependencies = [('<app>', '000X-1_initial')]

    operations = [
        migrations.RunSQL(
            sql="""
                ALTER TABLE <table_name> ENABLE ROW LEVEL SECURITY;

                CREATE POLICY tenant_select ON <table_name>
                    FOR SELECT
                    USING (org_id = current_setting('app.current_tenant_id')::uuid);

                CREATE POLICY tenant_insert ON <table_name>
                    FOR INSERT
                    WITH CHECK (org_id = current_setting('app.current_tenant_id')::uuid);

                CREATE POLICY tenant_update ON <table_name>
                    FOR UPDATE
                    USING (org_id = current_setting('app.current_tenant_id')::uuid)
                    WITH CHECK (org_id = current_setting('app.current_tenant_id')::uuid);

                CREATE POLICY tenant_delete ON <table_name>
                    FOR DELETE
                    USING (org_id = current_setting('app.current_tenant_id')::uuid);
            """,
            reverse_sql="""
                DROP POLICY IF EXISTS tenant_select ON <table_name>;
                DROP POLICY IF EXISTS tenant_insert ON <table_name>;
                DROP POLICY IF EXISTS tenant_update ON <table_name>;
                DROP POLICY IF EXISTS tenant_delete ON <table_name>;
                ALTER TABLE <table_name> DISABLE ROW LEVEL SECURITY;
            """
        )
    ]
```

---

## Middleware Implementation

### middleware/auth.py
```python
import jwt
from django.conf import settings
from django.http import JsonResponse


class JWTAuthMiddleware:
    """Decodes JWT, sets request.tenant_id and request.user_obj."""

    EXEMPT_PATHS = ['/auth/login/', '/auth/register/', '/auth/forgot-password/',
                    '/auth/reset-password/', '/health/', '/']

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Skip auth for public paths
        if any(request.path.startswith(p) for p in self.EXEMPT_PATHS):
            return self.get_response(request)

        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        if not token:
            # Also check session cookie for template views
            token = request.session.get('access_token', '')

        if token:
            try:
                payload = jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256'])
                request.tenant_id = payload.get('org_id')
                request.user_id = payload.get('user_id')
                request.user_role = payload.get('role')
            except jwt.ExpiredSignatureError:
                if request.path.startswith('/api/'):
                    return JsonResponse({'error': 'Token expired'}, status=401)
            except jwt.InvalidTokenError:
                if request.path.startswith('/api/'):
                    return JsonResponse({'error': 'Invalid token'}, status=401)

        return self.get_response(request)
```

### middleware/tenant.py
```python
from django.db import connection


class TenantRLSMiddleware:
    """Sets PostgreSQL RLS context. MUST run after JWTAuthMiddleware."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        tenant_id = getattr(request, 'tenant_id', None)
        if tenant_id:
            with connection.cursor() as cursor:
                # TRUE = transaction-local. Critical for connection pool safety.
                cursor.execute(
                    "SELECT set_config('app.current_tenant_id', %s, true)",
                    [str(tenant_id)]
                )
        return self.get_response(request)
```

---

## Tables That Need RLS
Apply RLS to ALL of these tables:
```
farms, houses, batches, mortality_logs, weight_records,
egg_production_logs, crate_inventory, broiler_weight_logs,
feed_consumption_logs, feed_stock, feed_movements, feed_schedules,
water_consumption_logs, waste_logs, expense_records, reports,
vaccination_schedules, medication_logs, health_observations,
symptom_logs, symptom_diagnoses,
sale_records, cost_summaries,
anomaly_alerts, forecast_results, theft_flags,
weather_alerts, market_season_alerts,
tasks, worker_assignments,
notifications, billing_invoices, cycle_subscriptions
```

## Tables That Must NOT Have RLS
```
organizations          — accessed during auth before tenant context is set
users                  — same as above
outbox_events          — workers poll cross-tenant
weather_cache          — infrastructure, accessed by worker cross-tenant
task_templates         — shared templates across all tenants
disease_outbreaks      — admin-managed, shown to all relevant tenants
age_based_feed_rates   — static reference data
age_based_water_rates  — static reference data
billing_plans          — public plan listing
django_* tables        — Django internals
celery_* tables        — Celery internals
```

---

## Composite Foreign Keys — Required Pattern
```sql
-- Child tables MUST reference parent with composite (org_id, parent_id)
-- This prevents cross-tenant data association at the DB constraint level

-- Example: batches reference farms
ALTER TABLE batches ADD CONSTRAINT batch_farm_fk
    FOREIGN KEY (org_id, farm_id) REFERENCES farms(org_id, id)
    ON DELETE CASCADE;

-- Example: mortality_logs reference batches
ALTER TABLE mortality_logs ADD CONSTRAINT mortality_batch_fk
    FOREIGN KEY (org_id, farm_id, batch_id) REFERENCES batches(org_id, farm_id, id)
    ON DELETE CASCADE;
```

In Django models:
```python
class Batch(TenantModel):
    farm = models.ForeignKey('farms.Farm', on_delete=models.CASCADE)

    class Meta(TenantModel.Meta):
        unique_together = [('org', 'farm', 'id')]  # enables composite FK from children

    def save(self, *args, **kwargs):
        # Enforce cross-tenant protection at application layer too
        if self.farm.org_id != self.org_id:
            raise ValueError("Farm does not belong to this organization")
        super().save(*args, **kwargs)
```

---

## Required Indexes for Every Tenant Table
```sql
-- Always add after enabling RLS
CREATE INDEX idx_<table>_org ON <table>(org_id);
-- For time-series tables add composite:
CREATE INDEX idx_mortality_batch_date ON mortality_logs(batch_id, record_date DESC);
CREATE INDEX idx_egg_batch_date ON egg_production_logs(batch_id, record_date DESC);
CREATE INDEX idx_water_batch_date ON water_consumption_logs(batch_id, record_date DESC);
-- For alert queries:
CREATE INDEX idx_alerts_unacked ON anomaly_alerts(org_id, triggered_at)
    WHERE acknowledged_at IS NULL;
-- For task queries:
CREATE INDEX idx_tasks_pending ON tasks(org_id, due_date)
    WHERE status = 'pending';
```

---

## Debugging RLS
```sql
-- Check if context is set in current session
SELECT current_setting('app.current_tenant_id', true);
-- Returns NULL if not set (the 'true' prevents error on missing var)

-- Test as a specific tenant manually
BEGIN;
SELECT set_config('app.current_tenant_id', 'your-org-uuid-here', true);
SELECT * FROM farms;  -- Should only show this tenant's farms
COMMIT;

-- List all tables with RLS enabled
SELECT schemaname, tablename, rowsecurity
FROM pg_tables
WHERE schemaname = 'public' ORDER BY rowsecurity DESC, tablename;

-- List all RLS policies
SELECT tablename, policyname, cmd, qual
FROM pg_policies
WHERE schemaname = 'public'
ORDER BY tablename;
```

---

## RLS Test Pattern — Mandatory for Every App
```python
# tests/test_rls.py
import pytest
from django.db import connection

@pytest.mark.django_db
def test_tenant_isolation_farms():
    """Tenant A cannot see Tenant B's farms."""
    from apps.tenants.models import Organization
    from apps.farms.models import Farm

    org_a = Organization.objects.create(name="Farm Corp A", slug="farm-a")
    org_b = Organization.objects.create(name="Farm Corp B", slug="farm-b")

    # Create farms directly (bypassing RLS as superuser in tests)
    farm_a = Farm.objects.create(org=org_a, name="A Farm", latitude=7.5, longitude=4.5)
    farm_b = Farm.objects.create(org=org_b, name="B Farm", latitude=8.0, longitude=5.0)

    # Set RLS context as Org A
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('app.current_tenant_id', %s, true)", [str(org_a.id)])

    farms = list(Farm.objects.all())
    assert len(farms) == 1
    assert farms[0].name == "A Farm"
    assert "B Farm" not in [f.name for f in farms]

@pytest.mark.django_db
def test_cross_tenant_insert_blocked():
    """RLS WITH CHECK blocks inserting data for wrong tenant."""
    from apps.tenants.models import Organization
    from apps.farms.models import Farm

    org_a = Organization.objects.create(name="Org A", slug="org-a")
    org_b = Organization.objects.create(name="Org B", slug="org-b")

    # Set context as Org A, try to insert for Org B
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('app.current_tenant_id', %s, true)", [str(org_a.id)])

    with pytest.raises(Exception):
        # This should be blocked by WITH CHECK policy
        Farm.objects.create(org=org_b, name="Sneaky Farm", latitude=7.5, longitude=4.5)
```

---

## Common Mistakes

1. **Outbox table with RLS** — Workers get zero results silently, no error.
   Check: `SELECT rowsecurity FROM pg_tables WHERE tablename = 'outbox_events';`

2. **set_config with false** — Session-scoped, persists after connection returns to pool.
   Always use `true` as the third argument.

3. **Forgetting composite UNIQUE on parent tables** — Child tables cannot create
   composite FKs without `UNIQUE(org_id, id)` on the parent.

4. **Running as superuser in production** — RLS is bypassed for superusers.
   Verify: `SELECT usesuper FROM pg_user WHERE usename = 'flockiq_app';`
   Must return `f` (false).

5. **Missing RLS migration** — After makemigrations, always create the RLS data migration.
   Check: `SELECT rowsecurity FROM pg_tables WHERE tablename = '<new_table>';`
