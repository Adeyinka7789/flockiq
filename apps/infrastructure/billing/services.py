import hashlib
import hmac
import uuid

import requests
import structlog
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.infrastructure.core.services import BaseService
from .models import BillingPlan, CycleSubscription, PaymentRecord

logger = structlog.get_logger(__name__)

PAYSTACK_BASE = "https://api.paystack.co"
TIMEOUT = 10


# ---------------------------------------------------------------------------
# Paystack API client — no org binding required
# ---------------------------------------------------------------------------

class PaystackService:
    """Thin wrapper around the Paystack REST API. Never raises — returns response dict."""

    @property
    def _headers(self):
        return {
            "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def verify_webhook_signature(payload: bytes, signature: str) -> bool:
        expected = hmac.new(
            settings.PAYSTACK_WEBHOOK_SECRET.encode("utf-8"),
            payload,
            hashlib.sha512,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    def create_plan(self, name: str, amount_kobo: int, interval: str) -> dict:
        log = logger.bind(action="paystack.create_plan", name=name, interval=interval)
        try:
            resp = requests.post(
                f"{PAYSTACK_BASE}/plan",
                headers=self._headers,
                json={"name": name, "amount": amount_kobo, "interval": interval},
                timeout=TIMEOUT,
            )
            data = resp.json()
            log.info("paystack.plan_created", plan_code=data.get("data", {}).get("plan_code"))
            return data
        except Exception as exc:
            log.error("paystack.create_plan_failed", error=str(exc))
            return {}

    def initialize_transaction(
        self,
        email: str,
        amount_kobo: int,
        reference: str,
        metadata: dict | None = None,
    ) -> dict:
        log = logger.bind(action="paystack.initialize_transaction", reference=reference)
        try:
            body = {"email": email, "amount": amount_kobo, "reference": reference}
            if metadata:
                body["metadata"] = metadata
            resp = requests.post(
                f"{PAYSTACK_BASE}/transaction/initialize",
                headers=self._headers,
                json=body,
                timeout=TIMEOUT,
            )
            data = resp.json()
            log.info("paystack.transaction_initialized")
            return data
        except Exception as exc:
            log.error("paystack.initialize_failed", error=str(exc))
            return {}

    def verify_transaction(self, reference: str) -> dict:
        log = logger.bind(action="paystack.verify_transaction", reference=reference)
        try:
            resp = requests.get(
                f"{PAYSTACK_BASE}/transaction/verify/{reference}",
                headers=self._headers,
                timeout=TIMEOUT,
            )
            data = resp.json()
            log.info("paystack.transaction_verified", status=data.get("data", {}).get("status"))
            return data
        except Exception as exc:
            log.error("paystack.verify_failed", error=str(exc))
            return {}

    def create_subscription(
        self,
        email: str,
        plan_code: str,
        authorization_code: str,
    ) -> dict:
        log = logger.bind(action="paystack.create_subscription", plan_code=plan_code)
        try:
            resp = requests.post(
                f"{PAYSTACK_BASE}/subscription",
                headers=self._headers,
                json={
                    "customer": email,
                    "plan": plan_code,
                    "authorization": authorization_code,
                },
                timeout=TIMEOUT,
            )
            data = resp.json()
            log.info("paystack.subscription_created")
            return data
        except Exception as exc:
            log.error("paystack.subscription_failed", error=str(exc))
            return {}

    def cancel_subscription(self, subscription_code: str, token: str) -> dict:
        log = logger.bind(action="paystack.cancel_subscription", code=subscription_code)
        try:
            resp = requests.post(
                f"{PAYSTACK_BASE}/subscription/disable",
                headers=self._headers,
                json={"code": subscription_code, "token": token},
                timeout=TIMEOUT,
            )
            data = resp.json()
            log.info("paystack.subscription_cancelled")
            return data
        except Exception as exc:
            log.error("paystack.cancel_failed", error=str(exc))
            return {}

    def get_subscription(self, subscription_code: str) -> dict:
        log = logger.bind(action="paystack.get_subscription", code=subscription_code)
        try:
            resp = requests.get(
                f"{PAYSTACK_BASE}/subscription/{subscription_code}",
                headers=self._headers,
                timeout=TIMEOUT,
            )
            data = resp.json()
            log.debug("paystack.subscription_fetched")
            return data
        except Exception as exc:
            log.error("paystack.get_subscription_failed", error=str(exc))
            return {}


# ---------------------------------------------------------------------------
# Billing domain service — tenant-scoped
# ---------------------------------------------------------------------------

class BillingService(BaseService):

    def get_active_plan(self) -> BillingPlan | None:
        return BillingPlan.objects.filter(
            plan_tier=self.org.plan_tier,
            is_active=True,
        ).first()

    @transaction.atomic
    def activate_cycle_subscription(self, batch_id) -> CycleSubscription:
        """
        Creates a CycleSubscription for the given batch_id UUID.
        Calls Paystack to create a recurring subscription if the org has a
        previous successful payment (authorization code on file).
        """
        plan = self.get_active_plan()
        if plan is None:
            self.logger.warning("billing.no_active_plan", batch_id=str(batch_id))
            plan = BillingPlan.objects.filter(is_active=True).first()

        sub, created = CycleSubscription.objects.get_or_create(
            org=self.org,
            batch_id=batch_id,
            defaults={"plan": plan, "status": "pending"},
        )

        if not created:
            self.logger.info("billing.cycle_sub_already_exists", batch_id=str(batch_id))
            return sub

        # Attempt Paystack subscription if org has an authorization code on file
        latest_payment = (
            PaymentRecord.objects.filter(org=self.org, status="success")
            .exclude(authorization_code="")
            .order_by("-paid_at")
            .first()
        )
        if latest_payment and plan.paystack_plan_code:
            ps = PaystackService()
            result = ps.create_subscription(
                email=self.org.owner_email,
                plan_code=plan.paystack_plan_code,
                authorization_code=latest_payment.authorization_code,
            )
            data = result.get("data") or {}
            if data.get("subscription_code"):
                sub.paystack_subscription_code = data["subscription_code"]
                sub.paystack_email_token = data.get("email_token", "")
                sub.status = "active"
                sub.activated_at = timezone.now()
                sub.save(update_fields=[
                    "paystack_subscription_code", "paystack_email_token",
                    "status", "activated_at",
                ])
                self.logger.info("billing.cycle_sub_activated", batch_id=str(batch_id))
        else:
            # No payment on file — mark active for trial orgs / manual billing
            sub.status = "active"
            sub.activated_at = timezone.now()
            sub.save(update_fields=["status", "activated_at"])

        return sub

    @transaction.atomic
    def deactivate_cycle_subscription(self, batch_id) -> None:
        try:
            sub = CycleSubscription.objects.get(org=self.org, batch_id=batch_id)
        except CycleSubscription.DoesNotExist:
            self.logger.warning("billing.cycle_sub_not_found", batch_id=str(batch_id))
            return

        if sub.paystack_subscription_code and sub.paystack_email_token:
            ps = PaystackService()
            ps.cancel_subscription(
                subscription_code=sub.paystack_subscription_code,
                token=sub.paystack_email_token,
            )

        sub.status = "cancelled"
        sub.deactivated_at = timezone.now()
        sub.save(update_fields=["status", "deactivated_at"])
        self.logger.info("billing.cycle_sub_deactivated", batch_id=str(batch_id))

    @transaction.atomic
    def record_payment(
        self,
        reference: str,
        amount_kobo: int,
        status: str,
        **kwargs,
    ) -> PaymentRecord:
        record, _ = PaymentRecord.objects.get_or_create(
            org=self.org,
            reference=reference,
            defaults={
                "amount_kobo": amount_kobo,
                "status": status,
                "channel": kwargs.get("channel", ""),
                "paystack_transaction_id": kwargs.get("paystack_transaction_id", ""),
                "authorization_code": kwargs.get("authorization_code", ""),
                "plan": kwargs.get("plan"),
                "paid_at": kwargs.get("paid_at"),
            },
        )
        self.logger.info("billing.payment_recorded", reference=reference, status=status)
        return record

    def get_billing_summary(self) -> dict:
        plan = self.get_active_plan()
        payments = list(
            PaymentRecord.objects.filter(org=self.org)
            .order_by("-created_at")[:10]
        )
        active_subs = list(
            CycleSubscription.objects.filter(org=self.org, status="active")
        )
        return {
            "plan": plan,
            "org": self.org,
            "payment_history": payments,
            "active_cycle_subscriptions": active_subs,
            "next_billing_date": None,
        }
