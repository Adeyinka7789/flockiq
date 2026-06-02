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

from .models import PaystackWebhookLog
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

        org = Organization.objects.filter(owner_email=customer_email).first()
        if org is None:
            logger.warning("webhook.org_not_found", email=customer_email, reference=reference)
            return

        with set_tenant_context(org):
            svc = BillingService(org)
            svc.record_payment(
                reference=reference,
                amount_kobo=amount_kobo,
                status="success",
                channel=channel,
                paystack_transaction_id=transaction_id,
                authorization_code=authorization_code,
                paid_at=paid_at,
            )
            # Update org subscription status if it was trial
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
        if not request.user.org:
            return render(request, "billing/billing_page.html", {"is_super_admin": True})

        from apps.infrastructure.core.rls import set_tenant_context
        with set_tenant_context(request.user.org):
            service = BillingService(request.user.org)
            summary = service.get_billing_summary()

        return render(request, "billing/billing_page.html", {
            **summary,
            "expired": request.GET.get("expired"),
        })


class UpgradeRequestView(LoginRequiredMixin, View):
    def post(self, request):
        if not request.user.org:
            return HttpResponse(status=403)
        if request.user.role not in ["owner"]:
            return HttpResponse(status=403)

        plan_tier = request.POST.get("plan_tier")
        if plan_tier not in ["monthly", "cycle", "yearly"]:
            return HttpResponse("Invalid plan", status=400)

        from apps.infrastructure.core.rls import set_tenant_context
        with set_tenant_context(request.user.org):
            service = BillingService(request.user.org)
            result = service.request_upgrade(
                plan_tier=plan_tier,
                user_email=request.user.email,
            )

        if result["method"] == "paystack":
            response = HttpResponse()
            response["HX-Redirect"] = result["authorization_url"]
            return response
        elif result["method"] == "email":
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
