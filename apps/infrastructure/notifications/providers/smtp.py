import structlog
from django.core.mail import EmailMultiAlternatives

from .base import AbstractNotificationProvider, DeliveryResult, NotificationPayload

logger = structlog.get_logger(__name__)


class SMTPProvider(AbstractNotificationProvider):
    @property
    def provider_name(self) -> str:
        return "smtp"

    def supports_channel(self, channel: str) -> bool:
        return channel == "email"

    def send(self, payload: NotificationPayload) -> DeliveryResult:
        log = logger.bind(
            provider=self.provider_name,
            idempotency_key=payload.idempotency_key,
            recipient_email=payload.recipient_email,
        )
        try:
            msg = EmailMultiAlternatives(
                subject=payload.subject,
                body=payload.body,
                to=[payload.recipient_email],
            )
            if payload.body_html:
                msg.attach_alternative(payload.body_html, "text/html")
            msg.send()
            log.info("smtp.delivered")
            return DeliveryResult(success=True, provider=self.provider_name)
        except Exception as exc:
            log.error("smtp.failed", error=str(exc))
            return DeliveryResult(
                success=False,
                provider=self.provider_name,
                error_detail=str(exc),
                should_retry=True,
            )
