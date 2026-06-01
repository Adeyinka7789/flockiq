from .base import *  # noqa: F401, F403

DEBUG = True

ALLOWED_HOSTS = ["*"]

INSTALLED_APPS += [  # noqa: F405
    "django_extensions",
]

INTERNAL_IPS = ["127.0.0.1"]

# SQLite fallback for early local dev (override DATABASE_URL in .env for Postgres)
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",  # noqa: F405
    }
}

# Simpler cache for dev if Redis is not running
# Override in .env: REDIS_URL=redis://127.0.0.1:6379/1
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
