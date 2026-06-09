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

## Redis DB allocation

| DB | Env var            | Used for                          |
|----|--------------------|-----------------------------------|
| 0  | —                  | reserved (Redis default)          |
| 1  | REDIS_URL          | Celery broker + general cache     |
| 2  | REDIS_SESSION_URL  | Sessions only                     |
| 3  | —                  | Celery results (prod: REDIS_URL/3)|

In production set (VPS environment / .env):

    REDIS_SESSION_URL=redis://127.0.0.1:6379/2

If unset, production.py defaults it to DB 2 of REDIS_URL.

### Why sessions get their own Redis DB
- Celery can flush or restart DB 1 without wiping user sessions on DB 2.
- Sessions are isolated from cache churn (TIMEOUT/eviction on DB 1).
- The `cached_db` session backend also writes every session to PostgreSQL,
  so a Redis failure degrades to a DB read — it does NOT log users out.

### Session backend per environment
- Local (development.py):  `db`        — pure PostgreSQL, no Redis dependency.
- Production (production.py): `cached_db` — Redis "sessions" cache + PostgreSQL fallback.

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