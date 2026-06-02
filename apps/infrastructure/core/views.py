import json

from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import redirect_to_login
from django.db.models import Sum
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.generic import TemplateView


class TenantRequiredMixin:
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not request.user.org:
            return redirect('/')
        return super().dispatch(request, *args, **kwargs)


class HtmxMixin:
    """
    Mixin for views that serve both full pages and HTMX partials.
    Provides HTMX detection, template switching, OOB swap helpers.
    """

    htmx_template = None
    full_template = None

    @property
    def is_htmx(self):
        return self.request.headers.get("HX-Request") == "true"

    def get_template_names(self):
        if self.is_htmx and self.htmx_template:
            return [self.htmx_template]
        return [self.full_template or super().get_template_names()[0]]

    def render_htmx_fragment(self, template_name, context, status=200):
        return render(self.request, template_name, context, status=status)

    def htmx_redirect(self, url):
        if self.is_htmx:
            response = HttpResponse()
            response["HX-Redirect"] = url
            return response
        return redirect(url)

    def htmx_refresh(self):
        response = HttpResponse()
        response["HX-Refresh"] = "true"
        return response

    def trigger_event(self, response, event_name, detail=None):
        payload = {event_name: detail or {}}
        response["HX-Trigger"] = json.dumps(payload)
        return response


class DashboardView(TemplateView):
    template_name = "dashboard.html"

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.render_landing(request)
        if request.user.role == "super_admin" or request.user.is_superuser:
            return self.super_admin_view(request)
        if not request.user.org:
            return self.render_landing(request)
        return super().dispatch(request, *args, **kwargs)

    def render_landing(self, request):
        from apps.infrastructure.billing.models import BillingPlan
        plans = BillingPlan.objects.filter(is_active=True).order_by("amount_kobo")
        return render(request, "landing.html", {
            "billing_plans": plans if plans.exists() else None,
        })

    def super_admin_view(self, request):
        from apps.infrastructure.accounts.models import CustomUser
        from apps.infrastructure.tenants.models import Organization

        orgs = Organization.objects.all().order_by("-created_at")
        total_users = CustomUser.objects.filter(
            role__in=["owner", "manager", "supervisor", "data_entry"]
        ).count()

        return render(request, "admin_dashboard.html", {
            "orgs": orgs,
            "total_orgs": orgs.count(),
            "active_orgs": orgs.filter(is_active=True).count(),
            "total_users": total_users,
        })

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        org = getattr(self.request.user, "org", None)

        farms_count = 0
        active_batches_count = 0
        total_live_birds = 0
        pending_alerts_count = 0
        active_batches = []

        if org:
            try:
                from apps.farm.farms.models import Farm
                from apps.farm.flocks.models import Batch
                from apps.infrastructure.notifications.models import NotificationLog

                farms_count = Farm.objects.filter(org=org, is_active=True).count()

                batch_qs = Batch.objects.filter(org=org, status=Batch.Status.ACTIVE)
                active_batches_count = batch_qs.count()
                total_live_birds = (
                    batch_qs.aggregate(t=Sum("current_count"))["t"] or 0
                )
                active_batches = list(
                    batch_qs.select_related("farm", "house").order_by("-placement_date")[:5]
                )
                pending_alerts_count = NotificationLog.objects.filter(
                    org=org,
                    recipient=self.request.user,
                    is_read=False,
                ).count()
            except Exception:
                pass

        ctx.update(
            {
                "farms_count": farms_count,
                "active_batches_count": active_batches_count,
                "total_live_birds": total_live_birds,
                "pending_alerts_count": pending_alerts_count,
                "active_batches": active_batches,
            }
        )
        return ctx
