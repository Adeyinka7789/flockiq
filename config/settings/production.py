from .base import *  # noqa: F401, F403
import dj_database_url
from decouple import config, Csv
import os

DEBUG = False

SECRET_KEY = config("SECRET_KEY")
ALLOWED_HOSTS = config(
    "ALLOWED_HOSTS",
    default="flockiq.com,www.flockiq.com,.flockiq.com",
    cast=Csv(),
)

# ── Database — connects via PgBouncer (transaction mode) ─────────────────────
# CONN_MAX_AGE=0 is REQUIRED: PgBouncer transaction mode leaks connections otherwise.
# DATABASE_URL must use port 6432 (PgBouncer), NOT 5432:
#   postgresql://flockiq_app:password@127.0.0.1:6432/flockiq
_db = dj_database_url.config(
    env="DATABASE_URL",
    conn_max_age=0,
)
_db["OPTIONS"] = {
    "connect_timeout": 10,
    "application_name": "flockiq_web",
    # Connection starvation guards: kill any statement over 20s and
    # any transaction idle over 30s. TenantMiddleware holds a
    # transaction for the whole request (SET LOCAL requires it), so a
    # slow external call inside a request would otherwise pin a
    # PgBouncer backend connection indefinitely.
    # NOTE: PgBouncer must allow the startup parameter:
    #   ignore_startup_parameters = options
    # in pgbouncer.ini, or every connection is rejected. See
    # RUNBOOK.md "PgBouncer Configuration" (an ALTER ROLE alternative
    # is documented there too).
    "options": (
        "-c statement_timeout=20000 "
        "-c idle_in_transaction_session_timeout=30000"
    ),
}
DATABASES = {"default": _db}

# ── Cache / Session ───────────────────────────────────────────────────────────
# REDIS_URL is the base connection (no DB suffix); DB numbers are appended below.
# Redis DB allocation (each concern gets its own DB — see RUNBOOK.md):
#   DB 0 → Celery broker   DB 1 → general cache
#   DB 2 → sessions        DB 3 → Celery results
REDIS_URL = config("REDIS_URL")
# Dedicated session store. Defaults to DB 2 of the same Redis if unset.
REDIS_SESSION_URL = config("REDIS_SESSION_URL", default=f"{REDIS_URL}/2")

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": f"{REDIS_URL}/1",
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            "SOCKET_CONNECT_TIMEOUT": 5,
            "SOCKET_TIMEOUT": 5,
            "IGNORE_EXCEPTIONS": True,  # Degrade gracefully if Redis is down
        },
        "KEY_PREFIX": "flockiq",
        "TIMEOUT": 300,
    },
    "sessions": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_SESSION_URL,
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            "SOCKET_CONNECT_TIMEOUT": 5,
            "SOCKET_TIMEOUT": 5,
            "IGNORE_EXCEPTIONS": False,  # sessions must not fail silently
        },
        "KEY_PREFIX": "flockiq_sess",
        "TIMEOUT": 60 * 60 * 2,  # match SESSION_COOKIE_AGE
    },
}

# cached_db: reads from the "sessions" Redis cache (fast), falls back to the
# django_session table on a cache miss/outage (resilient). A Redis restart does
# not log users out because session rows are always persisted in PostgreSQL.
SESSION_ENGINE = "django.contrib.sessions.backends.cached_db"
SESSION_CACHE_ALIAS = "sessions"

# ── Celery ────────────────────────────────────────────────────────────────────
# Broker on DB 0, results on DB 3 — NEVER share a DB with sessions (DB 2) or
# the cache (DB 1): a broker flush would wipe every user session.
CELERY_BROKER_URL = config("CELERY_BROKER_URL", default=f"{REDIS_URL}/0")
CELERY_RESULT_BACKEND = config("CELERY_RESULT_BACKEND", default=f"{REDIS_URL}/3")
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True

# ── Static & Media ────────────────────────────────────────────────────────────
STATIC_ROOT = "/www/wwwroot/flockiq/staticfiles"
MEDIA_ROOT = "/www/wwwroot/flockiq/media"
STATIC_URL = "/static/"
MEDIA_URL = "/media/"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# ── Security ──────────────────────────────────────────────────────────────────
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True
X_FRAME_OPTIONS = "DENY"
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
# Env-driven so tenant custom domains can be appended without a code change.
# Same-origin POSTs already pass Django's Origin check, so this list only
# matters for cross-origin requests — but every custom domain MUST also be in
# ALLOWED_HOSTS or Django rejects the request outright (see RUNBOOK.md
# "Custom domain onboarding"). Runtime mutation of settings is not
# thread/process-safe, so domains are listed at startup via this env var.
CSRF_TRUSTED_ORIGINS = config(
    "CSRF_TRUSTED_ORIGINS",
    default="https://flockiq.com,https://www.flockiq.com,https://*.flockiq.com",
    cast=Csv(),
)

# ── Password hashing ──────────────────────────────────────────────────────────
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",  # Fallback for existing hashes
]

# ── Email (Truehost VPS cPanel SMTP) ─────────────────────────────────────────
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = config("EMAIL_HOST", default="mail.flockiq.com")
EMAIL_PORT = config("EMAIL_PORT", cast=int, default=465)
EMAIL_USE_SSL = True
EMAIL_USE_TLS = False
EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")
DEFAULT_FROM_EMAIL = config(
    "DEFAULT_FROM_EMAIL", default="FlockIQ <noreply@flockiq.com>"
)
SERVER_EMAIL = config("SERVER_EMAIL", default="errors@flockiq.com")

# ── Sentry ────────────────────────────────────────────────────────────────────
# Sentry is initialised ONCE in base.py (imported above). Set SENTRY_DSN and
# DJANGO_ENV=production in the environment. Do NOT re-init here — a second
# sentry_sdk.init() would clobber the integrations configured in base.py.

# ── Logging ───────────────────────────────────────────────────────────────────
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
            "filename": "/www/wwwroot/flockiq/logs/django.log",
            "maxBytes": 10 * 1024 * 1024,
            "backupCount": 5,
            "formatter": "verbose",
        },
        "celery_file": {
            "level": "INFO",
            "class": "logging.handlers.RotatingFileHandler",
            "filename": "/www/wwwroot/flockiq/logs/celery.log",
            "maxBytes": 10 * 1024 * 1024,
            "backupCount": 5,
            "formatter": "verbose",
        },
    },
    "loggers": {
        "django": {"handlers": ["file"], "level": "WARNING", "propagate": False},
        "celery": {"handlers": ["celery_file"], "level": "INFO", "propagate": False},
        "apps": {"handlers": ["file"], "level": "INFO", "propagate": False},
    },
}

# ── Papertrail log shipping ───────────────────────────────────────────────────
# production.py replaces LOGGING wholesale (above), so the Papertrail wiring in
# base.py does not apply here — re-apply it against this LOGGING dict.
PAPERTRAIL_HOST = config("PAPERTRAIL_HOST", default="")
PAPERTRAIL_PORT = config("PAPERTRAIL_PORT", default=0, cast=int)

if PAPERTRAIL_HOST and PAPERTRAIL_PORT:
    import logging.handlers

    LOGGING["handlers"]["papertrail"] = {
        "class": "logging.handlers.SysLogHandler",
        "address": (PAPERTRAIL_HOST, PAPERTRAIL_PORT),
        "formatter": "verbose",
    }
    for _logger in LOGGING["loggers"].values():
        _logger["handlers"].append("papertrail")
