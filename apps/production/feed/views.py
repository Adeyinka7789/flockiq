import json

import structlog
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views import View
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.infrastructure.core.helpers import get_org_or_404
from apps.infrastructure.core.rls import set_tenant_context

from .services import FeedService

logger = structlog.get_logger(__name__)


class FeedLogView(LoginRequiredMixin, View):
    """GET/POST /production/feed/<batch_pk>/log/ → Modal form or log feed."""

    def get(self, request, batch_pk):
        from datetime import date
        from .forms import FeedLogForm
        from apps.farm.flocks.models import Batch

        org = get_org_or_404(request)
        with set_tenant_context(org):
            batch = get_object_or_404(Batch, pk=batch_pk)
        return render(request, "production/feed/_feed_log_form.html", {
            "form": FeedLogForm(),
            "batch": batch,
            "today": date.today(),
        })

    def post(self, request, batch_pk):
        from datetime import date
        from .forms import FeedLogForm
        from apps.farm.flocks.models import Batch

        form = FeedLogForm(request.POST)
        org = get_org_or_404(request)

        def _error(f, status=422):
            with set_tenant_context(org):
                batch = get_object_or_404(Batch, pk=batch_pk)
            return render(request, "production/feed/_feed_log_form.html",
                {"form": f, "batch": batch, "today": date.today()}, status=status)

        if form.is_valid():
            cd = form.cleaned_data
            try:
                with set_tenant_context(org):
                    FeedService(org).log_feed(
                        batch_id=str(batch_pk),
                        record_date=cd["record_date"],
                        feed_type=cd["feed_type"],
                        quantity_kg=cd["quantity_kg"],
                        cost_per_kg=cd.get("cost_per_kg"),
                        notes=cd.get("notes", ""),
                        recorded_by=request.user,
                    )
            except ValueError as exc:
                form.add_error(None, str(exc))
                return _error(form)

            response = HttpResponse('')
            response["HX-Trigger"] = json.dumps({
                "showToast": {"message": "Feed logged.", "type": "success"},
                "close-modal": True,
                "feedLogged": True,
            })
            return response

        return _error(form)


class FeedTableView(LoginRequiredMixin, View):
    """GET /production/feed/<batch_pk>/table/ → Returns feed table partial."""

    def get(self, request, batch_pk):
        from urllib.parse import urlencode

        from .models import FEED_TYPE_CHOICES, FeedLog

        org = get_org_or_404(request)
        page = int(request.GET.get("page", 1))
        date_from = request.GET.get("date_from", "").strip()
        date_to = request.GET.get("date_to", "").strip()
        feed_type = request.GET.get("feed_type", "").strip()

        with set_tenant_context(org):
            from django.core.paginator import Paginator
            qs = (
                FeedLog.objects
                .filter(batch_id=batch_pk)
                .select_related("recorded_by")
                .order_by("-record_date")
            )
            if date_from:
                qs = qs.filter(record_date__gte=date_from)
            if date_to:
                qs = qs.filter(record_date__lte=date_to)
            if feed_type:
                qs = qs.filter(feed_type=feed_type)
            page_obj = Paginator(qs, 20).get_page(page)

        # Preserve active filters across pagination links.
        filter_params = {
            k: v
            for k, v in (
                ("date_from", date_from),
                ("date_to", date_to),
                ("feed_type", feed_type),
            )
            if v
        }
        filter_querystring = urlencode(filter_params)

        return render(
            request,
            "production/feed/_feed_table.html",
            {
                "page_obj": page_obj,
                "batch_pk": batch_pk,
                "date_from": date_from,
                "date_to": date_to,
                "active_feed_type": feed_type,
                "feed_type_choices": FEED_TYPE_CHOICES,
                "filter_querystring": filter_querystring,
            },
        )


class FeedSummaryCardView(LoginRequiredMixin, View):
    """GET /production/feed/<batch_pk>/summary/ → Returns summary card fragment."""

    def get(self, request, batch_pk):
        org = get_org_or_404(request)

        with set_tenant_context(org):
            summary = FeedService(org).get_feed_summary(str(batch_pk))

        return render(
            request,
            "production/feed/_feed_summary_card.html",
            {**summary, "batch_pk": batch_pk},
        )


class FeedChartView(LoginRequiredMixin, View):
    """GET /production/feed/<batch_pk>/chart/ → Returns chart partial with Chart.js data."""

    def get(self, request, batch_pk):
        org = get_org_or_404(request)
        days = int(request.GET.get("days", 30))

        with set_tenant_context(org):
            data = FeedService(org).get_trend_data(str(batch_pk), days=days)

        return render(
            request,
            "production/feed/_feed_chart.html",
            {
                "chart_data": json.dumps(data),
                "batch_pk": batch_pk,
                "selected_days": days,
                "day_options": [7, 14, 30, 60],
            },
        )


class FeedStockView(LoginRequiredMixin, View):
    """GET /production/feed/<farm_pk>/stock/ → Returns stock panel partial."""

    def get(self, request, farm_pk):
        org = get_org_or_404(request)

        with set_tenant_context(org):
            stocks = FeedService(org).get_stock_levels(str(farm_pk))

        return render(
            request,
            "production/feed/_feed_stock_panel.html",
            {"stocks": stocks, "farm_pk": farm_pk},
        )


class FeedLogAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .models import FeedLog
        from rest_framework import serializers as drf_serializers

        org = getattr(request.user, "org", None)
        if not org:
            return Response({"error": "No organisation."}, status=403)

        batch_pk = request.query_params.get("batch_id")
        with set_tenant_context(org):
            qs = FeedLog.objects.order_by("-record_date")
            if batch_pk:
                qs = qs.filter(batch_id=batch_pk)
            logs = list(qs[:100])

        data = [
            {
                "id": str(log.id),
                "record_date": str(log.record_date),
                "feed_type": log.feed_type,
                "quantity_kg": str(log.quantity_kg),
                "requirement_kg": str(log.requirement_kg) if log.requirement_kg else None,
                "variance_kg": str(log.variance_kg) if log.variance_kg else None,
                "total_cost": str(log.total_cost) if log.total_cost else None,
            }
            for log in logs
        ]
        return Response({"data": data})

    def post(self, request):
        org = getattr(request.user, "org", None)
        if not org:
            return Response({"error": "No organisation."}, status=403)

        batch_pk = request.data.get("batch_id")
        if not batch_pk:
            return Response({"error": {"detail": "batch_id is required."}}, status=400)

        required_fields = ["record_date", "feed_type", "quantity_kg"]
        for field in required_fields:
            if field not in request.data:
                return Response(
                    {"error": {"detail": f"{field} is required."}}, status=400
                )

        try:
            import datetime as dt
            record_date = dt.date.fromisoformat(request.data["record_date"])
            with set_tenant_context(org):
                log = FeedService(org).log_feed(
                    batch_id=str(batch_pk),
                    record_date=record_date,
                    feed_type=request.data["feed_type"],
                    quantity_kg=request.data["quantity_kg"],
                    cost_per_kg=request.data.get("cost_per_kg"),
                    notes=request.data.get("notes", ""),
                )
        except ValueError as exc:
            return Response({"error": {"detail": str(exc)}}, status=400)

        return Response(
            {
                "data": {
                    "id": str(log.id),
                    "record_date": str(log.record_date),
                    "feed_type": log.feed_type,
                    "quantity_kg": str(log.quantity_kg),
                }
            },
            status=201,
        )
