import structlog
import waffle
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.views import View
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.farm.flocks.models import Batch
from apps.infrastructure.core.rls import set_tenant_context

from .models import AnomalyRecord
from .serializers import (
    AnomalyRecordSerializer,
    ForecastResultSerializer,
    SaleTimingSerializer,
    TheftFlagSerializer,
)
from .services import (
    AnomalyDetectionService,
    DiagnosisEngine,
    ProphetForecastService,
    SaleTimingService,
    TheftDetectionService,
)

logger = structlog.get_logger(__name__)


def _get_org(request):
    org = getattr(request.user, "org", None)
    if org is None:
        raise Http404("No organisation found for this user.")
    return org


def _get_batch(org, batch_pk):
    with set_tenant_context(org):
        batch = Batch.objects.filter(id=batch_pk, org=org).first()
    if batch is None:
        raise Http404
    return batch


def _coming_soon(request):
    return render(request, "analytics/_feature_coming_soon.html")


# ── HTMX views ─────────────────────────────────────────────────────────────────


class ForecastChartView(LoginRequiredMixin, View):
    """GET /analytics/forecast/<uuid:batch_pk>/ — Prophet forecast chart data."""

    def get(self, request, batch_pk):
        if not waffle.switch_is_active("ai_egg_forecast"):
            return _coming_soon(request)

        org = _get_org(request)
        batch = _get_batch(org, batch_pk)

        with set_tenant_context(org):
            data = ProphetForecastService(org).forecast_egg_production(batch)

        return render(request, "analytics/_forecast_chart.html", {"data": data, "batch": batch})


class AnomalyFeedView(LoginRequiredMixin, View):
    """GET /analytics/anomalies/<uuid:batch_pk>/ — Active anomaly list."""

    def get(self, request, batch_pk):
        if not waffle.switch_is_active("ai_anomaly_detection"):
            return _coming_soon(request)

        org = _get_org(request)
        batch = _get_batch(org, batch_pk)

        with set_tenant_context(org):
            anomalies = AnomalyDetectionService(org).get_active_anomalies(batch_id=batch_pk)

        return render(
            request,
            "analytics/_anomaly_feed.html",
            {"anomalies": anomalies, "batch": batch},
        )


class AnomalyResolveView(LoginRequiredMixin, View):
    """POST /analytics/anomalies/<uuid:pk>/resolve/ — Mark anomaly resolved."""

    def post(self, request, pk):
        org = _get_org(request)

        with set_tenant_context(org):
            record = AnomalyDetectionService(org).resolve_anomaly(
                anomaly_id=pk, note=request.POST.get("note", "")
            )
            anomalies = AnomalyDetectionService(org).get_active_anomalies(
                batch_id=str(record.batch_id)
            )

        return render(
            request,
            "analytics/_anomaly_feed.html",
            {"anomalies": anomalies, "batch": record.batch},
        )


class TheftReportView(LoginRequiredMixin, View):
    """GET /analytics/theft/<uuid:batch_pk>/ — Theft reconciliation report."""

    def get(self, request, batch_pk):
        if not waffle.switch_is_active("ai_theft_detection"):
            return _coming_soon(request)

        org = _get_org(request)
        batch = _get_batch(org, batch_pk)

        with set_tenant_context(org):
            data = TheftDetectionService(org).reconcile_batch(batch)

        return render(request, "analytics/_theft_report.html", {"data": data, "batch": batch})


class SaleTimingView(LoginRequiredMixin, View):
    """GET /analytics/sale-timing/<uuid:batch_pk>/ — Sale timing recommendation."""

    def get(self, request, batch_pk):
        if not waffle.switch_is_active("ai_sale_timing"):
            return _coming_soon(request)

        org = _get_org(request)
        batch = _get_batch(org, batch_pk)

        with set_tenant_context(org):
            data = SaleTimingService(org).get_recommendation(batch)

        return render(
            request, "analytics/_sale_timing_card.html", {"data": data, "batch": batch}
        )


class DiagnosisView(LoginRequiredMixin, View):
    """POST /analytics/diagnose/ — Symptom diagnosis."""

    def post(self, request):
        if not waffle.switch_is_active("ai_symptom_diagnosis"):
            return _coming_soon(request)

        org = _get_org(request)
        symptoms = request.POST.getlist("symptoms")
        batch_id = request.POST.get("batch_id")
        batch = None

        if batch_id:
            batch = _get_batch(org, batch_id)

        with set_tenant_context(org):
            result = DiagnosisEngine(org).diagnose(symptoms, batch=batch)

        return render(request, "analytics/_diagnosis_result.html", {"result": result})


# ── DRF API views ───────────────────────────────────────────────────────────────


class AlertListAPIView(APIView):
    """GET /api/v1/analytics/alerts/ — Active anomalies for authenticated org."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        org = _get_org(request)
        with set_tenant_context(org):
            anomalies = AnomalyDetectionService(org).get_active_anomalies()
            serializer = AnomalyRecordSerializer(anomalies, many=True)
        return Response({"data": serializer.data})


class AlertAcknowledgeAPIView(APIView):
    """POST /api/v1/analytics/alerts/<uuid>/acknowledge/"""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        org = _get_org(request)
        with set_tenant_context(org):
            record = AnomalyDetectionService(org).resolve_anomaly(
                anomaly_id=pk, note=request.data.get("note", "")
            )
            serializer = AnomalyRecordSerializer(record)
        return Response({"data": serializer.data})


class ForecastAPIView(APIView):
    """GET /api/v1/analytics/forecast/<uuid:batch_pk>/"""

    permission_classes = [IsAuthenticated]

    def get(self, request, batch_pk):
        org = _get_org(request)
        batch = _get_batch(org, batch_pk)
        with set_tenant_context(org):
            data = ProphetForecastService(org).forecast_egg_production(batch)
        return Response({"data": data})


class TheftAPIView(APIView):
    """GET /api/v1/analytics/theft/<uuid:batch_pk>/"""

    permission_classes = [IsAuthenticated]

    def get(self, request, batch_pk):
        org = _get_org(request)
        batch = _get_batch(org, batch_pk)
        with set_tenant_context(org):
            data = TheftDetectionService(org).reconcile_batch(batch)
        return Response({"data": data})


class SaleTimingAPIView(APIView):
    """GET /api/v1/analytics/sale-timing/<uuid:batch_pk>/"""

    permission_classes = [IsAuthenticated]

    def get(self, request, batch_pk):
        org = _get_org(request)
        batch = _get_batch(org, batch_pk)
        with set_tenant_context(org):
            data = SaleTimingService(org).get_recommendation(batch)
        return Response({"data": data})
