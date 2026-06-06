from pathlib import Path
from decouple import config, Csv
import dj_database_url
from django.utils.translation import gettext_lazy as _

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = config("SECRET_KEY", default="django-insecure-change-me-in-production")

DEBUG = False

ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="localhost,127.0.0.1", cast=Csv())

DJANGO_APPS = [
    "unfold",
    "unfold.contrib.filters",
    "unfold.contrib.forms",
    "unfold.contrib.import_export",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "django.contrib.humanize",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "django_filters",
    "crispy_forms",
    "crispy_tailwind",
    "import_export",
    "waffle",
    "axes",
    "auditlog",
    "django_structlog",
    "django_celery_beat",
    "django_celery_results",
    "drf_spectacular",
    "django_htmx",
    "template_partials",
]

FLOCKIQ_APPS = [
    "apps.infrastructure.core",
    "apps.infrastructure.tenants",
    "apps.infrastructure.accounts",
    "apps.infrastructure.notifications",
    "apps.infrastructure.billing",
    "apps.farm.farms",
    "apps.farm.flocks",
    "apps.farm.tasks",
    "apps.farm.weather",
    "apps.production.production",
    "apps.production.feed",
    "apps.production.water",
    "apps.production.waste",
    "apps.health.health",
    "apps.health.analytics",
    "apps.finance.expenses",
    "apps.finance.finance",
    "apps.finance.market",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + FLOCKIQ_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.infrastructure.core.middleware.ImpersonationMiddleware",
    "apps.infrastructure.core.middleware.HtmxSessionExpiredMiddleware",
    "apps.infrastructure.core.middleware.TenantMiddleware",
    "apps.infrastructure.tenants.middleware.TrialEnforcementMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "django_structlog.middlewares.RequestMiddleware",
    "axes.middleware.AxesMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.infrastructure.billing.context_processors.plan_features",
                "apps.infrastructure.billing.context_processors.support_contact",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# --- Database ---
DATABASES = {
    "default": dj_database_url.config(
        default=config("DATABASE_URL", default="sqlite:///db.sqlite3"),
        conn_max_age=0,  # PgBouncer transaction mode — NEVER change
    )
}

# --- Cache ---
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": config("REDIS_URL", default="redis://127.0.0.1:6379/1"),
        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
    }
}

SESSION_ENGINE = "django.contrib.sessions.backends.cache"
SESSION_CACHE_ALIAS = "default"

SESSION_COOKIE_AGE = 60 * 60 * 2        # 2 hours of inactivity
SESSION_SAVE_EVERY_REQUEST = True        # resets the 2-hour clock on every request
SESSION_EXPIRE_AT_BROWSER_CLOSE = False  # survive browser restart within 2 hours
SESSION_COOKIE_HTTPONLY = True           # JS cannot read session cookie
SESSION_COOKIE_SAMESITE = "Lax"

CSRF_COOKIE_HTTPONLY = False             # HTMX needs to read CSRF cookie
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_TRUSTED_ORIGINS = config(
    "CSRF_TRUSTED_ORIGINS",
    default="http://localhost:8000,http://127.0.0.1:8000",
    cast=Csv(),
)

# --- Auth ---
AUTH_USER_MODEL = "accounts.CustomUser"
LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "axes.backends.AxesStandaloneBackend",
]

# --- Internationalisation ---
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Africa/Lagos"
USE_I18N = True
USE_TZ = True

LANGUAGES = [
    ("en", _("English")),
    ("fr", _("French")),
    ("es", _("Spanish")),
]

LOCALE_PATHS = [
    BASE_DIR / "locale",
]

# --- Static files ---
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# --- Media ---
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Celery ---
CELERY_BROKER_URL = config("REDIS_URL", default="redis://127.0.0.1:6379/1")
CELERY_RESULT_BACKEND = "django-db"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_MAX_TASKS_PER_CHILD = 200
CELERY_TASK_SOFT_TIME_LIMIT = 180
CELERY_TASK_TIME_LIMIT = 240
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"
from celery.schedules import crontab  # noqa: E402
CELERY_BEAT_SCHEDULE = {
    "clear-expired-sessions": {
        "task": "apps.infrastructure.core.tasks.clear_expired_sessions",
        "schedule": crontab(hour=2, minute=0),
    },
}

# --- JWT ---
from datetime import timedelta

SIMPLE_JWT = {
    "TOKEN_OBTAIN_SERIALIZER": "apps.infrastructure.accounts.serializers.CustomTokenObtainPairSerializer",
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=8),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=30),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

# --- REST Framework ---
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 25,
}

SPECTACULAR_SETTINGS = {
    "TITLE": "FlockIQ API",
    "DESCRIPTION": "AI-powered poultry farm management SaaS",
    "VERSION": "1.0.0",
}

# --- Forms ---
CRISPY_TEMPLATE_PACK = "tailwind"
CRISPY_ALLOWED_TEMPLATE_PACKS = "tailwind"

# --- Axes (brute-force protection) ---
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = 0.25  # 15 minutes
AXES_LOCKOUT_CALLABLE = None

# --- Waffle feature flags ---
WAFFLE_FLAG_DEFAULT = False  # All AI features OFF until explicitly enabled

# --- Email ---
EMAIL_BACKEND = config(
    "EMAIL_BACKEND",
    default="django.core.mail.backends.console.EmailBackend",
)
EMAIL_HOST = config("EMAIL_HOST", default="smtp.gmail.com")
EMAIL_PORT = config("EMAIL_PORT", default=587, cast=int)
EMAIL_USE_TLS = config("EMAIL_USE_TLS", default=True, cast=bool)
EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")
DEFAULT_FROM_EMAIL = config(
    "DEFAULT_FROM_EMAIL", default="FlockIQ <noreply@flockiq.com>"
)
ADMIN_EMAIL = config("ADMIN_EMAIL", default="admin@flockiq.com")
SUPPORT_EMAIL = config("SUPPORT_EMAIL", default="support@flockiq.com")
SUPPORT_PHONE = config("SUPPORT_PHONE", default="+234 000 000 0000")
PASSWORD_RESET_TIMEOUT = 3600
SITE_URL = config("SITE_URL", default="http://localhost:8000")

# --- Third-party API keys ---
TERMII_API_KEY = config("TERMII_API_KEY", default="")
TERMII_SENDER_ID = config("TERMII_SENDER_ID", default="FlockIQ")
PAYSTACK_SECRET_KEY = config("PAYSTACK_SECRET_KEY", default="")
PAYSTACK_PUBLIC_KEY = config("PAYSTACK_PUBLIC_KEY", default="")
PAYSTACK_WEBHOOK_SECRET = config("PAYSTACK_WEBHOOK_SECRET", default="")
PAYSTACK_PLAN_CODES = {
    "monthly": config("PAYSTACK_MONTHLY_PLAN_CODE", default=""),
    "cycle": config("PAYSTACK_CYCLE_PLAN_CODE", default=""),
    "yearly": config("PAYSTACK_YEARLY_PLAN_CODE", default=""),
}
OPENWEATHERMAP_API_KEY = config("OPENWEATHERMAP_API_KEY", default="")

# --- Logging (structlog) ---
import structlog

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": structlog.stdlib.ProcessorFormatter,
            "processor": structlog.processors.JSONRenderer(),
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "celery": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.filter_by_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)
