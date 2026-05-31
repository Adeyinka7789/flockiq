from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class NotificationPayload:
    recipient_id: str
    recipient_phone: str
    recipient_email: str
    subject: str
    body: str
    body_html: str
    channel: str
    idempotency_key: str
    org_id: str


@dataclass
class DeliveryResult:
    success: bool
    provider: str
    external_id: str | None = None
    error_code: str | None = None
    error_detail: str | None = None
    should_retry: bool = False


class AbstractNotificationProvider(ABC):
    @property
    @abstractmethod
    def provider_name(self) -> str: ...

    @abstractmethod
    def supports_channel(self, channel: str) -> bool: ...

    @abstractmethod
    def send(self, payload: NotificationPayload) -> DeliveryResult: ...
