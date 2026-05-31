# FlockIQ — Claude Code Project Memory

## What this project is
FlockIQ is a multi-tenant AI-powered poultry farm management SaaS for Nigerian
and West African farmers. Django 5.x + HTMX 2.x + PostgreSQL 16 with Row-Level Security.
Stack: Django · DRF · Celery · Redis · Prophet · scikit-learn · Tailwind · Alpine.js · Chart.js
Payments: Paystack | SMS: Termii | Weather: OpenWeatherMap | Server: TrueHost VPS

## Read these FIRST before generating any code
- skills/system_architectures.md
- skills/api_contract.md
- skills/deployment_runbook.md
- skills/frontend_component_guide.md
- skills/testing_guide.md
- skills/claude_code_guide.md

## Architecture non-negotiables — NEVER violate
1. Every tenant-scoped model inherits TenantAwareModel (apps/infrastructure/core/models.py)
2. Every migration on a TenantAwareModel must call enable_rls() (core/migrations/_rls_helpers.py)
3. All business logic in services.py ONLY — never in models.py or views.py
4. Cross-app coordination through LedgerService (apps/infrastructure/core/services.py)
5. Celery tasks must call set_tenant_context(org_id) before ANY DB query
6. Notifications created atomically with domain writes via NotificationService
7. CONN_MAX_AGE = 0 ALWAYS — PgBouncer transaction mode requires this
8. POST views return the updated HTMX fragment — NOT a redirect
9. django-waffle flags guard all AI/ML features
10. django-axes handles auth brute-force — no custom login rate limit logic
11. django-auditlog on: Batch, MortalityLog, EggProductionLog, SalesRecord
12. Use structlog.get_logger() everywhere — not logging.getLogger()

## App directory
apps/infrastructure/ → core, tenants, accounts, notifications, billing
apps/farm/           → farms, flocks, tasks, weather
apps/production/     → production, feed, water, waste
apps/health/         → health, analytics
apps/finance/        → expenses, finance, market

## Key file locations
- Base models:        apps/infrastructure/core/models.py
- Base service:       apps/infrastructure/core/services.py
- RLS context:        apps/infrastructure/core/rls.py
- Calculator engine:  apps/infrastructure/core/calculator.py
- Notification svc:   apps/infrastructure/notifications/services.py
- Test fixtures:      tests/conftest.py
- Test factories:     tests/factories.py

## Waffle flag names
- "ai_egg_forecast", "ai_anomaly_detection", "ai_theft_detection"
- "ai_sale_timing", "ai_symptom_diagnosis", "regional_disease_alerts"
- "weather_alerts", "pdf_export", "excel_export", "white_label"

## Celery Beat — 11 scheduled tasks
1. midnight daily     → generate_daily_tasks
2. every 6 hours      → refresh_weather_cache
3. 06:00 daily        → check_mortality_anomaly_all_orgs
4. 06:15 daily        → run_egg_forecast_all_active_batches
5. 07:00 daily        → send_vaccination_reminders
6. 08:00 daily        → generate_feed_requirements_today
7. every 30 seconds   → process_notification_outbox
8. 18:00 daily        → send_incomplete_task_report
9. weekly Sunday      → run_theft_detection_reconciliation
10. weekly Sunday     → generate_weekly_performance_summary
11. monthly 1st       → process_monthly_billing_cycle

## The most critical test — run after every model change
pytest tests/rls/test_rls_isolation.py -v
