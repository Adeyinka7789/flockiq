import structlog
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404
from django.shortcuts import render
from django.views import View
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.infrastructure.core.rls import set_tenant_context

from .services import MarketService

logger = structlog.get_logger(__name__)


def _get_org(request):
    org = getattr(request.user, "org", None)
    if org is None:
        raise Http404("No organisation found for this user.")
    return org


class MarketPriceView(LoginRequiredMixin, View):
    """GET /market/prices/"""

    def get(self, request):
        org = _get_org(request)
        product_type = request.GET.get("product_type")
        with set_tenant_context(org):
            prices = MarketService(org).get_current_prices(product_type=product_type)
        return render(request, "market/_market_price_ticker.html", {"prices": prices})


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
