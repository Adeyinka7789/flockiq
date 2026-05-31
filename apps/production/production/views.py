import json

import structlog
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404
from django.shortcuts import render
from django.views import View
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.infrastructure.core.rls import set_tenant_context

from .exceptions import BatchNotLayerError, ProductionBatchClosedError
from .models import EggProductionLog
from .serializers import EggProductionLogCreateSerializer, EggProductionLogSerializer
from .services import EggProductionService

logger = structlog.get_logger(__name__)


def _get_org(request):
    org = getattr(request.user, "org", None)
    if org is None:
        raise Http404("No organisation found for this user.")
    return org


# ── HTMX Views ──────────────────────────────────────────────────────────────

class ProductionLogView(LoginRequiredMixin, View):
    """POST /production/eggs/<batch_pk>/log/ → Returns updated summary card."""

    def post(self, request, batch_pk):
        from .forms import EggProductionLogForm

        form = EggProductionLogForm(request.POST)
        org = _get_org(request)

        if form.is_valid():
            cd = form.cleaned_data
            try:
                with set_tenant_context(org):
                    svc = EggProductionService(org)
                    svc.log_production(
                        batch_id=str(batch_pk),
                        record_date=cd["record_date"],
                        total_eggs=cd["total_eggs"],
                        grade_a=cd.get("grade_a") or 0,
                        grade_b=cd.get("grade_b") or 0,
                        grade_c=cd.get("grade_c") or 0,
                        broken=cd.get("broken") or 0,
                        recorded_by=request.user,
                        notes=cd.get("notes", ""),
                    )
                    summary = svc.get_production_summary(str(batch_pk))
                    benchmark = svc.check_against_benchmark(str(batch_pk))
            except (BatchNotLayerError, ProductionBatchClosedError, ValueError) as exc:
                form.add_error(None, str(exc))
                return render(
                    request,
                    "production/production/_production_log_form.html",
                    {"form": form, "batch_pk": batch_pk},
                    status=422,
                )

            response = render(
                request,
                "production/production/_production_summary_card.html",
                {**summary, "benchmark": benchmark, "batch_pk": batch_pk},
            )
            response["HX-Trigger"] = json.dumps(
                {"showToast": {"message": "Production logged.", "type": "success"}}
            )
            return response

        return render(
            request,
            "production/production/_production_log_form.html",
            {"form": form, "batch_pk": batch_pk},
            status=422,
        )


class ProductionTableView(LoginRequiredMixin, View):
    """GET /production/eggs/<batch_pk>/table/ → Returns production table partial."""

    def get(self, request, batch_pk):
        org = _get_org(request)
        page = int(request.GET.get("page", 1))

        with set_tenant_context(org):
            page_obj = EggProductionService(org).get_production_table(
                str(batch_pk), page=page
            )

        return render(
            request,
            "production/production/_production_table.html",
            {"page_obj": page_obj, "batch_pk": batch_pk},
        )


class ProductionChartView(LoginRequiredMixin, View):
    """GET /production/eggs/<batch_pk>/chart/ → Returns chart partial with Chart.js data."""

    def get(self, request, batch_pk):
        org = _get_org(request)
        days = int(request.GET.get("days", 30))

        with set_tenant_context(org):
            data = EggProductionService(org).get_trend_data(str(batch_pk), days=days)

        return render(
            request,
            "production/production/_production_chart.html",
            {
                "chart_data": json.dumps(data),
                "batch_pk": batch_pk,
                "selected_days": days,
                "day_options": [7, 14, 30, 60],
            },
        )


class ProductionSummaryCardView(LoginRequiredMixin, View):
    """GET /production/eggs/<batch_pk>/summary/ → Returns summary card fragment."""

    def get(self, request, batch_pk):
        org = _get_org(request)

        with set_tenant_context(org):
            svc = EggProductionService(org)
            summary = svc.get_production_summary(str(batch_pk))
            benchmark = svc.check_against_benchmark(str(batch_pk))

        return render(
            request,
            "production/production/_production_summary_card.html",
            {**summary, "benchmark": benchmark, "batch_pk": batch_pk},
        )


# ── DRF API Views ────────────────────────────────────────────────────────────

class EggProductionAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        org = getattr(request.user, "org", None)
        if not org:
            return Response({"error": "No organisation."}, status=403)

        batch_pk = request.query_params.get("batch_id")
        with set_tenant_context(org):
            qs = EggProductionLog.objects.order_by("-record_date")
            if batch_pk:
                qs = qs.filter(batch_id=batch_pk)
            logs = list(qs[:100])

        return Response({"data": EggProductionLogSerializer(logs, many=True).data})

    def post(self, request):
        org = getattr(request.user, "org", None)
        if not org:
            return Response({"error": "No organisation."}, status=403)

        batch_pk = request.data.get("batch_id")
        if not batch_pk:
            return Response({"error": {"detail": "batch_id is required."}}, status=400)

        serializer = EggProductionLogCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"error": {"fields": serializer.errors}}, status=400)

        cd = serializer.validated_data
        try:
            with set_tenant_context(org):
                log = EggProductionService(org).log_production(
                    batch_id=str(batch_pk),
                    record_date=cd["record_date"],
                    total_eggs=cd["total_eggs"],
                    grade_a=cd.get("grade_a", 0),
                    grade_b=cd.get("grade_b", 0),
                    grade_c=cd.get("grade_c", 0),
                    broken=cd.get("broken", 0),
                    notes=cd.get("notes", ""),
                )
        except BatchNotLayerError as exc:
            return Response({"error": {"detail": str(exc)}}, status=422)
        except ProductionBatchClosedError as exc:
            return Response({"error": {"detail": str(exc)}}, status=422)
        except ValueError as exc:
            return Response({"error": {"detail": str(exc)}}, status=400)

        return Response({"data": EggProductionLogSerializer(log).data}, status=201)


class EggProductionDetailAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, batch_pk):
        org = getattr(request.user, "org", None)
        if not org:
            return Response({"error": "No organisation."}, status=403)

        with set_tenant_context(org):
            svc = EggProductionService(org)
            summary = svc.get_production_summary(str(batch_pk))
            benchmark = svc.check_against_benchmark(str(batch_pk))

        serialized = {
            "total_eggs_to_date": summary["total_eggs_to_date"],
            "average_hen_day_pct": summary["average_hen_day_pct"],
            "total_crates": summary["total_crates"],
            "best_day": (
                EggProductionLogSerializer(summary["best_day"]).data
                if summary["best_day"] else None
            ),
            "worst_day": (
                EggProductionLogSerializer(summary["worst_day"]).data
                if summary["worst_day"] else None
            ),
            "last_7_days": EggProductionLogSerializer(
                summary["last_7_days"], many=True
            ).data,
            "benchmark": benchmark,
        }
        return Response({"data": serialized})
