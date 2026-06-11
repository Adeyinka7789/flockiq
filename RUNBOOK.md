# FlockIQ Operations Runbook

## Database Roles

| Role | Superuser | Used For |
|------|-----------|----------|
| flockiq_app | NO | Django runtime — all application queries |
| flockiq_admin | YES | Migrations, fixtures, seeding, maintenance |
| postgres | YES | Emergency only |

## When to use flockiq_admin

Any operation that bypasses RLS:
- python manage.py migrate
- python manage.py loaddata
- python manage.py seed_*
- python manage.py createsuperuser

## Procedure
1. In pgAdmin: ALTER USER flockiq_app SUPERUSER;
2. Run the operation
3. In pgAdmin: ALTER USER flockiq_app NOSUPERUSER;

## Production .env
DATABASE_URL must use flockiq_app credentials — never flockiq_admin.

    DJANGO_ADMIN_URL=your-random-string-here/

See "Django Admin" below.

## Django Admin
Admin URL is set via DJANGO_ADMIN_URL env var (settings.DJANGO_ADMIN_URL).
Default (development): /_platform-admin/
Production: set to a random string e.g. 'xK9mP2-admin/'
Keep this secret — it must never appear in templates (use
{% url 'admin:index' %}), sitemaps, robots.txt or client-side JS.
IP-allowlist it in nginx:

    location /your-admin-path/ {
        allow YOUR_IP;
        deny all;
        proxy_pass http://127.0.0.1:8000;
    }

## Redis DB allocation

Each concern gets a DEDICATED Redis DB. Never share — a Celery broker flush
on a shared DB would wipe every user session (this was a real misconfiguration:
broker and sessions both sat on DB 2 until June 2026).

| DB | Env var               | Used for                          |
|----|-----------------------|-----------------------------------|
| 0  | CELERY_BROKER_URL     | Celery broker (dedicated)         |
| 1  | REDIS_URL (+/1)       | General cache                     |
| 2  | REDIS_SESSION_URL     | Sessions only                     |
| 3  | CELERY_RESULT_BACKEND | Celery results                    |

In production set (VPS environment / .env):

    CELERY_BROKER_URL=redis://127.0.0.1:6379/0
    REDIS_SESSION_URL=redis://127.0.0.1:6379/2
    CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/3

If unset, production.py defaults broker to `{REDIS_URL}/0`, sessions to
`{REDIS_URL}/2` and results to `{REDIS_URL}/3` — the same safe layout.

### Why sessions get their own Redis DB
- Celery can flush or restart DB 1 without wiping user sessions on DB 2.
- Sessions are isolated from cache churn (TIMEOUT/eviction on DB 1).
- The `cached_db` session backend also writes every session to PostgreSQL,
  so a Redis failure degrades to a DB read — it does NOT log users out.

### Session backend per environment
- Local (development.py):  `db`        — pure PostgreSQL, no Redis dependency.
- Production (production.py): `cached_db` — Redis "sessions" cache + PostgreSQL fallback.

## PgBouncer Configuration

    [pgbouncer]
    pool_mode = transaction
    default_pool_size = 20        # per database
    max_client_conn = 100
    ; REQUIRED: Django sends statement/idle timeouts as a startup parameter
    ; (DATABASES OPTIONS "options" in production.py). Without this line
    ; PgBouncer rejects every connection.
    ignore_startup_parameters = options

FlockIQ's RLS requires `SET LOCAL` (transaction-scoped), which only works
correctly with `pool_mode = transaction` — do not change the pool mode.

### PostgreSQL timeouts
production.py sets per-connection:
- `statement_timeout=20000` (20s) — kills runaway queries
- `idle_in_transaction_session_timeout=30000` (30s) — frees connections held
  by a transaction that is waiting on something else (e.g. network I/O)

If PgBouncer cannot pass startup parameters for some reason, set the same
timeouts at the role level instead and remove the "options" key:

    ALTER ROLE flockiq_app SET statement_timeout = '20s';
    ALTER ROLE flockiq_app SET idle_in_transaction_session_timeout = '30s';

### WARNING: external HTTP calls pin connections
TenantMiddleware wraps every tenant request in one transaction (required for
SET LOCAL), so an external HTTP call inside a request handler (Paystack,
weather API, WeasyPrint generation) pins a PgBouncer backend connection for
its full duration. Keep external calls outside `set_tenant_context` blocks
where possible (see `billing/views.py PaystackCallbackView` for the pattern)
and keep `requests` timeouts short. Effective request concurrency is capped
at `default_pool_size` — size it against your gunicorn worker count.

## Custom domain onboarding (per tenant)

When a tenant verifies a custom domain (e.g. app.obasanjofarm.com), the
domain must ALSO be added to two env vars, then the app restarted:

    ALLOWED_HOSTS=flockiq.com,www.flockiq.com,.flockiq.com,app.obasanjofarm.com
    CSRF_TRUSTED_ORIGINS=https://flockiq.com,https://www.flockiq.com,https://*.flockiq.com,https://app.obasanjofarm.com

- ALLOWED_HOSTS is mandatory — without it Django rejects every request for
  the domain with a 400 before any middleware runs.
- CSRF_TRUSTED_ORIGINS covers cross-origin POSTs. (Same-origin POSTs pass
  Django's Origin check automatically once the host is allowed.)
- Settings cannot be mutated safely at runtime across gunicorn workers, so
  this is a deliberate restart-required step until domains move to a
  DB-backed allowlist.

## Monitoring Stack

| Tool         | Purpose             | URL                    |
|--------------|---------------------|------------------------|
| Sentry       | Error tracking      | sentry.io/flockiq      |
| UptimeRobot  | Uptime alerts       | uptimerobot.com        |
| Papertrail   | Log search          | papertrailapp.com      |
| Silk         | Query profiling     | /silk/ (local)         |
| Health check | Status endpoint     | /healthz/              |
| Ping         | Uptime monitor target | /ping/               |

### Sentry (error monitoring)
Initialised **once** in `config/settings/base.py` (guarded by `SENTRY_DSN`).
Do NOT add a second `sentry_sdk.init()` in `production.py`.

Production `.env`:

    SENTRY_DSN=https://xxx@xxx.ingest.sentry.io/xxx
    DJANGO_ENV=production
    GIT_COMMIT_SHA=        # set by CI/CD pipeline (used as the Sentry release)

Locally Sentry is disabled (`development.py` sets `SENTRY_DSN=""`).
404s are filtered out via `_sentry_before_send`; `send_default_pii=False` (GDPR).

### Health check / Ping (UptimeRobot)
- `GET /healthz/` — checks database, cache/Redis, and Celery beat. Returns
  `200 {"status":"ok",...}` when healthy, `503 {"status":"degraded",...}` if any
  critical system is down.
- `GET /ping/` — lightweight liveness probe, always `200`.

UptimeRobot setup:
- Monitor URL: https://flockiq.com/ping/
- Monitor type: HTTP(s)
- Interval: 5 minutes
- Alert: email + SMS

### Papertrail (log shipping)
Logs ship over syslog via the stdlib `SysLogHandler` — no extra pip package.
1. Create an account at papertrailapp.com
2. Add a system — get host and port (e.g. logs.papertrailapp.com:12345)
3. Set env vars:

       PAPERTRAIL_HOST=logs.papertrailapp.com
       PAPERTRAIL_PORT=12345

4. Logs searchable at papertrailapp.com/events

NOTE: `production.py` overrides `LOGGING` wholesale, so the Papertrail handler is
re-applied in BOTH `base.py` (dev/other envs) and `production.py`.

### Silk (query/request profiling)
- Local: http://localhost:8000/silk/ (always on — `development.py` sets
  `ENABLE_SILK=True`).
- Production: set `ENABLE_SILK=True` in the env temporarily, inspect slow
  queries at `/silk/`, then set it back to `False`.
- `/silk/` requires a logged-in **staff** user (`SILKY_AUTHENTICATION` /
  `SILKY_AUTHORISATION`).
- Run `python manage.py migrate` after first enabling Silk (creates its tables).

## WeasyPrint (PDF generation)
Requires native Pango libraries on the server:
  sudo apt-get install -y libpango-1.0-0 libpangoft2-1.0-0 libpangocairo-1.0-0
Run this during VPS setup before starting the application.

## User Manual PDF
- Cached for 24 hours in Redis (sessions cache, DB 2)
- First request of the day takes 3-5 seconds to generate
- To force regeneration: `python manage.py regenerate_user_manual`
- WeasyPrint requires libpango on Linux:
  `sudo apt-get install -y libpango-1.0-0 libpangoft2-1.0-0 libpangocairo-1.0-0`