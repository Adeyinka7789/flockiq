import json
from datetime import date, timedelta

import structlog
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Avg, Sum
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.views import View
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.infrastructure.core.rls import set_tenant_context
from apps.infrastructure.core.views import TenantRequiredMixin

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

class ProductionOverviewView(TenantRequiredMixin, View):
    """GET /production/ → Production overview with metrics, filters, and per-batch table."""

    def get(self, request):
        import waffle
        from apps.infrastructure.core.filters import DateRangeFilter
        from apps.farm.flocks.models import Batch
        from apps.farm.farms.models import Farm

        org = request.user.org
        date_filter = DateRangeFilter()
        date_from, date_to = date_filter.get_date_range(request)
        today = date.today()

        farm_id = request.GET.get('farm') or ''
        batch_id = request.GET.get('batch') or ''
        preset = request.GET.get('preset', '7d')

        with set_tenant_context(org):
            qs = Batch.objects.filter(
                status='active', bird_type='layer'
            ).select_related('farm', 'house')
            if farm_id:
                qs = qs.filter(farm_id=farm_id)
            layer_batches = list(qs)

            farms = list(Farm.objects.filter(is_active=True))

            # Resolve active_batch to an object; default to first batch
            active_batch = None
            if batch_id:
                active_batch = next(
                    (b for b in layer_batches if str(b.pk) == batch_id), None
                )
            if active_batch is None and layer_batches:
                active_batch = layer_batches[0]

            todays_qs = EggProductionLog.objects.filter(
                record_date=today,
                batch__bird_type='layer',
                batch__status='active',
            )
            if farm_id:
                todays_qs = todays_qs.filter(farm_id=farm_id)
            if active_batch:
                todays_qs = todays_qs.filter(batch=active_batch)

            todays_eggs = todays_qs.aggregate(total=Sum('total_eggs'))['total'] or 0
            todays_hen_day = todays_qs.aggregate(avg=Avg('hen_day_pct'))['avg'] or 0
            todays_crates = round(todays_eggs / 30, 1)

            # 7-day averages for selected batch (or org-wide)
            seven_days_ago = today - timedelta(days=7)
            avg_qs = EggProductionLog.objects.filter(
                record_date__gte=seven_days_ago,
                record_date__lte=today,
            )
            if active_batch:
                avg_qs = avg_qs.filter(batch=active_batch)
            avg_7day = avg_qs.aggregate(avg=Avg('hen_day_pct'))['avg'] or 0
            avg_7day_eggs = avg_qs.aggregate(avg=Avg('total_eggs'))['avg'] or 0

            batch_summaries = []
            for batch in layer_batches:
                latest_log = EggProductionLog.objects.filter(
                    batch=batch, record_date=today
                ).first()
                b_avg_7day = EggProductionLog.objects.filter(
                    batch=batch,
                    record_date__gte=today - timedelta(days=7)
                ).aggregate(avg=Avg('hen_day_pct'))['avg'] or 0
                batch_summaries.append({
                    'batch': batch,
                    'todays_eggs': latest_log.total_eggs if latest_log else 0,
                    'todays_hen_day': float(latest_log.hen_day_pct) if latest_log and latest_log.hen_day_pct else 0,
                    'avg_7day_hen_day': round(float(b_avg_7day), 1),
                    'logged_today': latest_log is not None,
                })

            trend_data = []
            num_days = (date_to - date_from).days + 1
            for i in range(num_days):
                day = date_from + timedelta(days=i)
                day_qs = EggProductionLog.objects.filter(record_date=day)
                if farm_id:
                    day_qs = day_qs.filter(farm_id=farm_id)
                if active_batch:
                    day_qs = day_qs.filter(batch=active_batch)
                total = day_qs.aggregate(total=Sum('total_eggs'))['total'] or 0
                trend_data.append({'date': day.strftime('%d %b'), 'total': total})

            # Forecast vs Actual
            forecast_delta = None
            forecast_confidence = None
            forecast_total_14d = None
            ai_recommendations = []

            if active_batch and waffle.flag_is_active(request, 'ai_egg_forecast'):
                from apps.health.analytics.models import ForecastResult
                latest_forecast = list(
                    ForecastResult.objects.filter(
                        batch=active_batch,
                        forecast_type='egg',
                        forecast_date__gte=today,
                    ).order_by('forecast_date')[:14]
                )
                if latest_forecast:
                    forecast_total_14d = sum(
                        f.predicted_value for f in latest_forecast)
                    confidences = []
                    for f in latest_forecast:
                        if f.predicted_value > 0 and f.confidence_upper is not None and f.confidence_lower is not None:
                            band = f.confidence_upper - f.confidence_lower
                            pct = 100 - (band / f.predicted_value * 100)
                            confidences.append(max(0, min(100, float(pct))))
                    forecast_confidence = round(
                        sum(confidences) / len(confidences), 1
                    ) if confidences else None

                    today_forecast = next(
                        (f for f in latest_forecast if f.forecast_date == today), None)
                    if today_forecast and todays_eggs:
                        pv = float(today_forecast.predicted_value)
                        if pv > 0:
                            forecast_delta = round(
                                (todays_eggs - pv) / pv * 100, 1)

                    if forecast_confidence and forecast_confidence > 85:
                        ai_recommendations.append({
                            'type': 'good',
                            'text': 'Production forecast confidence is high. '
                                    'Maintain current feeding regime.',
                        })
                    avg_recent = float(avg_7day_eggs)
                    if avg_recent > 0 and forecast_total_14d:
                        daily_avg_forecast = float(forecast_total_14d) / 14
                        if daily_avg_forecast > avg_recent * 1.05:
                            ai_recommendations.append({
                                'type': 'warning',
                                'text': 'Forecast predicts a production increase. '
                                        'Ensure feed and water supply is adequate.',
                            })

            # Resource utilization
            crate_balance = None
            crate_utilization_pct = None
            todays_water_avg = None

            if active_batch:
                from apps.production.production.models import CrateInventory
                crate = CrateInventory.objects.filter(
                    farm=active_batch.farm
                ).order_by('-date').first()
                if crate:
                    crate_balance = crate.crates_balance
                    if crate.crates_produced > 0:
                        crate_utilization_pct = round(
                            float(crate.crates_sold) /
                            float(crate.crates_produced) * 100, 1)

                from apps.production.water.models import WaterLog
                water_today = WaterLog.objects.filter(
                    batch=active_batch,
                    record_date=today,
                ).aggregate(total=Sum('litres_consumed'))['total'] or 0
                if active_batch.current_count > 0:
                    todays_water_avg = round(
                        float(water_today) / active_batch.current_count * 1000, 0)

            # Daily records for selected batch (last 10)
            daily_records = []
            if active_batch:
                daily_records = list(
                    EggProductionLog.objects.filter(
                        batch=active_batch,
                    ).order_by('-record_date')[:10]
                )

            # Chart data: actual (last 21 days) + forecast (next 14 days)
            chart_actual_labels = []
            chart_actual_data = []
            chart_forecast_labels = []
            chart_forecast_data = []
            chart_today_index = None

            if active_batch:
                actual_logs = EggProductionLog.objects.filter(
                    batch=active_batch,
                    record_date__gte=today - timedelta(days=20),
                ).order_by('record_date')
                for log in actual_logs:
                    chart_actual_labels.append(log.record_date.strftime('%b %d'))
                    chart_actual_data.append(float(log.hen_day_pct or 0))
                    if log.record_date == today:
                        chart_today_index = len(chart_actual_labels) - 1

                if waffle.flag_is_active(request, 'ai_egg_forecast'):
                    from apps.health.analytics.models import ForecastResult
                    forecast_logs = ForecastResult.objects.filter(
                        batch=active_batch,
                        forecast_type='egg',
                        forecast_date__gt=today,
                        forecast_date__lte=today + timedelta(days=14),
                    ).order_by('forecast_date')
                    for f in forecast_logs:
                        chart_forecast_labels.append(f.forecast_date.strftime('%b %d'))
                        if active_batch.current_count > 0:
                            pct = float(f.predicted_value) / active_batch.current_count * 100
                            chart_forecast_data.append(round(pct, 1))

        context = {
            'todays_eggs': todays_eggs,
            'todays_crates': todays_crates,
            'todays_hen_day': round(float(todays_hen_day), 1),
            'active_layer_batches': len(layer_batches),
            'batch_summaries': batch_summaries,
            'trend_data': trend_data,
            'farms': farms,
            'layer_batches': layer_batches,
            'active_farm': farm_id,
            'active_batch': active_batch,
            'active_preset': preset,
            'date_from': date_from.strftime('%Y-%m-%d'),
            'date_to': date_to.strftime('%Y-%m-%d'),
            'today': today,
            'no_layer_batches': not batch_summaries,
            'avg_7day': round(float(avg_7day), 1),
            'avg_7day_eggs': round(float(avg_7day_eggs), 0),
            'forecast_delta': forecast_delta,
            'forecast_confidence': forecast_confidence,
            'forecast_total_14d': forecast_total_14d,
            'ai_recommendations': ai_recommendations,
            'crate_balance': crate_balance,
            'crate_utilization_pct': crate_utilization_pct,
            'todays_water_avg': todays_water_avg,
            'daily_records': daily_records,
            'chart_actual_labels': chart_actual_labels,
            'chart_actual_data': chart_actual_data,
            'chart_forecast_labels': chart_forecast_labels,
            'chart_forecast_data': chart_forecast_data,
            'chart_today_index': chart_today_index,
        }

        is_htmx = request.headers.get("HX-Request") == "true"
        if is_htmx:
            return render(request,
                'production/production/_production_overview_partial.html', context)
        return render(request,
            'production/production/production_overview.html', context)


class ProductionOverviewPDFExportView(TenantRequiredMixin, View):
    """GET /production/export/pdf/ → Waffle-gated PDF of production overview."""

    def get(self, request):
        from waffle import flag_is_active
        if not flag_is_active(request, 'pdf_export'):
            from django.http import HttpResponse
            return HttpResponse('PDF export requires an upgraded plan.', status=403)

        org = request.user.org
        today = date.today()
        with set_tenant_context(org):
            from apps.farm.flocks.models import Batch
            layer_batches = list(
                Batch.objects.filter(status='active', bird_type='layer')
                .select_related('farm', 'house')
            )
            batch_summaries = []
            for batch in layer_batches:
                latest_log = EggProductionLog.objects.filter(
                    batch=batch, record_date=today
                ).first()
                avg_7day = EggProductionLog.objects.filter(
                    batch=batch,
                    record_date__gte=today - timedelta(days=7)
                ).aggregate(avg=Avg('hen_day_pct'))['avg'] or 0
                batch_summaries.append({
                    'batch': batch,
                    'todays_eggs': latest_log.total_eggs if latest_log else 0,
                    'todays_hen_day': float(latest_log.hen_day_pct) if latest_log and latest_log.hen_day_pct else 0,
                    'avg_7day_hen_day': round(float(avg_7day), 1),
                    'logged_today': latest_log is not None,
                })

        from apps.infrastructure.core.exports import generate_production_overview_pdf
        from django.http import HttpResponse
        pdf_bytes = generate_production_overview_pdf(batch_summaries, today)
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="production-overview-{today}.pdf"'
        return response


class ProductionOverviewExcelExportView(TenantRequiredMixin, View):
    """GET /production/export/excel/ → Waffle-gated Excel of production overview."""

    def get(self, request):
        from waffle import flag_is_active
        if not flag_is_active(request, 'excel_export'):
            from django.http import HttpResponse
            return HttpResponse('Excel export requires an upgraded plan.', status=403)

        org = request.user.org
        today = date.today()
        with set_tenant_context(org):
            from apps.farm.flocks.models import Batch
            layer_batches = list(
                Batch.objects.filter(status='active', bird_type='layer')
                .select_related('farm', 'house')
            )
            batch_summaries = []
            for batch in layer_batches:
                latest_log = EggProductionLog.objects.filter(
                    batch=batch, record_date=today
                ).first()
                avg_7day = EggProductionLog.objects.filter(
                    batch=batch,
                    record_date__gte=today - timedelta(days=7)
                ).aggregate(avg=Avg('hen_day_pct'))['avg'] or 0
                batch_summaries.append({
                    'batch': batch,
                    'todays_eggs': latest_log.total_eggs if latest_log else 0,
                    'todays_hen_day': float(latest_log.hen_day_pct) if latest_log and latest_log.hen_day_pct else 0,
                    'avg_7day_hen_day': round(float(avg_7day), 1),
                    'logged_today': latest_log is not None,
                })

        from apps.infrastructure.core.exports import generate_production_overview_excel
        from django.http import HttpResponse
        xlsx_bytes = generate_production_overview_excel(batch_summaries, today)
        response = HttpResponse(
            xlsx_bytes,
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        response['Content-Disposition'] = f'attachment; filename="production-overview-{today}.xlsx"'
        return response


class EggProductionCSVExportView(TenantRequiredMixin, View):
    """GET /production/eggs/<batch_pk>/export/csv/ → CSV download of egg logs for a batch."""

    def get(self, request, batch_pk):
        import csv
        from django.http import HttpResponse
        from apps.farm.flocks.models import Batch

        org = request.user.org
        with set_tenant_context(org):
            batch = get_object_or_404(Batch, pk=batch_pk)
            logs = list(
                EggProductionLog.objects.filter(
                    batch=batch
                ).order_by('-record_date')
            )

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = (
            f'attachment; filename="eggs_{batch.batch_name}.csv"'
        )
        writer = csv.writer(response)
        writer.writerow([
            'Date', 'Total Eggs', 'Grade A', 'Grade B',
            'Cracked', 'Crates', 'Hen-Day %', 'Recorded By',
        ])
        for log in logs:
            writer.writerow([
                log.record_date,
                log.total_eggs,
                log.grade_a,
                log.grade_b,
                log.cracked,
                round(log.total_eggs / 30, 1),
                f'{log.hen_day_pct:.1f}%' if log.hen_day_pct else '',
                log.recorded_by.get_full_name() if log.recorded_by else '',
            ])
        return response


class ProductionLogView(LoginRequiredMixin, View):
    """GET/POST /production/eggs/<batch_pk>/log/ → Returns log form or updated summary card."""

    def get(self, request, batch_pk):
        from .forms import EggProductionLogForm
        return render(request, "production/production/_production_log_form.html", {
            "form": EggProductionLogForm(), "batch_pk": batch_pk,
        })

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
