# FlockIQ — Claude Code Guide
## `skills/claude_code_guide.md`

**Version:** 1.0  
**Date:** April 2026  
**Author:** ADM Tech Hub — Lead Systems Architecture  
**Purpose:** How to use Claude Code effectively during the FlockIQ 12-hour coding sprint  
**Prerequisite reading:** All five companion docs — read them before sprinting, or Claude Code won't have the context to help you at the right level.

---

## Table of Contents

1. [How Claude Code Thinks About This Codebase](#1-how-claude-code-thinks-about-this-codebase)
2. [CLAUDE.md — The Project Memory File](#2-claudemd--the-project-memory-file)
3. [Sprint Workflow Patterns](#3-sprint-workflow-patterns)
4. [Prompt Templates by Task Type](#4-prompt-templates-by-task-type)
5. [App Scaffolding Prompts](#5-app-scaffolding-prompts)
6. [Service Layer Prompts](#6-service-layer-prompts)
7. [API View & Serializer Prompts](#7-api-view--serializer-prompts)
8. [Model & Migration Prompts](#8-model--migration-prompts)
9. [Test Generation Prompts](#9-test-generation-prompts)
10. [HTMX Template Prompts](#10-htmx-template-prompts)
11. [Celery Task Prompts](#11-celery-task-prompts)
12. [Debugging Prompts](#12-debugging-prompts)
13. [Refactoring Prompts](#13-refactoring-prompts)
14. [Anti-Patterns to Avoid](#14-anti-patterns-to-avoid)
15. [Sprint Checklists](#15-sprint-checklists)

---

## 1. How Claude Code Thinks About This Codebase

### 1.1 What Claude Code Does Well in This Sprint

Claude Code performs best when it has:
- **Exact file paths** to read before generating code
- **Named patterns** from the docs (e.g. "HtmxMixin", "TenantAwareModel", "LedgerService")
- **Concrete constraints** — "must use set_rls_context", "must call transaction.atomic()"
- **An existing example to follow** — point it at a completed app to scaffold a new one

Claude Code underperforms when:
- Prompts are vague ("write the batch views")
- No architectural context is given (it invents its own patterns)
- You ask it to do too many things in one prompt
- You don't tell it which files to read first

### 1.2 The "Read First, Then Write" Rule

Before generating any file, always tell Claude Code to read the relevant existing file from the codebase. This is the single most important habit.

```bash
# BAD — Claude invents patterns
> Write the FeedService class

# GOOD — Claude follows the established pattern
> Read apps/farm/flocks/services.py first.
> Then write apps/production/feed/services.py following exactly the same
> patterns: BaseService inheritance, transaction.atomic(), inline imports
> for cross-app dependencies, fire-and-forget Celery tasks for ML triggers.
```

### 1.3 The Context Hierarchy

When Claude Code works on a file, feed it context in this order:

```
1. The relevant skills/*.md section (architecture contract)
2. The most similar existing app (concrete implementation to follow)
3. The specific task (what to build)
4. The constraints (what must not change)
```

---

## 2. CLAUDE.md — The Project Memory File

Place this file at the project root. Claude Code reads it automatically on every session start. It is the single most important file in the repo for AI-assisted development.

### 2.1 `/CLAUDE.md`

```markdown
# FlockIQ — Claude Code Project Memory

## What this project is
FlockIQ is a multi-tenant AI-powered poultry farm management SaaS for Nigerian
and West African farmers. Django 5.x + HTMX + PostgreSQL with Row-Level Security.

## Skills docs — read these before generating any code
- skills/system_architectures.md   — Core engines, RLS rules, service patterns
- skills/api_contract.md           — All 28 API endpoint groups, serializer contracts
- skills/deployment_runbook.md     — Stack, server config, migration protocol
- skills/frontend_component_guide.md — HTMX + Tailwind + Alpine component patterns
- skills/testing_guide.md          — pytest patterns, factory-boy, RLS test patterns

## Architecture non-negotiables (never violate these)
1. Every tenant-scoped model inherits TenantAwareModel from apps/infrastructure/core/models.py
2. Every migration on a TenantAwareModel must call enable_rls() from core/migrations/rls_helpers.py
3. All business logic lives in services.py — never in models.py or views.py
4. Cross-app coordination goes through apps/infrastructure/core/services.py (LedgerService)
5. Celery tasks must call set_tenant_context(org_id) before any DB query
6. Notifications are created atomically with domain writes via NotificationService
7. CONN_MAX_AGE = 0 always — PgBouncer transaction mode requires this
8. POST views return the updated fragment (not redirect) for HTMX clients

## App directory structure
apps/
  infrastructure/  → core, tenants, accounts, notifications, billing
  farm/            → farms, flocks, tasks, weather
  production/      → production, feed, water, waste
  health/          → health, analytics
  finance/         → expenses, finance, market

## Tech stack
- Backend: Django 5.x, DRF 3.15+, Celery 5.x, PostgreSQL 16, Redis 7.x
- Frontend: Django templates, HTMX 2.x, Alpine.js 3.x, Tailwind CSS 3.x, Chart.js 4.x
- ML: Prophet (egg forecasting), scikit-learn (anomaly detection)
- SMS: Termii | Payments: Paystack | Weather: OpenWeatherMap
- Server: Ubuntu 24.04, Nginx, Gunicorn, Supervisor, aaPanel, TrueHost VPS

## The most important test to run after any model change
pytest tests/rls/test_rls_isolation.py::TestBatchRLSIsolation::test_rls_policy_exists_for_all_tenant_models -v

## Current sprint focus
Building out all 18 apps from the architecture scaffolded in system_architectures.md.
Priority order: infrastructure → farms → flocks → production → health → finance

## Key file locations
- Base models:     apps/infrastructure/core/models.py
- Base service:    apps/infrastructure/core/services.py
- RLS context:     apps/infrastructure/core/rls.py
- Ledger engine:   apps/infrastructure/core/ledger.py
- Calculator:      apps/infrastructure/core/calculator.py
- Notification:    apps/infrastructure/notifications/services.py
- Test fixtures:   tests/conftest.py
- Test factories:  tests/factories.py
```

---

## 3. Sprint Workflow Patterns

### 3.1 The 4-Step App Build Loop

Use this pattern for every new app during the sprint. Each step has a corresponding prompt template in the sections below.

```
Step 1 — SCAFFOLD
  Prompt: "Scaffold the [app_name] app following the same structure as [reference_app]"
  Output: models.py, services.py, views.py, serializers.py, urls.py, apps.py, tasks.py

Step 2 — MODELS + MIGRATION
  Prompt: "Write the [Model] model and its migration with RLS enabled"
  Output: models.py, migration file

Step 3 — SERVICE + TESTS
  Prompt: "Write [Service] and its tests following tests/service/test_batch_service.py"
  Output: services.py, tests/service/test_[app]_service.py

Step 4 — VIEWS + SERIALIZERS
  Prompt: "Write the DRF views and serializers for [endpoint] following api_contract.md §[N]"
  Output: views.py, serializers.py, tests/api/test_[app].py
```

### 3.2 The Verification Loop

After every Claude Code output, run this sequence before accepting:

```bash
# 1. RLS check — must pass before any commit
pytest tests/rls/test_rls_isolation.py -q

# 2. Run the specific app's tests
pytest tests/service/test_[app]_service.py tests/api/test_[app].py -q

# 3. Migration check
python manage.py migrate --check

# 4. If any model was added or changed:
python manage.py verify_rls_policies
```

### 3.3 Session Startup Prompt

Use this at the start of every Claude Code session to re-establish context:

```
I'm building FlockIQ — a multi-tenant Django SaaS for poultry farm management.
Read CLAUDE.md and then read skills/system_architectures.md sections 1-3 to
understand the architecture. I'll then give you specific tasks.

Current sprint status:
- DONE: [list completed apps]
- IN PROGRESS: [current app]
- UP NEXT: [next app]

Do not write any code yet. Confirm you've read both files and summarise
the three most important architectural constraints before we start.
```

---

## 4. Prompt Templates by Task Type

The prompts in sections 5–11 are ready to copy and use. Placeholders are in `[SQUARE_BRACKETS]`. Replace them before running.

### 4.1 Prompt Anatomy

Every good Claude Code prompt for this project has four parts:

```
[CONTEXT]   — What files to read first
[TASK]      — Exactly what to build
[RULES]     — Non-negotiable constraints from the skills docs
[OUTPUT]    — Exactly which files to create/modify
```

If any of these four parts is missing, the output quality drops significantly.

---

## 5. App Scaffolding Prompts

### 5.1 Scaffold a Complete New App

```
Read these files first:
  1. apps/farm/flocks/models.py
  2. apps/farm/flocks/services.py
  3. apps/farm/flocks/views.py
  4. apps/farm/flocks/serializers.py
  5. apps/farm/flocks/urls.py
  6. apps/farm/flocks/apps.py

Now scaffold the [APP_NAME] app at apps/[DOMAIN]/[APP_NAME]/ following
exactly the same file structure and patterns.

The app handles: [ONE SENTENCE DESCRIPTION OF WHAT THIS APP DOES]

Key models to create: [MODEL_1, MODEL_2, MODEL_3]

Rules:
- All models inherit TenantAwareModel from apps/infrastructure/core/models.py
- services.py must import BaseService from apps/infrastructure/core/services.py
- views.py must use HtmxMixin from apps/infrastructure/core/views.py
- No business logic in models.py or views.py — services.py only
- Add the app to INSTALLED_APPS in config/settings/base.py

Create these files:
  apps/[DOMAIN]/[APP_NAME]/models.py
  apps/[DOMAIN]/[APP_NAME]/services.py
  apps/[DOMAIN]/[APP_NAME]/views.py
  apps/[DOMAIN]/[APP_NAME]/serializers.py
  apps/[DOMAIN]/[APP_NAME]/urls.py
  apps/[DOMAIN]/[APP_NAME]/apps.py
  apps/[DOMAIN]/[APP_NAME]/tasks.py     (stub — fill in later)
  apps/[DOMAIN]/[APP_NAME]/signals.py   (stub — fill in later)
  apps/[DOMAIN]/[APP_NAME]/admin.py     (basic ModelAdmin registrations)
  apps/[DOMAIN]/[APP_NAME]/tests/__init__.py
```

### 5.2 Scaffold the Feed App (Concrete Example)

```
Read these files first:
  1. skills/system_architectures.md (Section 2 — Django App Structure table)
  2. skills/api_contract.md (Section 11 — Feed Management)
  3. apps/production/production/models.py  (similar production app to follow)
  4. apps/farm/flocks/services.py          (service pattern reference)

Scaffold apps/production/feed/ — the feed management app.

This app tracks:
  - FeedStock: inventory records per feed type (starter/grower/finisher/layer_mash)
  - FeedMovement: individual stock-in and consumption records linked to batches
  - FeedSchedule: breed-standard daily feed recommendations per batch

Key constraints:
  - FeedMovement.consumption events must call LedgerService.post_feed_consumption()
    from apps/infrastructure/core/services.py (inline import inside the method)
  - FeedMovement.restock events must call LedgerService.post_feed_purchase()
  - Auto-calculate daily feed requirement using PoultryCalculator from
    apps/infrastructure/core/calculator.py on every FeedMovement save (signal)
  - If FeedStock.current_quantity_kg drops below reorder_threshold_kg, fire
    a NotificationService.send() event — channel "in_app" and "sms"
  - All models inherit TenantAwareModel
  - FeedMovement migration must include enable_rls() from rls_helpers

Create these files:
  apps/production/feed/models.py
  apps/production/feed/services.py
  apps/production/feed/views.py
  apps/production/feed/serializers.py
  apps/production/feed/urls.py
  apps/production/feed/signals.py
  apps/production/feed/apps.py
  apps/production/feed/admin.py
```

---

## 6. Service Layer Prompts

### 6.1 Write a Complete Service Class

```
Read these files first:
  1. apps/infrastructure/core/services.py  (BaseService definition)
  2. apps/farm/flocks/services.py          (full worked example)
  3. skills/system_architectures.md §3    (circular import prevention rules)
  4. skills/api_contract.md §[SECTION]    (the API contract for this domain)

Write apps/[DOMAIN]/[APP_NAME]/services.py for the [SERVICE_NAME] service.

This service must implement these methods:
  - [method_1(args)]: [what it does, what it returns]
  - [method_2(args)]: [what it does, what it returns]
  - [method_3(args)]: [what it does, what it returns]

Mandatory rules:
  1. Class inherits BaseService(org) — constructor takes org instance
  2. Every public method is wrapped in transaction.atomic()
  3. Cross-app imports are INLINE inside method bodies, never at module level
     (prevents circular imports — see system_architectures.md §3.4 Rule 5)
  4. Celery tasks are called with .delay() INSIDE the atomic block —
     fire-and-forget; never await them
  5. NotificationService.send() calls are INSIDE the same transaction.atomic()
     as the domain write (outbox pattern — must be atomic together)
  6. Use select_for_update() when modifying counter fields (current_count, stock_qty)
  7. Never pass Django model instances across service boundaries — use UUIDs
```

### 6.2 Add a Method to an Existing Service

```
Read apps/[DOMAIN]/[APP_NAME]/services.py first.

Add this method to [ServiceName]:

  def [method_name](self, [params]) -> [return_type]:
    """[Purpose: one sentence]"""

The method should:
  - [Behaviour 1]
  - [Behaviour 2]
  - [Behaviour 3 — include side effects like notifications, ledger posts]

Follow the exact style of the existing methods in this file:
  - transaction.atomic() wrapper
  - select_for_update() on the primary model if it writes a counter
  - inline imports for cross-app dependencies
  - Celery task .delay() call at the end if async processing is needed

Do NOT modify any existing methods. Only add the new method.
```

### 6.3 Write the Diagnosis Service (AI Integration)

```
Read these files first:
  1. skills/system_architectures.md §2.4  (Symptom-to-Disease AI section)
  2. apps/infrastructure/core/services.py (BaseService)
  3. apps/farm/flocks/services.py         (pattern reference)

Write apps/health/analytics/services/diagnosis.py

This is the DiagnosisService. It must:

  1. Implement diagnose(symptom_log_id: str) -> SymptomDiagnosis
     - Fetch SymptomLog by id within tenant context
     - Run _rule_match(observed_symptoms: frozenset) first (Phase 1)
     - Fall back to _fallback_result() if no rule matches
     - Create SymptomDiagnosis with suggested_disease, confidence_score,
       treatment_protocol (use update_or_create — idempotent)
     - Call NotificationService(self.org).send_diagnosis_alert(diag) after save

  2. Implement DISEASE_RULES class attribute — a dict mapping frozenset of
     symptom codes to a result dict with keys:
       "disease", "confidence", "protocol"
     Include at minimum these mappings (from Nigerian poultry disease field data):
       - Newcastle Disease: lethargy + ruffled_feathers + reduced_feed_intake
       - Infectious Bronchitis: watery_droppings + reduced_egg_production
       - Coccidiosis: bloody_droppings + lethargy + reduced_water_intake
       - Marek's Disease: lameness + twisted_neck + sudden_death
       - Fowl Pox: pale_comb + lethargy + reduced_egg_production
       - Gumboro: sudden_death + reduced_feed_intake + ruffled_feathers

  3. Phase 2 stub: _ml_classify(observed: frozenset) — not implemented yet,
     returns None. Add a TODO comment explaining the scikit-learn upgrade path.

Rules:
  - No ORM imports at module level — inline only
  - DISEASE_RULES uses frozenset keys with .issubset() matching (partial match)
  - Higher confidence for exact matches, lower for partial
  - Always return a result — never return None or raise from diagnose()
```

---

## 7. API View & Serializer Prompts

### 7.1 Write DRF Views for a Complete Endpoint Group

```
Read these files first:
  1. skills/api_contract.md §[SECTION_NUMBER] — [SECTION_NAME]
     (This is the authoritative contract. Do not deviate from it.)
  2. apps/farm/flocks/views.py    (reference view implementation)
  3. apps/farm/flocks/serializers.py (reference serializer implementation)
  4. apps/infrastructure/core/views.py (HtmxMixin, OfflineSyncMixin)

Write apps/[DOMAIN]/[APP_NAME]/views.py and apps/[DOMAIN]/[APP_NAME]/serializers.py

Implement these endpoints exactly as specified in the api_contract.md section:
  - [ENDPOINT_1]: [METHOD] [PATH] → [BEHAVIOUR]
  - [ENDPOINT_2]: [METHOD] [PATH] → [BEHAVIOUR]

View rules:
  - All views inherit HtmxMixin from apps/infrastructure/core/views.py
  - Views call service methods only — no ORM in views
  - Successful POSTs: return the new/updated object fragment (status 201 or 200)
  - Failed POSTs: return the form fragment at status 422 (not 400) for HTMX
  - Permission classes must match the permission matrix in api_contract.md §27
  - Use FlockIQCursorPagination from apps/infrastructure/core/pagination.py

Serializer rules:
  - Field-level validation in validate_[field]() methods, not views
  - Cross-field validation in validate() — not in the view
  - house_id, batch_id foreign key fields validate against request.org (tenant-scoped)
  - Decimal fields: max_digits=14, decimal_places=2 for money; =3 for kg quantities
  - Required=False fields must have a sensible default — never leave it as None

Response format: always wrap in {"data": ..., "meta": {"request_id": "..."}}
Use the flockiq_exception_handler from apps/infrastructure/core/exceptions.py
```

### 7.2 Add a Detail Action to an Existing View

```
Read apps/[DOMAIN]/[APP_NAME]/views.py and its corresponding URL conf.

Add a new @action to [ViewSetName]:

  Endpoint: [METHOD] /api/v1/[resource]/{id}/[action_name]/
  Purpose:  [What this action does]
  Permission: [role1, role2]

The action should:
  1. Validate input with [SerializerName] (create it if it doesn't exist)
  2. Call [ServiceName](request.org).[method_name]([params])
  3. Return [WHAT] at status [STATUS_CODE]
  4. For HTMX clients (self.is_htmx): return the [FRAGMENT_NAME] partial
  5. For non-HTMX clients: return the full object JSON

Side effects to document in the docstring:
  - [Side effect 1]
  - [Side effect 2]

Do not modify any existing methods on this ViewSet.
```

### 7.3 Write the Paystack Webhook Handler

```
Read these files first:
  1. skills/api_contract.md §24 — Billing & Subscriptions
  2. apps/infrastructure/billing/models.py (CycleSubscription, Invoice, Plan)
  3. skills/system_architectures.md §2 (billing app in app structure table)

Write apps/infrastructure/billing/views.py — specifically the webhook handler.

The PaystackWebhookView must:
  1. Verify the X-Paystack-Signature HMAC-SHA512 header on every request
     using PAYSTACK_WEBHOOK_SECRET from settings
     → Reject (400 immediately) if signature does not match
     → Never log the raw payload before verification

  2. Handle these Paystack event types:
     - charge.success    → mark Invoice as paid, activate subscription
     - subscription.create → create/update CycleSubscription record
     - subscription.disable → deactivate CycleSubscription
     - invoice.create    → create Invoice record with status "pending"
     - invoice.payment_failed → mark Invoice failed, send SMS to org owner

  3. Always return HTTP 200 — Paystack retries on non-200
     (idempotency: use paystack_reference as unique key on Invoice)

  4. All DB writes inside transaction.atomic()

  5. NotificationService.send() for payment_failed event only —
     channel "sms" to the org owner

Authentication: NOT JWT — this endpoint authenticates via the Paystack signature only.
Set authentication_classes = [] and permission_classes = [AllowAny] on the view.
Rate limiting: none (Paystack manages retry rate; nginx allows unlimited from Paystack IPs).
```

---

## 8. Model & Migration Prompts

### 8.1 Write a Model with Full RLS Migration

```
Read these files first:
  1. apps/infrastructure/core/models.py         (TenantAwareModel definition)
  2. apps/infrastructure/core/migrations/rls_helpers.py (enable_rls function)
  3. apps/farm/flocks/models.py                 (reference model implementation)
  4. The relevant section in skills/system_architectures.md §2 for this app

Write the [MODEL_NAME] model for apps/[DOMAIN]/[APP_NAME]/models.py

Fields:
  [field_name]: [type] — [description and constraints]
  [field_name]: [type] — [description and constraints]

Model rules:
  - Inherits TenantAwareModel (gives: id UUID pk, org FK, created_at,
    updated_at, is_deleted, archived_at, TenantAwareManager)
  - Add composite DB indexes for the most common query patterns:
    (org, [date_field]) and (org, [status_field]) if applicable
  - Add __str__ that returns something human-readable for Django admin
  - Add Meta.ordering = ["-created_at"] unless another ordering makes more sense
  - Never use CASCADE deletes on historical data — use PROTECT

Also write the migration file:
  apps/[DOMAIN]/[APP_NAME]/migrations/0001_initial.py

The migration must end with:
  from apps.infrastructure.core.migrations.rls_helpers import enable_rls
  operations += enable_rls("[table_name]")

Table name format: [app_label]_[model_name_lowercase]
e.g. feed_feedmovement, production_eggproductionlog
```

### 8.2 Add a Field Safely (Zero-Downtime)

```
Read apps/[DOMAIN]/[APP_NAME]/models.py first.
Read skills/deployment_runbook.md §11.2 (Safe Migration Rules table).

Add [field_name] to [ModelName]:
  Type: [CharField/DecimalField/ForeignKey/etc.]
  Purpose: [what it stores]
  Constraints: [max_length, null, blank, default, choices]

Safe migration strategy:
  - If this field has a NOT NULL constraint with no server-side default:
    Step 1: Add as nullable (null=True, blank=True) in this PR
    Step 2: Backfill in a separate data migration
    Step 3: Add NOT NULL constraint in a third migration
    Generate all three migrations now and label them clearly.

  - If this field has a sensible server-side default that PostgreSQL 16 can
    apply instantly (no table rewrite): generate a single migration.

  - If this is an index on a large table: use atomic=False and
    CREATE INDEX CONCURRENTLY (see deployment_runbook.md §11.2)

Do not use RunSQL directly — use migrations.AddField() where possible.
The migration must NOT include enable_rls() (RLS already applied to this table).
```

### 8.3 Write the Full Data Dictionary for an App

```
Read the FlockIQ_DataDictionary_v2.docx context from our previous sessions.
Read apps/[DOMAIN]/[APP_NAME]/models.py.

Generate a data dictionary entry for every model in this app.
Format each entry as:

## [ModelName]
**Table:** `[app_label]_[model_name]`  
**Purpose:** [One sentence]  
**RLS:** Enabled / Disabled (reason)

| Field | Type | Nullable | Default | Description |
|---|---|---|---|---|
| id | UUID | No | uuid4() | Primary key |
| org | FK→Organization | No | — | Tenant owner |
| [field] | [type] | [yes/no] | [val] | [description] |

**Indexes:**
- `(org_id, created_at)` — default composite from TenantAwareModel
- `(org_id, [field])` — [reason]

**Relationships:**
- FK to [ModelName] via [field_name]
- Reverse: [ModelName].set ([related_name])
```

---

## 9. Test Generation Prompts

### 9.1 Generate Full Test Suite for a Service

```
Read these files first:
  1. apps/[DOMAIN]/[APP_NAME]/services.py   (the service to test)
  2. tests/service/test_batch_service.py    (reference test file — follow this structure exactly)
  3. tests/conftest.py                      (available fixtures)
  4. tests/factories.py                     (available factories)
  5. skills/testing_guide.md §1.1           (the five most important test types)

Write tests/service/test_[APP_NAME]_service.py

Generate tests for every public method in [ServiceName].
For each method, write:
  1. Happy path test — valid inputs, correct output, correct side effects
  2. Edge case test — boundary values, empty lists, zero counts
  3. Failure test — invalid input raises correct exception
  4. Atomicity test — if the method writes to multiple tables, verify a failure
     mid-method rolls back all writes (monkeypatch one write to raise, assert others absent)
  5. RLS test — verify the method only operates within the tenant's scope

Test structure rules (from testing_guide.md):
  - Name format: test_[method]_[condition]_[expected_outcome]
  - Use set_rls_context fixture for all DB operations
  - Use factories from tests/factories.py — never .create() in tests directly
  - Mark with pytestmark = [pytest.mark.django_db, pytest.mark.service]
  - Group tests in classes named Test[MethodName] or Test[BehaviourGroup]
```

### 9.2 Generate RLS Isolation Tests for a New Model

```
Read these files first:
  1. tests/rls/test_rls_isolation.py         (the full reference test file)
  2. apps/[DOMAIN]/[APP_NAME]/models.py      (the models to test)
  3. tests/conftest.py                       (org, org_b, set_rls_context, clear_rls_context)
  4. tests/factories.py                      (existing factories)

Write RLS isolation tests for [ModelName] in tests/rls/test_rls_isolation.py
(add to the existing file — do not replace it).

Generate these five tests for [ModelName]:
  1. test_[model]_isolated_by_tenant — tenant A cannot read tenant B records
  2. test_[model]_query_without_context_returns_empty — clear_rls_context fixture
  3. test_[model]_sees_own_records_only — exact count assertion
  4. test_[model]_filter_by_other_tenant_id_returns_none — direct ID lookup
  5. test_[model]_related_objects_do_not_leak — if this model has FKs to other
     tenant models, verify select_related does not return cross-tenant objects

Additionally, if [ModelName] was not in the EXEMPT_TABLES set, verify:
  - test_[model]_rls_policy_exists — query pg_policies directly
```

### 9.3 Generate API Tests from the Contract

```
Read these files first:
  1. skills/api_contract.md §[SECTION] — [ENDPOINT GROUP NAME]
     This is the authoritative spec. Every test must validate a claim in this section.
  2. apps/[DOMAIN]/[APP_NAME]/views.py      (the views being tested)
  3. tests/api/test_batches.py              (reference API test file)
  4. tests/conftest.py                      (auth_client, worker_client, owner_client)

Write tests/api/test_[APP_NAME].py

For each endpoint in the spec section, write:
  1. Successful request test — correct payload → correct status code + response shape
  2. Missing required field → 400 with field name in error.fields
  3. Invalid field value → 400 with field name in error.fields
  4. Unauthenticated request → 401
  5. Wrong role → 403 (use worker_client or a client without the required role)
  6. Cross-tenant access attempt → 404 (not 403 — tenant shouldn't know it exists)
  7. Pagination test if it's a list endpoint — verify meta.next/previous structure

Response shape assertions must check:
  - response.data["data"] exists (envelope format from api_contract.md §1.7)
  - All required fields from the api_contract.md response schema are present
  - Decimal fields are strings (COERCE_DECIMAL_TO_STRING = True)
  - UUID fields are strings in correct format
```

### 9.4 Generate Factory for a New Model

```
Read these files first:
  1. tests/factories.py             (all existing factories — follow these patterns)
  2. apps/[DOMAIN]/[APP_NAME]/models.py  (the model to factory-ise)

Add a factory for [ModelName] to tests/factories.py.

Rules:
  - Inherit factory.django.DjangoModelFactory
  - Meta.model = "[app_label].[ModelName]" (string format)
  - id = factory.LazyFunction(uuid.uuid4)
  - org FK: use factory.LazyAttribute(lambda o: o.[parent_fk].org) if the org
    can be derived from a parent, otherwise use factory.SubFactory(OrganizationFactory)
  - All date fields: factory.LazyFunction(datetime.date.today) or today + delta
  - All datetime fields: factory.LazyFunction(timezone.now)
  - Decimal fields: use Decimal("...") literals with quotes — never bare floats
  - FuzzyInteger for counts that vary: factory.fuzzy.FuzzyInteger(min, max)
  - Add Params class with Traits for common variations (e.g. closed=True, layer=True)
  - If the model needs related data in bulk, add a make_[model]_series() helper
    function below the factory class (see make_mortality_series in factories.py)

Place the factory in the correct section comment in factories.py
(Infrastructure / Farm Structure / Flocks / Production / Health / Finance / Notifications)
```

---

## 10. HTMX Template Prompts

### 10.1 Write a Full Page with HTMX Partials

```
Read these files first:
  1. skills/frontend_component_guide.md §3  (base templates and layout)
  2. skills/frontend_component_guide.md §4  (HTMX interaction patterns)
  3. templates/pages/batches/list.html       (reference full page)
  4. templates/partials/batch_list.html      (reference partial)
  5. skills/api_contract.md §[SECTION]       (data shape for this page)

Write these templates for the [FEATURE_NAME] feature:

  templates/pages/[app]/[page].html
    - Extends base/_base.html
    - Contains the page header, filters/search, and the HTMX swap target div
    - Live search: hx-get, hx-target, hx-trigger="input changed delay:400ms"
    - Filter pills: hx-push-url="true" on every filter link

  templates/partials/[feature]_list.html
    - The fragment returned to HTMX requests
    - Loops over [model_name]_list context variable
    - Uses {% include "components/domain/_[model]_card.html" %}
    - Includes _pagination.html at the bottom
    - If empty: {% include "components/ui/_empty_state.html" %}

  templates/components/domain/_[model]_card.html
    - The card for a single [ModelName] instance
    - hx-get on the card itself → navigates to detail page
    - Shows key metrics using _stat_card.html or _metric_pill.html components
    - Badge showing status via _badge.html component

Tailwind rules:
  - All interactive elements: min-h-[44px] for touch targets
  - Numbers: tabular-nums class
  - Status colours: flock-green (active/good), flock-amber (warning), flock-red (danger)
  - Card style: bg-white rounded-xl border border-earth-200 shadow-sm
```

### 10.2 Write a Create/Edit Form

```
Read these files first:
  1. skills/frontend_component_guide.md §4.4   (form submit pattern)
  2. skills/frontend_component_guide.md §7      (form components)
  3. templates/pages/batches/create.html         (reference form page)
  4. apps/[DOMAIN]/[APP_NAME]/serializers.py    (validation rules to respect in UI)

Write templates/pages/[app]/[create_or_edit].html

The form must:
  - Use hx-post="{{ url '[app]:[action]' }}"
  - Use hx-target="#[form-id]" hx-swap="outerHTML"
  - Use hx-indicator="#form-spinner" for loading state
  - Wrap each field with {% include "components/forms/_field.html" %}
  - Show non-field errors with {% include "components/forms/_form_errors.html" %}

For each field, include:
  - Correct field type (number/text/date/select)
  - help text for non-obvious fields
  - min/max/step attributes for numeric fields
  - ARIA label via the _field.html component

Submit button must:
  - Use hx-disabled-elt="this" to prevent double submit
  - Show spinner inside the button (htmx-indicator class)
  - Min height: min-h-[44px]

Cancel link: plain <a> back to list page — no HTMX
```

### 10.3 Write an HTMX Dashboard Widget

```
Read these files first:
  1. skills/frontend_component_guide.md §11  (dashboard layout patterns)
  2. skills/frontend_component_guide.md §9   (chart components)
  3. templates/pages/dashboard.html           (reference dashboard)

Write a dashboard widget for [FEATURE_NAME]:
  templates/partials/[feature]_widget.html

The widget must:
  - Be a self-refreshing HTMX partial:
    hx-get="{{ url '[feature]:widget' }}"
    hx-trigger="load, [trigger_event] from:body, every [N]m"
    hx-swap="innerHTML"
  - Use bg-white rounded-xl border border-earth-200 p-5 card styling
  - Show a loading state using htmx-indicator
  - Show data using _stat_card.html for numbers
  - If it includes a chart:
    canvas id="[widget]-chart"
    A placeholder div that's hidden once Chart.js renders
    The Chart.js init script at the bottom (NOT in a separate file)

Context variable expected from the view: [list the variables]
```

---

## 11. Celery Task Prompts

### 11.1 Write a Fan-Out Celery Beat Task

```
Read these files first:
  1. skills/system_architectures.md §7.3  (Pattern 2 — Fan-out task)
  2. apps/health/analytics/tasks.py       (reference fan-out implementation)
  3. apps/infrastructure/core/rls.py      (set_tenant_context, no_tenant_context)
  4. config/celery.py                     (Beat schedule and queue routing)

Write the [TASK_NAME] Celery task in apps/[DOMAIN]/[APP_NAME]/tasks.py

This task:
  - Runs on schedule: [CRON or INTERVAL] — queue: [QUEUE_NAME]
  - Fan-out pattern: one Beat task → one sub-task per active tenant
  - Does: [what the per-org sub-task does]

Generate two functions:
  1. [task_name]() — the Beat-triggered fan-out
     - Uses no_tenant_context() for the initial cross-tenant query
     - Queries only Organisation.id values (not tenant-scoped data)
     - Calls [per_org_task_name].delay(org_id) for each active org

  2. [per_org_task_name](org_id: str) — the per-org worker task
     - Uses set_tenant_context(org_id) to establish RLS context
     - max_retries=3, default_retry_delay=120
     - Calls [ServiceName](org).[method]() inside the context
     - Handles and logs exceptions — never silently swallows them

Add to config/celery.py setup_periodic_tasks():
  sender.add_periodic_task(
      [schedule],
      "[app_label].[task_name]",
      name="[human readable name]"
  )

Add to config/celery.py task_routes:
  "[app_label].[task_name]": {"queue": "[QUEUE_NAME]"},
  "[app_label].[per_org_task_name]": {"queue": "[QUEUE_NAME]"},
```

### 11.2 Write a Signal-Triggered Celery Task

```
Read these files first:
  1. skills/system_architectures.md §7.3  (Pattern 3 — Signal-triggered task)
  2. apps/farm/flocks/signals.py           (reference signal implementation)
  3. apps/health/analytics/tasks.py        (reference task)

Write a signal in apps/[DOMAIN]/[APP_NAME]/signals.py that triggers
an async Celery task when [MODEL] is [SIGNAL — post_save/post_delete/etc.].

The signal must:
  - Pass ONLY primitive values to the task (str UUIDs, not model instances)
  - Pass org_id explicitly — the task re-establishes RLS context itself
  - Use .delay() not .apply_async() unless you need countdown/eta
  - Guard with `if created:` for post_save if it should only fire on creation
  - NOT call the task synchronously — it must be fire-and-forget

The task in apps/[DOMAIN]/[APP_NAME]/tasks.py must:
  - Accept (record_id: str, org_id: str) as arguments
  - Use set_tenant_context(org_id) before any DB access
  - Call the relevant service method
  - Be registered in CELERY_TASK_ROUTES with queue="[QUEUE_NAME]"

Register the signal in apps/[DOMAIN]/[APP_NAME]/apps.py:
  def ready(self):
      import apps.[domain].[app_name].signals  # noqa: F401
```

---

## 12. Debugging Prompts

### 12.1 Diagnose an RLS Failure

```
I have an RLS-related bug. Here is the error/symptom:
[PASTE ERROR OR DESCRIBE SYMPTOM]

Read these files:
  1. apps/infrastructure/core/rls.py
  2. apps/infrastructure/core/middleware.py
  3. apps/infrastructure/core/models.py (TenantAwareManager)
  4. The migration for the affected model: [MIGRATION FILE PATH]

Diagnose this systematically:
  1. Is set_config('app.current_org_id', ...) being called before the query?
     Check the middleware and/or set_tenant_context call chain.
  2. Is the migration's enable_rls() call present for this table?
  3. Is the PostgreSQL user flockiq_user a SUPERUSER or BYPASSRLS?
     (Run: SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'flockiq_user')
  4. Is CONN_MAX_AGE = 0? Non-zero causes context to bleed across requests.
  5. Is this in a Celery task? If so, is set_tenant_context() wrapping the query?

Provide:
  a) The most likely root cause
  b) The exact fix
  c) A test to add to tests/rls/ that would have caught this
```

### 12.2 Diagnose an N+1 Query

```
I have an N+1 query issue in [VIEW OR SERVICE NAME].

Read:
  1. [FILE_PATH of the view or service]
  2. The relevant model files

To confirm it's N+1:
  1. Add DEBUG=True temporarily
  2. Reset queries: from django.db import reset_queries, connection; reset_queries()
  3. Execute the queryset
  4. Print: len(connection.queries) — if > [expected], it's N+1

Identify:
  1. Which related object access triggers the N+1 (usually a FK traversal in a loop)
  2. Whether select_related or prefetch_related is the right fix
     - select_related: FK traversal (one-to-one, many-to-one) — generates JOIN
     - prefetch_related: reverse FK, M2M, or conditional prefetch — generates IN query

Write the fix using select_related/prefetch_related.
Write the query count assertion test:
  tests/service/test_query_counts.py — add a test for this view with
  assert query_count <= [N] where N is the optimised count.
```

### 12.3 Diagnose an OutboxEvent Delivery Failure

```
OutboxEvent records are stuck in [PENDING / FAILED] status.

Read:
  1. apps/infrastructure/notifications/tasks.py
  2. apps/infrastructure/notifications/providers/[PROVIDER].py
  3. The stuck events: SELECT * FROM notifications_outboxevent
     WHERE status IN ('pending', 'failed') ORDER BY created_at LIMIT 10;

Diagnose:
  1. Check attempt_count — if it's at MAX_ATTEMPTS (5), it's permanently failed.
     Check last_error for the root cause.

  2. Check next_attempt_at — if it's in the future, backoff is working correctly.
     The event will be picked up on the next process_outbox run.

  3. Check if the Celery default worker is running:
     sudo supervisorctl status flockiq:celery_worker_default

  4. Check for provider-level errors in last_error:
     - "TIMEOUT" → Termii API unreachable — check TERMII_API_KEY in .env
     - "INVALID_RECIPIENT" → phone number format wrong — check E.164 format
     - "NO_RECIPIENT" → User.id in recipient_id doesn't exist
     - "DB_ERROR" → Database write failed — check for full disk

  5. To manually retry all stuck pending events:
     from apps.infrastructure.notifications.tasks import process_outbox
     process_outbox.delay()

Provide a root cause and fix. If the fix requires a code change, write it.
```

### 12.4 Debug a Failing Test

```
This test is failing:

[PASTE TEST NAME AND FULL TRACEBACK]

Read:
  1. The test file: [FILE_PATH]
  2. The code being tested: [SERVICE OR VIEW FILE PATH]
  3. tests/conftest.py (check the fixture chain for the failing test)

Diagnose step by step:
  1. Is the RLS context set for this test? Check if set_rls_context is in the
     fixture params. If not, that's likely why queries return empty.
  2. Is the factory creating valid data? Add a print(factory_instance.__dict__)
     to verify the created object.
  3. Is there a transaction isolation issue? The test uses pytest.mark.django_db
     which wraps in a transaction — check if the code relies on committed data.
  4. Is the test order-dependent? Run with pytest --randomly-seed=0 to check.
  5. Is a monkeypatch not cleaning up? Check for autouse fixtures that might
     affect this test.

Fix the test and explain why it was failing.
Do NOT weaken the assertion to make the test pass — fix the root cause.
```

---

## 13. Refactoring Prompts

### 13.1 Extract Business Logic from a View

```
Read apps/[DOMAIN]/[APP_NAME]/views.py.

This view has business logic in it that violates the service layer rule
(system_architectures.md §3.3). Specifically:
  [DESCRIBE THE LOGIC IN THE VIEW — e.g. "it directly creates FeedMovement records
   and calls a Celery task instead of delegating to FeedService"]

Refactor:
  1. Extract the logic into a new method on [ServiceName] in services.py
     Method name: [method_name]
     Arguments: [params derived from the view's request.data]
     Returns: [the created/modified model instance]

  2. Simplify the view to: validate → call service → return response
     The view should have no ORM access after refactoring

  3. Write tests for the extracted service method following tests/service/test_batch_service.py

Rules:
  - Do not change the API response shape (api_contract.md §[SECTION] is the spec)
  - Do not change URL patterns
  - Keep all existing tests passing — only add new tests for the service method
```

### 13.2 Convert a Redirect-on-Success View to HTMX Pattern

```
Read:
  1. skills/frontend_component_guide.md §4.1 (The Three HTMX Rules)
  2. apps/[DOMAIN]/[APP_NAME]/views.py (the view to convert)
  3. templates/pages/[app]/[template].html (the template to update)

This view currently:
  - On success: returns HttpResponseRedirect(reverse('[url_name]'))
  - On failure: re-renders the template with form errors

Convert to HTMX pattern:
  1. On success (HTMX request): return self.htmx_redirect(reverse('[url_name]'))
     On success (non-HTMX): keep the existing redirect
  2. On failure (HTMX): return the form fragment at status=422
     (422 prevents HTMX from pushing the failed state into browser history)
  3. Add HtmxMixin to the view's inheritance chain

Update the template:
  1. Add hx-post="{{ url '[url_name]' }}" to the form tag
  2. Add hx-target="#[form-id]" hx-swap="outerHTML" to the form tag
  3. Add hx-indicator="#form-spinner" to the form tag
  4. Add the spinner inside the submit button

Verify existing non-HTMX tests still pass after the change.
Add one HTMX-specific test to tests/htmx/test_htmx_partials.py.
```

---

## 14. Anti-Patterns to Avoid

Tell Claude Code explicitly **not** to do these things. Include them in your prompts as constraints when relevant.

### 14.1 The Forbidden Patterns List

```
NEVER do these — add this block to prompts when working on models/services/views:

DO NOT:
  ✗ Put business logic in models.py (properties/methods that write to DB)
  ✗ Put ORM queries in views.py (views call services; services call ORM)
  ✗ Import other app's services at module level (use inline imports)
  ✗ Use transaction.atomic() inside a Celery task without set_tenant_context
  ✗ Set CONN_MAX_AGE to anything other than 0
  ✗ Use CASCADE on deletes for tenant data (use PROTECT)
  ✗ Create a new TenantAwareModel without enable_rls() in its migration
  ✗ Call NotificationService outside of a transaction.atomic() block
  ✗ Use offset-based pagination (always cursor-based via FlockIQCursorPagination)
  ✗ Return a redirect from a POST that will be called by HTMX
  ✗ Use float literals for Decimal fields — always Decimal("1.820"), never 1.82
  ✗ Skip the idempotency_key on OutboxEvent creation
  ✗ Query tenant-scoped models in Celery without set_tenant_context
  ✗ Use DEBUG=True in any settings file other than development.py
  ✗ Hardcode API keys — always settings.TERMII_API_KEY etc.
  ✗ Use .all() in Celery fan-out tasks — query org IDs only with no_tenant_context
  ✗ Inline Chart.js data as Python objects — always json.dumps() + |safe filter
  ✗ Use select_for_update() without skip_locked=True on polling queries
  ✗ Add migrations with atomic=True for CREATE INDEX CONCURRENTLY
```

### 14.2 When Claude Code Drifts — Correction Prompts

```
# If Claude generates business logic in a view:
"Stop. Read apps/farm/flocks/services.py and services.py line 1.
This logic must live in [ServiceName] in services.py.
Move everything between 'validate' and 'return Response' into a service method.
The view should be 5 lines: get serializer → validate → call service → return response."

# If Claude uses a raw DB query without RLS context:
"Stop. This query runs without tenant context — it will return empty rows in production.
Wrap the DB access in set_tenant_context(org_id) from apps/infrastructure/core/rls.py.
Read the existing task at apps/health/analytics/tasks.py for the correct pattern."

# If Claude skips the migration RLS step:
"The migration is incomplete. Every new TenantAwareModel table requires RLS.
Add these lines at the end of the migration's operations list:
  from apps.infrastructure.core.migrations.rls_helpers import enable_rls
  operations += enable_rls('[table_name]')
where table_name is [app_label]_[modelname_lowercase]."

# If Claude puts cross-app imports at module level:
"Stop. Read system_architectures.md §3.4 Rule 5.
Move the import of [AppName]Service inside the method body.
Module-level cross-app imports create circular import errors at startup."

# If Claude generates a test that weakens an assertion to pass:
"Do not change the assertion. Find why the code is wrong and fix the code.
A passing test with a weak assertion is worse than a failing test — it gives
false confidence while hiding a real bug."
```

---

## 15. Sprint Checklists

### 15.1 Before Starting Each App

```
[ ] Read the app's section in skills/system_architectures.md §2 (app structure table)
[ ] Read the relevant api_contract.md sections for this app's endpoints
[ ] Identify which reference app to follow (usually the most similar completed app)
[ ] Confirm which existing services this app calls (LedgerService? NotificationService?)
[ ] Confirm which models this app's models FK into (Batch? Farm? Organization?)
[ ] Check if this app needs Celery tasks — if so, which queue?
[ ] Check if this app fires notifications — if so, which event types?
```

### 15.2 After Each Claude Code Output

```
[ ] Read the generated code — don't blindly accept it
[ ] Check: does every new model inherit TenantAwareModel?
[ ] Check: does every migration end with enable_rls()?
[ ] Check: are all cross-app imports inline (inside methods, not at module top)?
[ ] Check: are all service methods wrapped in transaction.atomic()?
[ ] Check: are Decimal values using Decimal("...") not bare floats?
[ ] Run: pytest tests/rls/test_rls_isolation.py -q
[ ] Run: python manage.py migrate --check
[ ] Run: python manage.py verify_rls_policies
[ ] Run the generated tests: pytest tests/[test_file] -q
```

### 15.3 End-of-Sprint Verification

```
[ ] Full test suite passes: pytest tests/ --ignore=tests/integration/ -q
[ ] Coverage meets targets: pytest --cov=apps --cov-fail-under=80
[ ] No unapplied migrations: python manage.py migrate --check
[ ] RLS on all models: python manage.py verify_rls_policies
[ ] Security check: python manage.py check --deploy
[ ] No hardcoded secrets: git grep -rn "api_key\|password\|secret" apps/ -- '*.py' | grep -v settings
[ ] All Celery tasks registered in config/celery.py routes
[ ] All URL patterns registered in config/urls.py
[ ] Smoke test against staging: pytest tests/ -m "smoke" -v
```

### 15.4 App Build Order for the 12-Hour Sprint

Respect this order — later apps depend on earlier ones.

```
Hour 1–2:  infrastructure/core (models, ledger, calculator, RLS helpers)
            infrastructure/tenants
            infrastructure/accounts

Hour 3:    farm/farms
            farm/flocks  ← most complex; BatchService is the core

Hour 4:    production/feed
            production/water
            production/waste

Hour 5:    production/production (egg logs, hen-day %, crate inventory)

Hour 6:    health/health (vaccinations, medications, biosecurity)

Hour 7:    health/analytics (Prophet, anomaly detection, DiagnosisService)

Hour 8:    finance/expenses
            finance/finance (LedgerService integration, P&L)

Hour 9:    infrastructure/notifications (OutboxEvent, providers, Beat task)
            infrastructure/billing (Paystack, CycleSubscription)

Hour 10:   farm/tasks (daily task generation, completion tracking)
            farm/weather (OpenWeatherMap, Redis cache, alerts)
            finance/market (seasonal alerts, ROI calculator)

Hour 11:   HTMX templates — dashboard + batch detail + quick log forms

Hour 12:   Tests, RLS verification, smoke test against staging
```

---

*End of FlockIQ Claude Code Guide v1.0*

---

## Complete Skills Document Chain

| # | File | Size | Purpose |
|---|---|---|---|
| 1 | `skills/system_architectures.md` | ~2,200 lines | Core engines, RLS, service patterns |
| 2 | `skills/deployment_runbook.md`   | ~1,850 lines | Server setup, CI/CD, incident response |
| 3 | `skills/api_contract.md`         | ~2,440 lines | 28 endpoint groups, serializer contracts |
| 4 | `skills/frontend_component_guide.md` | ~2,120 lines | HTMX + Tailwind + Alpine patterns |
| 5 | `skills/testing_guide.md`        | ~2,970 lines | pytest, factories, RLS test patterns |
| 6 | `skills/claude_code_guide.md`    | This file    | AI-assisted development patterns |

**Total documentation:** ~13,600 lines across six files covering every layer of the system.
