import json
from datetime import date, datetime, timedelta

from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import redirect_to_login
from django.db.models import Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views import View
from django.views.generic import TemplateView

from apps.infrastructure.core.rls import set_tenant_context


def custom_404(request, exception=None):
    return render(request, '404.html', status=404)


def custom_500(request):
    return render(request, '500.html', status=500)


def setup_wizard(request):
    from django.contrib.auth.decorators import login_required
    if not request.user.is_authenticated:
        from django.contrib.auth.views import redirect_to_login
        return redirect_to_login(request.get_full_path())
    org = getattr(request.user, 'org', None)
    if not org or getattr(org, 'onboarding_complete', False):
        return redirect('/')
    return render(request, 'setup-wizard.html', {'org': org})


class SessionCheckView(View):
    def get(self, request):
        if request.user.is_authenticated:
            return JsonResponse({"authenticated": True})
        return JsonResponse({"authenticated": False}, status=401)


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
        if request.user.is_superuser or getattr(request.user, 'role', '') == 'super_admin':
            return redirect('superadmin:dashboard')
        if not request.user.org:
            return self.render_landing(request)

        # Handle "Skip onboarding" — mark complete and reload cleanly
        if request.GET.get('skip') == '1':
            org = request.user.org
            org.onboarding_complete = True
            org.save(update_fields=['onboarding_complete', 'updated_at'])
            return redirect('/')

        # Redirect new tenants to the onboarding wizard when no farms exist
        if not request.user.org.onboarding_complete:
            from apps.farm.farms.models import Farm
            from apps.infrastructure.core.rls import set_tenant_context
            with set_tenant_context(request.user.org):
                if not Farm.objects.exists():
                    return redirect('/onboarding/')

        return super().dispatch(request, *args, **kwargs)

    def render_landing(self, request):
        from apps.infrastructure.billing.models import BillingPlan
        from apps.farm.farms.models import Farm
        from apps.infrastructure.core.rls import no_tenant_context

        plans = BillingPlan.objects.filter(is_active=True).order_by("amount_kobo")

        try:
            with no_tenant_context():
                farm_locations = list(
                    Farm.objects.filter(is_active=True)
                    .values_list("location", flat=True)
                    .distinct()[:20]
                )
        except Exception:
            farm_locations = []

        if not farm_locations:
            farm_locations = [
                "Lagos", "Ibadan", "Kano", "Abuja",
                "Port Harcourt", "Osogbo", "Enugu", "Kaduna",
            ]

        return render(request, "landing.html", {
            "billing_plans": plans if plans.exists() else None,
            "farm_locations": farm_locations,
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

        today = date.today()
        farms_count = 0
        total_active_batches = 0
        total_live_birds = 0
        unread_alerts = 0
        active_batches = []
        todays_eggs = 0
        mortality_trend = []
        egg_trend = []
        upcoming_vaccinations = []
        task_summary = {}

        if org:
            with set_tenant_context(org):
                try:
                    from apps.farm.farms.models import Farm
                    from apps.farm.flocks.models import Batch
                    from apps.infrastructure.notifications.models import NotificationLog

                    farms_count = Farm.objects.filter(is_active=True).count()
                    batch_qs = Batch.objects.filter(status=Batch.Status.ACTIVE)
                    total_active_batches = batch_qs.count()
                    total_live_birds = (
                        batch_qs.aggregate(t=Sum("current_count"))["t"] or 0
                    )
                    active_batches = list(
                        batch_qs.select_related("farm", "house")
                        .order_by("-placement_date")[:5]
                    )
                    unread_alerts = NotificationLog.objects.filter(
                        recipient=self.request.user,
                        is_read=False,
                    ).count()
                except Exception:
                    pass

                try:
                    from apps.production.production.models import EggProductionLog
                    todays_eggs = (
                        EggProductionLog.objects.filter(record_date=today)
                        .aggregate(total=Sum("total_eggs"))["total"] or 0
                    )
                    for i in range(29, -1, -1):
                        day = today - timedelta(days=i)
                        total = (
                            EggProductionLog.objects.filter(record_date=day)
                            .aggregate(total=Sum("total_eggs"))["total"] or 0
                        )
                        egg_trend.append({"date": day.strftime("%d %b"), "total": total})
                except Exception:
                    egg_trend = [{"date": "", "total": 0}] * 30

                try:
                    from apps.farm.flocks.models import MortalityLog
                    for i in range(29, -1, -1):
                        day = today - timedelta(days=i)
                        count = (
                            MortalityLog.objects.filter(date=day)
                            .aggregate(total=Sum("count"))["total"] or 0
                        )
                        mortality_trend.append({"date": day.strftime("%d %b"), "count": count})
                except Exception:
                    mortality_trend = [{"date": "", "count": 0}] * 30

                try:
                    from apps.health.health.models import VaccinationSchedule
                    upcoming_vaccinations = list(
                        VaccinationSchedule.objects.filter(
                            status="scheduled",
                            due_date__gte=today,
                            due_date__lte=today + timedelta(days=7),
                        )
                        .select_related("batch__farm")
                        .order_by("due_date")[:5]
                    )
                except Exception:
                    pass

                try:
                    from apps.farm.tasks.services import TaskService
                    task_summary = TaskService(org).get_task_summary()
                except Exception:
                    pass

        daily_brief = {}
        today_brief = None
        has_patterns = False
        if org:
            try:
                from apps.health.analytics.daily_brief import DailyBriefService
                daily_brief = DailyBriefService(org).get_cached()
            except Exception:
                pass
            try:
                from apps.health.analytics.models import AIDailyBrief
                today_brief = AIDailyBrief.objects.filter(
                    org=org, brief_date=today).first()
                has_patterns = bool(
                    today_brief and today_brief.patterns_detected)
            except Exception:
                pass

        hour = datetime.now().hour
        if hour < 12:
            time_greeting = "Good morning"
            time_emoji = "🌅"
        elif hour < 17:
            time_greeting = "Good afternoon"
            time_emoji = "☀️"
        else:
            time_greeting = "Good evening"
            time_emoji = "🌙"

        ctx.update(
            {
                "farms_count": farms_count,
                "total_active_batches": total_active_batches,
                "total_live_birds": total_live_birds,
                "unread_alerts": unread_alerts,
                "active_batches": active_batches,
                "today": today,
                "todays_eggs": todays_eggs,
                "mortality_trend": mortality_trend,
                "egg_trend": egg_trend,
                "upcoming_vaccinations": upcoming_vaccinations,
                "task_summary": task_summary,
                "daily_brief": daily_brief,
                "today_brief": today_brief,
                "has_patterns": has_patterns,
                "time_greeting": time_greeting,
                "time_emoji": time_emoji,
            }
        )
        return ctx
