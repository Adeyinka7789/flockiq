import structlog
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.views import View

from apps.infrastructure.core.helpers import get_org_or_404
from apps.infrastructure.core.rls import set_tenant_context

from .models import WeatherAlert
from .services import WeatherService

logger = structlog.get_logger(__name__)


class WeatherStripView(LoginRequiredMixin, View):
    """GET /weather/farm/<uuid>/strip/ → 4-day forecast strip fragment for farm cards."""

    def get(self, request, farm_pk):
        org = get_org_or_404(request)

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


class WeatherAlertsPageView(LoginRequiredMixin, View):
    """GET /weather/ → Standalone weather & alerts page with farm cards, heat stress alerts, seasonal intel."""

    def get(self, request):
        from apps.farm.farms.models import Farm
        from apps.finance.market.seasonal_advisor import SeasonalAdvisor

        org = get_org_or_404(request)
        weather_data = []
        alerts = []

        with set_tenant_context(org):
            farms = list(Farm.objects.filter(is_active=True))

        for farm in farms:
            if farm.latitude is None or farm.longitude is None:
                continue
            try:
                service = WeatherService()
                cached = service.get_farm_weather_strip(str(farm.pk))
                data = cached or service.fetch_weather(
                    str(farm.pk), float(farm.latitude), float(farm.longitude)
                )
                if data:
                    data = dict(data)
                    data['farm'] = farm
                    weather_data.append(data)

                    temp = data.get('current_temp', 0) or 0
                    if temp >= 34:
                        alerts.append({
                            'severity': 'critical',
                            'farm': farm,
                            'title': f'Heat stress alert — {temp}°C at {farm.name}',
                            'body': (
                                f'Critical threshold exceeded (32°C). '
                                f'Increase ventilation NOW. '
                                f'Add extra water points. '
                                f'Birds require 250ml/day at this temperature. '
                                f'Reduce stocking density if possible.'
                            ),
                            'action': 'Action Required',
                        })
                    elif temp >= 30:
                        alerts.append({
                            'severity': 'warning',
                            'farm': farm,
                            'title': f'Heat stress warning — {temp}°C at {farm.name}',
                            'body': (
                                f'Temperature approaching stress threshold. '
                                f'Monitor closely. Ensure good ventilation '
                                f'and adequate water supply.'
                            ),
                            'action': 'Monitor',
                        })
            except Exception:
                logger.exception("weather_alerts_page.fetch_failed", farm_id=str(farm.pk))

        advisor = SeasonalAdvisor()
        context = {
            'weather_data': weather_data,
            'alerts': alerts,
            'farms': farms,
            'seasonal': advisor.get_current_season_insight(),
            'placement_rec': advisor.get_placement_recommendation(),
            'has_farms_with_gps': any(
                f.latitude is not None and f.longitude is not None for f in farms
            ),
        }
        return render(request, 'farm/weather/weather_alerts.html', context)


class WeatherAlertAcknowledgeView(LoginRequiredMixin, View):
    """POST /weather/alerts/<uuid>/acknowledge/ → Dismiss alert from UI."""

    def post(self, request, pk):
        org = get_org_or_404(request)

        with set_tenant_context(org):
            try:
                alert = WeatherAlert.objects.get(id=pk)
            except WeatherAlert.DoesNotExist:
                raise Http404("Alert not found.")

            alert.acknowledged_at = timezone.now()
            alert.save(update_fields=["acknowledged_at"])

        return HttpResponse(status=200)
