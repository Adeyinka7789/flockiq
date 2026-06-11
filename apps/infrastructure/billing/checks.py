"""
System checks for billing configuration.

PAYSTACK_WEBHOOK_SECRET is the HMAC key used to verify Paystack webhook
signatures. An empty key makes signatures trivially forgeable (anyone can
compute HMAC with an empty key), so production must refuse to start without
it. The webhook view also fails closed at runtime (503) as a second guard.
"""

from django.conf import settings
from django.core.checks import Error, Warning, register


@register()
def check_celery_beat_seeded(app_configs, **kwargs):
    """Warn if fewer than 10 periodic tasks are registered in the DB scheduler."""
    errors = []
    try:
        from django_celery_beat.models import PeriodicTask

        count = PeriodicTask.objects.count()
        if count < 10:
            errors.append(
                Warning(
                    f"Only {count} Celery beat tasks found. "
                    f"Run: python manage.py seed_celery_beat",
                    id="billing.W002",
                )
            )
    except Exception:
        pass
    return errors


@register()
def check_paystack_webhook_secret(app_configs, **kwargs):
    if getattr(settings, "PAYSTACK_WEBHOOK_SECRET", ""):
        return []

    msg = "PAYSTACK_WEBHOOK_SECRET is not set."
    hint = (
        "Set PAYSTACK_WEBHOOK_SECRET in your environment. Paystack signs "
        "webhooks with your account secret key, so it should equal "
        "PAYSTACK_SECRET_KEY. Until it is set, the webhook endpoint "
        "returns 503 and no billing events are processed."
    )
    if settings.DEBUG:
        # Development without Paystack configured is fine — warn only.
        return [Warning(msg, hint=hint, id="billing.W001")]
    return [Error(msg, hint=hint, id="billing.E001")]
