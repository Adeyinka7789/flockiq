# FlockIQ — AI-Powered Poultry Farm Management

FlockIQ is a multi-tenant SaaS platform purpose-built for Nigerian and West African poultry farmers. It replaces paper logbooks with breed-specific AI benchmarking, predictive analytics, and a structured financial ledger that produces a bankable **Farm Credit Score** — helping farmers access input loans and feed credit they previously could not qualify for.

The platform serves commercial broiler and layer operations of any scale: a single-house smallholder recording 500 birds manually on a smartphone, and a multi-farm integrator with 50,000 birds tracked by a team across multiple locations. Every account is isolated through PostgreSQL Row-Level Security, so data from one farm organisation is physically unreachable by any other — even under application bugs.

FlockIQ is built and maintained by **ADM Tech Hub**, Lagos, Nigeria.

---

## Overview

| | |
|---|---|
| **Target users** | Poultry farmers, farm managers, agri-finance officers, extension workers |
| **Geography** | Nigeria (primary), West Africa |
| **Languages** | English (French and Spanish in progress) |
| **Currency** | Nigerian Naira (₦) |
| **Timezone default** | Africa/Lagos (WAT, UTC+1) |
| **Deployment** | Single-server VPS (TrueHost / Hetzner) behind Nginx + PgBouncer |

### Key Differentiators

- **Row-Level Security at the database layer** — tenant isolation that cannot be bypassed by application code bugs.
- **Breed-specific calculation engine** — FCR, hen-day %, and water requirements use Cobb 500, Ross 308, Hy-Line Brown, and ISA Brown standards from published breed guides.
- **Farm Memory AI** — Prophet time-series forecasting and Z-score/IQR anomaly detection run nightly across all active batches, with SMS alerts via Termii.
- **Farm Credit Score** — a six-component weighted score (0–100) with a downloadable PDF report, designed to support loan applications.
- **Market Intelligence** — crowdsourced feed prices and a rated hatchery directory contributed by the farming community.
- **Offline-first PWA** — Service Worker + IndexedDB sync with full server-side idempotency, so data logged without connectivity is never lost or duplicated.

---

## Tech Stack

### Backend

| Component | Technology |
|---|---|
| Web framework | Django 5.1 |
| REST API | Django REST Framework 3.15 + drf-spectacular 0.27 |
| Authentication | JWT (djangorestframework-simplejwt 5.x) |
| Task queue | Celery 5.4 + django-celery-beat 2.7 |
| Database | PostgreSQL 16 with Row-Level Security |
| Connection pooler | PgBouncer (transaction mode, `CONN_MAX_AGE = 0`) |
| Cache / broker | Redis 7.x (DB 1: Celery + cache, DB 2: sessions) |
| Feature flags | django-waffle 4.1 |
| Brute-force protection | django-axes 6.5 |
| Audit logging | django-auditlog 3.0 |
| Structured logging | structlog + django-structlog 8 |

### Frontend

| Component | Technology |
|---|---|
| Partial-page updates | HTMX 2.x |
| Reactive UI | Alpine.js |
| Styling | Tailwind CSS 3.x |
| Charts | Chart.js |
| Forms | django-crispy-forms + crispy-tailwind |

### AI / ML

| Component | Technology |
|---|---|
| Egg production forecasting | Facebook Prophet 1.1 |
| Anomaly detection | scikit-learn 1.5 + NumPy 1.26 (Z-score / IQR ensemble) |
| Data processing | pandas 2.2 |

### Integrations

| Service | Purpose |
|---|---|
| **Paystack** | Subscription billing and payment processing |
| **Termii** | SMS notifications to Nigerian farm managers |
| **OpenWeatherMap** | Weather data for water requirement adjustments |
| **Sentry** | Real-time error tracking |
| **Papertrail** | Centralised log aggregation via syslog |
| **Django Silk** | Query profiling (development only) |

### Infrastructure

| Component | Technology |
|---|---|
| Web server | Nginx |
| WSGI server | Gunicorn |
| Process manager | Supervisor |
| SSL | Let's Encrypt (Certbot, wildcard cert for `*.flockiq.com`) |
| OS | Ubuntu 24.04 LTS |
| Exports | ReportLab 4.2 (PDF), openpyxl 3.1 (Excel) |

---

## Architecture

### Multi-Tenant with PostgreSQL Row-Level Security

Every tenant-scoped database table has a PostgreSQL RLS policy:

```sql
CREATE POLICY tenant_isolation ON flocks_batch
    USING (org_id = current_setting('app.current_org_id', TRUE)::uuid);
```

The `app.current_org_id` session variable is set at the start of every HTTP request by `TenantMiddleware` and at the start of every Celery task via the `set_tenant_context()` context manager. If the variable is unset, all queries against tenant tables return zero rows — no error, no data leak.

Isolation is enforced at two independent layers:

| Layer | Mechanism |
|---|---|
| PostgreSQL | RLS policy returns zero rows if `app.current_org_id` is unset or wrong |
| Django ORM | `TenantAwareManager` filters `org=get_current_org()` and raises if org is None |

An ORM bug cannot leak cross-tenant data because the DB will silently return nothing. An RLS misconfiguration is caught by the ORM filter.

### Application Structure

```
apps/
├── infrastructure/
│   ├── core/         # Base models, RLS context, calculator engine, credit scoring
│   ├── tenants/      # Organisation model, subdomain routing, trial enforcement
│   ├── accounts/     # CustomUser, JWT auth, email verification, impersonation
│   ├── notifications/ # Outbox pattern, Termii SMS, SMTP, in-app delivery
│   └── billing/      # Paystack integration, plan management, webhook log
├── farm/
│   ├── farms/        # Farm and House models
│   ├── flocks/       # Batch lifecycle, mortality log, weight records
│   ├── tasks/        # Daily task generation and tracking
│   └── weather/      # OpenWeatherMap cache, weather alerts
├── production/
│   ├── production/   # Egg production logs, harvest tracking
│   ├── feed/         # Feed log, inventory, FeedPrice submissions
│   ├── water/        # Water consumption log
│   └── waste/        # Waste log
├── health/
│   ├── health/       # Vaccinations, medication records, health events
│   └── analytics/    # Prophet forecasting, anomaly detection, sale timing
└── finance/
    ├── expenses/     # Expense records
    ├── finance/      # Sales records, P&L summaries, Farm Credit Score model
    └── market/       # Feed price reports, Hatchery directory, HatcheryReview
```

### Notification Architecture (Outbox Pattern)

Notifications are created atomically with domain writes inside the same `transaction.atomic()` block. If the HTTP request aborts before commit, neither the domain record nor the notification exists. A Celery Beat task runs every 30 seconds to drain the outbox:

```
[Domain Service]
      │ NotificationService(org).send(event)
      ▼
[PostgreSQL: notifications_outboxevent]
      ▲ polls every 30s (SELECT FOR UPDATE SKIP LOCKED)
[Celery Beat: process_outbox]
      │
      ├── TermiiProvider (SMS)
      ├── SMTPProvider (Email)
      └── InAppProvider (DB record)
```

Failed deliveries retry with exponential backoff (30 s → 2 min → 8 min → 32 min → 2 h), up to 5 attempts.

### Celery Task Architecture

12 scheduled tasks run via Celery Beat:

| Schedule | Task |
|---|---|
| Midnight daily | Generate daily work tasks for all orgs |
| 01:00 daily | Recompute farm baselines from closed batches |
| 03:00 daily | Recompute Farm Credit Scores for all active orgs |
| Every 6 hours | Check mortality anomaly across all active batches |
| 06:15 daily | Run egg forecast for all active layer batches |
| 07:00 daily | Send vaccination reminders |
| 08:00 daily | Generate feed requirements for today |
| 08:00 daily | Send subscription expiry reminders |
| 08:30 daily | Send trial expiry reminders |
| Every 30 seconds | Process notification outbox |
| 18:00 daily | Send incomplete task report |
| Monthly (1st) | Process monthly billing cycle |

### PWA / Offline Support

A Service Worker intercepts write requests when offline and stores them in IndexedDB. When connectivity is restored, records are flushed to `POST /api/sync/`. The server uses the client-generated UUID (`client_id`) as an idempotency key — duplicate sync submissions for the same record are silently de-duplicated.

---

## Local Development Setup

### Prerequisites

| Requirement | Version |
|---|---|
| Python | 3.11 or 3.12 |
| PostgreSQL | 14–16 |
| Redis | 6+ |
| Node.js | 20.x (for Tailwind CSS build only) |
| Git | Any recent version |

### Installation

**1. Clone the repository**

```bash
git clone https://github.com/admtechhub/flockiq.git
cd flockiq
```

**2. Create and activate a virtual environment**

```bash
python -m venv venv
# macOS / Linux
source venv/bin/activate
# Windows
venv\Scripts\activate
```

**3. Install Python dependencies**

```bash
pip install -r requirements/development.txt
```

**4. Install Node dependencies and build Tailwind**

```bash
npm install
npm run build   # or: npx tailwindcss -o static/css/tailwind.css --minify
```

**5. Create PostgreSQL database and roles**

Connect to PostgreSQL as a superuser (`psql -U postgres`) and run:

```sql
-- Runtime role — used by Django at all times
CREATE USER flockiq_app WITH PASSWORD 'flockiq_dev_pass' NOSUPERUSER CREATEDB;

-- Migration role — temporarily granted SUPERUSER when running migrations
-- (RLS operations require superuser; see RUNBOOK.md for the procedure)
CREATE USER flockiq_admin WITH PASSWORD 'flockiq_admin_pass' SUPERUSER;

-- Create the database, owned by the runtime role
CREATE DATABASE flockiq_dev OWNER flockiq_app;
GRANT ALL PRIVILEGES ON DATABASE flockiq_dev TO flockiq_app;
```

> ⚠️ Never use `flockiq_admin` credentials in the production `.env`. The runtime user `flockiq_app` must be `NOSUPERUSER` to prevent accidental RLS bypass.

**6. Configure environment variables**

```bash
cp .env.example .env
```

Edit `.env` with your local values. At minimum, set:

```bash
SECRET_KEY=your-local-secret-key
DATABASE_URL=postgresql://flockiq_app:flockiq_dev_pass@localhost:5432/flockiq_dev
REDIS_URL=redis://127.0.0.1:6379/1

# Production only (use PgBouncer port 6432):
# DATABASE_URL=postgresql://flockiq_app:password@127.0.0.1:6432/flockiq
```

**7. Run migrations**

```bash
# Temporarily grant SUPERUSER for RLS operations (see RUNBOOK.md)
python manage.py migrate
```

**8. Seed the database**

```bash
python manage.py seed_billing_plans    # creates Trial, Monthly, Cycle, Yearly plans
python manage.py seed_alert_rules      # creates default notification rules
python manage.py seed_celery_beat      # registers all 12 periodic tasks
python manage.py seed_hatcheries       # loads the hatchery directory
python manage.py create_test_tenant    # creates a sample org + superuser for development
```

**9. Start the development server**

```bash
python manage.py runserver
```

The application will be available at **http://localhost:8000**.

To run Celery (optional, required for background tasks):

```bash
# In a separate terminal
celery -A config worker -l info

# In another terminal (for scheduled tasks)
celery -A config beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
```

---

### Environment Variables

| Variable | Required | Description |
|---|---|---|
| `SECRET_KEY` | Yes | Django secret key — generate with `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"` |
| `DEBUG` | No | `True` for development, never `True` in production |
| `ALLOWED_HOSTS` | Yes | Comma-separated list of allowed hostnames (e.g., `flockiq.com,.flockiq.com`) |
| `DATABASE_URL` | Yes | PostgreSQL connection string — must use `flockiq_app` role. Dev: `postgresql://flockiq_app:pass@localhost:5432/flockiq_dev`. Production: `postgresql://flockiq_app:pass@127.0.0.1:6432/flockiq` (PgBouncer port 6432) |
| `REDIS_URL` | Yes | Redis connection string for Celery broker and default cache (DB 1) |
| `REDIS_SESSION_URL` | No | Redis connection for sessions only (DB 2). Defaults to DB 2 of `REDIS_URL` if unset |
| `PAYSTACK_SECRET_KEY` | Yes (prod) | Paystack secret key — starts with `sk_live_` in production |
| `PAYSTACK_PUBLIC_KEY` | Yes (prod) | Paystack public key — starts with `pk_live_` in production |
| `PAYSTACK_WEBHOOK_SECRET` | Yes (prod) | HMAC signature secret for Paystack webhook verification |
| `TERMII_API_KEY` | Yes (prod) | Termii SMS gateway API key |
| `TERMII_SENDER_ID` | No | Termii sender ID displayed on SMS (default: `FlockIQ`) |
| `OPENWEATHERMAP_API_KEY` | Yes (prod) | OpenWeatherMap API key for weather cache |
| `SENTRY_DSN` | No | Sentry error tracking DSN. Leave empty to disable Sentry |
| `ADMIN_EMAIL` | Yes | Email address for admin notifications and `DEFAULT_FROM_EMAIL` fallback |
| `SUPPORT_EMAIL` | Yes | Support contact email shown to users |
| `SUPPORT_PHONE` | No | Support phone number shown to users (default: `+234 000 000 0000`) |
| `SITE_URL` | Yes | Full base URL of the deployment (e.g., `https://app.flockiq.com`) |
| `PAPERTRAIL_HOST` | No | Papertrail syslog host (e.g., `logs.papertrailapp.com`) |
| `PAPERTRAIL_PORT` | No | Papertrail syslog UDP port |
| `DJANGO_ENV` | No | Environment name reported to Sentry (`production`, `staging`, `development`) |
| `GIT_COMMIT_SHA` | No | Git commit SHA set by CI/CD pipeline; used as the Sentry release identifier |
| `EMAIL_HOST` | No | SMTP host (default: `mail.flockiq.com` — Truehost cPanel) |
| `EMAIL_PORT` | No | SMTP port (default: `465` — SSL) |
| `EMAIL_USE_SSL` | No | Use SSL for SMTP (default: `True`) |
| `EMAIL_HOST_USER` | No | SMTP username (e.g. `noreply@flockiq.com`) |
| `EMAIL_HOST_PASSWORD` | No | SMTP password |
| `SERVER_EMAIL` | No | From address for error emails (default: `errors@flockiq.com`) |
| `CSRF_TRUSTED_ORIGINS` | Yes (prod) | Comma-separated origins for CSRF protection (e.g., `https://flockiq.com,https://app.flockiq.com`) |
| `IMPERSONATION_MAX_SECONDS` | No | Max duration of a superadmin impersonation session in seconds (default: `1800`) |
| `ENABLE_SILK` | No | Set to `True` to enable Django Silk query profiling (development only) |

---

## Running Tests

### Run the full test suite

```bash
pytest
```

The `pytest.ini` configuration applies `--cov=apps --cov-fail-under=75 --cov-report=term-missing` automatically. Tests fail if total coverage falls below **75%**.

### Run with verbose output

```bash
pytest -v --tb=short
```

### Run only the RLS isolation tests (run after every model change)

```bash
pytest tests/rls/test_rls_isolation.py -v
```

This is the most critical test suite. It spins up two separate tenant organisations and verifies that a query authenticated as Tenant A returns zero rows from Tenant B's tables — confirming that RLS policies are correctly applied on every tenant-scoped table.

### Coverage by app group

| App Group | Minimum Coverage |
|---|---|
| `apps/infrastructure/core/` | 95% |
| `apps/infrastructure/notifications/` | 90% |
| `apps/farm/flocks/` | 85% |
| `apps/production/` | 80% |
| `apps/health/analytics/` | 80% |
| `apps/finance/` | 85% |
| All views | 75% |

### Why PostgreSQL is required (not SQLite)

FlockIQ's RLS tests use PostgreSQL-specific SQL (`SET LOCAL app.current_org_id`, `CREATE POLICY`, `ENABLE ROW LEVEL SECURITY`). SQLite does not support these features. Tests will fail immediately with a database error if run against SQLite.

Always configure a real PostgreSQL instance in your test environment. The `pytest.ini` points to `config.settings.development`, which reads `DATABASE_URL` from your `.env` (e.g. `postgresql://flockiq_app:pass@localhost:5432/flockiq_dev`).

---

## Database Roles

| Role | Superuser | Used For |
|---|---|---|
| `flockiq_app` | NO (`NOSUPERUSER`) | Django runtime — all application queries via ORM |
| `flockiq_admin` | YES (`SUPERUSER`) | Migrations, fixtures, seeding, manual maintenance |
| `postgres` | YES | Emergency access only |

### When to use `flockiq_admin`

Any operation that must bypass RLS:

- `python manage.py migrate`
- `python manage.py loaddata`
- `python manage.py seed_*`
- `python manage.py createsuperuser`

**Procedure (development):**

```sql
-- In psql as postgres:
ALTER USER flockiq_app SUPERUSER;
-- Run the management command
ALTER USER flockiq_app NOSUPERUSER;
```

**Never** use `flockiq_admin` credentials in the production `DATABASE_URL`. The application must run as `flockiq_app` (non-superuser) at all times.

---

## CI/CD Pipeline

The project uses GitHub Actions. The workflow (`ci.yml`) runs on every push and pull request to `main`:

**Stages:**

| Stage | Steps |
|---|---|
| **Test** | Start PostgreSQL 16 and Redis 6 service containers; install dependencies; run `pytest --cov-fail-under=75` |
| **Security Audit** | Run `pip-audit` to check for known CVEs in `requirements/base.txt`; fail if any critical CVEs are found |
| **Deploy** | SSH to the VPS; pull the latest commit; run `migrate`, `collectstatic`, and reload Gunicorn (zero-downtime via `kill -HUP`) |

Deployment only runs on pushes to `main` with a passing test stage. PRs from feature branches run tests only.

**Deployment window:** Preferred between 01:00–03:00 WAT to avoid Celery Beat task overlap. The pipeline respects this window by default.

---

## API Documentation

API documentation is available in development mode at:

| URL | Description |
|---|---|
| `/api/docs/` | Swagger UI — interactive browser with "Authorize" for JWT tokens |
| `/api/redoc/` | ReDoc — clean read-only documentation |
| `/api/schema/` | Raw OpenAPI 3.0 JSON/YAML schema |

In production, API docs are not publicly exposed.

### Authentication

The REST API uses **JWT Bearer tokens**:

```bash
# Obtain a token
curl -X POST https://app.flockiq.com/api/auth/token/ \
  -H "Content-Type: application/json" \
  -d '{"email": "you@example.com", "password": "yourpassword"}'

# Use the token
curl https://app.flockiq.com/api/batches/ \
  -H "Authorization: Bearer <access_token>"
```

| Token | Lifetime |
|---|---|
| Access token | 8 hours |
| Refresh token | 30 days (rotates on use) |

Refresh tokens are blacklisted on rotation — a stolen refresh token cannot be used after the legitimate client has rotated it.

---

## Project Structure

```
flockiq/
├── apps/
│   ├── infrastructure/
│   │   ├── core/          # Base classes, RLS engine, calculator, credit scoring, ledger
│   │   ├── tenants/       # Organisation model, tenant middleware, onboarding, domain verification
│   │   ├── accounts/      # CustomUser, JWT views, email verification, impersonation
│   │   ├── notifications/ # Outbox model, Termii/SMTP/in-app providers, Celery delivery tasks
│   │   └── billing/       # BillingPlan, Paystack webhook, PaymentRecord, CycleSubscription
│   ├── farm/
│   │   ├── farms/         # Farm and House models, farm-level analytics
│   │   ├── flocks/        # Batch lifecycle, MortalityLog, WeightRecord, DOC sourcing
│   │   ├── tasks/         # DailyTask, TaskTemplate, task generation service
│   │   └── weather/       # WeatherCache, OpenWeatherMap client, weather alerts
│   ├── production/
│   │   ├── production/    # EggProductionLog, harvest tracking
│   │   ├── feed/          # FeedLog, FeedStock, FeedMovement, feed inventory
│   │   ├── water/         # WaterLog, water anomaly detection
│   │   └── waste/         # WasteLog
│   ├── health/
│   │   ├── health/        # VaccinationSchedule, VaccinationRecord, MedicationRecord
│   │   └── analytics/     # ForecastResult, AnomalyRecord, SaleTimingRecommendation, ProphetService
│   └── finance/
│       ├── expenses/      # ExpenseRecord, expense categories
│       ├── finance/       # SaleRecord, BatchFinancialSummary, FarmCreditScore, LedgerEntry
│       └── market/        # FeedPriceReport, Hatchery, HatcheryReview, MarketPrice
├── config/
│   ├── settings/
│   │   ├── base.py        # Shared settings for all environments
│   │   ├── development.py # Local dev overrides (DEBUG, Silk, eager Celery)
│   │   └── production.py  # Production overrides (HTTPS, CSP, HSTS, Gunicorn)
│   ├── urls.py            # Root URL configuration
│   ├── celery.py          # Celery app and beat schedule
│   └── wsgi.py
├── templates/             # Django templates (HTMX partials and full pages)
├── static/                # CSS (Tailwind), JavaScript (Alpine.js, Chart.js, SW)
├── tests/
│   ├── conftest.py        # Root fixtures (DB, two-tenant setup, user factories)
│   ├── factories.py       # factory-boy factories for all models
│   ├── unit/              # Pure logic tests — no DB, no HTTP
│   ├── integration/       # API and service tests — real DB
│   └── rls/               # Cross-tenant isolation tests — run after every model change
├── skills/                # Architecture specifications and developer guides
├── requirements/
│   ├── base.txt           # Production dependencies
│   └── development.txt    # Dev-only additions (django-extensions, etc.)
├── CLAUDE.md              # Claude Code project memory and architecture rules
├── RUNBOOK.md             # Ops runbook — database roles, Redis allocation, monitoring
├── pytest.ini             # pytest configuration
├── tailwind.config.js     # Tailwind CSS configuration
└── manage.py
```

---

## Contributing

### Branch Naming Convention

```
feature/<short-description>     # New functionality
fix/<short-description>         # Bug fix
refactor/<short-description>    # Code restructure without behaviour change
chore/<short-description>       # Tooling, dependencies, CI changes
```

### Commit Message Format

```
<type>: <short imperative summary>

<optional body — the WHY, not the what>
```

Types: `feat`, `fix`, `refactor`, `chore`, `docs`, `test`

Examples:

```
feat: add hatchery rating prompt on batch close
fix: prevent double mortality decrement in offline sync retry
chore: upgrade Prophet to 1.1.6
```

### Test Requirements

- All new model migrations on `TenantAwareModel` must call `enable_rls()`.
- New services must have service-layer unit tests.
- New API endpoints must have integration tests covering 200, 400, and 401 responses.
- After any migration change: `pytest tests/rls/test_rls_isolation.py -v` must pass.
- Overall coverage must not drop below 75%.

### Code Style

- **Business logic in `services.py` only** — never in `models.py` or `views.py`.
- **`structlog.get_logger()` everywhere** — never `logging.getLogger()`.
- **No comments explaining what the code does** — only comments explaining non-obvious WHY.
- `Black` for formatting, `isort` for imports.
- Maximum line length: 100 characters.

---

## License

Proprietary — © 2026 ADM Tech Hub. All rights reserved.

This software is not open source. Unauthorised copying, distribution, or use of this code — in whole or in part — is strictly prohibited without written permission from ADM Tech Hub.

For licensing inquiries: admin@flockiq.com
