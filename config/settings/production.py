from .base import *  # noqa: F401, F403
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
# This is already enforced in base.py via dj_database_url — do not override.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "HOST": "127.0.0.1",
        "PORT": "6432",  # PgBouncer — NOT 5432
        "NAME": config("DB_NAME"),
        "USER": config("DB_USER"),
        "PASSWORD": config("DB_PASSWORD"),
        "CONN_MAX_AGE": 0,
        "OPTIONS": {
            "connect_timeout": 10,
            "application_name": "flockiq_web",
        },
    }
}

# ── Cache / Session ───────────────────────────────────────────────────────────
REDIS_URL = config("REDIS_URL")

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
    }
}

SESSION_ENGINE = "django.contrib.sessions.backends.cache"
SESSION_CACHE_ALIAS = "default"

# ── Celery ────────────────────────────────────────────────────────────────────
CELERY_BROKER_URL = f"{REDIS_URL}/2"
CELERY_RESULT_BACKEND = f"{REDIS_URL}/3"
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
# REQUIRED: set this env var in production
# CSRF_TRUSTED_ORIGINS=https://*.flockiq.com,https://flockiq.com
CSRF_TRUSTED_ORIGINS = [
    "https://flockiq.com",
    "https://www.flockiq.com",
    "https://*.flockiq.com",
]

# ── Password hashing ──────────────────────────────────────────────────────────
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",  # Fallback for existing hashes
]

# ── Email ─────────────────────────────────────────────────────────────────────
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = config("EMAIL_HOST", default="smtp.gmail.com")
EMAIL_PORT = config("EMAIL_PORT", cast=int, default=465)
EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_SSL = True
DEFAULT_FROM_EMAIL = "FlockIQ <noreply@flockiq.com>"

# ── Sentry ────────────────────────────────────────────────────────────────────
SENTRY_DSN = config("SENTRY_DSN", default="")
if SENTRY_DSN:
    import sentry_sdk

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        traces_sample_rate=0.1,
        profiles_sample_rate=0.05,
        environment="production",
    )

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
