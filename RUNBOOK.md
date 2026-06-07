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