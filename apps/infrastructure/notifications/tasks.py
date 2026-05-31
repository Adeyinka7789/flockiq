import structlog
from celery import shared_task
from django.db import connection, models, transaction
from django.utils import timezone

from .models import NotificationLog, OutboxEvent
from .providers.base import NotificationPayload
from .providers.inapp import InAppProvider
from .providers.smtp import SMTPProvider
from .providers.termii import TermiiProvider

logger = structlog.get_logger(__name__)

_PROVIDERS = [TermiiProvider(), SMTPProvider(), InAppProvider()]
BATCH_SIZE = 50


def _get_provider(channel):
    for p in _PROVIDERS:
        if p.supports_channel(channel):
            return p
    return None


@shared_task(name="notifications.process_outbox")
def process_outbox():
    """
    Polls OutboxEvent for pending deliveries every 30 seconds.
    Uses select_for_update(skip_locked=True) on PostgreSQL to prevent double-processing
    across multiple Celery workers. SQLite (dev/test) falls back to a plain query.
    """
    is_postgres = connection.vendor == "postgresql"
    with transaction.atomic():
        qs = (
            OutboxEvent.objects.filter(
                status="pending",
                attempts__lt=models.F("max_attempts"),
            )
            .order_by("created_at")[:BATCH_SIZE]
        )
        if is_postgres:
            qs = qs.select_for_update(skip_locked=True)
        event_ids = list(qs.values_list("id", flat=True))

    if not event_ids:
        return

    for event_id in event_ids:
        _deliver_event(event_id)


def _deliver_event(event_id):
    is_postgres = connection.vendor == "postgresql"
    with transaction.atomic():
        try:
            qs = OutboxEvent.objects.filter(id=event_id, status="pending")
            if is_postgres:
                qs = qs.select_for_update(skip_locked=True)
            event = qs.get()
        except OutboxEvent.DoesNotExist:
            return

        event.status = "processing"
        event.attempts += 1
        event.last_attempted_at = timezone.now()
        event.save(update_fields=["status", "attempts", "last_attempted_at"])

    log = logger.bind(
        event_id=str(event_id),
        event_type=event.event_type,
        channel=event.channel,
        attempt=event.attempts,
        idempotency_key=event.idempotency_key,
    )

    provider = _get_provider(event.channel)
    if provider is None:
        log.error("outbox.no_provider")
        _mark_failed(event, "no_provider", "No provider found for channel", retry=False)
        return

    payload = NotificationPayload(
        recipient_id=str(event.recipient_user_id),
        recipient_phone=event.recipient_phone,
        recipient_email=event.recipient_email,
        subject=event.subject,
        body=event.body,
        body_html=event.body_html,
        channel=event.channel,
        idempotency_key=event.idempotency_key,
        org_id=str(event.org_id),
    )

    result = provider.send(payload)

    with transaction.atomic():
        if result.success:
            event.status = "delivered"
            event.delivered_at = timezone.now()
            event.save(update_fields=["status", "delivered_at"])
            log.info("outbox.delivered", provider=result.provider)
            if event.channel == "in_app":
                _create_notification_log(event)
        else:
            can_retry = result.should_retry and event.attempts < event.max_attempts
            _mark_failed(event, result.error_code, result.error_detail or "", retry=can_retry)
            log.warning(
                "outbox.delivery_failed",
                provider=result.provider,
                error_code=result.error_code,
                will_retry=can_retry,
            )


def _mark_failed(event, error_code, error_detail, retry=True):
    event.status = "pending" if retry else "failed"
    event.error_detail = f"{error_code}: {error_detail}"[:1000]
    event.save(update_fields=["status", "error_detail"])


def _create_notification_log(event):
    from apps.infrastructure.accounts.models import CustomUser
    from apps.infrastructure.core.rls import set_tenant_context
    from apps.infrastructure.tenants.models import Organization

    try:
        org = Organization.objects.get(id=event.org_id)
        user = CustomUser.objects.get(id=event.recipient_user_id)
    except Exception as exc:
        logger.error("outbox.log_create_failed", event_id=str(event.id), error=str(exc))
        return

    with set_tenant_context(org):
        NotificationLog.objects.create(
            org=org,
            event_type=event.event_type,
            title=event.subject,
            body=event.body,
            severity="info",
            channel="in_app",
            recipient=user,
            outbox_event_id=event.id,
        )
