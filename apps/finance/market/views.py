import calendar
import datetime
import json

import structlog
from django.contrib.auth.mixins import LoginRequiredMixin
from apps.infrastructure.core.views import TenantRequiredMixin
from django.http import Http404, HttpResponse, HttpResponseBadRequest
from django.shortcuts import render
from django.views import View
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.infrastructure.core.rls import set_tenant_context

from .models import MarketPrice
from .services import MarketService

logger = structlog.get_logger(__name__)


def _get_org(request):
    org = getattr(request.user, "org", None)
    if org is None:
        raise Http404("No organisation found for this user.")
    return org


def _build_seasonal_data():
    from .models import SeasonalDemandIndex

    today = datetime.date.today()
    seasonal_data = []
    for offset in range(4):
        month = ((today.month - 1 + offset) % 12) + 1
        entry = SeasonalDemandIndex.objects.filter(product_type="eggs", month=month).first()
        demand_index = entry.demand_index if entry else 5
        seasonal_data.append({
            "month_name": calendar.month_abbr[month],
            "demand_index": demand_index,
            "index_pct": demand_index * 10,
        })
    return seasonal_data


class MarketPriceView(TenantRequiredMixin, View):
    """GET /market/prices/ — full page market intelligence view."""

    def get(self, request):
        org = _get_org(request)
        product_type = request.GET.get("product_type")
        with set_tenant_context(org):
            prices = MarketService(org).get_current_prices(product_type=product_type)
        seasonal_data = _build_seasonal_data()

        seasonal_insight = None
        placement_recommendation = None
        try:
            from apps.finance.market.seasonal_advisor import SeasonalAdvisor
            advisor = SeasonalAdvisor()
            seasonal_insight = advisor.get_current_season_insight()
            placement_recommendation = advisor.get_placement_recommendation()
        except Exception:
            pass

        return render(request, "market/market_prices.html", {
            "prices": prices,
            "seasonal_data": seasonal_data,
            "seasonal_insight": seasonal_insight,
            "placement_recommendation": placement_recommendation,
        })


class RecordMarketPriceView(LoginRequiredMixin, View):
    """GET /market/prices/record/ — modal fragment; POST saves a price record."""

    def get(self, request):
        return render(request, "market/_record_price_form.html", {
            "product_types": MarketPrice._meta.get_field("product_type").choices,
        })

    def post(self, request):
        if not request.htmx:
            return HttpResponseBadRequest()
        org = _get_org(request)
        try:
            with set_tenant_context(org):
                MarketService(org).record_market_price(
                    product_type=request.POST.get("product_type"),
                    price_per_unit_kobo=int(float(request.POST.get("price_naira", 0)) * 100),
                    unit=request.POST.get("unit"),
                    market_name=request.POST.get("market_name"),
                    region=request.POST.get("region", "Lagos"),
                    recorded_by=request.user,
                )
            response = HttpResponse()
            response["HX-Trigger"] = json.dumps({
                "showToast": {"message": "Price recorded", "type": "success"},
                "closeModal": True,
            })
            response["HX-Refresh"] = "true"
            return response
        except Exception as exc:
            logger.warning("market.record_price_failed", error=str(exc))
            return render(request, "market/_record_price_form.html", {"error": str(exc)})


class SeasonalForecastView(LoginRequiredMixin, View):
    """GET /market/seasonal/"""

    def get(self, request):
        org = _get_org(request)
        product_type = request.GET.get("product_type", "eggs")
        with set_tenant_context(org):
            forecast = MarketService(org).get_seasonal_forecast(product_type)
        return render(request, "market/_seasonal_forecast.html", {"forecast": forecast, "product_type": product_type})


class MinViablePriceView(LoginRequiredMixin, View):
    """GET /market/mvp/<uuid:batch_pk>/"""

    def get(self, request, batch_pk):
        org = _get_org(request)
        with set_tenant_context(org):
            try:
                data = MarketService(org).get_minimum_viable_price(str(batch_pk))
            except ValueError as exc:
                raise Http404(str(exc))
        return render(request, "market/_mvp_calculator.html", {"data": data, "batch_pk": batch_pk})
