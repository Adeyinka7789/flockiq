import os
from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

app = Celery("flockiq")

app.config_from_object("django.conf:settings", namespace="CELERY")

app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_max_tasks_per_child=200,
    task_soft_time_limit=180,
    task_time_limit=240,
)

app.autodiscover_tasks([
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
])
