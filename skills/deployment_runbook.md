# FlockIQ — Deployment Runbook
## `skills/deployment_runbook.md`

**Version:** 1.0  
**Date:** April 2026  
**Author:** ADM Tech Hub — Lead Systems Architecture  
**Companion to:** `skills/system_architectures.md`  
**Target Environment:** Ubuntu 24.04 LTS VPS, single-server deployment  
**Stack:** Python 3.12 · Django 5.x · PostgreSQL 16 · Redis 7.x · Celery 5.x · Nginx · Gunicorn · aaPanel  

---

## Table of Contents

1. [Pre-Deployment Checklist](#1-pre-deployment-checklist)
2. [Server Provisioning](#2-server-provisioning)
3. [PostgreSQL Setup & RLS Hardening](#3-postgresql-setup--rls-hardening)
4. [Redis Configuration](#4-redis-configuration)
5. [Application Deployment](#5-application-deployment)
6. [Gunicorn & Nginx Configuration](#6-gunicorn--nginx-configuration)
7. [Celery Workers & Beat](#7-celery-workers--beat)
8. [GitHub Actions CI/CD Pipeline](#8-github-actions-cicd-pipeline)
9. [SSL & Wildcard Certificate](#9-ssl--wildcard-certificate)
10. [Environment Variables Reference](#10-environment-variables-reference)
11. [Database Migration Protocol](#11-database-migration-protocol)
12. [Zero-Downtime Deployment Procedure](#12-zero-downtime-deployment-procedure)
13. [Monitoring & Alerting](#13-monitoring--alerting)
14. [Backup & Recovery](#14-backup--recovery)
15. [Incident Response Runbook](#15-incident-response-runbook)
16. [Rollback Procedure](#16-rollback-procedure)

---

## 1. Pre-Deployment Checklist

Run this checklist before **every** production deployment, including hotfixes. Check each box manually — do not automate this list away.

### 1.1 Code Readiness

```
[ ] All tests passing locally:  pytest --tb=short -q
[ ] No unapplied migrations:    python manage.py migrate --check
[ ] No missing migrations:      python manage.py makemigrations --check --dry-run
[ ] Security check passes:      python manage.py check --deploy
[ ] Static files collected:     python manage.py collectstatic --dry-run
[ ] No DEBUG=True in settings:  grep -r "DEBUG = True" config/settings/production.py
[ ] All secrets in .env, not in code: git diff --staged | grep -i "secret\|password\|api_key"
[ ] Dependency audit clean:     pip-audit (no critical CVEs in requirements.txt)
[ ] RLS migrations present:     grep -r "ROW LEVEL SECURITY" apps/*/migrations/*.py | wc -l
```

### 1.2 Infrastructure Readiness

```
[ ] VPS disk space > 20% free:  df -h /
[ ] PostgreSQL version = 16:    psql --version
[ ] Redis running:              redis-cli ping → PONG
[ ] Celery workers healthy:     celery -A config inspect ping
[ ] Nginx config valid:         nginx -t
[ ] SSL cert expiry > 30 days:  certbot certificates
[ ] Backups ran within 24h:     ls -lt /var/backups/flockiq/ | head -5
[ ] Staging deployment tested:  (green CI on staging branch)
```

### 1.3 Deployment Window

- **Preferred window:** 01:00–03:00 WAT (West Africa Time, UTC+1)
- **Reason:** Celery Beat daily tasks run at 1:00 AM — deploy AFTER they complete
- **Never deploy:** During the 18:00 incomplete-task-report window (18:00–18:05)
- **Never deploy:** When active WebSocket connections > 50 (check Nginx status page)

---

## 2. Server Provisioning

### 2.1 VPS Specifications

| Resource | Minimum | Recommended |
|---|---|---|
| CPU | 2 vCPU | 4 vCPU |
| RAM | 4 GB | 8 GB |
| Disk | 40 GB SSD | 80 GB SSD |
| OS | Ubuntu 24.04 LTS | Ubuntu 24.04 LTS |
| Bandwidth | 1 TB/mo | 2 TB/mo |
| Provider | TrueHost / Hetzner | Hetzner CX32 |

> **RAM breakdown (8 GB target):**  
> Gunicorn (4 workers × 200 MB) = 800 MB  
> PostgreSQL shared_buffers = 2 GB  
> Redis maxmemory = 1 GB  
> Celery (3 workers) = 600 MB  
> Prophet/scikit-learn peak = 1.5 GB  
> OS + overhead = 1.1 GB  
> **Total = ~7 GB** — comfortable on 8 GB

### 2.2 Initial Server Setup

```bash
# Run as root on fresh Ubuntu 24.04

# 1. Update system
apt update && apt upgrade -y

# 2. Create deploy user (never run the app as root)
adduser deploy
usermod -aG sudo deploy
# Copy your SSH public key
mkdir -p /home/deploy/.ssh
echo "YOUR_PUBLIC_KEY" >> /home/deploy/.ssh/authorized_keys
chmod 700 /home/deploy/.ssh
chmod 600 /home/deploy/.ssh/authorized_keys
chown -R deploy:deploy /home/deploy/.ssh

# 3. Harden SSH
sed -i 's/#PermitRootLogin yes/PermitRootLogin no/' /etc/ssh/sshd_config
sed -i 's/#PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
systemctl restart sshd

# 4. Firewall
ufw allow 22/tcp    # SSH
ufw allow 80/tcp    # HTTP (redirects to HTTPS)
ufw allow 443/tcp   # HTTPS
ufw deny 5432/tcp   # PostgreSQL — internal only
ufw deny 6379/tcp   # Redis — internal only
ufw enable

# 5. Install aaPanel (web-based server management)
wget -O install.sh https://www.aapanel.com/script/install_6.0_en.sh
bash install.sh aapanel
# Note the aaPanel login URL and credentials printed at the end

# 6. System packages
apt install -y git curl wget build-essential libpq-dev \
  python3.12 python3.12-venv python3.12-dev \
  postgresql-16 postgresql-client-16 \
  redis-server \
  nginx \
  supervisor \
  certbot python3-certbot-nginx \
  htop iotop ncdu fail2ban \
  libffi-dev libssl-dev

# 7. Install PgBouncer (connection pooler — required for 200+ tenant load)
apt install -y pgbouncer

# 8. Node.js (for Tailwind CSS build only — not runtime)
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt install -y nodejs
```

### 2.3 Application Directory Structure

```bash
# Run as deploy user
sudo mkdir -p /var/www/flockiq
sudo chown deploy:deploy /var/www/flockiq

# Create directory layout
mkdir -p /var/www/flockiq/{releases,shared,logs,backups}
mkdir -p /var/www/flockiq/shared/{media,staticfiles,.env}

# releases/ — each deployment is a timestamped directory
# shared/   — persists across deployments (media, static, .env)
# logs/     — Gunicorn + Celery logs
# backups/  — database dump staging area (before offsite transfer)
```

---

## 3. PostgreSQL Setup & RLS Hardening

### 3.1 PostgreSQL Configuration

```bash
# Edit /etc/postgresql/16/main/postgresql.conf
sudo nano /etc/postgresql/16/main/postgresql.conf
```

```ini
# Memory (tuned for 8 GB VPS)
shared_buffers          = 2GB           # 25% of RAM
effective_cache_size    = 6GB           # 75% of RAM
work_mem                = 16MB          # Per sort/hash operation
maintenance_work_mem    = 256MB         # VACUUM, CREATE INDEX

# Write performance
wal_buffers             = 64MB
checkpoint_completion_target = 0.9
wal_compression         = on

# Connection limits
max_connections         = 100           # PgBouncer handles the rest
superuser_reserved_connections = 3

# Logging (useful for slow query identification)
log_min_duration_statement = 500        # Log queries > 500ms
log_line_prefix         = '%t [%p]: [%l-1] user=%u,db=%d,app=%a,client=%h '
log_checkpoints         = on
log_lock_waits          = on
log_temp_files          = 0

# Performance
random_page_cost        = 1.1           # SSD: set close to 1
effective_io_concurrency = 200          # SSD: higher is better
```

```bash
# Edit /etc/postgresql/16/main/pg_hba.conf
sudo nano /etc/postgresql/16/main/pg_hba.conf
```

```
# TYPE  DATABASE        USER            ADDRESS         METHOD
# Local connections
local   all             postgres                        peer
local   all             all                             peer

# Application user — local socket only (no network exposure)
local   flockiq_db      flockiq_user                    md5

# PgBouncer — connects via local socket
local   flockiq_db      pgbouncer                       md5

# Reject all other connections
host    all             all             0.0.0.0/0       reject
```

```bash
sudo systemctl restart postgresql
```

### 3.2 Database & User Creation

```bash
sudo -u postgres psql
```

```sql
-- Create application database
CREATE DATABASE flockiq_db
    ENCODING 'UTF8'
    LC_COLLATE 'en_US.UTF-8'
    LC_CTYPE 'en_US.UTF-8'
    TEMPLATE template0;

-- Create application user (non-superuser — RLS always enforced)
CREATE USER flockiq_user WITH
    PASSWORD 'STRONG_RANDOM_PASSWORD_HERE'
    NOSUPERUSER
    NOCREATEDB
    NOCREATEROLE
    LOGIN;

-- Grant privileges
GRANT CONNECT ON DATABASE flockiq_db TO flockiq_user;
GRANT USAGE ON SCHEMA public TO flockiq_user;
GRANT CREATE ON SCHEMA public TO flockiq_user;     -- Required for migrations
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO flockiq_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO flockiq_user;

-- Verify: this user must NOT be able to bypass RLS
-- (superuser and BYPASSRLS role both bypass RLS — never grant these)
SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'flockiq_user';
-- Expected: rolsuper=false, rolbypassrls=false

\q
```

### 3.3 RLS Migration Helper

Every Django migration that creates a tenant-scoped model must include this operation. Add it to a `data_migrations/` app or directly in the model's initial migration.

```python
# apps/infrastructure/core/migrations/rls_helpers.py
# Import this in every migration that creates a tenant-scoped table.

def enable_rls(table_name: str) -> list:
    """
    Returns the RunSQL operations to enable RLS on a table.
    Call this at the END of the migration that creates the table.

    Usage in migration:
        operations = [
            migrations.CreateModel(...),
            *rls_helpers.enable_rls("flocks_batch"),
        ]
    """
    return [
        migrations.RunSQL(
            sql=f"""
                ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY;
                ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY;

                CREATE POLICY tenant_isolation ON {table_name}
                    USING (
                        org_id = current_setting('app.current_org_id', TRUE)::uuid
                    );
            """,
            reverse_sql=f"""
                DROP POLICY IF EXISTS tenant_isolation ON {table_name};
                ALTER TABLE {table_name} DISABLE ROW LEVEL SECURITY;
            """,
        )
    ]


def disable_rls_infrastructure(table_name: str) -> list:
    """
    For cross-tenant infrastructure tables only.
    Tables: weather_weathercache, notifications_outboxevent,
            tasks_tasktemplate, billing_billingplan
    Requires explicit justification comment in the migration file.
    """
    return [
        migrations.RunSQL(
            sql=f"ALTER TABLE {table_name} DISABLE ROW LEVEL SECURITY;",
            reverse_sql=f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY;",
        )
    ]
```

### 3.4 PgBouncer Configuration

```bash
sudo nano /etc/pgbouncer/pgbouncer.ini
```

```ini
[databases]
flockiq_db = host=/var/run/postgresql port=5432 dbname=flockiq_db user=flockiq_user

[pgbouncer]
listen_addr         = 127.0.0.1
listen_port         = 6432
auth_type           = md5
auth_file           = /etc/pgbouncer/userlist.txt

# Transaction mode: connection released after each transaction.
# Required for RLS set_config(..., TRUE) — transaction-local scope.
# Do NOT use session mode — the RLS variable would persist across requests.
pool_mode           = transaction

max_client_conn     = 500           # Max connections from Gunicorn + Celery
default_pool_size   = 20            # PostgreSQL connections per database
reserve_pool_size   = 5             # Emergency reserve
reserve_pool_timeout = 5

server_idle_timeout = 600
client_idle_timeout = 300

log_connections     = 0             # Reduce noise in production
log_disconnections  = 0
log_pooler_errors   = 1

# Admin interface (restricted to localhost)
admin_users         = pgbouncer
stats_users         = pgbouncer
```

```bash
# /etc/pgbouncer/userlist.txt
# "username" "md5hash_of_password"
# Generate with: echo -n "passwordusername" | md5sum → prepend "md5"
echo '"flockiq_user" "md5'$(echo -n "STRONG_RANDOM_PASSWORD_HEREflockiq_user" | md5sum | cut -d' ' -f1)'"' | sudo tee /etc/pgbouncer/userlist.txt

sudo systemctl enable pgbouncer
sudo systemctl start pgbouncer

# Verify
psql -h 127.0.0.1 -p 6432 -U flockiq_user flockiq_db -c "SELECT 1"
```

---

## 4. Redis Configuration

```bash
sudo nano /etc/redis/redis.conf
```

```ini
# Binding — local only, never expose to network
bind 127.0.0.1 ::1

# Memory management
maxmemory 1gb
maxmemory-policy allkeys-lru      # Evict least-recently-used keys under memory pressure
                                   # Safe for FlockIQ: all caches are regeneratable

# Persistence — RDB snapshot (AOF is overkill for a cache layer)
save 900 1       # Save if 1 key changed in 900 seconds
save 300 10      # Save if 10 keys changed in 300 seconds
save 60 10000    # Save if 10000 keys changed in 60 seconds
rdbcompression yes
rdbfilename dump.rdb
dir /var/lib/redis

# Security
requirepass REDIS_STRONG_PASSWORD_HERE
rename-command FLUSHALL ""         # Disable dangerous commands
rename-command FLUSHDB  ""
rename-command CONFIG   ""
rename-command DEBUG    ""

# Connection limits
maxclients 256
tcp-backlog 511

# Celery broker tuning
hz 15                              # Key expiry check frequency
tcp-keepalive 300
```

```bash
sudo systemctl enable redis-server
sudo systemctl restart redis-server
redis-cli -a REDIS_STRONG_PASSWORD_HERE ping  # → PONG
```

---

## 5. Application Deployment

### 5.1 Python Virtual Environment

```bash
# As deploy user
cd /var/www/flockiq

python3.12 -m venv venv
source venv/bin/activate

# Upgrade pip first
pip install --upgrade pip setuptools wheel

# Install dependencies
pip install -r requirements/production.txt
```

### 5.2 requirements/production.txt

```text
# Core
django==5.2.13
djangorestframework==3.15.2
djangorestframework-simplejwt==5.3.1
django-cors-headers==4.3.1

# Database
psycopg2-binary==2.9.9
django-redis==5.4.0

# Task queue
celery==5.3.6
redis==5.0.1
flower==2.0.1                  # Celery monitoring UI

# ML
prophet==1.1.5
scikit-learn==1.5.2
pandas==2.2.2
numpy==1.26.4

# HTTP / Async
gunicorn==21.2.0
httpx==0.27.0                  # For Termii, Paystack, OpenWeatherMap
requests==2.32.3

# Utilities
python-decouple==3.8           # .env file management
Pillow==10.3.0                 # Image handling
whitenoise==6.6.0              # Static file serving fallback
django-extensions==3.2.3

# Security
django-ratelimit==4.1.0
cryptography==42.0.5

# Monitoring
sentry-sdk[django]==2.7.0

# Dev tools (not in production — use requirements/development.txt)
# pytest-django, factory-boy, coverage, etc.
```

### 5.3 Django Production Settings

```python
# config/settings/production.py

from .base import *
from decouple import config, Csv

DEBUG = False
SECRET_KEY = config("DJANGO_SECRET_KEY")
ALLOWED_HOSTS = config("ALLOWED_HOSTS", cast=Csv())  # ['.flockiq.com']

# Database — connect via PgBouncer
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "HOST": "127.0.0.1",
        "PORT": "6432",             # PgBouncer port, not 5432
        "NAME": config("DB_NAME"),
        "USER": config("DB_USER"),
        "PASSWORD": config("DB_PASSWORD"),
        "CONN_MAX_AGE": 0,          # CRITICAL: 0 with PgBouncer transaction mode
                                    # Non-zero CONN_MAX_AGE leaks connections
        "OPTIONS": {
            "connect_timeout": 10,
            "application_name": "flockiq_web",
        },
    }
}

# Redis — separate logical databases per concern
REDIS_URL = config("REDIS_URL")  # redis://:password@127.0.0.1:6379

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": f"{REDIS_URL}/1",   # DB 1: Django cache
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            "SOCKET_CONNECT_TIMEOUT": 5,
            "SOCKET_TIMEOUT": 5,
            "IGNORE_EXCEPTIONS": True,   # Degrade gracefully if Redis is down
        },
        "KEY_PREFIX": "flockiq",
        "TIMEOUT": 300,
    }
}

CELERY_BROKER_URL           = f"{REDIS_URL}/2"    # DB 2: Celery broker
CELERY_RESULT_BACKEND       = f"{REDIS_URL}/3"    # DB 3: Celery results
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True

# Static & Media
STATIC_ROOT = "/var/www/flockiq/shared/staticfiles"
MEDIA_ROOT  = "/var/www/flockiq/shared/media"
STATIC_URL  = "/static/"
MEDIA_URL   = "/media/"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# Security headers
SECURE_SSL_REDIRECT          = True
SECURE_HSTS_SECONDS          = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD          = True
SECURE_PROXY_SSL_HEADER      = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_CONTENT_TYPE_NOSNIFF  = True
SECURE_BROWSER_XSS_FILTER    = True
X_FRAME_OPTIONS              = "DENY"
SESSION_COOKIE_SECURE        = True
CSRF_COOKIE_SECURE           = True
SESSION_COOKIE_HTTPONLY      = True

# Password hashing — bcrypt in production
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",  # Fallback for migrating existing hashes
]

# Sentry error tracking
import sentry_sdk
sentry_sdk.init(
    dsn=config("SENTRY_DSN", default=""),
    traces_sample_rate=0.1,         # 10% of transactions
    profiles_sample_rate=0.05,
    environment="production",
)

# Email
EMAIL_BACKEND   = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST      = config("EMAIL_HOST")
EMAIL_PORT      = config("EMAIL_PORT", cast=int, default=465)
EMAIL_HOST_USER = config("EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD")
EMAIL_USE_SSL   = True
DEFAULT_FROM_EMAIL = "FlockIQ <noreply@flockiq.com>"

# Logging
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {process:d} {thread:d} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "file": {
            "level": "WARNING",
            "class": "logging.handlers.RotatingFileHandler",
            "filename": "/var/www/flockiq/logs/django.log",
            "maxBytes": 10 * 1024 * 1024,  # 10 MB
            "backupCount": 5,
            "formatter": "verbose",
        },
        "celery_file": {
            "level": "INFO",
            "class": "logging.handlers.RotatingFileHandler",
            "filename": "/var/www/flockiq/logs/celery.log",
            "maxBytes": 10 * 1024 * 1024,
            "backupCount": 5,
            "formatter": "verbose",
        },
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "loggers": {
        "django": {"handlers": ["file"], "level": "WARNING", "propagate": False},
        "celery": {"handlers": ["celery_file"], "level": "INFO", "propagate": False},
        "apps":   {"handlers": ["file", "console"], "level": "INFO", "propagate": False},
        "notifications": {"handlers": ["file"], "level": "DEBUG", "propagate": False},
    },
}
```

---

## 6. Gunicorn & Nginx Configuration

### 6.1 Gunicorn

```bash
# /var/www/flockiq/shared/gunicorn.conf.py

import multiprocessing

# Workers: (2 × CPU cores) + 1 is standard
# On a 4-core VPS: 9 workers
workers             = (multiprocessing.cpu_count() * 2) + 1
worker_class        = "sync"            # Sync is correct for Django + PgBouncer
threads             = 1                 # 1 thread per sync worker
worker_connections  = 1000
timeout             = 120               # Prophet inference can take up to 5s; allow overhead
keepalive           = 5
graceful_timeout    = 30

# Binding
bind                = "unix:/run/gunicorn/flockiq.sock"   # Unix socket, not TCP
umask               = 0o007

# Logging
accesslog           = "/var/www/flockiq/logs/gunicorn_access.log"
errorlog            = "/var/www/flockiq/logs/gunicorn_error.log"
loglevel            = "warning"
access_log_format   = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Process naming
proc_name           = "flockiq"

# Worker restart on memory growth (prevents Prophet memory leaks)
max_requests        = 1000
max_requests_jitter = 100

# Pre-load app (faster worker startup; required for Prophet model caching)
preload_app         = True
```

```bash
# Create socket directory
sudo mkdir -p /run/gunicorn
sudo chown deploy:www-data /run/gunicorn
sudo chmod 770 /run/gunicorn
```

### 6.2 Nginx

```nginx
# /etc/nginx/sites-available/flockiq

# Rate limiting zones
limit_req_zone $binary_remote_addr zone=auth:10m rate=5r/m;
limit_req_zone $binary_remote_addr zone=api:10m  rate=100r/m;
limit_conn_zone $binary_remote_addr zone=conn:10m;

# Redirect HTTP → HTTPS
server {
    listen 80;
    server_name *.flockiq.com flockiq.com;
    return 301 https://$host$request_uri;
}

# Main application server
server {
    listen 443 ssl http2;
    server_name *.flockiq.com flockiq.com;

    # SSL — wildcard cert for all subdomains
    ssl_certificate     /etc/letsencrypt/live/flockiq.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/flockiq.com/privkey.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;
    ssl_session_cache   shared:SSL:10m;
    ssl_session_timeout 1d;
    ssl_stapling        on;
    ssl_stapling_verify on;

    # Security headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload" always;
    add_header X-Content-Type-Options    "nosniff" always;
    add_header X-Frame-Options           "DENY" always;
    add_header Referrer-Policy           "strict-origin-when-cross-origin" always;
    add_header Permissions-Policy        "geolocation=(), microphone=(), camera=()" always;

    # Connection limits
    limit_conn conn 50;

    client_max_body_size 20M;    # For batch photo uploads
    client_body_timeout  30s;
    client_header_timeout 10s;
    send_timeout         30s;

    # Logging
    access_log /var/www/flockiq/logs/nginx_access.log combined;
    error_log  /var/www/flockiq/logs/nginx_error.log warn;

    # Static files — served directly by Nginx (no Django)
    location /static/ {
        alias /var/www/flockiq/shared/staticfiles/;
        expires 1y;
        add_header Cache-Control "public, immutable";
        access_log off;
        gzip_static on;
    }

    # Media files
    location /media/ {
        alias /var/www/flockiq/shared/media/;
        expires 7d;
        add_header Cache-Control "private";
    }

    # PWA service worker — must not be cached
    location = /sw.js {
        alias /var/www/flockiq/shared/staticfiles/sw/sw.js;
        add_header Cache-Control "no-cache, no-store, must-revalidate";
        add_header Service-Worker-Allowed "/";
    }

    # PWA manifest
    location = /manifest.json {
        alias /var/www/flockiq/shared/staticfiles/manifest.json;
        add_header Cache-Control "public, max-age=3600";
    }

    # Auth endpoints — strict rate limit
    location ~ ^/api/(auth|token)/ {
        limit_req zone=auth burst=10 nodelay;
        include proxy_params;
        proxy_pass http://unix:/run/gunicorn/flockiq.sock;
    }

    # Sync endpoint — allow higher burst for offline sync batches
    location /api/sync/ {
        limit_req zone=api burst=20 nodelay;
        client_max_body_size 5M;    # Sync payloads can be large
        include proxy_params;
        proxy_pass http://unix:/run/gunicorn/flockiq.sock;
    }

    # Paystack webhook — no rate limit (Paystack IP whitelist handles this)
    location /api/billing/webhook/ {
        include proxy_params;
        proxy_pass http://unix:/run/gunicorn/flockiq.sock;
    }

    # All other API and web requests
    location / {
        limit_req zone=api burst=50 nodelay;
        include proxy_params;
        proxy_pass http://unix:/run/gunicorn/flockiq.sock;

        # Timeouts
        proxy_connect_timeout 10s;
        proxy_read_timeout    120s;     # Long-running dashboard requests
        proxy_send_timeout    30s;
    }
}
```

```bash
# /etc/nginx/proxy_params
proxy_set_header Host               $http_host;
proxy_set_header X-Real-IP          $remote_addr;
proxy_set_header X-Forwarded-For    $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto  $scheme;
proxy_redirect off;
proxy_buffering on;
proxy_buffer_size 4k;
proxy_buffers 8 4k;
```

```bash
sudo ln -s /etc/nginx/sites-available/flockiq /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

---

## 7. Celery Workers & Beat

### 7.1 Supervisor Configuration

Supervisor manages Gunicorn, Celery workers, and Celery Beat as system services with auto-restart on crash.

```ini
# /etc/supervisor/conf.d/flockiq.conf

[group:flockiq]
programs=gunicorn,celery_worker_default,celery_worker_ml,celery_beat


# ── Gunicorn ──────────────────────────────────────────────────────────────
[program:gunicorn]
command=/var/www/flockiq/venv/bin/gunicorn
        config.wsgi:application
        --config /var/www/flockiq/shared/gunicorn.conf.py
directory=/var/www/flockiq/current
user=deploy
environment=DJANGO_SETTINGS_MODULE="config.settings.production"
autostart=true
autorestart=true
startsecs=5
stopwaitsecs=30
stopasgroup=true
killasgroup=true
stderr_logfile=/var/www/flockiq/logs/gunicorn.err.log
stdout_logfile=/var/www/flockiq/logs/gunicorn.out.log


# ── Celery Default Worker ─────────────────────────────────────────────────
# Handles: notifications, tasks, weather, billing, sync
[program:celery_worker_default]
command=/var/www/flockiq/venv/bin/celery
        -A config
        worker
        --loglevel=info
        --concurrency=4
        --queues=default,notifications,weather,tasks
        --hostname=worker-default@%%h
        --max-tasks-per-child=200
directory=/var/www/flockiq/current
user=deploy
environment=DJANGO_SETTINGS_MODULE="config.settings.production"
autostart=true
autorestart=true
startsecs=10
stopwaitsecs=60
stopasgroup=true
killasgroup=true
stderr_logfile=/var/www/flockiq/logs/celery_default.err.log
stdout_logfile=/var/www/flockiq/logs/celery_default.out.log


# ── Celery ML Worker ──────────────────────────────────────────────────────
# Handles: Prophet forecasting, anomaly detection, symptom diagnosis
# Isolated because Prophet is memory-hungry; separate worker prevents OOM
[program:celery_worker_ml]
command=/var/www/flockiq/venv/bin/celery
        -A config
        worker
        --loglevel=info
        --concurrency=1
        --queues=ml
        --hostname=worker-ml@%%h
        --max-tasks-per-child=50
directory=/var/www/flockiq/current
user=deploy
environment=DJANGO_SETTINGS_MODULE="config.settings.production"
autostart=true
autorestart=true
startsecs=10
stopwaitsecs=120          ; Prophet cleanup can be slow
stopasgroup=true
killasgroup=true
stderr_logfile=/var/www/flockiq/logs/celery_ml.err.log
stdout_logfile=/var/www/flockiq/logs/celery_ml.out.log


# ── Celery Beat ───────────────────────────────────────────────────────────
# Only ONE Beat instance should ever run — supervisor ensures this
[program:celery_beat]
command=/var/www/flockiq/venv/bin/celery
        -A config
        beat
        --loglevel=info
        --scheduler django_celery_beat.schedulers:DatabaseScheduler
        --pidfile=/var/run/celerybeat.pid
directory=/var/www/flockiq/current
user=deploy
environment=DJANGO_SETTINGS_MODULE="config.settings.production"
autostart=true
autorestart=true
startsecs=10
stopwaitsecs=30
stderr_logfile=/var/www/flockiq/logs/celery_beat.err.log
stdout_logfile=/var/www/flockiq/logs/celery_beat.out.log
```

### 7.2 Celery Queue Routing

```python
# config/celery.py  — task routing

from kombu import Queue

app.conf.task_queues = (
    Queue("default"),           # General tasks
    Queue("notifications"),     # OutboxEvent processor — high priority
    Queue("weather"),           # OpenWeatherMap fetches
    Queue("tasks"),             # Daily task generation
    Queue("ml"),                # Prophet + scikit-learn — isolated, low priority
)

app.conf.task_default_queue = "default"

app.conf.task_routes = {
    "notifications.*":           {"queue": "notifications"},
    "weather.*":                 {"queue": "weather"},
    "tasks.*":                   {"queue": "tasks"},
    "analytics.daily_egg_forecast":       {"queue": "ml"},
    "analytics.forecast_single_batch":    {"queue": "ml"},
    "analytics.check_mortality_anomaly":  {"queue": "ml"},
    "analytics.run_symptom_diagnosis":    {"queue": "ml"},
}
```

```bash
# Apply supervisor config
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl start flockiq:*
sudo supervisorctl status
```

---

## 8. GitHub Actions CI/CD Pipeline

```yaml
# .github/workflows/deploy.yml

name: FlockIQ CI/CD

on:
  push:
    branches: [main]
  pull_request:
    branches: [main, staging]

env:
  PYTHON_VERSION: "3.12"
  DJANGO_SETTINGS_MODULE: "config.settings.test"

jobs:
  # ── Test ──────────────────────────────────────────────────────────────
  test:
    name: Test Suite
    runs-on: ubuntu-latest

    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_DB: flockiq_test
          POSTGRES_USER: flockiq_user
          POSTGRES_PASSWORD: test_password
        ports: ["5432:5432"]
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5

      redis:
        image: redis:7
        ports: ["6379:6379"]
        options: --health-cmd "redis-cli ping" --health-interval 10s

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
          cache: pip

      - name: Install dependencies
        run: |
          pip install --upgrade pip
          pip install -r requirements/development.txt

      - name: Run migrations
        env:
          DATABASE_URL: postgresql://flockiq_user:test_password@localhost:5432/flockiq_test
          REDIS_URL: redis://localhost:6379
          DJANGO_SECRET_KEY: test-secret-key-not-for-production
        run: python manage.py migrate --noinput

      - name: Run test suite
        env:
          DATABASE_URL: postgresql://flockiq_user:test_password@localhost:5432/flockiq_test
          REDIS_URL: redis://localhost:6379
          DJANGO_SECRET_KEY: test-secret-key-not-for-production
        run: |
          pytest \
            --tb=short \
            --cov=apps \
            --cov-report=xml \
            --cov-fail-under=80 \
            -q

      - name: Upload coverage
        uses: codecov/codecov-action@v4
        with:
          files: coverage.xml
          fail_ci_if_error: false

  # ── Security Audit ────────────────────────────────────────────────────
  security:
    name: Security Audit
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
      - run: pip install pip-audit bandit
      - run: pip-audit -r requirements/production.txt --ignore-vuln PYSEC-2022-42969
      - run: bandit -r apps/ -ll --exclude apps/*/tests/

  # ── Deploy (main branch only) ─────────────────────────────────────────
  deploy:
    name: Deploy to Production
    needs: [test, security]
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main' && github.event_name == 'push'

    steps:
      - uses: actions/checkout@v4

      - name: Set release tag
        id: tag
        run: echo "RELEASE=$(date +%Y%m%d_%H%M%S)_$(git rev-parse --short HEAD)" >> $GITHUB_OUTPUT

      - name: Deploy to VPS
        uses: appleboy/ssh-action@v1
        with:
          host: ${{ secrets.VPS_HOST }}
          username: deploy
          key: ${{ secrets.VPS_SSH_PRIVATE_KEY }}
          script: |
            set -euo pipefail
            export RELEASE="${{ steps.tag.outputs.RELEASE }}"
            /var/www/flockiq/scripts/deploy.sh "$RELEASE"

      - name: Notify on failure
        if: failure()
        run: |
          curl -X POST ${{ secrets.SLACK_WEBHOOK }} \
            -H 'Content-type: application/json' \
            --data '{"text":"⚠️ FlockIQ deploy FAILED on commit ${{ github.sha }} by ${{ github.actor }}"}'
```

### 8.2 Deploy Script

```bash
#!/bin/bash
# /var/www/flockiq/scripts/deploy.sh
# Runs on the VPS, invoked by GitHub Actions.
# Follows a blue-green symlink pattern for zero-downtime deploys.

set -euo pipefail

RELEASE="${1:?Release tag required}"
APP_DIR="/var/www/flockiq"
RELEASE_DIR="$APP_DIR/releases/$RELEASE"
CURRENT_DIR="$APP_DIR/current"
SHARED_DIR="$APP_DIR/shared"
VENV="$APP_DIR/venv"
REPO_URL="git@github.com:ADMTechHub/flockiq.git"

echo "▶ Starting deploy: $RELEASE"
echo "  Time: $(date)"

# ── 1. Clone release ──────────────────────────────────────────────────────
echo "▶ Cloning release..."
git clone --depth=1 --branch main "$REPO_URL" "$RELEASE_DIR"

# ── 2. Link shared resources ──────────────────────────────────────────────
echo "▶ Linking shared resources..."
ln -sf "$SHARED_DIR/.env/production.env" "$RELEASE_DIR/.env"
ln -sf "$SHARED_DIR/staticfiles" "$RELEASE_DIR/staticfiles"
ln -sf "$SHARED_DIR/media" "$RELEASE_DIR/media"

# ── 3. Install Python dependencies ────────────────────────────────────────
echo "▶ Installing dependencies..."
source "$VENV/bin/activate"
pip install --quiet -r "$RELEASE_DIR/requirements/production.txt"

# ── 4. Build Tailwind CSS ─────────────────────────────────────────────────
echo "▶ Building CSS..."
cd "$RELEASE_DIR"
npm ci --silent
npx tailwindcss -i ./static/src/input.css -o ./static/dist/output.css --minify

# ── 5. Collect static files ───────────────────────────────────────────────
echo "▶ Collecting static files..."
DJANGO_SETTINGS_MODULE=config.settings.production \
  python manage.py collectstatic --noinput --clear

# ── 6. Run migrations ─────────────────────────────────────────────────────
echo "▶ Running migrations..."
DJANGO_SETTINGS_MODULE=config.settings.production \
  python manage.py migrate --noinput

# Verify RLS is applied to all tenant tables
echo "▶ Verifying RLS..."
DJANGO_SETTINGS_MODULE=config.settings.production \
  python manage.py verify_rls_policies
# This management command queries pg_tables and pg_policies to ensure
# every TenantAwareModel subclass has RLS enabled.

# ── 7. Symlink new release ────────────────────────────────────────────────
echo "▶ Switching to new release..."
ln -sfn "$RELEASE_DIR" "$CURRENT_DIR"

# ── 8. Reload application processes ──────────────────────────────────────
echo "▶ Reloading Gunicorn (zero-downtime)..."
sudo supervisorctl signal HUP flockiq:gunicorn

echo "▶ Restarting Celery workers..."
sudo supervisorctl restart flockiq:celery_worker_default
sudo supervisorctl restart flockiq:celery_worker_ml
sudo supervisorctl restart flockiq:celery_beat

# ── 9. Health check ───────────────────────────────────────────────────────
echo "▶ Running health check..."
sleep 5   # Allow Gunicorn workers to boot
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" https://app.flockiq.com/api/health/)
if [ "$HTTP_STATUS" != "200" ]; then
  echo "✖ Health check failed (HTTP $HTTP_STATUS). Initiating rollback..."
  /var/www/flockiq/scripts/rollback.sh
  exit 1
fi

# ── 10. Prune old releases ────────────────────────────────────────────────
echo "▶ Pruning old releases (keeping last 5)..."
ls -dt "$APP_DIR/releases"/*/ | tail -n +6 | xargs rm -rf

echo "✔ Deploy complete: $RELEASE"
```

```python
# apps/infrastructure/core/management/commands/verify_rls_policies.py

from django.core.management.base import BaseCommand
from django.db import connection
from django.apps import apps


class Command(BaseCommand):
    help = "Verify RLS policies are applied to all TenantAwareModel subclasses"

    EXEMPT_TABLES = {
        "notifications_outboxevent",
        "weather_weathercache",
        "tasks_tasktemplate",
        "billing_billingplan",
    }

    def handle(self, *args, **options):
        from apps.infrastructure.core.models import TenantAwareModel

        tenant_tables = {
            model._meta.db_table
            for model in apps.get_models()
            if issubclass(model, TenantAwareModel) and not model._meta.abstract
        }

        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT tablename
                FROM pg_tables
                WHERE schemaname = 'public'
                AND rowsecurity = TRUE
            """)
            rls_enabled = {row[0] for row in cursor.fetchall()}

        missing = tenant_tables - rls_enabled - self.EXEMPT_TABLES
        if missing:
            self.stderr.write(f"✖ RLS NOT ENABLED on {len(missing)} tables:")
            for table in sorted(missing):
                self.stderr.write(f"  - {table}")
            raise SystemExit(1)

        self.stdout.write(f"✔ RLS verified on {len(tenant_tables)} tenant tables.")
```

---

## 9. SSL & Wildcard Certificate

FlockIQ uses wildcard SSL (`*.flockiq.com`) because tenants access via subdomains (`farmname.flockiq.com`).

```bash
# Wildcard cert requires DNS challenge (not HTTP challenge)
# Requires DNS API access — this example uses Cloudflare

# Install Certbot Cloudflare plugin
pip install certbot-dns-cloudflare

# Create Cloudflare API credentials file
sudo mkdir -p /etc/letsencrypt/cloudflare
sudo nano /etc/letsencrypt/cloudflare/credentials.ini
```

```ini
# /etc/letsencrypt/cloudflare/credentials.ini
dns_cloudflare_api_token = YOUR_CLOUDFLARE_API_TOKEN
```

```bash
sudo chmod 600 /etc/letsencrypt/cloudflare/credentials.ini

# Issue wildcard certificate
sudo certbot certonly \
  --dns-cloudflare \
  --dns-cloudflare-credentials /etc/letsencrypt/cloudflare/credentials.ini \
  -d flockiq.com \
  -d "*.flockiq.com" \
  --agree-tos \
  --email michael@admtechhub.com \
  --non-interactive

# Auto-renewal cron
echo "0 3 * * * root certbot renew --quiet --post-hook 'systemctl reload nginx'" \
  | sudo tee /etc/cron.d/certbot-renew

# Verify
sudo certbot certificates
# Expected: valid until ~90 days from issue, covering *.flockiq.com
```

---

## 10. Environment Variables Reference

Store these in `/var/www/flockiq/shared/.env/production.env`. **Never commit to Git.**

```bash
# /var/www/flockiq/shared/.env/production.env

# ── Django Core ────────────────────────────────────────────────────────
DJANGO_SETTINGS_MODULE=config.settings.production
DJANGO_SECRET_KEY=<64-char random string: python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())">
ALLOWED_HOSTS=.flockiq.com,flockiq.com

# ── Database ────────────────────────────────────────────────────────────
DB_NAME=flockiq_db
DB_USER=flockiq_user
DB_PASSWORD=<strong random password>
DB_HOST=127.0.0.1
DB_PORT=6432          # PgBouncer — NOT 5432

# ── Redis ────────────────────────────────────────────────────────────────
REDIS_URL=redis://:REDIS_PASSWORD@127.0.0.1:6379

# ── JWT ─────────────────────────────────────────────────────────────────
JWT_SIGNING_KEY=<64-char random key, rotate every 90 days>
JWT_ACCESS_TOKEN_LIFETIME_MINUTES=60
JWT_REFRESH_TOKEN_LIFETIME_DAYS=7

# ── Notifications ────────────────────────────────────────────────────────
TERMII_API_KEY=<from https://termii.com/account/api>
TERMII_SENDER_ID=FlockIQ

EMAIL_HOST=smtp.yourdomain.com
EMAIL_HOST_USER=noreply@flockiq.com
EMAIL_HOST_PASSWORD=<smtp password>
EMAIL_PORT=465

# ── Payments ─────────────────────────────────────────────────────────────
PAYSTACK_SECRET_KEY=sk_live_<key>
PAYSTACK_PUBLIC_KEY=pk_live_<key>
PAYSTACK_WEBHOOK_SECRET=<from Paystack dashboard>

# ── External APIs ─────────────────────────────────────────────────────────
OPENWEATHERMAP_API_KEY=<from openweathermap.org>

# ── Monitoring ────────────────────────────────────────────────────────────
SENTRY_DSN=https://<key>@sentry.io/<project>

# ── Admin ─────────────────────────────────────────────────────────────────
DJANGO_ADMIN_URL=admin-<random-slug>/    # Obscure the admin URL
```

---

## 11. Database Migration Protocol

### 11.1 Standard Migration

```bash
# Always do this before deploying — never auto-migrate in CI
cd /var/www/flockiq/current
source /var/www/flockiq/venv/bin/activate

# 1. Check what will run
python manage.py showmigrations --list | grep "\[ \]"

# 2. Dry-run (Django 4.2+)
python manage.py migrate --check
python manage.py migrate --run-syncdb --noinput --dry-run 2>&1 | head -50

# 3. Run
python manage.py migrate --noinput

# 4. Verify RLS
python manage.py verify_rls_policies
```

### 11.2 Safe Migration Rules

These rules prevent production downtime from migration locks.

| Operation | Safety | Approach |
|---|---|---|
| Add nullable column | Safe | Normal migration |
| Add column with default | Safe in PG16 | Normal migration |
| Add NOT NULL column without default | **Unsafe** | Add nullable → backfill → add constraint |
| Drop column | **Unsafe** | 3-step: stop reading → deploy → drop column |
| Add index | **Unsafe on large tables** | `CREATE INDEX CONCURRENTLY` (never in `atomic()`) |
| Rename column | **Unsafe** | Add new → dual-write → migrate reads → drop old |
| Alter column type | **Unsafe** | Shadow column pattern |
| Add FK constraint | **Unsafe on large tables** | `NOT VALID` → `VALIDATE CONSTRAINT` separately |

```python
# Safe concurrent index creation in migration
from django.db import migrations


class Migration(migrations.Migration):
    # Concurrent index creation cannot run inside a transaction
    atomic = False

    operations = [
        migrations.RunSQL(
            sql="CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                "flocks_batch_org_status_idx ON flocks_batch(org_id, status);",
            reverse_sql="DROP INDEX CONCURRENTLY IF EXISTS flocks_batch_org_status_idx;",
        ),
    ]
```

---

## 12. Zero-Downtime Deployment Procedure

The `deploy.sh` script handles the happy path. This section documents the manual procedure and the reasoning behind each step.

```
Phase 1: Prepare (without touching live traffic)
─────────────────────────────────────────────────
1. Clone new code to releases/<timestamp>
2. Install pip dependencies into shared venv
   (venv is shared across releases to avoid 2-minute install on each deploy)
3. Collect static files to shared/staticfiles
4. Run migrations against the live database
   ← New code is NOT serving traffic yet; old code reads new columns

Phase 2: Switch (< 1 second)
─────────────────────────────
5. Atomic symlink swap: ln -sfn releases/<new> current
   ← This is the actual deployment moment

Phase 3: Reload (graceful)
───────────────────────────
6. Send HUP signal to Gunicorn master
   ← Gunicorn forks new workers from the new code
   ← Old workers finish in-flight requests (up to graceful_timeout=30s)
   ← At no point are zero workers running

Phase 4: Restart background workers
─────────────────────────────────────
7. Restart Celery workers
   ← In-progress tasks are requeued via task_acks_late=True
   ← No tasks are lost

Phase 5: Verify
────────────────
8. Health check: GET /api/health/ → 200
9. Smoke tests: POST /api/auth/token/ (login works)
10. Celery check: celery -A config inspect ping
```

### 12.1 Health Check Endpoint

```python
# apps/infrastructure/core/views.py

from django.db import connection
from django.core.cache import cache
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny


class HealthCheckView(APIView):
    """
    GET /api/health/
    Returns 200 if all critical subsystems are operational.
    Returns 503 if any critical subsystem is down.
    Used by deploy script and load balancer.
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        checks = {}
        status_code = 200

        # PostgreSQL
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            checks["postgresql"] = "ok"
        except Exception as e:
            checks["postgresql"] = f"error: {e}"
            status_code = 503

        # Redis
        try:
            cache.set("health_check", "1", timeout=10)
            assert cache.get("health_check") == "1"
            checks["redis"] = "ok"
        except Exception as e:
            checks["redis"] = f"error: {e}"
            status_code = 503

        # Celery (non-blocking — doesn't fail deploy if workers are restarting)
        try:
            from celery.app.control import Inspect
            from config.celery import app as celery_app
            inspector = Inspect(app=celery_app, timeout=2.0)
            ping = inspector.ping()
            checks["celery"] = "ok" if ping else "no_workers"
        except Exception:
            checks["celery"] = "timeout"

        import django
        checks["django_version"] = django.__version__
        checks["git_sha"] = open("/var/www/flockiq/current/.git/HEAD").read().strip()[:12]

        return Response(checks, status=status_code)
```

---

## 13. Monitoring & Alerting

### 13.1 Sentry Integration

Already configured in `production.py`. Set up these alert rules in the Sentry dashboard:

| Alert | Condition | Action |
|---|---|---|
| RLS context missing | Error: "Tenant context not set" | PagerDuty P1 |
| Outbox delivery failure | OutboxEvent permanently failed | Email to admin |
| Unbalanced ledger | ValueError: "Unbalanced ledger" | PagerDuty P1 |
| Prophet forecast failure | Exception in forecasting.py | Slack alert |
| Paystack webhook rejected | 400 on billing/webhook/ | Email to admin |

### 13.2 Server Metrics (cron-based lightweight monitoring)

```bash
# /var/www/flockiq/scripts/healthcheck_cron.sh
# Runs every 5 minutes via crontab

#!/bin/bash
set -euo pipefail

ALERT_EMAIL="michael@admtechhub.com"
HOSTNAME=$(hostname)

# Disk space — alert if < 15% free
DISK_FREE=$(df / | awk 'NR==2{print $5}' | tr -d '%')
if [ "$DISK_FREE" -gt 85 ]; then
  echo "ALERT: Disk usage at ${DISK_FREE}% on $HOSTNAME" | \
    mail -s "FlockIQ: Disk Space Warning" "$ALERT_EMAIL"
fi

# RAM — alert if > 90% used
MEM_FREE=$(free | awk '/^Mem/{printf("%.0f", ($3/$2)*100)}')
if [ "$MEM_FREE" -gt 90 ]; then
  echo "ALERT: Memory usage at ${MEM_FREE}% on $HOSTNAME" | \
    mail -s "FlockIQ: Memory Warning" "$ALERT_EMAIL"
fi

# Celery — alert if no workers running
CELERY_WORKERS=$(supervisorctl status flockiq:celery_worker_default | grep RUNNING | wc -l)
if [ "$CELERY_WORKERS" -eq 0 ]; then
  echo "ALERT: Celery default worker is DOWN on $HOSTNAME" | \
    mail -s "FlockIQ: Celery Down" "$ALERT_EMAIL"
fi

# Outbox — alert if > 100 events stuck in PENDING for > 10 minutes
STUCK=$(psql -U flockiq_user -d flockiq_db -t -c \
  "SELECT COUNT(*) FROM notifications_outboxevent
   WHERE status='pending'
   AND next_attempt_at < NOW() - INTERVAL '10 minutes'")
if [ "$STUCK" -gt 100 ]; then
  echo "ALERT: $STUCK stuck OutboxEvents on $HOSTNAME" | \
    mail -s "FlockIQ: Notification Backlog" "$ALERT_EMAIL"
fi
```

```bash
# Add to deploy user's crontab
crontab -e
# Add:
*/5 * * * * /var/www/flockiq/scripts/healthcheck_cron.sh >> /var/www/flockiq/logs/healthcheck.log 2>&1
```

### 13.3 Key Metrics to Watch (aaPanel Dashboard)

| Metric | Warning | Critical | Action |
|---|---|---|---|
| CPU usage | > 70% sustained 5m | > 90% sustained 2m | Scale workers down, profile |
| RAM usage | > 80% | > 92% | Reduce Gunicorn workers; check Prophet memory |
| Disk I/O wait | > 30% | > 60% | Check PostgreSQL checkpoint frequency |
| PostgreSQL connections | > 80 (via PgBouncer) | > 95 | Increase pool size or add VPS |
| Redis memory | > 80% maxmemory | > 95% | Increase maxmemory or audit TTLs |
| Celery queue depth | > 500 | > 2000 | Scale workers or investigate slow tasks |

---

## 14. Backup & Recovery

### 14.1 Automated Backup Script

```bash
# /var/www/flockiq/scripts/backup.sh
# Runs daily at 02:00 WAT via cron

#!/bin/bash
set -euo pipefail

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="/var/www/flockiq/backups"
RETENTION_DAYS=7
DB_NAME="flockiq_db"
DB_USER="flockiq_user"

echo "▶ Starting backup: $TIMESTAMP"

# ── PostgreSQL dump ────────────────────────────────────────────────────────
echo "  Database..."
pg_dump \
  -U "$DB_USER" \
  -Fc \
  --no-owner \
  --no-acl \
  "$DB_NAME" \
  > "$BACKUP_DIR/db_${TIMESTAMP}.dump"

# Verify dump integrity
pg_restore --list "$BACKUP_DIR/db_${TIMESTAMP}.dump" > /dev/null
echo "  ✔ Database: $(du -sh $BACKUP_DIR/db_${TIMESTAMP}.dump | cut -f1)"

# ── Media files ────────────────────────────────────────────────────────────
echo "  Media files..."
tar -czf "$BACKUP_DIR/media_${TIMESTAMP}.tar.gz" \
  -C /var/www/flockiq/shared media/
echo "  ✔ Media: $(du -sh $BACKUP_DIR/media_${TIMESTAMP}.tar.gz | cut -f1)"

# ── Environment file ───────────────────────────────────────────────────────
# Encrypted backup of .env (critical — losing this = losing the app)
echo "  Environment..."
gpg --symmetric \
  --cipher-algo AES256 \
  --batch \
  --passphrase-fd 3 \
  --output "$BACKUP_DIR/env_${TIMESTAMP}.gpg" \
  /var/www/flockiq/shared/.env/production.env \
  3<<<$(cat /root/.backup_passphrase)
echo "  ✔ Environment: encrypted"

# ── Offsite sync (to object storage) ─────────────────────────────────────
# Uses rclone — configure with your preferred provider (S3, Backblaze B2, etc.)
echo "  Uploading to offsite storage..."
rclone copy "$BACKUP_DIR/" remote:flockiq-backups/$(date +%Y/%m/%d)/ \
  --include "*.{dump,tar.gz,gpg}" \
  --min-age 1m \
  --progress

# ── Prune local backups ────────────────────────────────────────────────────
find "$BACKUP_DIR" -name "*.dump" -mtime +$RETENTION_DAYS -delete
find "$BACKUP_DIR" -name "*.tar.gz" -mtime +$RETENTION_DAYS -delete
find "$BACKUP_DIR" -name "*.gpg" -mtime +$RETENTION_DAYS -delete

echo "✔ Backup complete: $TIMESTAMP"
```

```bash
# Add to root crontab (needs DB access as postgres)
sudo crontab -e
# Add:
0 2 * * * /var/www/flockiq/scripts/backup.sh >> /var/www/flockiq/logs/backup.log 2>&1
```

### 14.2 Restore Procedure

```bash
# Full restore from backup (disaster recovery)

BACKUP_FILE="db_20260408_020000.dump"

# 1. Stop application traffic
sudo supervisorctl stop flockiq:*
sudo systemctl stop nginx

# 2. Drop and recreate database
sudo -u postgres psql -c "DROP DATABASE IF EXISTS flockiq_db;"
sudo -u postgres psql -c "CREATE DATABASE flockiq_db OWNER flockiq_user;"

# 3. Restore
pg_restore \
  -U flockiq_user \
  -d flockiq_db \
  --no-owner \
  --no-acl \
  --verbose \
  "/var/www/flockiq/backups/$BACKUP_FILE"

# 4. Re-apply RLS (pg_restore preserves policies, but verify)
cd /var/www/flockiq/current
source /var/www/flockiq/venv/bin/activate
DJANGO_SETTINGS_MODULE=config.settings.production \
  python manage.py verify_rls_policies

# 5. Restart application
sudo systemctl start nginx
sudo supervisorctl start flockiq:*

# 6. Health check
curl https://app.flockiq.com/api/health/
```

---

## 15. Incident Response Runbook

### 15.1 P1 — Data Leak Suspected (RLS Failure)

```
DETECTION: User sees another tenant's data | Sentry: "RLS context not set"

IMMEDIATE ACTIONS (< 5 minutes):
1. Put site into maintenance mode:
   sudo supervisorctl stop flockiq:gunicorn
   # Nginx will serve a 502; better than leaking data

2. Check RLS policy status:
   sudo -u postgres psql flockiq_db -c "
     SELECT tablename, rowsecurity
     FROM pg_tables
     WHERE schemaname = 'public'
     AND rowsecurity = FALSE
     AND tablename NOT IN (
       'notifications_outboxevent', 'weather_weathercache',
       'tasks_tasktemplate', 'billing_billingplan'
     );"
   # Any row here is a compromised table

3. Check app.current_org_id is being set:
   grep -r "set_config" apps/infrastructure/core/middleware.py
   grep -r "set_tenant_context" apps/infrastructure/core/rls.py

4. If a specific org is affected: identify which orgs may have been exposed
   by checking PostgreSQL query logs (log_min_duration_statement captures all)

5. Re-enable RLS on any affected tables:
   sudo -u postgres psql flockiq_db -c "
     ALTER TABLE <table> ENABLE ROW LEVEL SECURITY;
     ALTER TABLE <table> FORCE ROW LEVEL SECURITY;"

6. Bring site back up and verify with verify_rls_policies

7. Notify affected tenants within 24h (legal obligation under NDPR)
```

### 15.2 P1 — Database Down

```
DETECTION: Health check returns 503 | Sentry: OperationalError | Gunicorn 500s

1. Check PostgreSQL status:
   sudo systemctl status postgresql
   sudo journalctl -u postgresql -n 50

2. Check disk space (most common cause of PG shutdown):
   df -h /
   # If full: clean old WAL files
   sudo -u postgres psql -c "SELECT pg_walfile_name(pg_current_wal_lsn());"
   sudo find /var/lib/postgresql/16/main/pg_wal -name "*.history" -mtime +1 -delete

3. Check PgBouncer:
   sudo systemctl status pgbouncer
   psql -h 127.0.0.1 -p 6432 -U pgbouncer pgbouncer -c "SHOW POOLS;"

4. Attempt restart:
   sudo systemctl restart postgresql
   sudo systemctl restart pgbouncer
   sudo supervisorctl restart flockiq:gunicorn

5. If PostgreSQL won't start, restore from backup (Section 14.2)
```

### 15.3 P2 — Celery Workers Down

```
DETECTION: Notifications delayed > 5 min | OutboxEvent backlog growing

1. Check worker status:
   sudo supervisorctl status flockiq:celery_*
   celery -A config inspect ping

2. Check Redis (broker must be up):
   redis-cli -a $REDIS_PASSWORD ping

3. Restart workers:
   sudo supervisorctl restart flockiq:celery_worker_default
   sudo supervisorctl restart flockiq:celery_worker_ml

4. If Beat is down, restart it — but check if another Beat is running first:
   ps aux | grep celery | grep beat
   sudo supervisorctl restart flockiq:celery_beat

5. Process any stuck OutboxEvents manually:
   python manage.py shell -c "
     from apps.infrastructure.notifications.tasks import process_outbox
     process_outbox.delay()"
```

### 15.4 P2 — High Memory (OOM Risk)

```
DETECTION: RAM > 90% | Supervisor restarting workers | aaPanel alert

1. Identify memory consumers:
   ps aux --sort=-%mem | head -20

2. Prophet worker typically uses 1.5–2 GB during inference.
   If it's running, wait for it to complete (max 4 min per task_time_limit).

3. If OOM is imminent, reduce Gunicorn workers temporarily:
   # Edit gunicorn.conf.py: workers = 2 (instead of 9)
   sudo supervisorctl signal HUP flockiq:gunicorn

4. Check for memory leak (workers not releasing Prophet model):
   # max_requests_per_child=50 on ML worker should prevent this
   sudo supervisorctl restart flockiq:celery_worker_ml

5. Long-term: add swap (2 GB) as emergency buffer:
   sudo fallocate -l 2G /swapfile
   sudo chmod 600 /swapfile
   sudo mkswap /swapfile
   sudo swapon /swapfile
   echo '/swapfile swap swap defaults 0 0' | sudo tee -a /etc/fstab
```

---

## 16. Rollback Procedure

```bash
#!/bin/bash
# /var/www/flockiq/scripts/rollback.sh
# Reverts to the previous release. Safe to run during an incident.

set -euo pipefail

APP_DIR="/var/www/flockiq"
CURRENT=$(readlink -f "$APP_DIR/current")
PREVIOUS=$(ls -dt "$APP_DIR/releases"/*/ | sed -n '2p' | tr -d '/')

if [ -z "$PREVIOUS" ]; then
  echo "✖ No previous release found. Cannot rollback."
  exit 1
fi

echo "▶ Rolling back from: $(basename $CURRENT)"
echo "▶ Rolling back to:   $(basename $PREVIOUS)"
echo ""
echo "  This will NOT reverse database migrations."
echo "  If the new code added new migrations, those tables/columns will remain."
echo "  This is safe — old code ignores new nullable columns."
echo ""
read -p "Continue? (yes/no) " CONFIRM
[ "$CONFIRM" != "yes" ] && exit 0

# Symlink rollback
ln -sfn "$PREVIOUS" "$APP_DIR/current"

# Reload application
sudo supervisorctl signal HUP flockiq:gunicorn
sleep 3
sudo supervisorctl restart flockiq:celery_worker_default
sudo supervisorctl restart flockiq:celery_worker_ml
sudo supervisorctl restart flockiq:celery_beat

# Health check
sleep 5
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" https://app.flockiq.com/api/health/)
if [ "$HTTP_STATUS" == "200" ]; then
  echo "✔ Rollback successful. App is healthy."
else
  echo "✖ Rollback health check failed (HTTP $HTTP_STATUS)."
  echo "  Check logs: tail -f /var/www/flockiq/logs/gunicorn.err.log"
  exit 1
fi
```

> **On database migrations and rollback:** Django does not automatically reverse migrations on rollback. If a deployment added migrations, run `python manage.py migrate <app> <previous_migration_number>` manually before running the rollback script. However, for additive migrations (new nullable columns, new tables) this is usually unnecessary — old code simply ignores the new schema.

---

*End of FlockIQ Deployment Runbook v1.0*  
*Companion documents:*  
*— `skills/system_architectures.md` (Core Engine Technical Specification)*  
*— Next: `skills/api_contract.md` (REST API endpoints, request/response schemas, versioning)*
