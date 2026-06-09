import json

import structlog
from django.contrib.auth.mixins import LoginRequiredMixin
from apps.infrastructure.core.views import TenantRequiredMixin
from django.http import HttpResponse, HttpResponseBadRequest
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
    Always returns 200 to prevent retry storms (except 400 for invalid signatures).
    All events are logged to PaystackWebhookLog before processing.
    """

    def post(self, request):
        payload = request.body
        signature = request.headers.get("X-Paystack-Signature", "")
        sig_valid = PaystackService.verify_webhook_signature(payload, signature)

        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            data = {}

        event_type = data.get("event", "unknown")

        # Always log — even invalid signatures need an audit trail
        log_entry = PaystackWebhookLog.objects.create(
            event_type=event_type,
            payload=data,
            signature_valid=sig_valid,
        )

        if not sig_valid:
            logger.warning("webhook.invalid_signature", event_type=event_type)
            return HttpResponseBadRequest("Invalid signature")

        error = ""
        try:
            self._dispatch(event_type, data.get("data", {}))
            log_entry.processed = True
        except Exception as exc:
            error = str(exc)
            logger.error("webhook.processing_error", event_type=event_type, error=error)

        log_entry.error = error
        log_entry.save(update_fields=["processed", "error"])

        # Always 200 — Paystack must not retry
        return HttpResponse(status=200)

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

    def _handle_charge_success(self, data: dict):
        from apps.infrastructure.tenants.models import Organization
        from apps.infrastructure.core.rls import set_tenant_context

        customer_email = (data.get("customer") or {}).get("email", "")
        reference = data.get("reference", "")
        amount_kobo = data.get("amount", 0)
        channel = data.get("channel", "")
        transaction_id = str(data.get("id", ""))
        authorization_code = (data.get("authorization") or {}).get("authorization_code", "")
        paid_at = timezone.now()
        plan_tier = (data.get("metadata") or {}).get("plan_tier")

        org = Organization.objects.filter(owner_email=customer_email).first()
        if org is None:
            logger.warning("webhook.org_not_found", email=customer_email, reference=reference)
            return

        with set_tenant_context(org):
            svc = BillingService(org)
            if plan_tier:
                # Plan upgrade/renewal — activate (records payment, sets expiry,
                # notifies). Idempotent on reference, so a prior callback that
                # already activated this payment is a safe no-op.
                svc.activate_plan(
                    plan_tier=plan_tier,
                    payment_reference=reference,
                    activated_by="paystack",
                    amount_kobo=amount_kobo,
                    channel=channel,
                    authorization_code=authorization_code,
                    paystack_transaction_id=transaction_id,
                    paid_at=paid_at,
                )
            else:
                # Non-plan charge (e.g. cycle subscription) — just record it.
                svc.record_payment(
                    reference=reference,
                    amount_kobo=amount_kobo,
                    status="success",
                    channel=channel,
                    paystack_transaction_id=transaction_id,
                    authorization_code=authorization_code,
                    paid_at=paid_at,
                )
                if org.subscription_status in ("trial",):
                    org.subscription_status = "active"
                    org.save(update_fields=["subscription_status"])
        logger.info("webhook.charge_success_processed", reference=reference)

    def _handle_subscription_created(self, data: dict):
        from apps.infrastructure.billing.models import CycleSubscription

        subscription_code = data.get("subscription_code", "")
        email_token = data.get("email_token", "")
        # Match by subscription code if we already stored it, otherwise try email_token
        CycleSubscription.objects.filter(
            paystack_subscription_code=subscription_code
        ).update(status="active", activated_at=timezone.now())
        logger.info("webhook.subscription_created", code=subscription_code)

    def _handle_subscription_disabled(self, data: dict):
        from apps.infrastructure.billing.models import CycleSubscription

        subscription_code = data.get("subscription_code", "")
        CycleSubscription.objects.filter(
            paystack_subscription_code=subscription_code
        ).update(status="paused")
        logger.info("webhook.subscription_disabled", code=subscription_code)

    def _handle_invoice_payment_failed(self, data: dict):
        from apps.infrastructure.tenants.models import Organization
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.infrastructure.notifications.services import NotificationService

        customer_email = (data.get("customer") or {}).get("email", "")
        org = Organization.objects.filter(owner_email=customer_email).first()
        if org is None:
            logger.warning("webhook.invoice_failed_org_not_found", email=customer_email)
            return

        with set_tenant_context(org):
            NotificationService(org).send(
                "disease_outbreak",  # closest available alert for financial failure
                {"farm_name": org.name, "value": "payment failed"},
                severity="critical",
            )
        logger.warning("webhook.invoice_payment_failed", org=str(org.id))


class BillingPageView(LoginRequiredMixin, View):
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

        team_count = request.user.__class__.objects.filter(
            org=org, is_active=True
        ).count()

        current_features = get_plan_features(org.plan_tier)
        max_farms = current_features.get('max_farms', 1)
        max_team = current_features.get('team_members', 1)

        farm_usage_pct = min(100, round(farm_count / max(max_farms, 1) * 100))
        team_usage_pct = min(100, round(team_count / max(max_team, 1) * 100))

        # Next renewal date from last successful payment
        next_renewal = None
        last_payment = PaymentRecord.objects.filter(
            org=org, status='success'
        ).order_by('-created_at').first()

        if last_payment and last_payment.plan:
            interval = last_payment.plan.billing_interval
            if interval == 'monthly':
                next_renewal = last_payment.created_at.date() + timedelta(days=30)
            elif interval == 'annually':
                next_renewal = last_payment.created_at.date() + timedelta(days=365)
        elif org.trial_ends_at:
            next_renewal = org.trial_ends_at

        all_plans = BillingPlan.objects.filter(is_active=True).order_by('amount_kobo')

        # Pre-compute amount_naira on each payment record
        payments = list(
            PaymentRecord.objects.filter(org=org)
            .select_related('plan')
            .order_by('-created_at')[:10]
        )
        for payment in payments:
            payment.amount_naira = payment.amount_kobo // 100

        platform_config = PlatformConfig.get()

        plan_expired = bool(
            org.plan_expires_at and org.plan_expires_at < timezone.now()
        )

        return render(request, "billing/billing_page.html", {
            **summary,
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
        })


class UpgradeRequestView(LoginRequiredMixin, View):
    def post(self, request):
        if not request.user.org:
            return HttpResponse(status=403)
        if request.user.role not in ["owner"]:
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

        from apps.infrastructure.core.rls import set_tenant_context
        with set_tenant_context(request.user.org):
            service = BillingService(request.user.org)
            success = service.verify_and_activate(reference)

        if success:
            return redirect("/billing/?upgraded=1")
        return redirect("/billing/?error=payment_failed")


class BankTransferNotifyView(TenantRequiredMixin, View):
    """
    User clicks "I've paid" after a bank transfer.
    Creates an in-app notification log entry and returns a WhatsApp link.
    """

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
