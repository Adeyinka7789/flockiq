import structlog

from .base import AbstractNotificationProvider, DeliveryResult, NotificationPayload

logger = structlog.get_logger(__name__)


class InAppProvider(AbstractNotificationProvider):
    @property
    def provider_name(self) -> str:
        return "inapp"

    def supports_channel(self, channel: str) -> bool:
        return channel == "in_app"

    def send(self, payload: NotificationPayload) -> DeliveryResult:
        log = logger.bind(
            provider=self.provider_name,
            idempotency_key=payload.idempotency_key,
            recipient_id=payload.recipient_id,
        )
        # Notification log is written by the outbox processor after calling send(),
        # so it can associate the outbox_event_id. InAppProvider just signals success.
        log.info("inapp.queued_for_log_write")
        return DeliveryResult(success=True, provider=self.provider_name)
