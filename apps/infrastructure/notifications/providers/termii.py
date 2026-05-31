import structlog
import requests
from django.conf import settings

from .base import AbstractNotificationProvider, DeliveryResult, NotificationPayload

logger = structlog.get_logger(__name__)

BASE_URL = "https://api.ng.termii.com/api"
TIMEOUT = 10


class TermiiProvider(AbstractNotificationProvider):
    @property
    def provider_name(self) -> str:
        return "termii"

    def supports_channel(self, channel: str) -> bool:
        return channel == "sms"

    def send(self, payload: NotificationPayload) -> DeliveryResult:
        body_text = payload.body[:160]
        log = logger.bind(
            provider=self.provider_name,
            idempotency_key=payload.idempotency_key,
            recipient_phone=payload.recipient_phone,
        )
        try:
            response = requests.post(
                f"{BASE_URL}/sms/send",
                json={
                    "to": payload.recipient_phone,
                    "from": settings.TERMII_SENDER_ID,
                    "sms": body_text,
                    "type": "plain",
                    "api_key": settings.TERMII_API_KEY,
                    "channel": "generic",
                },
                timeout=TIMEOUT,
            )
        except requests.Timeout:
            log.warning("termii.timeout")
            return DeliveryResult(
                success=False,
                provider=self.provider_name,
                error_code="timeout",
                error_detail="Request timed out",
                should_retry=True,
            )
        except requests.RequestException as exc:
            log.error("termii.request_error", error=str(exc))
            return DeliveryResult(
                success=False,
                provider=self.provider_name,
                error_code="request_error",
                error_detail=str(exc),
                should_retry=True,
            )

        if response.status_code in (400, 422):
            log.error("termii.permanent_failure", status=response.status_code, body=response.text[:200])
            return DeliveryResult(
                success=False,
                provider=self.provider_name,
                error_code=str(response.status_code),
                error_detail=response.text[:500],
                should_retry=False,
            )

        try:
            data = response.json()
        except Exception:
            data = {}

        if response.status_code == 200 and data.get("code") == "ok":
            log.info("termii.delivered", message_id=data.get("message_id"))
            return DeliveryResult(
                success=True,
                provider=self.provider_name,
                external_id=str(data.get("message_id", "")),
            )

        log.error("termii.unexpected_response", status=response.status_code, body=response.text[:200])
        return DeliveryResult(
            success=False,
            provider=self.provider_name,
            error_code=str(response.status_code),
            error_detail=response.text[:500],
            should_retry=True,
        )
