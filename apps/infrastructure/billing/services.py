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

# Days a plan stays valid after activation/renewal, per tier.
PLAN_DURATIONS = {
    "trial": 14,
    "monthly": 30,
    "cycle": 42,
    "yearly": 365,
}


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
            body = {
                "email": email,
                "amount": amount_kobo,
                "reference": reference,
                "callback_url": f"{settings.SITE_URL}/billing/verify/",
            }
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

    def _get_plan_price_kobo(self, plan_tier: str) -> int:
        plan = BillingPlan.objects.filter(plan_tier=plan_tier, is_active=True).first()
        return plan.amount_kobo if plan else 0

    @transaction.atomic
    def activate_plan(
        self,
        plan_tier: str,
        payment_reference: str = "",
        activated_by: str = "paystack",
        **payment_kwargs,
    ) -> bool:
        """
        Activate or renew a plan. Extends expiry from now by the plan tier's
        duration (see PLAN_DURATIONS).
        Called by: Paystack webhook (charge.success), Paystack callback,
        and admin manual upgrade.

        Idempotent on payment_reference: if a PaymentRecord already exists for the
        reference (e.g. the callback already processed the payment before the
        webhook arrived), this is a no-op and returns False. Admin activations
        (no reference) always proceed.

        Returns True when the activation was applied, False when skipped as a
        duplicate.
        """
        import datetime
        from django.core.cache import cache

        org = self.org
        now = timezone.now()

        plan = BillingPlan.objects.filter(plan_tier=plan_tier, is_active=True).first()

        # Idempotency guard + payment record for paid activations.
        if payment_reference:
            _, created = PaymentRecord.objects.get_or_create(
                org=org,
                reference=payment_reference,
                defaults={
                    "amount_kobo": payment_kwargs.get("amount_kobo")
                    or self._get_plan_price_kobo(plan_tier),
                    "status": "success",
                    "paid_at": payment_kwargs.get("paid_at") or now,
                    "plan": plan,
                    "channel": payment_kwargs.get("channel", ""),
                    "authorization_code": payment_kwargs.get("authorization_code", ""),
                    "paystack_transaction_id": payment_kwargs.get("paystack_transaction_id", ""),
                },
            )
            if not created:
                self.logger.info(
                    "billing.activate_plan_duplicate", reference=payment_reference
                )
                return False

        previous_plan = org.plan_tier

        org.plan_tier = plan_tier
        days = PLAN_DURATIONS.get(plan_tier, 30)
        org.plan_expires_at = now + datetime.timedelta(days=days)
        org.subscription_status = "active"
        org.is_active = True
        # Activation always clears any deferred upgrade — it's now in effect.
        org.upgrade_pending = ""
        org.upgrade_timing = ""
        org.save(update_fields=[
            "plan_tier", "plan_expires_at", "subscription_status",
            "is_active", "upgrade_pending", "upgrade_timing", "updated_at",
        ])

        # Invalidate the org-active cache read by core.middleware.
        cache.delete(f"org_active:{org.id}")

        self._notify_plan_activated(plan_tier, previous_plan, activated_by)
        self.logger.info(
            "billing.plan_activated",
            org=str(org.id),
            plan_tier=plan_tier,
            previous_plan=previous_plan,
            activated_by=activated_by,
        )
        return True

    def _notify_plan_activated(self, new_plan, previous_plan, activated_by):
        """Email + in-app notification to the owner, plus an admin alert.

        Uses NotificationLog (tenant-scoped owner inbox) and AdminNotification
        (global superadmin inbox) directly — NotificationService.send() is not
        used here because it requires a configured AlertRule + message template,
        which billing events do not have.
        """
        from django.contrib.auth import get_user_model

        from apps.infrastructure.core.email_service import EmailService
        from apps.infrastructure.notifications.models import (
            AdminNotification,
            NotificationLog,
        )

        org = self.org
        action = "upgraded" if new_plan != previous_plan else "renewed"
        expires = org.plan_expires_at
        owner = org.users.filter(role="owner").first()

        if owner:
            EmailService.send_plan_activated(
                owner=owner,
                org=org,
                plan_name=new_plan,
                expires_at=expires,
                action=action,
                activated_by=activated_by,
            )

            NotificationLog.objects.create(
                org=org,
                recipient=owner,
                event_type="billing_plan_activated",
                title=f"Plan {action} — {new_plan.title()}",
                body=(
                    f"Your {new_plan.title()} plan is active until "
                    f"{expires.strftime('%B %d, %Y') if expires else '—'}."
                ),
                severity="info",
                channel="in_app",
                action_url="/billing/",
            )

        # Superadmin in-app alert (not tenant-scoped).
        User = get_user_model()
        source = "Activated by admin." if activated_by == "admin" else "Paid via Paystack."
        for admin in User.objects.filter(is_superuser=True):
            AdminNotification.objects.create(
                recipient=admin,
                title=f"Plan {action} — {org.name}",
                body=f"{org.name} has {action} to the {new_plan.title()} plan. {source}",
            )

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
        from django.utils import timezone as tz
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.farm.farms.models import Farm
        from apps.farm.flocks.models import Batch

        org = self.org
        days_remaining = None
        if org.trial_ends_at:
            delta = org.trial_ends_at - tz.now()
            days_remaining = max(0, delta.days)

        plan = self.get_active_plan()
        payments = list(
            PaymentRecord.objects.filter(org=org).order_by("-created_at")[:10]
        )

        with set_tenant_context(org):
            farm_count = Farm.objects.count()
            active_batches = Batch.objects.filter(status="active").count()

        return {
            "org": org,
            "plan": plan,
            "days_remaining": days_remaining,
            "payments": payments,
            "farm_count": farm_count,
            "active_batches": active_batches,
            "is_trial": org.plan_tier == "trial",
            "is_active": org.subscription_status == "active",
            # legacy keys kept for BillingAPIView
            "payment_history": payments,
            "active_cycle_subscriptions": list(
                CycleSubscription.objects.filter(org=org, status="active")
            ),
        }

    def request_upgrade(self, plan_tier: str, user_email: str) -> dict:
        import secrets

        plan = BillingPlan.objects.filter(
            plan_tier=plan_tier, is_active=True
        ).first()
        if not plan:
            return {"method": "error", "message": "Plan not found"}

        if settings.PAYSTACK_SECRET_KEY:
            reference = f"FIQ-{secrets.token_hex(8).upper()}"
            result = PaystackService().initialize_transaction(
                email=user_email,
                amount_kobo=plan.amount_kobo,
                reference=reference,
                metadata={
                    "org_id": str(self.org.id),
                    "plan_tier": plan_tier,
                    "org_name": self.org.name,
                },
            )
            if result.get("status"):
                return {
                    "method": "paystack",
                    "authorization_url": result["data"]["authorization_url"],
                    "reference": reference,
                }
            return {"method": "error", "message": "Payment initialization failed"}

        self._send_upgrade_request_email(plan_tier, plan, user_email)
        return {
            "method": "email",
            "message": (
                f"Upgrade request sent. Our team will activate your "
                f"{plan_tier} plan within 24 hours."
            ),
        }

    def _send_upgrade_request_email(self, plan_tier: str, plan, user_email: str) -> None:
        from apps.infrastructure.core.email_service import EmailService

        EmailService.send_upgrade_request_admin(
            org=self.org,
            plan_tier=plan_tier,
            plan=plan,
            owner_email=user_email,
        )

        EmailService.send_upgrade_request_received(
            owner_email=user_email,
            owner_name=self.org.owner_name or "there",
            org_name=self.org.name,
            plan_tier=plan_tier,
        )
        self.logger.info("billing.upgrade_email_sent", org=str(self.org.id), plan_tier=plan_tier)

        owner = self.org.users.filter(role="owner").first()
        if owner:
            from apps.infrastructure.core.rls import set_tenant_context
            from apps.infrastructure.notifications.models import NotificationLog
            with set_tenant_context(self.org):
                NotificationLog.objects.create(
                    org=self.org,
                    recipient=owner,
                    event_type="billing_upgrade_request",
                    title="Upgrade Request Received",
                    body=(
                        f"Your request to upgrade to the {plan_tier.title()} plan has been received. "
                        f"Our team will activate your account within 24 hours."
                    ),
                    severity="info",
                    channel="in_app",
                    is_read=False,
                )

    @transaction.atomic
    def schedule_upgrade(self, plan_tier: str, timing: str = "on_renewal") -> dict:
        """
        Record a deferred plan change to be applied at the next renewal.
        Does NOT charge or change the active plan — activate_plan() clears the
        pending flag and applies it when the next payment/renewal lands.
        """
        from apps.infrastructure.notifications.models import NotificationLog

        org = self.org
        org.upgrade_pending = plan_tier
        org.upgrade_timing = timing
        org.save(update_fields=["upgrade_pending", "upgrade_timing", "updated_at"])

        owner = org.users.filter(role="owner").first()
        if owner:
            NotificationLog.objects.create(
                org=org,
                recipient=owner,
                event_type="billing_upgrade_scheduled",
                title=f"Upgrade scheduled — {plan_tier.title()}",
                body=(
                    f"Your switch to the {plan_tier.title()} plan will take effect "
                    f"at your next renewal."
                ),
                severity="info",
                channel="in_app",
                action_url="/billing/",
            )

        self.logger.info(
            "billing.upgrade_scheduled", org=str(org.id), plan_tier=plan_tier, timing=timing
        )
        return {
            "method": "scheduled",
            "message": (
                f"Your upgrade to the {plan_tier.title()} plan will take effect "
                f"at your next renewal."
            ),
        }

    @transaction.atomic
    def verify_and_activate(self, reference: str) -> bool:
        result = PaystackService().verify_transaction(reference)
        if not result.get("status"):
            return False

        data = result.get("data", {})
        if data.get("status") != "success":
            return False

        metadata = data.get("metadata", {})
        plan_tier = metadata.get("plan_tier")
        if not plan_tier:
            return False

        self.activate_plan(
            plan_tier=plan_tier,
            payment_reference=reference,
            activated_by="paystack",
            amount_kobo=data.get("amount", 0),
            channel=data.get("channel", ""),
            paystack_transaction_id=str(data.get("id", "")),
            paid_at=timezone.now(),
        )
        return True
