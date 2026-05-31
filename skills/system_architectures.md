# FlockIQ — Core Engine Technical Specification
## `skills/system_architectures.md`

**Version:** 1.0  
**Date:** April 2026  
**Author:** ADM Tech Hub — Lead Systems Architecture  
**Status:** PRE-SPRINT FINAL — Approved for 12-hour coding sprint  
**Governs:** All 18 Django apps across `apps/infrastructure/`, `apps/farm/`, `apps/production/`, `apps/health/`, `apps/finance/`

---

## Table of Contents

1. [Zero-Leak RLS Rule — The Prime Directive](#1-zero-leak-rls-rule--the-prime-directive)
2. [Resilient Notification Engine](#2-resilient-notification-engine)
3. [Financial & Inventory Reconciliation System](#3-financial--inventory-reconciliation-system)
4. [Breed-Specific Calculation Engine](#4-breed-specific-calculation-engine)
5. [AI/ML Background Pipeline](#5-aiml-background-pipeline)
6. [Offline-Sync (PWA) Protocol](#6-offline-sync-pwa-protocol)
7. [RLS-Aware Celery Context](#7-rls-aware-celery-context)
8. [Cross-Cutting Invariants](#8-cross-cutting-invariants)

---

## 1. Zero-Leak RLS Rule — The Prime Directive

Every design decision in this document is subordinate to this rule. Read it before touching any code.

### 1.1 Rule Definition

> **No query against a tenant-scoped table may execute without an active `app.current_org_id` session variable set at the PostgreSQL transaction level.**

This is enforced at **two independent layers**. Both must hold:

| Layer | Mechanism | Fail-open? |
|---|---|---|
| PostgreSQL RLS | `SET LOCAL app.current_org_id = '{uuid}'` before every DML | No — RLS policy returns zero rows |
| Django ORM | `TenantAwareManager` filters `org=get_current_org()` | No — manager raises `ImproperlyConfigured` if org is None in non-worker context |

The two-layer design means **an ORM bug cannot leak data** — the DB will silently return nothing. An RLS misconfiguration will be caught by the ORM filter. Neither layer alone is sufficient.

### 1.2 PostgreSQL RLS Policy (Reference)

```sql
-- Applied to every tenant-scoped table at migration time
ALTER TABLE flocks_batch ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON flocks_batch
    USING (org_id = current_setting('app.current_org_id', TRUE)::uuid);

-- The TRUE arg means: return NULL (not error) when variable is unset.
-- The USING clause then fails the uuid cast → zero rows returned.
-- This is the safe default. Never use FALSE.
```

### 1.3 The One Permitted Bypass

Infrastructure tables that are explicitly cross-tenant (read-only by workers) must be declared at migration time:

```python
# In the migration that creates the table:
operations = [
    migrations.RunSQL(
        "ALTER TABLE weather_weathercache DISABLE ROW LEVEL SECURITY;",
        reverse_sql="ALTER TABLE weather_weathercache ENABLE ROW LEVEL SECURITY;",
    )
]
# Tables that may disable RLS: WeatherCache, OutboxEvent (read by processor),
# TaskTemplate (shared definitions), BillingPlan (global plans).
# Every other table: RLS ON, no exceptions.
```

---

## 2. Resilient Notification Engine

### 2.1 Architecture Overview

```
[Domain Service]
      │ NotificationService(org).send(event)
      ▼
[NotificationService]  ←── reads AlertRule per org
      │ creates OutboxEvent (atomic with domain write)
      ▼
[PostgreSQL: notifications_outboxevent]
      ▲
      │ polls every 30s
[Celery Beat: process_outbox]
      │
      ├── TermiiProvider (SMS)
      ├── SMTPProvider (Email)
      └── InAppProvider (DB record + WebSocket push)
```

The key invariant: **notification creation is atomic with the domain write**. If the batch mortality log saves, the notification will eventually deliver. If the HTTP request aborts before commit, neither record exists.

### 2.2 Abstract Provider Interface

```python
# apps/infrastructure/notifications/providers/base.py

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
import enum


class NotificationChannel(str, enum.Enum):
    SMS = "sms"
    EMAIL = "email"
    IN_APP = "in_app"


@dataclass(frozen=True)
class NotificationPayload:
    """
    Immutable value object passed to every provider.
    No Django models — providers must not touch the ORM.
    """
    recipient_id: str          # UUID string of the User
    recipient_phone: str       # E.164 format: +2348012345678
    recipient_email: str
    subject: str               # Used by email; truncated for SMS
    body: str                  # Plain text; HTML variant in body_html
    body_html: Optional[str]
    channel: NotificationChannel
    idempotency_key: str       # Prevents duplicate delivery on retry
    org_id: str                # For provider-level logging only; no DB queries


class AbstractNotificationProvider(ABC):
    """
    Contract every channel provider must implement.
    Providers are stateless — instantiate fresh per-delivery attempt.
    """

    @abstractmethod
    def send(self, payload: NotificationPayload) -> "DeliveryResult":
        """
        Attempt delivery. Never raises — return a failed DeliveryResult instead.
        Raising inside a provider crashes the Celery task and bypasses retry logic.
        """
        ...

    @abstractmethod
    def supports_channel(self, channel: NotificationChannel) -> bool:
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str:
        ...


@dataclass
class DeliveryResult:
    success: bool
    provider: str
    external_id: Optional[str]   # Termii message ID, SMTP message ID, etc.
    error_code: Optional[str]
    error_detail: Optional[str]
    should_retry: bool            # False for permanent failures (invalid number)
```

### 2.3 Concrete Provider Implementations

```python
# apps/infrastructure/notifications/providers/termii.py

import hashlib
import logging
import requests
from django.conf import settings
from .base import AbstractNotificationProvider, DeliveryResult, NotificationChannel, NotificationPayload

logger = logging.getLogger(__name__)


class TermiiProvider(AbstractNotificationProvider):
    """
    Termii SMS gateway — primary channel for Nigerian farmers.
    Docs: https://developers.termii.com/messaging
    """
    BASE_URL = "https://api.ng.termii.com/api"
    TIMEOUT = 10  # seconds

    def supports_channel(self, channel: NotificationChannel) -> bool:
        return channel == NotificationChannel.SMS

    @property
    def provider_name(self) -> str:
        return "termii"

    def send(self, payload: NotificationPayload) -> DeliveryResult:
        try:
            response = requests.post(
                f"{self.BASE_URL}/sms/send",
                json={
                    "to": payload.recipient_phone,
                    "from": settings.TERMII_SENDER_ID,
                    "sms": payload.body[:160],  # Hard SMS limit
                    "type": "plain",
                    "api_key": settings.TERMII_API_KEY,
                    "channel": "generic",
                },
                timeout=self.TIMEOUT,
            )
            data = response.json()

            if response.status_code == 200 and data.get("code") == "ok":
                return DeliveryResult(
                    success=True,
                    provider=self.provider_name,
                    external_id=data.get("message_id"),
                    error_code=None,
                    error_detail=None,
                    should_retry=False,
                )

            # Termii permanent failures: invalid number, DND list
            permanent = response.status_code in (400, 422)
            return DeliveryResult(
                success=False,
                provider=self.provider_name,
                external_id=None,
                error_code=str(response.status_code),
                error_detail=data.get("message", "Unknown Termii error"),
                should_retry=not permanent,
            )

        except requests.Timeout:
            logger.warning("Termii timeout for idempotency_key=%s", payload.idempotency_key)
            return DeliveryResult(False, self.provider_name, None, "TIMEOUT", "Request timed out", should_retry=True)
        except Exception as exc:
            logger.exception("Termii unexpected error: %s", exc)
            return DeliveryResult(False, self.provider_name, None, "EXCEPTION", str(exc), should_retry=True)


# apps/infrastructure/notifications/providers/smtp.py

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from django.conf import settings
from .base import AbstractNotificationProvider, DeliveryResult, NotificationChannel, NotificationPayload


class SMTPProvider(AbstractNotificationProvider):

    def supports_channel(self, channel: NotificationChannel) -> bool:
        return channel == NotificationChannel.EMAIL

    @property
    def provider_name(self) -> str:
        return "smtp"

    def send(self, payload: NotificationPayload) -> DeliveryResult:
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = payload.subject
            msg["From"] = settings.DEFAULT_FROM_EMAIL
            msg["To"] = payload.recipient_email
            msg["X-Idempotency-Key"] = payload.idempotency_key  # For de-dup at receiver

            msg.attach(MIMEText(payload.body, "plain"))
            if payload.body_html:
                msg.attach(MIMEText(payload.body_html, "html"))

            with smtplib.SMTP_SSL(settings.EMAIL_HOST, settings.EMAIL_PORT) as server:
                server.login(settings.EMAIL_HOST_USER, settings.EMAIL_HOST_PASSWORD)
                server.sendmail(settings.DEFAULT_FROM_EMAIL, [payload.recipient_email], msg.as_string())

            return DeliveryResult(True, self.provider_name, None, None, None, False)

        except smtplib.SMTPRecipientsRefused:
            return DeliveryResult(False, self.provider_name, None, "INVALID_RECIPIENT", "Address rejected", should_retry=False)
        except Exception as exc:
            return DeliveryResult(False, self.provider_name, None, "EXCEPTION", str(exc), should_retry=True)


# apps/infrastructure/notifications/providers/inapp.py

from django.utils import timezone
from .base import AbstractNotificationProvider, DeliveryResult, NotificationChannel, NotificationPayload


class InAppProvider(AbstractNotificationProvider):
    """
    Writes to notifications_inappnotification table.
    The frontend polls /api/notifications/unread/ or consumes Django Channels WS.
    This provider is the guaranteed fallback — it never fails.
    """

    def supports_channel(self, channel: NotificationChannel) -> bool:
        return channel == NotificationChannel.IN_APP

    @property
    def provider_name(self) -> str:
        return "in_app"

    def send(self, payload: NotificationPayload) -> DeliveryResult:
        # Inline import to avoid circular dependency at module load
        from apps.infrastructure.notifications.models import InAppNotification
        try:
            InAppNotification.objects.update_or_create(
                idempotency_key=payload.idempotency_key,
                defaults={
                    "user_id": payload.recipient_id,
                    "org_id": payload.org_id,
                    "subject": payload.subject,
                    "body": payload.body,
                    "delivered_at": timezone.now(),
                    "is_read": False,
                },
            )
            return DeliveryResult(True, self.provider_name, None, None, None, False)
        except Exception as exc:
            return DeliveryResult(False, self.provider_name, None, "DB_ERROR", str(exc), should_retry=True)
```

### 2.4 Outbox Pattern — Models

```python
# apps/infrastructure/notifications/models.py

import uuid
from django.db import models
from apps.infrastructure.core.models import TimeStampedModel


class OutboxEvent(TimeStampedModel):
    """
    Transactionally created alongside domain writes.
    No RLS — read by Celery worker cross-tenant.
    Processor atomically claims events with SELECT FOR UPDATE SKIP LOCKED.
    """

    class Status(models.TextChoices):
        PENDING   = "pending",   "Pending"
        CLAIMED   = "claimed",   "Claimed by worker"
        DELIVERED = "delivered", "Delivered"
        FAILED    = "failed",    "Permanently failed"

    class Channel(models.TextChoices):
        SMS    = "sms",    "SMS"
        EMAIL  = "email",  "Email"
        IN_APP = "in_app", "In-App"

    id              = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org_id          = models.UUIDField(db_index=True)  # Not FK — RLS bypass
    recipient_id    = models.UUIDField()
    channel         = models.CharField(max_length=10, choices=Channel.choices)
    subject         = models.CharField(max_length=255)
    body            = models.TextField()
    body_html       = models.TextField(blank=True, default="")
    idempotency_key = models.CharField(max_length=128, unique=True, db_index=True)
    status          = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True)
    attempt_count   = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_error      = models.TextField(blank=True, default="")
    external_id     = models.CharField(max_length=128, blank=True, default="")
    delivered_at    = models.DateTimeField(null=True, blank=True)

    MAX_ATTEMPTS = 5

    class Meta:
        indexes = [
            models.Index(fields=["status", "next_attempt_at"]),
            models.Index(fields=["org_id", "created_at"]),
        ]

    def compute_next_attempt(self) -> "datetime":
        """Exponential backoff: 30s, 2m, 8m, 32m, 2h"""
        from django.utils import timezone
        import datetime
        delay_seconds = 30 * (4 ** self.attempt_count)
        delay_seconds = min(delay_seconds, 7200)  # Cap at 2 hours
        return timezone.now() + datetime.timedelta(seconds=delay_seconds)
```

### 2.5 Idempotency Key Generation

```python
# apps/infrastructure/notifications/utils.py

import hashlib


def build_idempotency_key(event_type: str, domain_id: str, recipient_id: str, channel: str) -> str:
    """
    Deterministic key — safe to retry, safe to replay.
    Same inputs always produce the same key, so update_or_create is safe.

    Format: sha256(event_type:domain_id:recipient_id:channel)[:40]

    Examples:
        build_idempotency_key("mortality_alert", batch_id, user_id, "sms")
        build_idempotency_key("vaccination_reminder", schedule_id, user_id, "email")
        build_idempotency_key("diagnosis_ready", diagnosis_id, user_id, "in_app")
    """
    raw = f"{event_type}:{domain_id}:{recipient_id}:{channel}"
    return hashlib.sha256(raw.encode()).hexdigest()[:40]
```

### 2.6 NotificationService — Orchestration Layer

```python
# apps/infrastructure/notifications/services.py

import logging
from django.db import transaction
from django.utils import timezone
from apps.infrastructure.core.services import BaseService
from .models import OutboxEvent
from .utils import build_idempotency_key

logger = logging.getLogger(__name__)


class NotificationService(BaseService):
    """
    The single entry point for all notifications.
    Domain services call this — never instantiate providers directly.
    """

    def send(
        self,
        event_type: str,
        domain_id: str,
        recipient_id: str,
        channel: str,
        subject: str,
        body: str,
        body_html: str = "",
    ) -> OutboxEvent:
        """
        MUST be called inside the same transaction.atomic() block as the domain write.
        If the outer transaction rolls back, this event is never committed.

        Usage:
            with transaction.atomic():
                log = MortalityLog.objects.create(...)
                NotificationService(org).send(
                    event_type="mortality_alert",
                    domain_id=str(log.id),
                    recipient_id=str(manager.id),
                    channel="sms",
                    subject="Mortality Alert",
                    body=f"Batch {log.batch}: {log.count} deaths logged.",
                )
        """
        key = build_idempotency_key(event_type, domain_id, recipient_id, channel)

        event, created = OutboxEvent.objects.get_or_create(
            idempotency_key=key,
            defaults={
                "org_id": self.org.id,
                "recipient_id": recipient_id,
                "channel": channel,
                "subject": subject,
                "body": body,
                "body_html": body_html,
                "status": OutboxEvent.Status.PENDING,
                "next_attempt_at": timezone.now(),
            },
        )

        if not created:
            logger.info("Duplicate notification suppressed: key=%s", key)

        return event

    def send_diagnosis_alert(self, diagnosis) -> None:
        """Convenience method for the AI pipeline."""
        from apps.infrastructure.accounts.models import User
        managers = User.objects.filter(
            org=self.org,
            role__in=["farm_manager", "vet"],
        )
        for manager in managers:
            self.send(
                event_type="diagnosis_ready",
                domain_id=str(diagnosis.id),
                recipient_id=str(manager.id),
                channel="in_app",
                subject="AI Diagnosis Ready",
                body=f"Probable: {diagnosis.suggested_disease} ({diagnosis.confidence_score:.0%} confidence). "
                     f"Protocol: {diagnosis.treatment_protocol}",
            )
```

### 2.7 Outbox Processor — Celery Task

```python
# apps/infrastructure/notifications/tasks.py

import logging
from celery import shared_task
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

PROVIDER_REGISTRY = {
    "sms":    "apps.infrastructure.notifications.providers.termii.TermiiProvider",
    "email":  "apps.infrastructure.notifications.providers.smtp.SMTPProvider",
    "in_app": "apps.infrastructure.notifications.providers.inapp.InAppProvider",
}


@shared_task(name="notifications.process_outbox")
def process_outbox():
    """
    Runs every 30 seconds via Celery Beat.
    Claims a batch of PENDING events atomically, delivers each in a sub-task.
    SELECT FOR UPDATE SKIP LOCKED prevents multiple workers competing for the same rows.
    """
    from .models import OutboxEvent

    with transaction.atomic():
        events = (
            OutboxEvent.objects
            .select_for_update(skip_locked=True)
            .filter(
                status__in=[OutboxEvent.Status.PENDING],
                next_attempt_at__lte=timezone.now(),
            )
            .exclude(attempt_count__gte=OutboxEvent.MAX_ATTEMPTS)
            [:50]  # Process in batches of 50; prevents long-lock transactions
        )

        ids = list(events.values_list("id", flat=True))
        if ids:
            OutboxEvent.objects.filter(id__in=ids).update(status=OutboxEvent.Status.CLAIMED)

    # Deliver outside the lock — failures don't block other workers
    for event_id in ids:
        deliver_outbox_event.delay(str(event_id))


@shared_task(name="notifications.deliver_event", max_retries=0)
def deliver_outbox_event(event_id: str):
    """
    Delivers a single OutboxEvent. Handles its own retry state.
    max_retries=0 because retry logic is in the OutboxEvent model itself.
    """
    import importlib
    from .models import OutboxEvent
    from .providers.base import NotificationPayload

    try:
        event = OutboxEvent.objects.get(id=event_id)
    except OutboxEvent.DoesNotExist:
        logger.error("OutboxEvent %s not found", event_id)
        return

    # Resolve provider
    provider_path = PROVIDER_REGISTRY.get(event.channel)
    if not provider_path:
        logger.error("No provider for channel=%s event=%s", event.channel, event_id)
        _mark_failed(event, "NO_PROVIDER", f"No provider registered for {event.channel}")
        return

    module_path, class_name = provider_path.rsplit(".", 1)
    ProviderClass = getattr(importlib.import_module(module_path), class_name)
    provider = ProviderClass()

    # Fetch recipient contact info — must re-establish tenant context
    from apps.infrastructure.accounts.models import User
    try:
        user = User.objects.get(id=event.recipient_id)
    except User.DoesNotExist:
        _mark_failed(event, "NO_RECIPIENT", "Recipient user not found")
        return

    payload = NotificationPayload(
        recipient_id=str(event.recipient_id),
        recipient_phone=user.phone_number or "",
        recipient_email=user.email,
        subject=event.subject,
        body=event.body,
        body_html=event.body_html,
        channel=event.channel,
        idempotency_key=event.idempotency_key,
        org_id=str(event.org_id),
    )

    result = provider.send(payload)
    event.attempt_count += 1

    if result.success:
        event.status = OutboxEvent.Status.DELIVERED
        event.external_id = result.external_id or ""
        event.delivered_at = timezone.now()
        logger.info("Delivered event=%s via %s", event_id, result.provider)
    elif not result.should_retry or event.attempt_count >= OutboxEvent.MAX_ATTEMPTS:
        _mark_failed(event, result.error_code, result.error_detail)
    else:
        event.status = OutboxEvent.Status.PENDING
        event.next_attempt_at = event.compute_next_attempt()
        event.last_error = f"{result.error_code}: {result.error_detail}"
        logger.warning(
            "Delivery failed, retry scheduled: event=%s attempt=%d next=%s",
            event_id, event.attempt_count, event.next_attempt_at
        )

    event.save(update_fields=[
        "status", "attempt_count", "next_attempt_at",
        "last_error", "external_id", "delivered_at"
    ])


def _mark_failed(event, error_code, error_detail):
    event.status = OutboxEvent.Status.FAILED
    event.last_error = f"{error_code}: {error_detail}"
    logger.error("Permanently failed event=%s: %s — %s", event.id, error_code, error_detail)
```

---

## 3. Financial & Inventory Reconciliation System

### 3.1 Double-Entry Accounting Model

FlockIQ uses a simplified double-entry model adapted for farm economics. Every financial event creates **two ledger entries** — a debit and a credit — that always balance.

```
TRANSACTION TYPE        DEBIT                   CREDIT
─────────────────────   ─────────────────────   ─────────────────────
Feed purchase           FeedStock (asset +)     Cash/Payable (equity -)
Feed consumption        CostOfGoods (expense +) FeedStock (asset -)
Egg sale                Cash (asset +)           Revenue (income +)
Broiler sale            Cash (asset +)           Revenue (income +)
Mortality               Loss (expense +)         LivestockAsset (asset -)
Medication purchase     MedInventory (asset +)   Cash/Payable (equity -)
```

### 3.2 Ledger Model

```python
# apps/infrastructure/core/ledger.py

import enum
from django.db import models
from apps.infrastructure.core.models import TenantAwareModel


class LedgerEntryType(str, enum.Enum):
    DEBIT  = "debit"
    CREDIT = "credit"


class LedgerAccount(str, enum.Enum):
    # Assets
    CASH            = "cash"
    FEED_STOCK      = "feed_stock"
    MED_INVENTORY   = "med_inventory"
    LIVESTOCK_ASSET = "livestock_asset"
    ACCOUNTS_REC    = "accounts_receivable"
    # Income
    EGG_REVENUE     = "egg_revenue"
    BROILER_REVENUE = "broiler_revenue"
    # Expenses
    FEED_COST       = "feed_cost"
    MED_COST        = "med_cost"
    LABOUR_COST     = "labour_cost"
    MORTALITY_LOSS  = "mortality_loss"
    OVERHEAD        = "overhead"
    # Equity / Contra
    ACCOUNTS_PAY    = "accounts_payable"
    OWNER_EQUITY    = "owner_equity"


class LedgerEntry(TenantAwareModel):
    """
    Immutable — never UPDATE or DELETE a LedgerEntry.
    Corrections use reversal entries (equal and opposite).
    """
    batch         = models.ForeignKey("flocks.Batch", on_delete=models.PROTECT, null=True, blank=True)
    entry_type    = models.CharField(max_length=6, choices=[(e.value, e.value) for e in LedgerEntryType])
    account       = models.CharField(max_length=32, choices=[(e.value, e.value) for e in LedgerAccount])
    amount        = models.DecimalField(max_digits=14, decimal_places=2)  # Always positive
    currency      = models.CharField(max_length=3, default="NGN")
    reference_id  = models.UUIDField(db_index=True)   # FK to the source record (FeedMovement, SaleRecord, etc.)
    reference_type = models.CharField(max_length=64)   # e.g. "feed.FeedMovement", "finance.SaleRecord"
    description   = models.TextField()
    transaction_date = models.DateField(db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=["org", "account", "transaction_date"]),
            models.Index(fields=["batch", "transaction_date"]),
            models.Index(fields=["reference_id", "reference_type"]),
        ]
```

### 3.3 Reconciliation Service

```python
# apps/infrastructure/core/services.py
# This is the ONLY file allowed to import across domain boundaries for financial ops.
# Domain services call into here; they never import each other directly.

from decimal import Decimal
from django.db import transaction
from .ledger import LedgerEntry, LedgerEntryType, LedgerAccount


class LedgerService:
    """
    Central double-entry engine. All cross-app financial writes go through here.
    Circular import prevention: this file imports from ORM models only — never from
    other services. Domain services pass data as primitives, not model instances.
    """

    @staticmethod
    def _post(org_id, batch_id, reference_id, reference_type, description, date, entries: list[dict]):
        """
        Posts a balanced set of ledger entries atomically.
        Raises ValueError if entries don't balance (sum of debits ≠ sum of credits).
        """
        debits  = sum(e["amount"] for e in entries if e["type"] == LedgerEntryType.DEBIT)
        credits = sum(e["amount"] for e in entries if e["type"] == LedgerEntryType.CREDIT)
        if round(debits - credits, 2) != Decimal("0.00"):
            raise ValueError(
                f"Unbalanced ledger transaction: debits={debits} credits={credits} "
                f"ref={reference_type}:{reference_id}"
            )
        with transaction.atomic():
            LedgerEntry.objects.bulk_create([
                LedgerEntry(
                    org_id=org_id,
                    batch_id=batch_id,
                    entry_type=e["type"],
                    account=e["account"],
                    amount=e["amount"],
                    reference_id=reference_id,
                    reference_type=reference_type,
                    description=description,
                    transaction_date=date,
                )
                for e in entries
            ])

    # ── Feed purchase (procurement → inventory) ────────────────────────────
    @classmethod
    def post_feed_purchase(cls, org_id, batch_id, movement_id, amount: Decimal, date):
        cls._post(org_id, batch_id, movement_id, "feed.FeedMovement", "Feed stock purchase", date, [
            {"type": LedgerEntryType.DEBIT,  "account": LedgerAccount.FEED_STOCK,   "amount": amount},
            {"type": LedgerEntryType.CREDIT, "account": LedgerAccount.ACCOUNTS_PAY, "amount": amount},
        ])

    # ── Feed consumption (inventory → cost of goods) ───────────────────────
    @classmethod
    def post_feed_consumption(cls, org_id, batch_id, movement_id, amount: Decimal, date):
        cls._post(org_id, batch_id, movement_id, "feed.FeedMovement", "Daily feed consumption", date, [
            {"type": LedgerEntryType.DEBIT,  "account": LedgerAccount.FEED_COST,   "amount": amount},
            {"type": LedgerEntryType.CREDIT, "account": LedgerAccount.FEED_STOCK,  "amount": amount},
        ])

    # ── Egg sale ───────────────────────────────────────────────────────────
    @classmethod
    def post_egg_sale(cls, org_id, batch_id, sale_id, amount: Decimal, date):
        cls._post(org_id, batch_id, sale_id, "finance.SaleRecord", "Egg sale", date, [
            {"type": LedgerEntryType.DEBIT,  "account": LedgerAccount.CASH,         "amount": amount},
            {"type": LedgerEntryType.CREDIT, "account": LedgerAccount.EGG_REVENUE,  "amount": amount},
        ])

    # ── Broiler sale ───────────────────────────────────────────────────────
    @classmethod
    def post_broiler_sale(cls, org_id, batch_id, sale_id, amount: Decimal, date):
        cls._post(org_id, batch_id, sale_id, "finance.SaleRecord", "Broiler sale", date, [
            {"type": LedgerEntryType.DEBIT,  "account": LedgerAccount.CASH,             "amount": amount},
            {"type": LedgerEntryType.CREDIT, "account": LedgerAccount.BROILER_REVENUE,  "amount": amount},
        ])

    # ── Mortality write-down ───────────────────────────────────────────────
    @classmethod
    def post_mortality_writedown(cls, org_id, batch_id, log_id, amount: Decimal, date):
        cls._post(org_id, batch_id, log_id, "flocks.MortalityLog", "Mortality asset write-down", date, [
            {"type": LedgerEntryType.DEBIT,  "account": LedgerAccount.MORTALITY_LOSS,  "amount": amount},
            {"type": LedgerEntryType.CREDIT, "account": LedgerAccount.LIVESTOCK_ASSET, "amount": amount},
        ])

    # ── Reconciliation query ───────────────────────────────────────────────
    @classmethod
    def get_batch_pnl(cls, org_id, batch_id) -> dict:
        """Returns a profit-and-loss summary for a batch using the ledger."""
        from django.db.models import Sum, Q
        from .ledger import LedgerAccount as LA, LedgerEntryType as LET

        entries = LedgerEntry.objects.filter(org_id=org_id, batch_id=batch_id)

        def balance(account):
            debits  = entries.filter(account=account, entry_type=LET.DEBIT).aggregate(t=Sum("amount"))["t"] or 0
            credits = entries.filter(account=account, entry_type=LET.CREDIT).aggregate(t=Sum("amount"))["t"] or 0
            return debits - credits

        revenue   = abs(balance(LA.EGG_REVENUE)) + abs(balance(LA.BROILER_REVENUE))
        feed_cost = abs(balance(LA.FEED_COST))
        med_cost  = abs(balance(LA.MED_COST))
        mortality = abs(balance(LA.MORTALITY_LOSS))
        overhead  = abs(balance(LA.OVERHEAD))
        total_cost = feed_cost + med_cost + mortality + overhead

        return {
            "revenue":    float(revenue),
            "feed_cost":  float(feed_cost),
            "med_cost":   float(med_cost),
            "mortality_loss": float(mortality),
            "overhead":   float(overhead),
            "total_cost": float(total_cost),
            "gross_profit": float(revenue - total_cost),
            "margin_pct": round(((revenue - total_cost) / revenue * 100), 2) if revenue else 0,
        }
```

### 3.4 Circular Import Prevention Rules

These rules are **enforced at code review**. PR reviewers must reject any violation.

```
RULE 1 — Direction of import:
    infrastructure/* ← farm/* ← production/* ← health/* ← finance/*
    Lower layers NEVER import from higher layers.

RULE 2 — Cross-domain coordination:
    If App A needs data from App B (same or different domain group),
    it calls LedgerService or a shared service in apps/infrastructure/core/services.py.
    It never imports App B's service directly.

RULE 3 — Model FKs are allowed across apps:
    FeedMovement.batch = FK(flocks.Batch) is fine.
    FeedService importing BatchService is NOT fine.

RULE 4 — The one permitted cross-domain service call:
    notifications.services.NotificationService may be called from any domain service.
    analytics.services.DiagnosisService may read (not write) from any domain model.

RULE 5 — Inline imports for unavoidable runtime dependencies:
    If a circular import is architecturally required (e.g., signals),
    use inline imports inside the method body, never at module level.
    Document with a comment: # Inline import: avoids circular import with flocks.services
```

---

## 4. Breed-Specific Calculation Engine

### 4.1 Design Rationale

All calculations are centralised in a single `PoultryCalculator` class. The alternative — scattering formula logic across `signals.py` files — causes drift when breed standards change (e.g., a new Ross 308 performance target) and makes testing difficult.

The calculator is **pure Python** — no ORM access, no Celery. It receives primitive values and returns primitive values. This makes it trivially testable and safe to call from signals, services, and Celery tasks alike.

### 4.2 Breed Standards Registry

```python
# apps/infrastructure/core/breed_standards.py

from dataclasses import dataclass
from typing import Dict, List


@dataclass(frozen=True)
class WeeklyFeedRate:
    week: int
    grams_per_bird_per_day: float


@dataclass(frozen=True)
class BreedStandard:
    name: str
    bird_type: str                         # "broiler" | "layer" | "cockerel" | "turkey"
    water_ml_per_bird_per_day: float       # Base; adjusted +10% per °C above 25°C
    acceptable_mortality_pct_weekly: float # Alert threshold
    target_fcr_at_close: float             # Broiler: typically 1.7–1.9
    target_hen_day_pct: float              # Layer: 80–90%
    expected_egg_weight_g: float           # Layer: typically 55–65g
    feed_rates: List[WeeklyFeedRate]       # Per-week standard


# Standards sourced from Cobb, Ross, and Hy-Line breed guides.
# Update this registry when new breeds or updated guides are adopted.
BREED_STANDARDS: Dict[str, BreedStandard] = {

    "broiler_cobb500": BreedStandard(
        name="Cobb 500",
        bird_type="broiler",
        water_ml_per_bird_per_day=200,
        acceptable_mortality_pct_weekly=0.5,
        target_fcr_at_close=1.80,
        target_hen_day_pct=0.0,
        expected_egg_weight_g=0.0,
        feed_rates=[
            WeeklyFeedRate(1, 25), WeeklyFeedRate(2, 50),
            WeeklyFeedRate(3, 80), WeeklyFeedRate(4, 110),
            WeeklyFeedRate(5, 140), WeeklyFeedRate(6, 160),
        ],
    ),

    "broiler_ross308": BreedStandard(
        name="Ross 308",
        bird_type="broiler",
        water_ml_per_bird_per_day=200,
        acceptable_mortality_pct_weekly=0.5,
        target_fcr_at_close=1.75,
        target_hen_day_pct=0.0,
        expected_egg_weight_g=0.0,
        feed_rates=[
            WeeklyFeedRate(1, 23), WeeklyFeedRate(2, 48),
            WeeklyFeedRate(3, 78), WeeklyFeedRate(4, 107),
            WeeklyFeedRate(5, 138), WeeklyFeedRate(6, 158),
        ],
    ),

    "layer_hyline_brown": BreedStandard(
        name="Hy-Line Brown",
        bird_type="layer",
        water_ml_per_bird_per_day=250,
        acceptable_mortality_pct_weekly=0.3,
        target_fcr_at_close=2.20,
        target_hen_day_pct=85.0,
        expected_egg_weight_g=62.0,
        feed_rates=[
            WeeklyFeedRate(w, 110) for w in range(1, 73)  # Stable consumption in lay
        ],
    ),

    "layer_isa_brown": BreedStandard(
        name="ISA Brown",
        bird_type="layer",
        water_ml_per_bird_per_day=240,
        acceptable_mortality_pct_weekly=0.3,
        target_fcr_at_close=2.10,
        target_hen_day_pct=88.0,
        expected_egg_weight_g=63.0,
        feed_rates=[
            WeeklyFeedRate(w, 112) for w in range(1, 73)
        ],
    ),

    # Fallback for unregistered breeds
    "generic_broiler": BreedStandard(
        name="Generic Broiler",
        bird_type="broiler",
        water_ml_per_bird_per_day=200,
        acceptable_mortality_pct_weekly=0.8,
        target_fcr_at_close=2.00,
        target_hen_day_pct=0.0,
        expected_egg_weight_g=0.0,
        feed_rates=[WeeklyFeedRate(w, 100) for w in range(1, 9)],
    ),
    "generic_layer": BreedStandard(
        name="Generic Layer",
        bird_type="layer",
        water_ml_per_bird_per_day=240,
        acceptable_mortality_pct_weekly=0.5,
        target_fcr_at_close=2.20,
        target_hen_day_pct=80.0,
        expected_egg_weight_g=58.0,
        feed_rates=[WeeklyFeedRate(w, 110) for w in range(1, 73)],
    ),
}


def get_breed_standard(bird_type_code: str) -> BreedStandard:
    """
    Returns the standard for a given bird_type code.
    Falls back to generic_broiler or generic_layer if specific breed not registered.
    Never raises — always returns a usable standard.
    """
    if bird_type_code in BREED_STANDARDS:
        return BREED_STANDARDS[bird_type_code]
    # Infer generic from code prefix
    if "layer" in bird_type_code.lower():
        return BREED_STANDARDS["generic_layer"]
    return BREED_STANDARDS["generic_broiler"]
```

### 4.3 PoultryCalculator — Central Engine

```python
# apps/infrastructure/core/calculator.py

from dataclasses import dataclass
from typing import Optional
from .breed_standards import BreedStandard, get_breed_standard


@dataclass
class FCRResult:
    fcr: float
    target_fcr: float
    variance: float          # Positive = worse than target
    performance_pct: float   # >100 = better than target
    rating: str              # "excellent" | "good" | "acceptable" | "poor"


@dataclass
class HenDayResult:
    hen_day_pct: float
    target_pct: float
    variance: float
    rating: str


@dataclass
class MortalityResult:
    cumulative_mortality_pct: float
    weekly_mortality_pct: float
    is_above_threshold: bool
    threshold_pct: float
    alert_required: bool


@dataclass
class WaterRequirement:
    base_litres: float
    heat_adjusted_litres: float   # Adjusted for ambient temperature
    temperature_used: float


@dataclass
class FeedRequirement:
    grams_per_bird: float
    total_kg: float
    week_of_age: int
    is_interpolated: bool  # True if week is beyond the breed table


class PoultryCalculator:
    """
    Stateless calculation engine. All inputs are primitives. All outputs are dataclasses.
    No ORM. No Celery. No side effects.

    Usage:
        calc = PoultryCalculator(bird_type_code="broiler_cobb500")
        fcr = calc.fcr(cumulative_feed_kg=850, cumulative_weight_gain_kg=480)
        water = calc.daily_water_requirement(bird_count=5000, ambient_temp_c=32)
    """

    def __init__(self, bird_type_code: str):
        self.bird_type_code = bird_type_code
        self.standard: BreedStandard = get_breed_standard(bird_type_code)

    # ── Feed Conversion Ratio ──────────────────────────────────────────────
    def fcr(self, cumulative_feed_kg: float, cumulative_weight_gain_kg: float) -> FCRResult:
        if cumulative_weight_gain_kg <= 0:
            raise ValueError("Weight gain must be > 0 to calculate FCR")

        fcr = round(cumulative_feed_kg / cumulative_weight_gain_kg, 3)
        target = self.standard.target_fcr_at_close
        variance = round(fcr - target, 3)
        performance_pct = round((target / fcr) * 100, 1) if fcr > 0 else 0

        if fcr <= target * 0.95:
            rating = "excellent"
        elif fcr <= target:
            rating = "good"
        elif fcr <= target * 1.10:
            rating = "acceptable"
        else:
            rating = "poor"

        return FCRResult(fcr, target, variance, performance_pct, rating)

    # ── Hen-Day Percentage ─────────────────────────────────────────────────
    def hen_day_pct(self, total_eggs: int, live_hen_count: int) -> HenDayResult:
        if self.standard.bird_type != "layer":
            raise ValueError(f"Hen-day % not applicable for bird_type={self.standard.bird_type}")
        if live_hen_count <= 0:
            raise ValueError("live_hen_count must be > 0")

        hdp = round((total_eggs / live_hen_count) * 100, 2)
        target = self.standard.target_hen_day_pct
        variance = round(hdp - target, 2)

        if hdp >= target * 1.05:
            rating = "excellent"
        elif hdp >= target:
            rating = "good"
        elif hdp >= target * 0.90:
            rating = "acceptable"
        else:
            rating = "poor"

        return HenDayResult(hdp, target, variance, rating)

    # ── Mortality Assessment ───────────────────────────────────────────────
    def mortality_assessment(
        self,
        initial_count: int,
        cumulative_deaths: int,
        deaths_this_week: int,
    ) -> MortalityResult:
        cumulative_pct = round((cumulative_deaths / initial_count) * 100, 3) if initial_count else 0
        weekly_pct     = round((deaths_this_week / initial_count) * 100, 3) if initial_count else 0
        threshold      = self.standard.acceptable_mortality_pct_weekly
        above          = weekly_pct > threshold

        return MortalityResult(
            cumulative_mortality_pct=cumulative_pct,
            weekly_mortality_pct=weekly_pct,
            is_above_threshold=above,
            threshold_pct=threshold,
            alert_required=above,
        )

    # ── Daily Water Requirement ────────────────────────────────────────────
    def daily_water_requirement(
        self,
        bird_count: int,
        ambient_temp_c: float = 25.0,
    ) -> WaterRequirement:
        base_ml = self.standard.water_ml_per_bird_per_day * bird_count
        # +10% for each degree above 25°C (industry standard heat correction)
        heat_factor = max(0, (ambient_temp_c - 25) * 0.10)
        adjusted_ml = base_ml * (1 + heat_factor)

        return WaterRequirement(
            base_litres=round(base_ml / 1000, 2),
            heat_adjusted_litres=round(adjusted_ml / 1000, 2),
            temperature_used=ambient_temp_c,
        )

    # ── Daily Feed Requirement ─────────────────────────────────────────────
    def daily_feed_requirement(self, bird_count: int, age_days: int) -> FeedRequirement:
        week = (age_days // 7) + 1
        rates = self.standard.feed_rates
        interpolated = False

        if week <= len(rates):
            rate = rates[week - 1].grams_per_bird_per_day
        else:
            # Beyond table — use last known rate
            rate = rates[-1].grams_per_bird_per_day
            interpolated = True

        total_g = rate * bird_count
        return FeedRequirement(
            grams_per_bird=rate,
            total_kg=round(total_g / 1000, 3),
            week_of_age=week,
            is_interpolated=interpolated,
        )

    # ── Batch-close Summary ────────────────────────────────────────────────
    def batch_performance_summary(
        self,
        initial_count: int,
        final_count: int,
        total_feed_kg: float,
        total_weight_gain_kg: float,
        total_eggs: Optional[int],
        total_days: int,
    ) -> dict:
        """Produces a full performance summary for a closed batch."""
        result = {
            "bird_type": self.standard.bird_type,
            "breed": self.standard.name,
            "total_days": total_days,
            "initial_count": initial_count,
            "final_count": final_count,
        }

        # Mortality
        deaths = initial_count - final_count
        mort = self.mortality_assessment(initial_count, deaths, 0)
        result["cumulative_mortality_pct"] = mort.cumulative_mortality_pct

        # FCR (broilers / any fattening flock)
        if total_weight_gain_kg > 0:
            result["fcr"] = self.fcr(total_feed_kg, total_weight_gain_kg).__dict__

        # Hen-Day (layers)
        if self.standard.bird_type == "layer" and total_eggs and final_count > 0:
            avg_live = (initial_count + final_count) / 2
            hdp = self.hen_day_pct(total_eggs // total_days, int(avg_live))
            result["hen_day_pct"] = hdp.__dict__

        return result
```

---

## 5. AI/ML Background Pipeline

### 5.1 Architecture Overview

```
[Celery Beat]
    │
    ├── daily_egg_forecast (1:00 AM)
    │       │
    │       ▼
    │   [ProphetForecastService]
    │       │  fetches 90d of EggProductionLog per active layer batch
    │       │  runs Prophet model
    │       │  writes ForecastResult to DB
    │       └─ caches result in Redis (key: forecast:{batch_id}, TTL: 25h)
    │
    └── mortality_anomaly_check (every 6h)
            │
            ▼
        [AnomalyDetectionService]
            │  fetches 30d of MortalityLog per active batch
            │  runs Z-score + IQR ensemble
            │  writes AnomalyAlert if threshold exceeded
            └─ sends notification if alert created
```

### 5.2 Prophet Egg Forecasting

```python
# apps/health/analytics/services/forecasting.py

import json
import logging
import pickle
from datetime import timedelta
from typing import Optional

import pandas as pd
from django.core.cache import cache
from django.utils import timezone

from apps.infrastructure.core.services import BaseService

logger = logging.getLogger(__name__)

FORECAST_CACHE_KEY    = "forecast:egg:{batch_id}"
FORECAST_CACHE_TTL    = 25 * 3600   # 25 hours — outlasts the 24h Celery schedule
FORECAST_MIN_ROWS     = 21          # Prophet needs at least 21 observations
FORECAST_HORIZON_DAYS = 14          # Forecast 2 weeks ahead


class ProphetForecastService(BaseService):
    """
    Runs a Facebook Prophet time-series model per active layer batch.
    Called exclusively by Celery Beat — never from HTTP views.
    """

    def forecast_batch(self, batch_id: str) -> Optional[dict]:
        """
        Main entry point. Returns forecast dict or None if insufficient data.
        Result is stored in DB and cached in Redis.
        """
        from apps.production.production.models import EggProductionLog
        from apps.health.analytics.models import ForecastResult

        # Fetch production history for this batch
        logs = (
            EggProductionLog.objects
            .filter(batch_id=batch_id, org=self.org)
            .values("date", "total_eggs", "live_hen_count")
            .order_by("date")
        )

        if len(logs) < FORECAST_MIN_ROWS:
            logger.info("Insufficient data for forecast: batch=%s rows=%d", batch_id, len(logs))
            return None

        df = pd.DataFrame(logs)
        df["hen_day_pct"] = df["total_eggs"] / df["live_hen_count"] * 100
        df = df.rename(columns={"date": "ds", "hen_day_pct": "y"})

        try:
            from prophet import Prophet
            model = Prophet(
                yearly_seasonality=False,   # Batches < 1 year
                weekly_seasonality=True,    # Market demand patterns
                daily_seasonality=False,
                changepoint_prior_scale=0.05,  # Conservative — avoid overfitting short series
                interval_width=0.80,
            )
            model.fit(df[["ds", "y"]])

            future = model.make_future_dataframe(periods=FORECAST_HORIZON_DAYS)
            forecast = model.predict(future)

            # Extract only the future window
            future_forecast = forecast[forecast["ds"] > df["ds"].max()][
                ["ds", "yhat", "yhat_lower", "yhat_upper"]
            ]

            result_data = {
                "batch_id": batch_id,
                "generated_at": timezone.now().isoformat(),
                "horizon_days": FORECAST_HORIZON_DAYS,
                "forecast": [
                    {
                        "date": row["ds"].date().isoformat(),
                        "predicted_hen_day_pct": round(max(0, row["yhat"]), 2),
                        "lower_bound": round(max(0, row["yhat_lower"]), 2),
                        "upper_bound": round(min(100, row["yhat_upper"]), 2),
                    }
                    for _, row in future_forecast.iterrows()
                ],
            }

            # Persist to DB
            ForecastResult.objects.update_or_create(
                org=self.org,
                batch_id=batch_id,
                forecast_date=timezone.now().date(),
                defaults={
                    "forecast_type": "egg_production",
                    "result_json": result_data,
                    "model_version": "prophet-1.1",
                    "training_rows": len(df),
                },
            )

            # Cache for dashboard (fast path)
            cache_key = FORECAST_CACHE_KEY.format(batch_id=batch_id)
            cache.set(cache_key, json.dumps(result_data), timeout=FORECAST_CACHE_TTL)

            logger.info("Forecast complete: batch=%s horizon=%dd", batch_id, FORECAST_HORIZON_DAYS)
            return result_data

        except Exception as exc:
            logger.exception("Prophet forecast failed: batch=%s error=%s", batch_id, exc)
            return None

    @staticmethod
    def get_cached_forecast(batch_id: str) -> Optional[dict]:
        """
        Fast path for dashboard. Returns cached forecast without DB hit.
        Falls back to DB if cache is cold, then back to None.
        """
        cache_key = FORECAST_CACHE_KEY.format(batch_id=batch_id)
        raw = cache.get(cache_key)
        if raw:
            return json.loads(raw)

        # Cache miss — try DB (Celery may have just run)
        from apps.health.analytics.models import ForecastResult
        result = (
            ForecastResult.objects
            .filter(batch_id=batch_id, forecast_type="egg_production")
            .order_by("-forecast_date")
            .first()
        )
        if result:
            data = result.result_json
            cache.set(cache_key, json.dumps(data), timeout=FORECAST_CACHE_TTL)
            return data

        return None
```

### 5.3 Anomaly Detection (Z-Score + IQR Ensemble)

```python
# apps/health/analytics/services/anomaly.py

import logging
import numpy as np
from django.utils import timezone
from apps.infrastructure.core.services import BaseService

logger = logging.getLogger(__name__)

ANOMALY_CACHE_KEY = "anomaly:mortality:{batch_id}"
ANOMALY_CACHE_TTL = 6 * 3600  # Matches the Celery Beat schedule

Z_SCORE_THRESHOLD = 2.5    # Alert if mortality is 2.5 std deviations above mean
IQR_MULTIPLIER    = 1.75   # Alert if above Q3 + 1.75 * IQR
LOOKBACK_DAYS     = 30     # Rolling window for statistics
MIN_OBSERVATIONS  = 7      # Need at least 7 days to compute meaningful stats


class AnomalyDetectionService(BaseService):

    def check_batch_mortality(self, batch_id: str) -> Optional[dict]:
        from apps.farm.flocks.models import MortalityLog
        from apps.health.analytics.models import AnomalyAlert

        cutoff = timezone.now().date() - timezone.timedelta(days=LOOKBACK_DAYS)
        logs = list(
            MortalityLog.objects
            .filter(batch_id=batch_id, org=self.org, date__gte=cutoff)
            .values_list("count", flat=True)
            .order_by("date")
        )

        if len(logs) < MIN_OBSERVATIONS:
            return None

        values = np.array(logs, dtype=float)
        latest = values[-1]

        # Z-Score detection
        mean, std = values.mean(), values.std()
        z_score = (latest - mean) / std if std > 0 else 0

        # IQR detection
        q1, q3 = np.percentile(values, [25, 75])
        iqr = q3 - q1
        iqr_upper = q3 + IQR_MULTIPLIER * iqr

        is_anomaly = (z_score > Z_SCORE_THRESHOLD) or (latest > iqr_upper and z_score > 1.5)

        result = {
            "batch_id": batch_id,
            "latest_mortality": int(latest),
            "rolling_mean": round(float(mean), 2),
            "z_score": round(float(z_score), 3),
            "iqr_upper_bound": round(float(iqr_upper), 2),
            "is_anomaly": is_anomaly,
            "checked_at": timezone.now().isoformat(),
        }

        if is_anomaly:
            alert, created = AnomalyAlert.objects.get_or_create(
                org=self.org,
                batch_id=batch_id,
                alert_date=timezone.now().date(),
                alert_type="mortality_spike",
                defaults={
                    "severity": "high" if z_score > 3.5 else "medium",
                    "detail_json": result,
                    "resolved": False,
                },
            )
            if created:
                from apps.infrastructure.notifications.services import NotificationService
                NotificationService(self.org).send(
                    event_type="mortality_anomaly",
                    domain_id=str(alert.id),
                    recipient_id=str(self._get_farm_manager_id(batch_id)),
                    channel="sms",
                    subject="Mortality Anomaly Detected",
                    body=f"Unusual mortality detected on batch. "
                         f"Today: {int(latest)} deaths (avg: {mean:.1f}). Investigate immediately.",
                )

        from django.core.cache import cache
        cache.set(ANOMALY_CACHE_KEY.format(batch_id=batch_id), result, timeout=ANOMALY_CACHE_TTL)
        return result

    def _get_farm_manager_id(self, batch_id: str) -> str:
        from apps.farm.flocks.models import Batch
        from apps.infrastructure.accounts.models import User
        batch = Batch.objects.select_related("house__farm").get(id=batch_id)
        manager = User.objects.filter(org=self.org, role="farm_manager").first()
        return str(manager.id) if manager else ""
```

### 5.4 Celery Tasks for ML Pipeline

```python
# apps/health/analytics/tasks.py

from celery import shared_task
import logging

logger = logging.getLogger(__name__)


@shared_task(name="analytics.daily_egg_forecast", max_retries=2, default_retry_delay=300)
def daily_egg_forecast():
    """
    Triggered by Celery Beat at 1:00 AM daily.
    Iterates all active layer batches across ALL tenants.
    Each batch gets its own tenant context before forecast runs.
    """
    from apps.farm.flocks.models import Batch
    from apps.tenants.models import Organization
    from apps.infrastructure.core.rls import set_tenant_context

    # Cross-tenant query: no RLS on this lookup (see Section 7.3)
    active_batches = (
        Batch.all_objects  # Bypass TenantAwareManager
        .filter(status="active", bird_type__contains="layer")
        .values("id", "org_id")
    )

    for row in active_batches:
        _forecast_single_batch.delay(str(row["id"]), str(row["org_id"]))


@shared_task(name="analytics.forecast_single_batch", max_retries=3, default_retry_delay=120)
def _forecast_single_batch(batch_id: str, org_id: str):
    from apps.tenants.models import Organization
    from apps.infrastructure.core.rls import set_tenant_context
    from .services.forecasting import ProphetForecastService

    with set_tenant_context(org_id):
        try:
            org = Organization.objects.get(id=org_id)
            ProphetForecastService(org).forecast_batch(batch_id)
        except Exception as exc:
            logger.exception("Forecast failed: batch=%s org=%s", batch_id, org_id)
            raise


@shared_task(name="analytics.check_mortality_anomaly")
def check_mortality_anomaly(batch_id: str):
    """
    Fired from BatchService.log_mortality() after each mortality entry.
    Resolves org_id from batch — no need to pass it from the view.
    """
    from apps.farm.flocks.models import Batch
    from apps.infrastructure.core.rls import set_tenant_context
    from .services.anomaly import AnomalyDetectionService

    batch = Batch.all_objects.get(id=batch_id)
    with set_tenant_context(str(batch.org_id)):
        from apps.tenants.models import Organization
        org = Organization.objects.get(id=batch.org_id)
        AnomalyDetectionService(org).check_batch_mortality(batch_id)
```

---

## 6. Offline-Sync (PWA) Protocol

### 6.1 Problem Statement

Farm workers in low-connectivity areas (rural Nigeria) must be able to log mortality counts, egg production, feed entries, and water consumption offline. Data must sync without duplication when connectivity is restored, regardless of how many times the sync fires.

### 6.2 API Requirements (Server-Side)

Every endpoint that serves data to be cached offline must return these headers:

```python
# apps/infrastructure/core/views.py  — mixin for offline-capable views

from django.utils.http import http_date
from hashlib import md5
import json


class OfflineSyncMixin:
    """
    Add to any DRF APIView that serves data consumed by the PWA.
    Provides ETag and Last-Modified support for conditional requests.
    """

    def get_etag(self, data) -> str:
        """ETag = MD5 of the serialized response body."""
        return md5(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        if response.status_code == 200 and hasattr(response, "data"):
            etag = self.get_etag(response.data)
            response["ETag"] = f'"{etag}"'
            response["Cache-Control"] = "private, max-age=0, must-revalidate"

            # Support conditional GET: If-None-Match
            if request.META.get("HTTP_IF_NONE_MATCH") == f'"{etag}"':
                response.status_code = 304
                response.data = None

        return response
```

### 6.3 Sync Endpoint Contract

```python
# apps/farm/flocks/views.py  — offline sync endpoints

class OfflineSyncView(OfflineSyncMixin, APIView):
    """
    POST /api/sync/
    Accepts a batch of records collected offline.
    Returns per-record results without aborting the whole batch on partial failure.
    """

    def post(self, request):
        serializer = SyncBatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        records = serializer.validated_data["records"]
        results = []

        for record in records:
            result = self._process_record(record, request.org)
            results.append(result)

        # Always return 200 — let the client inspect per-record status
        return Response({
            "synced_at": timezone.now().isoformat(),
            "results": results,
        })

    def _process_record(self, record: dict, org) -> dict:
        """
        Each record has: type, client_id, payload, client_timestamp
        Returns: client_id, server_id, status, conflict_data (if any)
        """
        from apps.infrastructure.core.sync import SyncProcessor
        return SyncProcessor(org).process(record)
```

```python
# Sync record schema (DRF serializer)
class SyncRecordSerializer(serializers.Serializer):
    type             = serializers.ChoiceField(choices=["mortality_log", "egg_log", "feed_entry", "water_log"])
    client_id        = serializers.UUIDField()      # UUID generated on device; used as idempotency key
    client_timestamp = serializers.DateTimeField()  # When the record was created on device
    payload          = serializers.DictField()      # The actual data

class SyncBatchSerializer(serializers.Serializer):
    device_id = serializers.CharField(max_length=64)  # Identifies the specific device
    records   = SyncRecordSerializer(many=True, max_length=500)
```

### 6.4 Server-Side Reconciliation Logic

```python
# apps/infrastructure/core/sync.py

import logging
from django.db import transaction, IntegrityError
from apps.infrastructure.core.services import BaseService

logger = logging.getLogger(__name__)

CONFLICT_WINDOW_SECONDS = 300  # Records within 5 min of server record = potential conflict


class SyncProcessor(BaseService):
    """
    Handles all record types from the offline sync endpoint.
    Idempotency: client_id is stored as external_id on each record.
    Re-syncing the same client_id is a no-op — returns the existing server_id.
    """

    PROCESSORS = {
        "mortality_log": "_sync_mortality",
        "egg_log":       "_sync_egg_production",
        "feed_entry":    "_sync_feed_entry",
        "water_log":     "_sync_water_log",
    }

    def process(self, record: dict) -> dict:
        processor_method = self.PROCESSORS.get(record["type"])
        if not processor_method:
            return self._error_result(record["client_id"], "UNKNOWN_TYPE", f"Unknown type: {record['type']}")

        try:
            return getattr(self, processor_method)(record)
        except Exception as exc:
            logger.exception("Sync failed: client_id=%s type=%s", record["client_id"], record["type"])
            return self._error_result(record["client_id"], "SERVER_ERROR", str(exc))

    def _sync_mortality(self, record: dict) -> dict:
        from apps.farm.flocks.models import MortalityLog, Batch

        client_id = str(record["client_id"])
        payload   = record["payload"]

        # Idempotency check: already synced?
        existing = MortalityLog.objects.filter(external_id=client_id, org=self.org).first()
        if existing:
            return self._ok_result(client_id, str(existing.id), "already_synced")

        # Conflict check: another entry for same batch+date close in time
        conflict = MortalityLog.objects.filter(
            org=self.org,
            batch_id=payload["batch_id"],
            date=payload["date"],
        ).exclude(external_id=client_id).first()

        if conflict:
            return {
                "client_id": client_id,
                "status": "conflict",
                "conflict_data": {
                    "server_id": str(conflict.id),
                    "server_count": conflict.count,
                    "server_timestamp": conflict.created_at.isoformat(),
                    "client_count": payload.get("count"),
                },
            }

        with transaction.atomic():
            try:
                batch = Batch.objects.get(id=payload["batch_id"], org=self.org)
            except Batch.DoesNotExist:
                return self._error_result(client_id, "BATCH_NOT_FOUND", payload["batch_id"])

            from apps.farm.flocks.services import BatchService
            log = BatchService(self.org).log_mortality(
                batch_id=str(batch.id),
                date=payload["date"],
                count=payload["count"],
                cause=payload.get("cause"),
                external_id=client_id,  # Stored for idempotency
            )

        return self._ok_result(client_id, str(log.id), "created")

    def _sync_egg_production(self, record: dict) -> dict:
        from apps.production.production.models import EggProductionLog
        from apps.production.production.services import ProductionService

        client_id = str(record["client_id"])
        payload   = record["payload"]

        existing = EggProductionLog.objects.filter(external_id=client_id, org=self.org).first()
        if existing:
            return self._ok_result(client_id, str(existing.id), "already_synced")

        with transaction.atomic():
            log = ProductionService(self.org).log_egg_production(
                batch_id=payload["batch_id"],
                date=payload["date"],
                total_eggs=payload["total_eggs"],
                cracked=payload.get("cracked", 0),
                external_id=client_id,
            )

        return self._ok_result(client_id, str(log.id), "created")

    # _sync_feed_entry and _sync_water_log follow the same pattern

    @staticmethod
    def _ok_result(client_id, server_id, status):
        return {"client_id": client_id, "server_id": server_id, "status": status}

    @staticmethod
    def _error_result(client_id, code, detail):
        return {"client_id": client_id, "status": "error", "error_code": code, "error_detail": detail}
```

### 6.5 Service Worker Sync Strategy

```javascript
// static/sw/sync-strategy.js

const OFFLINE_QUEUE_KEY = 'flockiq_offline_queue';
const SYNC_TAG = 'flockiq-data-sync';

// Register background sync when a record is saved offline
async function queueForSync(recordType, payload) {
    const record = {
        type: recordType,
        client_id: crypto.randomUUID(),         // Idempotency key — generated once, persisted
        client_timestamp: new Date().toISOString(),
        payload,
    };

    // Persist to IndexedDB — survives browser close
    await idbQueue.add(record);

    // Request background sync (fires when connectivity restored)
    if ('serviceWorker' in navigator && 'SyncManager' in window) {
        const reg = await navigator.serviceWorker.ready;
        await reg.sync.register(SYNC_TAG);
    }
}

// Background sync handler (fires in SW context)
self.addEventListener('sync', event => {
    if (event.tag === SYNC_TAG) {
        event.waitUntil(flushOfflineQueue());
    }
});

async function flushOfflineQueue() {
    const records = await idbQueue.getAll();
    if (!records.length) return;

    const token = await getAuthToken();  // Refreshed JWT from IndexedDB
    const response = await fetch('/api/sync/', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify({
            device_id: await getDeviceId(),
            records,
        }),
    });

    if (!response.ok) return;  // Leave in queue; SW will retry on next sync event

    const { results } = await response.json();

    // Remove successfully synced records from queue
    // Conflict records are kept in a separate conflict queue for user review
    for (const result of results) {
        if (result.status === 'created' || result.status === 'already_synced') {
            await idbQueue.remove(result.client_id);
        } else if (result.status === 'conflict') {
            await idbConflicts.add(result);
            await idbQueue.remove(result.client_id);
        }
    }
}
```

---

## 7. RLS-Aware Celery Context

### 7.1 The Problem

Celery workers are separate OS processes. They have no HTTP request context, no `TenantMiddleware`, and no `set_config` call. A task that queries a tenant model without first setting `app.current_org_id` will receive **zero rows** (the safe default) or, if RLS is misconfigured, **every tenant's data** (catastrophic).

### 7.2 The `set_tenant_context` Context Manager

```python
# apps/infrastructure/core/rls.py

import logging
from contextlib import contextmanager
from typing import Union
import uuid

from django.db import connection, transaction

logger = logging.getLogger(__name__)


@contextmanager
def set_tenant_context(org_id: Union[str, uuid.UUID]):
    """
    Context manager that sets PostgreSQL's app.current_org_id for the duration
    of the block. MUST wrap all DB operations in Celery tasks that touch
    tenant-scoped tables.

    Uses set_config(..., TRUE) — transaction-local scope. The variable is
    automatically cleared when the transaction ends, preventing context leaks
    between Celery tasks sharing the same database connection via PgBouncer.

    Usage:
        with set_tenant_context(org_id):
            batches = Batch.objects.filter(status="active")  # RLS satisfied
            # ... all DB ops here are tenant-scoped

    The outer transaction.atomic() is required for set_config to be transaction-local.
    Without it, the setting persists for the lifetime of the DB connection — a
    cross-tenant data leak waiting to happen.
    """
    org_id_str = str(org_id)

    with transaction.atomic():
        with connection.cursor() as cursor:
            # Third arg TRUE = transaction-local (cleared on COMMIT/ROLLBACK)
            cursor.execute(
                "SELECT set_config('app.current_org_id', %s, TRUE)",
                [org_id_str],
            )
            logger.debug("RLS context set: org_id=%s", org_id_str)

        try:
            yield
        except Exception:
            # transaction.atomic() will ROLLBACK, which clears the set_config automatically
            raise


@contextmanager
def no_tenant_context():
    """
    Explicit context for cross-tenant infrastructure operations
    (e.g., iterating all active orgs in a Celery Beat task).

    This clears the current tenant context rather than setting a new one.
    Use only in:
    - Management commands
    - Celery Beat tasks that iterate across tenants
    - Analytics aggregations with explicit aggregate models (no RLS tables)

    DO NOT use this to query any TenantAwareModel — you will get all rows.
    """
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT set_config('app.current_org_id', '', TRUE)")
        yield


def assert_tenant_context():
    """
    Guards against accidentally running tenant queries without a context.
    Call at the start of any service method that must have a tenant context.
    Raises in development; logs in production (fail-safe).
    """
    from django.conf import settings
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_setting('app.current_org_id', TRUE)")
        value = cursor.fetchone()[0]

    if not value:
        msg = "Tenant context not set — query would return empty resultset or all rows."
        if settings.DEBUG:
            raise RuntimeError(msg)
        else:
            logger.error(msg)
```

### 7.3 Celery Task Patterns

```python
# Pattern 1 — Single-org task (most common)
# Called from a domain service with a specific org context

@shared_task(name="analytics.forecast_single_batch")
def forecast_single_batch(batch_id: str, org_id: str):
    """
    Always receives org_id explicitly. Never infers it from the batch.
    This makes the task testable and avoids an extra DB lookup.
    """
    from apps.infrastructure.core.rls import set_tenant_context
    from apps.tenants.models import Organization

    with set_tenant_context(org_id):
        org = Organization.objects.get(id=org_id)
        # All queries inside this block are RLS-scoped to org_id
        ProphetForecastService(org).forecast_batch(batch_id)


# Pattern 2 — Fan-out task (Celery Beat → all tenants)
# Used for scheduled jobs that run once globally but operate per-tenant

@shared_task(name="tasks.generate_daily_tasks")
def generate_daily_tasks():
    """
    Runs at midnight. Generates daily work tasks for every active tenant.
    Uses no_tenant_context() for the fan-out query, then sets per-org context
    for the actual task generation.
    """
    from apps.infrastructure.core.rls import no_tenant_context
    from apps.farm.flocks.models import Batch

    with no_tenant_context():
        # This model must have RLS DISABLED or be an aggregate view
        # Query only the org_id — no tenant data
        from apps.tenants.models import Organization
        active_org_ids = list(
            Organization.objects
            .filter(subscription_status="active")
            .values_list("id", flat=True)
        )

    for org_id in active_org_ids:
        generate_tasks_for_org.delay(str(org_id))


@shared_task(name="tasks.generate_tasks_for_org")
def generate_tasks_for_org(org_id: str):
    from apps.infrastructure.core.rls import set_tenant_context
    from apps.tenants.models import Organization

    with set_tenant_context(org_id):
        org = Organization.objects.get(id=org_id)
        from apps.farm.tasks.services import TaskGenerationService
        TaskGenerationService(org).generate_daily_tasks()


# Pattern 3 — Signal-triggered task
# The signal fires in the HTTP request context; the task receives org_id as a primitive

# In apps/farm/flocks/signals.py:
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import MortalityLog

@receiver(post_save, sender=MortalityLog)
def trigger_anomaly_check(sender, instance, created, **kwargs):
    if created:
        from apps.health.analytics.tasks import check_mortality_anomaly
        # Pass org_id as string — the task re-establishes context
        check_mortality_anomaly.delay(
            batch_id=str(instance.batch_id),
            org_id=str(instance.org_id),
        )
```

### 7.4 Celery Configuration for RLS Safety

```python
# config/celery.py

from celery import Celery
from django.conf import settings

app = Celery("flockiq")
app.config_from_object("django.conf:settings", namespace="CELERY")

# Critical: always acknowledge AFTER task completes, not before.
# If worker crashes mid-task, the task re-queues. With RLS, a partially-executed
# task is safer to retry than to silently lose.
app.conf.task_acks_late = True
app.conf.task_reject_on_worker_lost = True

# Prevent tasks from accumulating stale DB connections
app.conf.worker_max_tasks_per_child = 200

# Task soft/hard time limits — prevents Prophet from running forever on bad data
app.conf.task_soft_time_limit = 180   # 3 minutes; raises SoftTimeLimitExceeded
app.conf.task_time_limit = 240        # 4 minutes; kills and re-queues


@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    from celery.schedules import crontab

    sender.add_periodic_task(30.0,                               "notifications.process_outbox")
    sender.add_periodic_task(crontab(hour=1, minute=0),          "analytics.daily_egg_forecast")
    sender.add_periodic_task(crontab(minute=0, hour="*/6"),      "analytics.mortality_anomaly_check_all")
    sender.add_periodic_task(crontab(hour=7, minute=0),          "health.vaccination_reminders")
    sender.add_periodic_task(crontab(minute=0, hour="*/2"),      "tasks.feeding_schedule_monitor")
    sender.add_periodic_task(crontab(minute=0, hour="*/6"),      "weather.refresh_all_farms")
    sender.add_periodic_task(crontab(hour=8, minute=0),          "water.anomaly_check_all")
    sender.add_periodic_task(crontab(hour=0, minute=0),          "tasks.generate_daily_tasks")
    sender.add_periodic_task(crontab(hour=18, minute=0),         "tasks.incomplete_task_report")
    sender.add_periodic_task(crontab(day_of_week=0, hour=0),     "reporting.weekly_reports")
    sender.add_periodic_task(crontab(day_of_month=1, hour=0),    "market.seasonal_alert")
```

### 7.5 Middleware for HTTP Request Context

```python
# apps/infrastructure/core/middleware.py

import threading
from django.db import connection, transaction

_thread_local = threading.local()


def get_current_org():
    """Thread-safe accessor for TenantAwareManager."""
    return getattr(_thread_local, "current_org", None)


class TenantMiddleware:
    """
    Sets RLS context on every HTTP request that resolves to a tenant.
    Must be positioned AFTER AuthenticationMiddleware in MIDDLEWARE setting.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        org = self._resolve_org(request)
        _thread_local.current_org = org

        if org:
            # Wrap the entire request in a transaction so set_config is transaction-local
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT set_config('app.current_org_id', %s, TRUE)",
                        [str(org.id)],
                    )
                response = self.get_response(request)
        else:
            response = self.get_response(request)

        _thread_local.current_org = None  # Clean up for connection pool safety
        return response

    def _resolve_org(self, request):
        """
        Resolves the tenant from the subdomain.
        Returns None for requests to the root domain (marketing, admin).
        """
        from apps.infrastructure.tenants.models import Organization

        host = request.get_host().split(":")[0]  # Strip port
        parts = host.split(".")

        # app.flockiq.com → subdomain = "app" (main SPA — auth resolves org from JWT)
        # farmname.flockiq.com → subdomain = org slug
        if len(parts) < 3:
            return None  # Root domain

        subdomain = parts[0]
        if subdomain in ("www", "app", "admin", "api"):
            # Auth middleware handles org resolution for these subdomains via JWT
            if hasattr(request, "user") and request.user.is_authenticated:
                return getattr(request.user, "org", None)
            return None

        try:
            return Organization.objects.get(subdomain=subdomain, is_active=True)
        except Organization.DoesNotExist:
            return None
```

---

## 8. Cross-Cutting Invariants

These rules apply uniformly across all 18 apps and all 6 engines above. They are **not guidelines** — violations must be caught at code review.

### 8.1 Transaction Boundaries

| Rule | Rationale |
|---|---|
| Every service method that writes to multiple tables uses `transaction.atomic()` | Prevents partial writes on crash |
| `OutboxEvent` creation MUST be inside the same `atomic()` as the domain write | Guarantees notification delivery |
| `LedgerEntry` pairs MUST be created in the same `atomic()` as the originating record | Prevents unbalanced books |
| `select_for_update()` MUST use `skip_locked=True` on polling queries | Prevents long lock waits on busy tables |
| Never call `transaction.atomic()` inside a Celery task without also calling `set_tenant_context` | RLS requires a transaction to hold the config |

### 8.2 Naming Conventions

| Concept | Pattern | Example |
|---|---|---|
| Service class | `{Domain}Service` | `BatchService`, `DiagnosisService` |
| Celery task | snake_case noun phrase | `daily_egg_forecast`, `process_outbox` |
| Cache key | `{domain}:{entity}:{id}` | `forecast:egg:{batch_id}` |
| Idempotency key | `{event_type}:{domain_id}:{recipient_id}:{channel}` | SHA-256 truncated to 40 chars |
| RLS session var | `app.current_org_id` | Never rename — PostgreSQL policies reference this string |
| Sync client_id | UUID v4 generated on device | `crypto.randomUUID()` |

### 8.3 Test Coverage Requirements

Every engine in this spec must have the following test categories:

```python
# Minimum test coverage per engine

# 1. Notification Engine
test_outbox_created_atomically_with_domain_write()
test_duplicate_idempotency_key_suppressed()
test_exponential_backoff_intervals()
test_termii_timeout_retried_not_failed()
test_invalid_phone_marked_permanent_failure()

# 2. Ledger / Finance
test_feed_purchase_creates_balanced_entries()
test_unbalanced_entries_raise_value_error()
test_batch_pnl_aggregation_correct()
test_no_cross_tenant_ledger_leakage()

# 3. Calculator
test_fcr_correct_for_known_inputs()
test_hen_day_pct_raises_for_broiler()
test_heat_adjusted_water_above_25c()
test_unknown_breed_falls_back_to_generic()

# 4. ML Pipeline
test_prophet_not_called_below_min_rows()
test_cached_forecast_returned_on_cache_hit()
test_anomaly_z_score_threshold()
test_anomaly_alert_not_duplicated_same_day()

# 5. Offline Sync
test_sync_idempotent_on_duplicate_client_id()
test_conflict_detected_same_batch_date()
test_partial_batch_failure_does_not_abort_others()

# 6. RLS / Celery
test_task_with_no_context_returns_empty_queryset()
test_set_tenant_context_cleared_after_block()
test_cross_tenant_fan_out_uses_no_tenant_context()
test_middleware_sets_rls_on_subdomain_request()
```

### 8.4 Environment Variables Required

```bash
# Notification
TERMII_API_KEY=
TERMII_SENDER_ID=FlockIQ
EMAIL_HOST=
EMAIL_HOST_USER=
EMAIL_HOST_PASSWORD=
EMAIL_PORT=465
DEFAULT_FROM_EMAIL=noreply@flockiq.com

# Payments
PAYSTACK_SECRET_KEY=
PAYSTACK_PUBLIC_KEY=
PAYSTACK_WEBHOOK_SECRET=

# Weather
OPENWEATHERMAP_API_KEY=

# Redis
REDIS_URL=redis://localhost:6379/0

# Security
DJANGO_SECRET_KEY=
JWT_SIGNING_KEY=
ALLOWED_HOSTS=.flockiq.com

# Database
DATABASE_URL=postgresql://flockiq_user:password@localhost:5432/flockiq_db
```

---

*End of FlockIQ Core Engine Technical Specification v1.0*  
*Next document: `skills/deployment_runbook.md`*
