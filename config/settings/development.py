import structlog
import dj_database_url
from .base import *  # noqa: F401, F403

DEBUG = True

ALLOWED_HOSTS = ["*"]

INSTALLED_APPS += [  # noqa: F405
    "django_extensions",
]

INTERNAL_IPS = ["127.0.0.1"]

# --- Sentry: disabled locally ---
SENTRY_DSN = ""  # base.py skips sentry_sdk.init() when this is empty

# --- Django Silk: always on locally ---
# base.py only wires Silk when ENABLE_SILK is set in the env, and that check has
# already run by the time this module loads. So enable it explicitly here.
ENABLE_SILK = True
if "silk" not in INSTALLED_APPS:  # noqa: F405
    INSTALLED_APPS += ["silk"]  # noqa: F405
    MIDDLEWARE += ["silk.middleware.SilkyMiddleware"]  # noqa: F405
    SILKY_PYTHON_PROFILER = False
    # MUST stay False — see base.py: EXPLAIN ANALYZE executes DML in PostgreSQL,
    # so query profiling would re-run every INSERT/UPDATE/DELETE and double our
    # mortality/feed-stock decrement signals.
    SILKY_ANALYZE_QUERIES = False
    SILKY_MAX_RECORDED_REQUESTS = 1000
    SILKY_MAX_RECORDED_REQUESTS_CHECK_PERCENT = 10
    SILKY_AUTHENTICATION = True
    SILKY_AUTHORISATION = True
    SILKY_META = True


DATABASES = {
    "default": dj_database_url.config(
        default="postgresql://flockiq_app:flockiq_dev_pass@localhost:5432/flockiq_dev",
        conn_max_age=0,
    )
}

# Simpler cache for dev if Redis is not running
# Override in .env: REDIS_URL=redis://127.0.0.1:6379/1
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Dev-only webhook HMAC key. The webhook view fails closed (503) when this is
# empty, and a system check (billing.E001) blocks production startup — this
# default keeps local webhook testing and the test suite working without a
# real Paystack key. Production reads it from the environment (base.py).
if not PAYSTACK_WEBHOOK_SECRET:  # noqa: F405
    PAYSTACK_WEBHOOK_SECRET = "dev-webhook-secret"

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.dev.ConsoleRenderer(colors=True),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "simple",
        },
    },
    "formatters": {
        "simple": {
            "format": "{levelname} {message}",
            "style": "{",
        },
    },
    "loggers": {
        "django_structlog": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "django.server": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "WARNING",
    },
}


# Pure DB-backed sessions for local dev. Overrides base's cached_db so local has
# NO Redis dependency for auth — sessions survive Redis/server restarts. No
# SESSION_CACHE_ALIAS needed; the db backend never touches the cache.
SESSION_ENGINE = "django.contrib.sessions.backends.db"
