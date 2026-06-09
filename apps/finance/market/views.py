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

from apps.infrastructure.core.helpers import get_org_or_404
from apps.infrastructure.core.rls import set_tenant_context

from .models import FeedPriceReport, Hatchery, HatcheryReview, MarketPrice, NIGERIAN_STATE_CHOICES
from .services import FeedPriceService, HatcheryService, MarketService
from .forms import FeedPriceSubmitForm, HatcheryReviewForm, SuggestHatcheryForm

logger = structlog.get_logger(__name__)


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
        org = get_org_or_404(request)
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
        org = get_org_or_404(request)
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
                "close-modal": True,
            })
            response["HX-Refresh"] = "true"
            return response
        except Exception as exc:
            logger.warning("market.record_price_failed", error=str(exc))
            return render(request, "market/_record_price_form.html", {"error": str(exc)})


class SeasonalForecastView(LoginRequiredMixin, View):
    """GET /market/seasonal/"""

    def get(self, request):
        org = get_org_or_404(request)
        product_type = request.GET.get("product_type", "eggs")
        with set_tenant_context(org):
            forecast = MarketService(org).get_seasonal_forecast(product_type)
        return render(request, "market/_seasonal_forecast.html", {"forecast": forecast, "product_type": product_type})


class MinViablePriceView(LoginRequiredMixin, View):
    """GET /market/mvp/<uuid:batch_pk>/"""

    def get(self, request, batch_pk):
        org = get_org_or_404(request)
        with set_tenant_context(org):
            try:
                data = MarketService(org).get_minimum_viable_price(str(batch_pk))
            except ValueError as exc:
                raise Http404(str(exc))
        return render(request, "market/_mvp_calculator.html", {"data": data, "batch_pk": batch_pk})


# ── Feed Price Intelligence ───────────────────────────────────────────────────────

class FeedPricesView(LoginRequiredMixin, View):
    """GET /market/feed-prices/ → Aggregated crowdsourced feed price dashboard."""

    def get(self, request):
        import json as _json
        feed_type = request.GET.get("feed_type", "")
        state = request.GET.get("state", "")
        data = FeedPriceService.get_current_prices(
            feed_type=feed_type or None,
            state=state or None,
        )
        form = FeedPriceSubmitForm()
        return render(request, "market/feed_prices.html", {
            "data": data,
            "trend_json": _json.dumps(data["trend"]),
            "form": form,
            "feed_types": FeedPriceReport.FeedType.choices,
            "nigerian_states": NIGERIAN_STATE_CHOICES,
            "active_feed_type": feed_type,
            "active_state": state,
        })


class SubmitFeedPriceView(LoginRequiredMixin, View):
    """POST /market/feed-prices/submit/ → HTMX fragment on success or rate-limit."""

    def post(self, request):
        form = FeedPriceSubmitForm(request.POST)
        if not form.is_valid():
            return render(request, "market/_feed_price_form.html", {"form": form}, status=422)

        cd = form.cleaned_data
        org = get_org_or_404(request)
        try:
            FeedPriceService.submit_price(
                user=request.user,
                org=org,
                feed_type=cd["feed_type"],
                brand=cd["brand"],
                price=cd["price_per_25kg_bag"],
                state=cd["state"],
                lga=cd.get("lga", ""),
                brand_other=cd.get("brand_other", ""),
            )
        except ValueError as exc:
            response = HttpResponse(status=429)
            response["HX-Trigger"] = json.dumps({
                "showToast": {"message": str(exc), "type": "error"}
            })
            return response

        return render(request, "market/_feed_price_submitted.html", {
            "state": cd["state"],
            "feed_type": dict(FeedPriceReport.FeedType.choices).get(cd["feed_type"], cd["feed_type"]),
            "price": cd["price_per_25kg_bag"],
        })


# ── Hatchery Directory ────────────────────────────────────────────────────────────

class HatcheryDirectoryView(LoginRequiredMixin, View):
    """GET /market/hatcheries/ → Hatcheries ranked by farmer reviews."""

    def get(self, request):
        state = request.GET.get("state", "")
        bird_type = request.GET.get("bird_type", "")
        hatcheries = HatcheryService.get_top_hatcheries(
            state=state or None,
            bird_type=bird_type or None,
        )
        # Also include hatcheries with zero reviews so directory isn't empty
        from django.db.models import Avg, Count
        hatcheries_no_reviews = list(
            Hatchery.objects.filter(is_verified=True)
            .annotate(avg_rating=Avg("reviews__overall_rating"), review_count=Count("reviews"))
            .filter(review_count=0)
            .order_by("state", "name")[:40]
        )
        suggest_form = SuggestHatcheryForm()
        return render(request, "market/hatcheries.html", {
            "hatcheries": hatcheries,
            "hatcheries_no_reviews": hatcheries_no_reviews,
            "nigerian_states": NIGERIAN_STATE_CHOICES,
            "active_state": state,
            "active_bird_type": bird_type,
            "suggest_form": suggest_form,
        })


class HatcheryDetailView(LoginRequiredMixin, View):
    """GET /market/hatcheries/<int:pk>/ → Full hatchery profile with reviews."""

    def get(self, request, pk):
        try:
            hatchery = Hatchery.objects.get(pk=pk)
        except Hatchery.DoesNotExist:
            raise Http404("Hatchery not found.")

        from django.db.models import Avg, Count
        reviews = list(HatcheryReview.objects.filter(hatchery=hatchery).order_by("-created_at")[:50])
        stats = HatcheryReview.objects.filter(hatchery=hatchery).aggregate(
            avg_overall=Avg("overall_rating"),
            avg_quality=Avg("doc_quality_rating"),
            avg_delivery=Avg("delivery_reliability"),
            avg_survival=Avg("survival_rate_pct"),
            avg_price=Avg("price_per_doc"),
            total=Count("id"),
        )
        review_form = HatcheryReviewForm(initial={"hatchery_id": pk})
        return render(request, "market/hatchery_detail.html", {
            "hatchery": hatchery,
            "reviews": reviews,
            "stats": stats,
            "review_form": review_form,
        })


class SubmitHatcheryReviewView(LoginRequiredMixin, View):
    """POST /market/hatcheries/<int:pk>/review/ → Save hatchery review (HTMX)."""

    def get(self, request, pk):
        try:
            hatchery = Hatchery.objects.get(pk=pk)
        except Hatchery.DoesNotExist:
            raise Http404("Hatchery not found.")
        form = HatcheryReviewForm(initial={"hatchery_id": pk})
        org = get_org_or_404(request)
        # Provide user's recent closed batches so they can link the review
        with set_tenant_context(org):
            from apps.farm.flocks.models import Batch
            import datetime
            two_weeks_ago = datetime.date.today() - datetime.timedelta(days=14)
            eligible_batches = list(
                Batch.objects.filter(
                    status="closed",
                    closed_at__date__lte=two_weeks_ago,
                ).order_by("-closed_at")[:20]
            )
        return render(request, "market/_hatchery_review_modal.html", {
            "hatchery": hatchery,
            "form": form,
            "eligible_batches": eligible_batches,
        })

    def post(self, request, pk):
        form = HatcheryReviewForm(request.POST)
        org = get_org_or_404(request)

        if not form.is_valid():
            try:
                hatchery = Hatchery.objects.get(pk=pk)
            except Hatchery.DoesNotExist:
                raise Http404()
            return render(request, "market/_hatchery_review_modal.html", {
                "hatchery": hatchery,
                "form": form,
            }, status=422)

        cd = form.cleaned_data
        batch = None
        if cd.get("batch_id"):
            with set_tenant_context(org):
                from apps.farm.flocks.models import Batch
                batch = Batch.objects.filter(id=cd["batch_id"]).first()

        # Enforce 2-week minimum age
        if batch:
            import datetime
            min_age = datetime.date.today() - datetime.timedelta(days=14)
            if batch.placement_date > min_age:
                response = HttpResponse(status=422)
                response["HX-Trigger"] = json.dumps({
                    "showToast": {
                        "message": "Reviews are only allowed for batches at least 2 weeks old.",
                        "type": "error",
                    }
                })
                return response

        try:
            HatcheryService.submit_review(
                hatchery_id=pk,
                batch=batch,
                user=request.user,
                org=org,
                data={
                    "doc_quality_rating": cd["doc_quality_rating"],
                    "survival_rate_pct": cd["survival_rate_pct"],
                    "delivery_reliability": cd["delivery_reliability"],
                    "overall_rating": cd["overall_rating"],
                    "comment": cd.get("comment", ""),
                    "batch_size": cd["batch_size"],
                    "purchase_date": cd["purchase_date"],
                    "price_per_doc": cd["price_per_doc"],
                },
            )
        except Exception as exc:
            logger.warning("hatchery.review_failed", error=str(exc))
            response = HttpResponse(status=422)
            response["HX-Trigger"] = json.dumps({
                "showToast": {"message": str(exc), "type": "error"}
            })
            return response

        response = HttpResponse(status=204)
        response["HX-Trigger"] = json.dumps({
            "showToast": {"message": "Review submitted. Thank you!", "type": "success"},
            "close-modal": True,
            "hatchery-reviewed": True,
        })
        return response


class SuggestHatcheryView(LoginRequiredMixin, View):
    """POST /market/hatcheries/suggest/ → Farmer-submitted hatchery (pending verification)."""

    def get(self, request):
        form = SuggestHatcheryForm()
        return render(request, "market/_suggest_hatchery_modal.html", {"form": form})

    def post(self, request):
        form = SuggestHatcheryForm(request.POST)
        if not form.is_valid():
            return render(request, "market/_suggest_hatchery_modal.html", {"form": form}, status=422)

        cd = form.cleaned_data
        org = get_org_or_404(request)
        HatcheryService.suggest_hatchery(
            user=request.user,
            org=org,
            name=cd["name"],
            state=cd["state"],
            lga=cd.get("lga", ""),
            address=cd.get("address", ""),
            phone=cd.get("phone", ""),
            website=cd.get("website", ""),
            bird_types=cd.get("bird_types", []),
        )
        response = HttpResponse(status=204)
        response["HX-Trigger"] = json.dumps({
            "showToast": {
                "message": "Thank you! Your suggestion has been submitted for review.",
                "type": "success",
            },
            "close-modal": True,
        })
        return response
