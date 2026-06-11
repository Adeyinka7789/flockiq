import json

import structlog
from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from apps.infrastructure.core.mixins import RoleRequiredMixin
from apps.infrastructure.core.views import TenantRequiredMixin
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import PaymentRecord, PaystackWebhookLog
from .services import BillingService, PaystackService

logger = structlog.get_logger(__name__)


@method_decorator(csrf_exempt, name="dispatch")
class PaystackWebhookView(View):
    """
    Receives Paystack webhook events.
    All events are logged to PaystackWebhookLog before processing.

    Response codes:
        200 — processed, duplicate delivery, or unhandled event type
        400 — invalid signature (do not retry)
        500 — genuine processing failure (Paystack retries for up to 72h)
        503 — PAYSTACK_WEBHOOK_SECRET not configured (fail closed: an empty
              HMAC key would make signatures trivially forgeable)
    """

    def post(self, request):
        if not settings.PAYSTACK_WEBHOOK_SECRET:
            logger.error("billing.webhook_secret_missing")
            return JsonResponse({"error": "Webhook not configured"}, status=503)

        payload = request.body
        signature = request.headers.get("X-Paystack-Signature", "")
        sig_valid = PaystackService.verify_webhook_signature(payload, signature)

        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            data = {}

        event_type = data.get("event", "unknown")
        # Paystack has no event-level id; the transaction/subscription id under
        # `data` is the stable identifier across retried deliveries.
        event_id = str((data.get("data") or {}).get("id", ""))

        # Always log — even invalid signatures need an audit trail
        log_entry = PaystackWebhookLog.objects.create(
            event_type=event_type,
            event_id=event_id,
            payload=data,
            signature_valid=sig_valid,
        )

        if not sig_valid:
            logger.warning("webhook.invalid_signature", event_type=event_type)
            return HttpResponseBadRequest("Invalid signature")

        # Idempotency: if a *prior* delivery with this event_id was already
        # processed, acknowledge with 200 and skip re-dispatch. activate_plan /
        # record_payment are also idempotent on reference as a second guard.
        if event_id and PaystackWebhookLog.objects.filter(
            event_id=event_id, processed=True
        ).exclude(pk=log_entry.pk).exists():
            logger.info(
                "webhook.duplicate", event_id=event_id, event_type=event_type
            )
            log_entry.error = "duplicate: already processed"
            log_entry.save(update_fields=["error"])
            return HttpResponse(status=200)

        try:
            self._dispatch(event_type, data.get("data", {}))
        except Exception as exc:
            import sentry_sdk

            log_entry.error = str(exc)
            log_entry.save(update_fields=["error"])
            logger.error(
                "billing.webhook_processing_failed",
                event_type=event_type,
                error=str(exc),
            )
            sentry_sdk.capture_exception(exc)
            # 500 — Paystack retries for up to 72 hours, so a transient DB or
            # service failure cannot silently drop a billing event. Duplicates,
            # unknown event types and invalid signatures still return 200/400
            # above (those must NOT be retried).
            return JsonResponse({"error": "Processing failed"}, status=500)

        log_entry.processed = True
        log_entry.error = ""
        log_entry.save(update_fields=["processed", "error"])
        return JsonResponse({"status": "ok"}, status=200)

    def _dispatch(self, event_type: str, data: dict):
        handlers = {
            "charge.success": self._handle_charge_success,
            "subscription.create": self._handle_subscription_created,
            "subscription.disable": self._handle_subscription_disabled,
            "invoice.payment_failed": self._handle_invoice_payment_failed,
        }
        handler = handlers.get(event_type)
        if handler:
            handler(data)
        else:
            logger.debug("webhook.unhandled_event", event_type=event_type)

    @staticmethod
    def _resolve_org(data: dict):
        """
        Resolve the paying org. metadata.org_id is authoritative — it is set
        server-side by BillingService.request_upgrade() at transaction init.
        Customer email is only a fallback for charges without metadata (e.g.
        Paystack subscription renewals). Organization and CustomUser have RLS
        disabled, so both are safe to query without a tenant context.
        """
        from django.core.exceptions import ValidationError
        from apps.infrastructure.tenants.models import Organization

        metadata = data.get("metadata") or {}
        org_id = metadata.get("org_id") or metadata.get("org")
        if org_id:
            try:
                return Organization.objects.get(id=org_id)
            except (Organization.DoesNotExist, ValidationError, ValueError):
                logger.warning(
                    "billing.charge_success_org_not_found",
                    org_id=str(org_id),
                    reference=data.get("reference"),
                )

        customer_email = (data.get("customer") or {}).get("email", "")
        if not customer_email:
            return None

        org = Organization.objects.filter(
            owner_email__iexact=customer_email
        ).first()
        if org:
            return org

        # Owner may have changed their login email without owner_email
        # being updated — match the owner user instead.
        from django.contrib.auth import get_user_model

        user = (
            get_user_model().objects
            .filter(email__iexact=customer_email, role="owner")
            .select_related("org")
            .first()
        )
        return user.org if user else None

    @staticmethod
    def _match_renewal_plan(data: dict):
        """
        Match a metadata-less charge (Paystack-initiated subscription renewal)
        back to a BillingPlan via the Paystack plan code carried on the charge.
        BillingPlan is global (RLS disabled) — safe without a tenant context.
        """
        from apps.infrastructure.billing.models import BillingPlan

        plan_data = data.get("plan") or data.get("plan_object") or {}
        if isinstance(plan_data, dict):
            plan_code = plan_data.get("plan_code", "")
        else:
            plan_code = str(plan_data)
        if not plan_code:
            return None
        return BillingPlan.objects.filter(
            paystack_plan_code=plan_code, is_active=True
        ).first()

    def _handle_charge_success(self, data: dict):
        from apps.infrastructure.core.rls import set_tenant_context

        reference = data.get("reference", "")
        plan_tier = (data.get("metadata") or {}).get("plan_tier")
        payment_kwargs = {
            "amount_kobo": data.get("amount", 0),
            "channel": data.get("channel", ""),
            "authorization_code": (data.get("authorization") or {}).get(
                "authorization_code", ""
            ),
            "paystack_transaction_id": str(data.get("id", "")),
            "paid_at": timezone.now(),
        }

        org = self._resolve_org(data)
        if org is None:
            logger.warning(
                "billing.charge_success_unmatched",
                reference=reference,
                email=(data.get("customer") or {}).get("email", ""),
            )
            return

        with set_tenant_context(org):
            svc = BillingService(org)
            if plan_tier:
                # FlockIQ-initiated upgrade/renewal — metadata carries the
                # tier. activate_plan records the payment, extends expiry and
                # notifies; idempotent on reference, so a prior callback that
                # already activated this payment is a safe no-op.
                svc.activate_plan(
                    plan_tier=plan_tier,
                    payment_reference=reference,
                    activated_by="paystack",
                    **payment_kwargs,
                )
            else:
                # No metadata — a Paystack-initiated subscription renewal.
                # Match the plan code on the charge so the renewal extends
                # plan_expires_at instead of only logging a payment.
                renewal_plan = self._match_renewal_plan(data)
                if renewal_plan:
                    svc.activate_plan(
                        plan_tier=renewal_plan.plan_tier,
                        payment_reference=reference,
                        activated_by="paystack_renewal",
                        **payment_kwargs,
                    )
                else:
                    # Truly unmatched charge — record it and flag for manual
                    # review; do NOT guess a plan tier.
                    svc.record_payment(
                        reference=reference,
                        status="success",
                        **payment_kwargs,
                    )
                    if org.subscription_status == "trial":
                        org.subscription_status = "active"
                        org.save(update_fields=["subscription_status"])
                    logger.warning(
                        "billing.charge_success_no_plan_matched",
                        reference=reference,
                        org=str(org.id),
                    )
        logger.info("webhook.charge_success_processed", reference=reference)

    def _handle_subscription_created(self, data: dict):
        """
        Race-safe subscription.create handling. Paystack can deliver this
        webhook BEFORE our create_subscription API response is processed, in
        which case no CycleSubscription carries the code yet. Resolution order:
          1. Match an existing CycleSubscription by subscription_code.
          2. Attach the code to the org's pending code-less CycleSubscription.
          3. Park the code on the org (paystack_subscription_code) for
             activate_cycle_subscription to consume later.
        CycleSubscription is tenant-scoped, so the org must be resolved first
        and queried inside set_tenant_context — a bare query here matches
        nothing under RLS.
        """
        from apps.infrastructure.billing.models import CycleSubscription
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.infrastructure.tenants.models import Organization

        subscription_code = data.get("subscription_code", "")
        email_token = data.get("email_token", "")
        customer_email = (data.get("customer") or {}).get("email", "")

        if not subscription_code:
            logger.warning("webhook.subscription_created_no_code", email=customer_email)
            return

        org = self._resolve_org(data)
        if org is None:
            logger.warning(
                "billing.subscription_created_unmatched",
                code=subscription_code,
                email=customer_email,
            )
            return

        with set_tenant_context(org):
            updated = CycleSubscription.objects.filter(
                paystack_subscription_code=subscription_code
            ).update(status="active", activated_at=timezone.now())
            if updated:
                logger.info("webhook.subscription_created", code=subscription_code)
                return

            # Webhook beat our response — attach to the newest code-less sub.
            pending = (
                CycleSubscription.objects.filter(
                    org=org, paystack_subscription_code=""
                )
                .exclude(status="cancelled")
                .order_by("-created_at")
                .first()
            )
            if pending:
                pending.paystack_subscription_code = subscription_code
                pending.paystack_email_token = email_token
                pending.status = "active"
                pending.activated_at = timezone.now()
                pending.save(update_fields=[
                    "paystack_subscription_code", "paystack_email_token",
                    "status", "activated_at",
                ])
                logger.info(
                    "billing.subscription_code_attached_via_webhook",
                    code=subscription_code,
                    sub_id=str(pending.id),
                )
                return

        # No subscription row visible yet (our transaction has not committed)
        # — park the code on the org for later matching. Organization has RLS
        # disabled, so no tenant context is needed.
        Organization.objects.filter(id=org.id).update(
            paystack_subscription_code=subscription_code
        )
        logger.info(
            "billing.subscription_code_stored_via_webhook",
            email=customer_email,
            code=subscription_code,
        )

    def _handle_subscription_disabled(self, data: dict):
        from apps.infrastructure.billing.models import CycleSubscription

        subscription_code = data.get("subscription_code", "")
        CycleSubscription.objects.filter(
            paystack_subscription_code=subscription_code
        ).update(status="paused")
        logger.info("webhook.subscription_disabled", code=subscription_code)

    def _handle_invoice_payment_failed(self, data: dict):
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.infrastructure.notifications.models import NotificationLog

        org = self._resolve_org(data)
        if org is None:
            logger.warning(
                "webhook.invoice_failed_org_not_found",
                email=(data.get("customer") or {}).get("email", ""),
            )
            return

        # A failed card charge is a billing event — never reuse health/alert
        # event types here (a farmer once got a "disease outbreak" SMS for a
        # declined card).
        owner = org.users.filter(role="owner").first()
        if owner:
            with set_tenant_context(org):
                NotificationLog.objects.create(
                    org=org,
                    recipient=owner,
                    event_type="payment_failed",
                    title="Payment failed",
                    body=(
                        "Your subscription payment could not be processed. "
                        "Please update your payment method on the billing "
                        "page to keep your plan active."
                    ),
                    severity="warning",
                    channel="in_app",
                    action_url="/billing/",
                )
        logger.warning("webhook.invoice_payment_failed", org=str(org.id))


class BillingPageView(RoleRequiredMixin, View):
    # Managers may view the billing page read-only; only the owner can change
    # the plan (enforced both here via can_change_plan and in UpgradeRequestView).
    allowed_roles = ['owner', 'manager']

    def get(self, request):
        # Super admins have no org — redirect to admin dashboard
        if request.user.is_superuser or \
           getattr(request.user, 'role', '') == 'super_admin':
            return redirect('superadmin:billing')

        from datetime import timedelta
        from apps.infrastructure.billing.features import get_plan_features
        from apps.infrastructure.billing.models import BillingPlan
        from apps.infrastructure.core.config import PlatformConfig
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.farm.farms.models import Farm

        org = request.user.org

        with set_tenant_context(org):
            service = BillingService(org)
            summary = service.get_billing_summary()

            farm_count = Farm.objects.filter(is_active=True).count()

            from apps.infrastructure.core.credit_scoring import CreditScoringService
            credit_score = CreditScoringService.get_latest(org)

            # PaymentRecord is tenant-scoped — load inside the RLS scope.
            # select_related('plan') so last_payment.plan (read below) and each
            # payment.plan are preloaded and need no query outside the block.
            last_payment = PaymentRecord.objects.filter(
                org=org, status='success'
            ).select_related('plan').order_by('-created_at').first()

            payments = list(
                PaymentRecord.objects.filter(org=org)
                .select_related('plan')
                .order_by('-created_at')[:10]
            )

        team_count = request.user.__class__.objects.filter(
            org=org, is_active=True
        ).count()

        # Only the owner can change the plan / make payments. Managers see the
        # page read-only. (accounts_user has RLS disabled, so this is safe
        # outside the tenant context.)
        can_change_plan = request.user.role == 'owner'
        owner = request.user.__class__.objects.filter(
            org=org, role='owner'
        ).first()

        current_features = get_plan_features(org.plan_tier)
        max_farms = current_features.get('max_farms', 1)
        max_team = current_features.get('team_members', 1)

        farm_usage_pct = min(100, round(farm_count / max(max_farms, 1) * 100))
        team_usage_pct = min(100, round(team_count / max(max_team, 1) * 100))

        # Next renewal date from last successful payment (loaded in RLS scope above)
        next_renewal = None
        if last_payment and last_payment.plan:
            interval = last_payment.plan.billing_interval
            if interval == 'monthly':
                next_renewal = last_payment.created_at.date() + timedelta(days=30)
            elif interval == 'annually':
                next_renewal = last_payment.created_at.date() + timedelta(days=365)
        elif org.trial_ends_at:
            next_renewal = org.trial_ends_at

        all_plans = BillingPlan.objects.filter(is_active=True).order_by('amount_kobo')

        # Pre-compute amount_naira on each payment record (loaded in RLS scope above)
        for payment in payments:
            payment.amount_naira = payment.amount_kobo // 100

        platform_config = PlatformConfig.get()

        plan_expired = bool(
            org.plan_expires_at and org.plan_expires_at < timezone.now()
        )

        return render(request, "billing/billing_page.html", {
            **summary,
            "credit_score": credit_score,
            "expired": request.GET.get("expired"),
            "plan_expired": plan_expired,
            "all_plans": all_plans,
            "current_features": current_features,
            "farm_count": farm_count,
            "team_count": team_count,
            "max_farms": max_farms,
            "max_team": max_team,
            "farm_usage_pct": farm_usage_pct,
            "team_usage_pct": team_usage_pct,
            "next_renewal": next_renewal,
            "payments": payments,
            "platform_config": platform_config,
            "can_change_plan": can_change_plan,
            "owner": owner,
        })


class UpgradeRequestView(RoleRequiredMixin, View):
    # Only the owner can change the plan / initiate payment.
    allowed_roles = ["owner"]

    def post(self, request):
        if not request.user.org:
            return HttpResponse(status=403)

        plan_tier = request.POST.get("plan_tier")
        timing = request.POST.get("timing", "immediate")
        if plan_tier not in ["monthly", "cycle", "yearly"]:
            return HttpResponse("Invalid plan", status=400)

        from apps.infrastructure.core.rls import set_tenant_context
        with set_tenant_context(request.user.org):
            service = BillingService(request.user.org)
            if timing == "on_renewal":
                # Defer the change — record it instead of charging now.
                result = service.schedule_upgrade(plan_tier=plan_tier, timing=timing)
            else:
                result = service.request_upgrade(
                    plan_tier=plan_tier,
                    user_email=request.user.email,
                )

        if result["method"] == "paystack":
            response = HttpResponse()
            response["HX-Redirect"] = result["authorization_url"]
            return response
        elif result["method"] in ("email", "scheduled"):
            response = HttpResponse()
            response["HX-Trigger"] = json.dumps({
                "showToast": {"message": result["message"], "type": "success"},
                "refreshBell": True,
            })
            return response
        else:
            response = HttpResponse()
            response["HX-Trigger"] = json.dumps({
                "showToast": {"message": result.get("message", "Error"), "type": "error"}
            })
            return response


class PaystackCallbackView(View):
    def get(self, request):
        reference = request.GET.get("reference")
        if not reference:
            return redirect("/billing/?error=missing_reference")

        if not request.user.is_authenticated or not request.user.org:
            return redirect("/login/")

        # Verify with Paystack BEFORE entering the explicit tenant context so
        # the HTTP round-trip (up to 10s) is not spent inside the activation
        # transaction.
        # KNOWN ISSUE: TenantMiddleware already wraps this whole request in
        # set_tenant_context() (one transaction per request — required for
        # SET LOCAL), so a PgBouncer connection is still pinned during this
        # call. Mitigated by statement/idle-in-transaction timeouts in
        # production.py; the full fix is restructuring the per-request
        # transaction scope. See RUNBOOK.md "PgBouncer Configuration".
        try:
            result = PaystackService().verify_transaction(reference)
        except Exception:
            result = None

        from apps.infrastructure.core.rls import set_tenant_context
        with set_tenant_context(request.user.org):
            service = BillingService(request.user.org)
            success = service.activate_from_verified_data(result, reference)

        if success:
            return redirect("/billing/?upgraded=1")
        return redirect("/billing/?error=payment_failed")


class BankTransferNotifyView(RoleRequiredMixin, TenantRequiredMixin, View):
    """
    User clicks "I've paid" after a bank transfer.
    Creates an in-app notification log entry and returns a WhatsApp link.

    Owner only — payment management is the owner's responsibility (mirrors
    UpgradeRequestView and the can_change_plan gate on the billing page).
    """

    allowed_roles = ["owner"]

    def post(self, request):
        import urllib.parse
        from apps.infrastructure.core.config import PlatformConfig
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.infrastructure.notifications.models import NotificationLog

        org = request.user.org
        plan_tier = request.POST.get('plan_tier', '')
        amount = request.POST.get('amount', '')

        with set_tenant_context(org):
            NotificationLog.objects.create(
                org=org,
                recipient=request.user,
                event_type='billing_upgrade_request',
                title='Bank Transfer Payment Claimed',
                body=(
                    f'{org.name} ({request.user.email}) has claimed '
                    f'a bank transfer payment for the {plan_tier} plan '
                    f'(₦{amount}). Please verify and activate manually.'
                ),
                severity='warning',
                channel='in_app',
            )

        config = PlatformConfig.get()
        wa_message = (
            f'Hello FlockIQ Support,\n\n'
            f'I have made a bank transfer payment for the '
            f'*{plan_tier.title()} Plan* (₦{amount}).\n\n'
            f'Organisation: *{org.name}*\n'
            f'Email: *{request.user.email}*\n\n'
            f'Please verify and activate my subscription.\n\nThank you.'
        )
        wa_url = (
            f'https://wa.me/{config.admin_whatsapp}'
            f'?text={urllib.parse.quote(wa_message)}'
        )

        response = HttpResponse(
            content_type='application/json',
            status=200,
        )
        response.content = json.dumps({
            'wa_url': wa_url,
            'message': (
                'Thank you! Please send us a WhatsApp message '
                'to confirm your payment.'
            ),
        })
        response['HX-Trigger'] = json.dumps({
            'showToast': {
                'message': 'Payment notification sent! Please confirm via WhatsApp.',
                'type': 'success',
            }
        })
        return response


class BillingAPIView(APIView):
    def get(self, request):
        svc = BillingService(request.user.org)
        summary = svc.get_billing_summary()
        plan = summary["plan"]
        return Response({
            "data": {
                "plan_tier": plan.plan_tier if plan else None,
                "plan_name": plan.name if plan else None,
                "amount_kobo": plan.amount_kobo if plan else 0,
                "subscription_status": request.user.org.subscription_status,
                "payment_count": len(summary["payment_history"]),
                "active_cycle_subscriptions": len(summary["active_cycle_subscriptions"]),
            }
        })
