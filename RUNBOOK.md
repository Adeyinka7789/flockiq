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