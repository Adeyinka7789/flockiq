import structlog
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.views import View

from apps.infrastructure.core.rls import set_tenant_context

from .models import WeatherAlert
from .services import WeatherService

logger = structlog.get_logger(__name__)


def _get_org(request):
    org = getattr(request.user, "org", None)
    if org is None:
        raise Http404("No organisation found for this user.")
    return org


class WeatherStripView(LoginRequiredMixin, View):
    """GET /weather/farm/<uuid>/strip/ → 4-day forecast strip fragment for farm cards."""

    def get(self, request, farm_pk):
        org = _get_org(request)

        with set_tenant_context(org):
            from apps.farm.farms.models import Farm
            try:
                farm = Farm.objects.get(id=farm_pk)
            except Farm.DoesNotExist:
                raise Http404("Farm not found.")

        weather_data = WeatherService().get_farm_weather_strip(str(farm_pk))
        return render(
            request,
            "weather/_weather_strip.html",
            {"weather": weather_data, "farm": farm},
        )


class WeatherAlertAcknowledgeView(LoginRequiredMixin, View):
    """POST /weather/alerts/<uuid>/acknowledge/ → Dismiss alert from UI."""

    def post(self, request, pk):
        org = _get_org(request)

        with set_tenant_context(org):
            try:
                alert = WeatherAlert.objects.get(id=pk)
            except WeatherAlert.DoesNotExist:
                raise Http404("Alert not found.")

            alert.acknowledged_at = timezone.now()
            alert.save(update_fields=["acknowledged_at"])

        return HttpResponse(status=200)
