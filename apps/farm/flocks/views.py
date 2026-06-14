import json

import structlog
from django.contrib.auth.mixins import LoginRequiredMixin
from apps.infrastructure.accounts.permissions import CanRecord, IsSupervisorOrAbove
from apps.infrastructure.core.mixins import RoleRequiredMixin
from apps.infrastructure.core.views import TenantRequiredMixin
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views import View
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.infrastructure.core.delete_views import SoftDeleteView
from apps.infrastructure.core.helpers import get_org_or_404
from apps.infrastructure.core.rls import set_tenant_context

from .exceptions import (
    BatchAlreadyClosedError,
    BatchClosedError,
    HouseCapacityExceededError,
    HouseOccupiedError,
    MortalityExceedsLiveBirdsError,
)
from .forms import (
    BatchCloseForm,
    BatchCreateForm,
    LossDocumentationForm,
    MortalityLogForm,
    WeightRecordForm,
)
from apps.farm.farms.models import House
from .models import Batch, MortalityLog, WeightRecord
from .serializers import (
    BatchCreateSerializer,
    BatchSerializer,
    MortalityLogCreateSerializer,
    MortalityLogSerializer,
)
from .services import BatchService

logger = structlog.get_logger(__name__)




# ── HTMX views ─────────────────────────────────────────────────────────────────

class BatchListView(TenantRequiredMixin, View):
    """GET /batches/ → Full batch list page with farm/type/status/search filtering."""

    def get(self, request):
        from datetime import date, timedelta
        from django.core.paginator import Paginator
        from django.db.models import Q, Sum

        org = get_org_or_404(request)
        today = date.today()

        farm_id = request.GET.get("farm", "")
        bird_type = request.GET.get("bird_type", "all")
        status_filter = request.GET.get("status", "active")
        q = request.GET.get("q", "").strip()

        with set_tenant_context(org):
            from apps.farm.farms.models import Farm

            farms = list(Farm.objects.filter(is_active=True))

            batches = Batch.objects.filter(org=org).select_related("farm", "house").order_by("-placement_date")

            if farm_id:
                batches = batches.filter(farm_id=farm_id)
            if bird_type and bird_type != "all":
                batches = batches.filter(bird_type=bird_type)
            if status_filter == "active":
                batches = batches.filter(status="active")
            elif status_filter == "closed":
                batches = batches.filter(status="closed")
            if q:
                batches = batches.filter(
                    Q(batch_name__icontains=q)
                    | Q(farm__name__icontains=q)
                    | Q(breed_name__icontains=q)
                )

            paginator = Paginator(batches, 10)
            page_num = request.GET.get("page", 1)
            page_obj = paginator.get_page(page_num)
            # Materialise the page rows inside the RLS scope — the template
            # iterates page_obj (and reads batch.farm, preloaded above) during
            # rendering, which happens outside set_tenant_context().
            page_obj.object_list = list(page_obj.object_list)

            active_batches = Batch.objects.filter(org=org, status="active")

            from .models import MortalityLog as _MortalityLog
            last_30 = today - timedelta(days=30)
            total_mort = (
                _MortalityLog.objects.filter(
                    batch__in=active_batches,
                    date__gte=last_30,
                ).aggregate(total=Sum("count"))["total"] or 0
            )
            total_live = active_batches.aggregate(total=Sum("current_count"))["total"] or 1
            avg_mortality_rate = round((total_mort / max(total_live * 30, 1)) * 100, 2)

            from apps.production.feed.models import FeedLog
            total_feed = (
                FeedLog.objects.filter(batch__in=active_batches)
                .aggregate(total=Sum("quantity_kg"))["total"] or 0
            )
            total_weight = sum(
                float(b.current_count) * 1.8
                for b in active_batches
                if b.bird_type == "broiler"
            )
            avg_fcr = round(float(total_feed) / float(total_weight), 2) if total_weight > 0 and total_feed > 0 else None

            upcoming_harvest = None
            broilers = list(active_batches.filter(bird_type="broiler").order_by("-placement_date"))
            for b in broilers:
                days_to_harvest = max(0, 38 - b.cycle_day)
                if days_to_harvest <= 10:
                    upcoming_harvest = {"batch": b, "days_to_harvest": days_to_harvest}
                    break
            if not upcoming_harvest and broilers:
                b = broilers[0]
                upcoming_harvest = {"batch": b, "days_to_harvest": max(0, 38 - b.cycle_day)}

        context = {
            "page_obj": page_obj,
            "farms": farms,
            "active_farm": farm_id,
            "active_bird_type": bird_type,
            "active_status": status_filter,
            "search_query": q,
            "total_count": paginator.count,
            "avg_mortality_rate": avg_mortality_rate,
            "avg_fcr": avg_fcr,
            "upcoming_harvest": upcoming_harvest,
            "today": today,
        }

        if request.headers.get("HX-Request"):
            return render(request, "flocks/_batch_list_partial.html", context)
        return render(request, "flocks/batch_list.html", context)


class BatchCreateSelectView(RoleRequiredMixin, View):
    """GET /batches/create/ → Step 1 of batch creation: pick a farm + house.

    Opened from the batch list ("New Batch Entry") and from a farm detail page
    ("New Intake", which passes ?farm_id= to pre-filter to that farm). Renders
    into #modal-body; selecting a house swaps in the batch create form.
    """

    allowed_roles = ["owner", "manager", "supervisor"]

    def get(self, request):
        from django.db.models import Count, Prefetch, Q

        org = get_org_or_404(request)
        farm_id = request.GET.get("farm_id")
        with set_tenant_context(org):
            from apps.farm.farms.models import Farm, House

            # Annotate occupancy in-query (inside the tenant context) so the
            # template can read it at render time without firing a fresh query
            # that would run outside set_tenant_context() and return none().
            houses_qs = (
                House.objects.filter(is_active=True)
                .annotate(
                    active_batch_count=Count(
                        "batches", filter=Q(batches__status="active")
                    )
                )
                .order_by("name")
            )
            qs = Farm.objects.prefetch_related(
                Prefetch("houses", queryset=houses_qs)
            ).filter(is_active=True)
            if farm_id:
                qs = qs.filter(pk=farm_id)
            farms = list(qs)
        return render(
            request,
            "flocks/_batch_select_farm_house.html",
            {"farms": farms, "farm_id": farm_id},
        )


class BatchCreateView(RoleRequiredMixin, View):
    """POST /farms/<uuid>/batches/create/ → Creates batch; returns toast + detail redirect."""

    allowed_roles = ["owner", "manager", "supervisor"]

    def get(self, request, farm_pk):
        org = get_org_or_404(request)
        preselected_house = None
        initial = {"farm_id": farm_pk}
        house_id = request.GET.get("house")
        if house_id:
            try:
                with set_tenant_context(org):
                    preselected_house = House.objects.get(id=house_id)
                initial["house_id"] = house_id
            except (House.DoesNotExist, Exception):
                pass
        form = BatchCreateForm(initial=initial, country=org.country)
        return render(request, "flocks/_batch_create_modal.html", {
            "form": form,
            "farm_pk": farm_pk,
            "preselected_house": preselected_house,
        })

    def post(self, request, farm_pk):
        org = get_org_or_404(request)
        form = BatchCreateForm(request.POST, country=org.country)
        is_htmx = request.headers.get("HX-Request") == "true"

        from apps.infrastructure.core.helpers import write_blocked_response
        blocked = write_blocked_response(request, org)
        if blocked is not None:
            return blocked

        from apps.infrastructure.billing.features import get_plan_features
        features = get_plan_features(org.plan_tier)
        with set_tenant_context(org):
            active_batches = Batch.objects.filter(status='active').count()
        if active_batches >= features['max_active_batches']:
            response = HttpResponse(status=403)
            response['HX-Trigger'] = json.dumps({
                'showToast': {
                    'message': (
                        f'Your {org.plan_tier} plan allows {features["max_active_batches"]} active batch(es). '
                        f'Upgrade to add more.'
                    ),
                    'type': 'error',
                }
            })
            return response

        if form.is_valid():
            cd = form.cleaned_data
            try:
                with set_tenant_context(org):
                    batch = BatchService(org).create_batch(
                        farm_id=str(farm_pk),
                        house_id=str(cd["house_id"]),
                        batch_name=cd["batch_name"],
                        bird_type=cd["bird_type"],
                        placement_date=cd["placement_date"],
                        initial_count=cd["initial_count"],
                        breed_name=cd.get("breed_name", ""),
                        hatchery=cd.get("hatchery"),
                        doc_price_per_chick=cd.get("doc_price_per_chick"),
                        doc_supplier_name=cd.get("doc_supplier_name", ""),
                    )
            except (HouseOccupiedError, HouseCapacityExceededError, ValueError) as exc:
                form.add_error(None, str(exc))
                if is_htmx:
                    return render(
                        request,
                        "flocks/_batch_create_modal.html",
                        {"form": form, "farm_pk": farm_pk},
                        status=422,
                    )
                return render(request, "flocks/_batch_create_modal.html", {"form": form, "farm_pk": farm_pk})

            if is_htmx:
                response = HttpResponse(status=204)
                response["HX-Trigger"] = json.dumps({
                    "close-modal": True,
                    "showToast": {
                        "message": f'Batch "{batch.batch_name}" created.',
                        "type": "success",
                    },
                    "batchCreated": {"batch_id": str(batch.pk)},
                })
                response["HX-Redirect"] = f"/batches/{batch.pk}/"
                return response

            from django.shortcuts import redirect
            return redirect("flocks:detail", pk=batch.pk)

        if is_htmx:
            return render(
                request,
                "flocks/_batch_create_modal.html",
                {"form": form, "farm_pk": farm_pk},
                status=422,
            )
        return render(request, "flocks/_batch_create_modal.html", {"form": form, "farm_pk": farm_pk})


COBB_500_STANDARD = {
    7: 170, 14: 400, 21: 780, 28: 1260,
    35: 1800, 42: 2400, 49: 2950,
}


def _interpolate_cobb_standard(day):
    days = sorted(COBB_500_STANDARD.keys())
    if day <= days[0]:
        return COBB_500_STANDARD[days[0]]
    for i, d in enumerate(days):
        if day <= d:
            prev_d = days[i - 1]
            ratio = (day - prev_d) / (d - prev_d)
            return int(COBB_500_STANDARD[prev_d] + ratio * (COBB_500_STANDARD[d] - COBB_500_STANDARD[prev_d]))
    return COBB_500_STANDARD[days[-1]]


class BatchDetailView(TenantRequiredMixin, View):
    """GET /batches/<uuid>/ → Full batch detail page with Alpine.js tabs."""

    def get(self, request, pk):
        org = get_org_or_404(request)
        weight_data_json = "[]"

        with set_tenant_context(org):
            try:
                batch = Batch.objects.select_related("farm", "house", "hatchery").get(id=pk)
            except Batch.DoesNotExist:
                raise Http404("Batch not found.")

            if batch.bird_type == "broiler":
                weight_records = list(
                    WeightRecord.objects.filter(batch=batch).order_by("sample_date")
                )
                if weight_records:
                    weight_data = []
                    for wr in weight_records:
                        day = (wr.sample_date - batch.placement_date).days
                        standard = _interpolate_cobb_standard(day)
                        weight_data.append({
                            "day": day,
                            "date": wr.sample_date.strftime("%d %b"),
                            "actual": round(float(wr.avg_weight_kg) * 1000, 1),
                            "standard": standard,
                        })
                    import json as _json
                    weight_data_json = _json.dumps(weight_data)

        exit_analysis = None
        fcr_analysis = None
        if batch.bird_type == "broiler":
            from apps.health.analytics.exit_optimizer import BroilerExitOptimizer
            from apps.production.feed.models import FeedLog
            from django.db.models import Sum as _Sum

            price = int(request.GET.get("price_per_kg", 1850))
            exit_analysis = BroilerExitOptimizer().analyze(batch, price)

            with set_tenant_context(org):
                total_feed = (
                    FeedLog.objects.filter(batch=batch)
                    .aggregate(total=_Sum("quantity_kg"))["total"] or 0
                )

            estimated_weight_kg = batch.current_count * exit_analysis["estimated_weight_g"] / 1000
            if estimated_weight_kg > 0 and total_feed > 0:
                actual_fcr = round(float(total_feed) / estimated_weight_kg, 2)
                cobb_target = 1.75
                if actual_fcr <= cobb_target:
                    fcr_status = "good"
                elif actual_fcr <= cobb_target * 1.1:
                    fcr_status = "warning"
                else:
                    fcr_status = "poor"
                fcr_diff_pct = round(abs(actual_fcr - cobb_target) / cobb_target * 100)
                fcr_analysis = {
                    "actual": actual_fcr,
                    "target": cobb_target,
                    "status": fcr_status,
                    "diff_pct": fcr_diff_pct,
                    "advice": {
                        "good": "Excellent FCR — on track with Cobb 500 standard.",
                        "warning": "FCR slightly above target. Monitor feed quality.",
                        "poor": (
                            f"FCR is {fcr_diff_pct}% above Cobb 500 target. "
                            f"Check: feed quality, disease, ventilation."
                        ),
                    }[fcr_status],
                    "total_feed_kg": round(float(total_feed), 1),
                }

        from apps.infrastructure.billing.features import get_plan_features
        import waffle

        plan_features = get_plan_features(org.plan_tier)

        # --- AI Insights context ---
        sale_timing = None
        if batch.bird_type == "broiler" and waffle.flag_is_active(request, "ai_sale_timing"):
            try:
                with set_tenant_context(org):
                    from apps.health.analytics.services import SaleTimingService
                    raw = SaleTimingService(org).get_recommendation(batch)
                days_until = max(0, 38 - batch.cycle_day) if batch.cycle_day < 38 else 0
                sale_timing = {
                    **raw,
                    "status": None if raw.get("available") else "unavailable",
                    "recommendation": raw.get("urgency", "wait"),
                    "batch_age": raw.get("cycle_day", batch.cycle_day),
                    "recommended_date": raw.get("recommended_sale_date"),
                    "optimal_date": raw.get("recommended_sale_date"),
                    "days_until_optimal": days_until,
                }
            except Exception:
                pass

        anomaly_result = None
        if waffle.flag_is_active(request, "ai_anomaly_detection"):
            try:
                with set_tenant_context(org):
                    from apps.health.analytics.services import AnomalyDetectionService
                    raw = AnomalyDetectionService(org).check_mortality_anomaly(batch)
                anomaly_result = {
                    **raw,
                    "status": None,
                    "message": raw.get("description"),
                }
            except Exception:
                pass

        theft_result = None
        if waffle.flag_is_active(request, "ai_theft_detection"):
            try:
                with set_tenant_context(org):
                    from apps.health.analytics.services import TheftDetectionService
                    raw = TheftDetectionService(org).reconcile_batch(batch)
                theft_result = {
                    **raw,
                    "status": None,
                    "theft_suspected": raw.get("flagged"),
                    "accounted_for": raw.get("accounted"),
                }
            except Exception:
                pass

        has_hatchery_review = False
        if batch.hatchery_id:
            from apps.finance.market.models import HatcheryReview
            has_hatchery_review = HatcheryReview.objects.filter(batch=batch).exists()

        # Estimated flock value — active batches only. Closed batches have real
        # sale data, so an estimate would be noise there.
        valuation = None
        if batch.status == "active":
            from apps.infrastructure.core.valuation import FlockValuationService
            valuation = FlockValuationService(batch).estimate_value()

        context = {
            "batch": batch,
            "mortality_form": MortalityLogForm(),
            "weight_form": WeightRecordForm(),
            "close_form": BatchCloseForm(),
            "weight_data_json": weight_data_json,
            "exit_analysis": exit_analysis,
            "fcr_analysis": fcr_analysis,
            "plan_features": plan_features,
            "sale_timing": sale_timing,
            "anomaly_result": anomaly_result,
            "theft_result": theft_result,
            "has_hatchery_review": has_hatchery_review,
            "valuation": valuation,
            "symptom_choices": [
                ("respiratory", "Respiratory distress / coughing"),
                ("sudden_death", "Sudden unexplained death"),
                ("diarrhoea", "Diarrhoea"),
                ("bloody_diarrhoea", "Bloody diarrhoea"),
                ("lethargy", "Lethargy / ruffled feathers"),
                ("drop_in_production", "Drop in egg production"),
                ("poor_growth", "Poor growth / bad FCR"),
                ("nervous", "Twisted neck / nervous signs"),
                ("watery_eggs", "Watery/poor quality eggs"),
            ],
        }
        return render(request, "flocks/batch_detail.html", context)


class ExitOptimizerPartialView(TenantRequiredMixin, View):
    """GET /batches/<uuid>/exit-optimizer/ → HTMX partial for price adjustment."""

    def get(self, request, pk):
        from apps.health.analytics.exit_optimizer import BroilerExitOptimizer

        org = get_org_or_404(request)
        with set_tenant_context(org):
            batch = get_object_or_404(Batch, id=pk)
        price = int(request.GET.get("price_per_kg", 1850))
        exit_analysis = BroilerExitOptimizer().analyze(batch, price)
        return render(
            request,
            "flocks/_exit_optimizer_card.html",
            {"batch": batch, "exit_analysis": exit_analysis},
        )


class MortalityRecentView(LoginRequiredMixin, View):
    """GET /batches/<uuid:pk>/mortality/recent/ → HTMX mortality table fragment with filters."""

    def get(self, request, pk):
        from datetime import datetime as dt

        org = get_org_or_404(request)
        date_from_str = request.GET.get("date_from", "")
        date_to_str = request.GET.get("date_to", "")
        cause = request.GET.get("cause", "")

        with set_tenant_context(org):
            try:
                batch = Batch.objects.get(id=pk)
            except Batch.DoesNotExist:
                raise Http404("Batch not found.")

            logs = MortalityLog.objects.filter(batch_id=pk).order_by("-date")

            if date_from_str:
                try:
                    logs = logs.filter(date__gte=dt.strptime(date_from_str, "%Y-%m-%d").date())
                except ValueError:
                    date_from_str = ""

            if date_to_str:
                try:
                    logs = logs.filter(date__lte=dt.strptime(date_to_str, "%Y-%m-%d").date())
                except ValueError:
                    date_to_str = ""

            if cause:
                logs = logs.filter(cause=cause)

            logs = list(logs[:50])

        return render(
            request,
            "flocks/_mortality_table.html",
            {
                "logs": logs,
                "batch": batch,
                "batch_pk": pk,
                "active_cause": cause,
                "date_from": date_from_str,
                "date_to": date_to_str,
            },
        )


class MortalityLogView(RoleRequiredMixin, View):
    """GET /batches/<uuid>/mortality/ → modal form; POST → logs mortality and closes modal.

    Recording production data — vet_advisor (read-only) is excluded.
    """

    allowed_roles = ["owner", "manager", "supervisor", "data_entry"]

    def get(self, request, pk):
        from datetime import date
        org = get_org_or_404(request)
        with set_tenant_context(org):
            batch = get_object_or_404(Batch, id=pk)
        form = MortalityLogForm()
        return render(request, "flocks/_mortality_modal.html", {
            "form": form, "batch": batch, "today": date.today(),
        })

    def post(self, request, pk):
        form = MortalityLogForm(request.POST)
        org = get_org_or_404(request)

        from apps.infrastructure.core.helpers import write_blocked_response
        blocked = write_blocked_response(request, org)
        if blocked is not None:
            return blocked

        if form.is_valid():
            cd = form.cleaned_data
            try:
                with set_tenant_context(org):
                    BatchService(org).log_mortality(
                        batch_id=str(pk),
                        count=cd["count"],
                        cause=cd["cause"],
                        date=cd["date"],
                        notes=cd.get("notes", ""),
                    )
            except (BatchClosedError, MortalityExceedsLiveBirdsError) as exc:
                form.add_error(None, str(exc))
                with set_tenant_context(org):
                    batch = get_object_or_404(Batch, id=pk)
                return render(
                    request,
                    "flocks/_mortality_modal.html",
                    {"form": form, "batch": batch},
                    status=422,
                )

            with set_tenant_context(org):
                batch = get_object_or_404(Batch, id=pk)
                logs = list(MortalityLog.objects.filter(batch_id=pk).order_by("-date")[:30])
            response = render(
                request,
                "flocks/_mortality_table.html",
                {"logs": logs, "batch": batch, "batch_pk": pk},
            )
            response["HX-Trigger"] = json.dumps({
                "showToast": {"message": f"{cd['count']} mortality logged.", "type": "success"},
                "mortalityLogged": True,
                "close-modal": True,
            })
            return response

        with set_tenant_context(org):
            batch = get_object_or_404(Batch, id=pk)
        return render(
            request,
            "flocks/_mortality_modal.html",
            {"form": form, "batch": batch},
            status=422,
        )


class WeightRecordView(RoleRequiredMixin, View):
    """POST /batches/<uuid>/weight/ → HTMX weight record submission.

    Recording production data — vet_advisor (read-only) is excluded.
    """

    allowed_roles = ["owner", "manager", "supervisor", "data_entry"]

    def post(self, request, pk):
        form = WeightRecordForm(request.POST)
        org = get_org_or_404(request)

        if form.is_valid():
            cd = form.cleaned_data
            try:
                with set_tenant_context(org):
                    BatchService(org).log_weight(
                        batch_id=str(pk),
                        sample_size=cd["sample_size"],
                        avg_weight_kg=cd["avg_weight_kg"],
                        min_weight_kg=cd.get("min_weight_kg"),
                        max_weight_kg=cd.get("max_weight_kg"),
                        sample_date=cd["sample_date"],
                        notes=cd.get("notes", ""),
                    )
                    records = list(
                        WeightRecord.objects.filter(batch_id=pk).order_by("-sample_date")[:20]
                    )
            except (BatchClosedError, ValueError) as exc:
                form.add_error(None, str(exc))
                return render(
                    request,
                    "flocks/_weight_form.html",
                    {"form": form, "batch_pk": pk},
                    status=422,
                )

            response = render(
                request,
                "flocks/_weight_table.html",
                {"records": records, "batch_pk": pk},
            )
            response["HX-Trigger"] = json.dumps({
                "showToast": {"message": "Weight recorded.", "type": "success"}
            })
            return response

        return render(
            request,
            "flocks/_weight_form.html",
            {"form": form, "batch_pk": pk},
            status=422,
        )


class BatchCloseView(RoleRequiredMixin, View):
    """POST /batches/<uuid>/close/ → Closes batch, shows reconciliation result."""

    allowed_roles = ["owner", "manager", "supervisor"]

    def get(self, request, pk):
        org = get_org_or_404(request)
        with set_tenant_context(org):
            try:
                batch = Batch.objects.get(id=pk)
            except Batch.DoesNotExist:
                raise Http404("Batch not found.")
        form = BatchCloseForm()
        return render(request, "flocks/_batch_close_modal.html", {"form": form, "batch": batch})

    def post(self, request, pk):
        form = BatchCloseForm(request.POST)
        org = get_org_or_404(request)
        is_htmx = request.headers.get("HX-Request") == "true"

        if form.is_valid():
            cd = form.cleaned_data
            try:
                with set_tenant_context(org):
                    batch = BatchService(org).close_batch(
                        batch_id=str(pk),
                        notes=cd.get("notes", ""),
                    )
                    reconciliation = batch.reconciliations.order_by("-date").first()
            except (BatchAlreadyClosedError, ValueError) as exc:
                form.add_error(None, str(exc))
                if is_htmx:
                    return render(
                        request,
                        "flocks/_batch_close_modal.html",
                        {"form": form, "batch_pk": pk},
                        status=422,
                    )

            if is_htmx:
                response = render(
                    request,
                    "flocks/_batch_close_result.html",
                    {"batch": batch, "reconciliation": reconciliation},
                )
                response["HX-Trigger"] = json.dumps({
                    "showToast": {"message": f'Batch "{batch.batch_name}" closed.', "type": "success"}
                })
                return response

            from django.shortcuts import redirect
            return redirect("flocks:detail", pk=pk)

        if is_htmx:
            return render(
                request,
                "flocks/_batch_close_modal.html",
                {"form": form, "batch_pk": pk},
                status=422,
            )
        return render(request, "flocks/_batch_close_modal.html", {"form": form})


class BatchMetricsCardView(LoginRequiredMixin, View):
    """GET /batches/<uuid>/metrics/ → HTMX fragment for skeleton loader pattern."""

    def get(self, request, pk):
        org = get_org_or_404(request)
        with set_tenant_context(org):
            try:
                data = BatchService(org).get_batch_dashboard_data(str(pk))
            except ValueError:
                raise Http404("Batch not found.")

        return render(request, "flocks/_batch_metrics_cards.html", data)


class LossDocumentationReportView(RoleRequiredMixin, View):
    """
    GET  /batches/<uuid>/loss-report/ → cause-of-death form modal.
    POST /batches/<uuid>/loss-report/ → generate and return the loss report PDF.

    Insurance supporting documentation — owner/manager/supervisor only.
    """

    allowed_roles = ["owner", "manager", "supervisor"]

    def get(self, request, pk):
        org = get_org_or_404(request)
        with set_tenant_context(org):
            batch = get_object_or_404(Batch, id=pk)
        form = LossDocumentationForm(
            initial={"birds_affected": batch.initial_count - batch.current_count or None}
        )
        return render(
            request,
            "flocks/_loss_report_form_modal.html",
            {"form": form, "batch": batch},
        )

    def post(self, request, pk):
        org = get_org_or_404(request)
        form = LossDocumentationForm(request.POST)

        with set_tenant_context(org):
            batch = get_object_or_404(Batch, id=pk)

            if not form.is_valid():
                return render(
                    request,
                    "flocks/_loss_report_form_modal.html",
                    {"form": form, "batch": batch},
                    status=422,
                )

            from apps.health.health.models import VaccinationSchedule
            from apps.infrastructure.core.valuation import FlockValuationService
            from apps.production.feed.models import FeedLog

            mortality_logs = list(
                MortalityLog.objects.filter(batch=batch).order_by("date")
            )
            feed_logs = list(
                FeedLog.objects.filter(batch=batch).order_by("record_date")
            )
            vaccinations = list(
                VaccinationSchedule.objects.filter(batch=batch).order_by("due_date")
            )
            valuation = FlockValuationService(batch).estimate_value()

        from apps.infrastructure.core.exports import generate_loss_documentation_pdf
        pdf_bytes = generate_loss_documentation_pdf(
            batch=batch,
            loss_details=form.cleaned_data,
            mortality_logs=mortality_logs,
            feed_logs=feed_logs,
            vaccinations=vaccinations,
            valuation=valuation,
        )

        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = (
            f'attachment; filename="Loss_Report_{batch.batch_name}_'
            f'{form.cleaned_data["incident_date"]}.pdf"'
        )
        return response


class ValuationOverrideView(RoleRequiredMixin, View):
    """GET → confirmed-price modal; POST → set or clear the batch valuation override.

    The override is the highest-priority input to FlockValuationService (beats
    market data and the admin fallback). Owner/manager only — supervisors and
    data-entry users cannot set a flock's confirmed sale value.
    """

    allowed_roles = ["owner", "manager"]

    def get(self, request, pk):
        org = get_org_or_404(request)
        with set_tenant_context(org):
            batch = get_object_or_404(Batch, id=pk)
        return render(
            request, "flocks/_valuation_override_modal.html", {"batch": batch}
        )

    def post(self, request, pk):
        from decimal import Decimal, InvalidOperation
        from django.utils import timezone

        org = get_org_or_404(request)

        from apps.infrastructure.core.helpers import write_blocked_response
        blocked = write_blocked_response(request, org)
        if blocked is not None:
            return blocked

        with set_tenant_context(org):
            batch = get_object_or_404(Batch, id=pk)
            action = request.POST.get("action", "save")

            if action == "clear":
                batch.valuation_override_per_unit = None
                batch.valuation_override_unit = None
                batch.valuation_override_set_by = None
                batch.valuation_override_set_at = None
                batch.save()
                msg = "Confirmed price cleared — reverted to market pricing."
            else:
                raw = request.POST.get("price", "").strip()
                unit = request.POST.get("unit", "")
                error = None
                price = None
                try:
                    price = Decimal(raw)
                except (InvalidOperation, ValueError):
                    error = "Enter a valid price."
                if error is None and price <= 0:
                    error = "Enter a price greater than zero."
                if error is None and unit not in ("kg", "bird"):
                    error = "Choose a unit (per kg or per bird)."

                if error:
                    return render(
                        request,
                        "flocks/_valuation_override_modal.html",
                        {"batch": batch, "error": error},
                        status=422,
                    )

                batch.valuation_override_per_unit = price
                batch.valuation_override_unit = unit
                batch.valuation_override_set_by = request.user
                batch.valuation_override_set_at = timezone.now()
                batch.save()
                msg = "Confirmed price saved."

        response = HttpResponse(status=204)
        response["HX-Trigger"] = json.dumps({
            "showToast": {"message": msg, "type": "success"},
            "close-modal": True,
        })
        response["HX-Refresh"] = "true"
        return response


# ── Export views ────────────────────────────────────────────────────────────────

class BatchPDFExportView(LoginRequiredMixin, View):
    """GET /batches/<uuid>/export/pdf/ → Plan-gated PDF download."""

    def get(self, request, pk):
        from apps.infrastructure.billing.features import has_feature
        if not has_feature(request.user.org, 'pdf_export'):
            response = HttpResponse(status=200)
            response['HX-Trigger'] = json.dumps({
                'showToast': {
                    'message': '🔒 PDF exports are available on the Monthly plan and above. Upgrade to unlock.',
                    'type': 'error',
                }
            })
            return response

        org = get_org_or_404(request)
        with set_tenant_context(org):
            batch = get_object_or_404(Batch.objects.select_related('farm', 'house'), id=pk)

        from apps.infrastructure.core.exports import generate_batch_report
        pdf_bytes = generate_batch_report(batch)

        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = (
            f'attachment; filename="batch-{batch.batch_name}.pdf"'
        )
        return response


class BatchExcelExportView(LoginRequiredMixin, View):
    """GET /batches/<uuid>/export/excel/ → Plan-gated Excel download."""

    def get(self, request, pk):
        from apps.infrastructure.billing.features import has_feature
        if not has_feature(request.user.org, 'excel_export'):
            response = HttpResponse(status=200)
            response['HX-Trigger'] = json.dumps({
                'showToast': {
                    'message': '🔒 Excel exports are available on the Monthly plan and above. Upgrade to unlock.',
                    'type': 'error',
                }
            })
            return response

        org = get_org_or_404(request)
        with set_tenant_context(org):
            batch = get_object_or_404(Batch.objects.select_related('farm', 'house'), id=pk)

        from apps.infrastructure.core.exports import generate_batch_excel
        xlsx_bytes = generate_batch_excel(batch)

        response = HttpResponse(
            xlsx_bytes,
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        response['Content-Disposition'] = (
            f'attachment; filename="batch-{batch.batch_name}.xlsx"'
        )
        return response


# ── Soft delete views ───────────────────────────────────────────────────────

class BatchDeleteView(SoftDeleteView):
    """Soft-delete a batch (owner, manager). Requires typing the batch name."""

    model = Batch
    allowed_roles = ["owner", "manager"]
    success_url = "/batches/"
    confirmation_field = "batch_name"


class MortalityLogDeleteView(SoftDeleteView):
    """Soft-delete a mortality log (owner, manager, supervisor). Simple confirm."""

    model = MortalityLog
    allowed_roles = ["owner", "manager", "supervisor"]

    def get_success_url(self, obj):
        return f"/batches/{obj.batch_id}/"


class WeightRecordDeleteView(SoftDeleteView):
    """Soft-delete a weight record (owner, manager, supervisor). Simple confirm."""

    model = WeightRecord
    allowed_roles = ["owner", "manager", "supervisor"]

    def get_success_url(self, obj):
        return f"/batches/{obj.batch_id}/"


# ── DRF API views ───────────────────────────────────────────────────────────────

class BatchListAPIView(APIView):
    """
    List and create batches for the authenticated tenant.

    GET  /api/v1/batches/  → List batches (optional ?status= filter), scoped to
                             the current organisation via RLS.
    POST /api/v1/batches/  → Create a batch for the given farm and house.
                             Triggers vaccination schedule generation automatically.
    """

    def get_permissions(self):
        # Reading the batch list is open to any authenticated tenant user;
        # creating/mutating a batch requires supervisor or above.
        if self.request.method in ("POST", "PUT", "PATCH", "DELETE"):
            return [IsAuthenticated(), IsSupervisorOrAbove()]
        return [IsAuthenticated()]

    def get(self, request):
        org = getattr(request.user, "org", None)
        if not org:
            return Response({"error": "No organisation."}, status=403)

        status_filter = request.query_params.get("status")
        with set_tenant_context(org):
            qs = Batch.objects.select_related("farm", "house")
            if status_filter:
                qs = qs.filter(status=status_filter)
            batches = list(qs)

        serializer = BatchSerializer(batches, many=True)
        return Response({"data": serializer.data})

    def post(self, request):
        org = getattr(request.user, "org", None)
        if not org:
            return Response({"error": "No organisation."}, status=403)

        serializer = BatchCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"error": {"fields": serializer.errors}}, status=400)

        cd = serializer.validated_data
        try:
            with set_tenant_context(org):
                batch = BatchService(org).create_batch(
                    farm_id=str(cd["farm_id"]),
                    house_id=str(cd["house_id"]),
                    batch_name=cd["batch_name"],
                    bird_type=cd["bird_type"],
                    placement_date=cd["placement_date"],
                    initial_count=cd["initial_count"],
                    breed_name=cd.get("breed_name", ""),
                )
        except (HouseOccupiedError, HouseCapacityExceededError) as exc:
            return Response({"error": {"detail": str(exc)}}, status=409)
        except ValueError as exc:
            return Response({"error": {"detail": str(exc)}}, status=400)

        return Response({"data": BatchSerializer(batch).data}, status=201)


class BatchDetailAPIView(APIView):
    """GET /api/v1/batches/<uuid>/ → Batch detail, scoped to the current org via RLS."""

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        org = getattr(request.user, "org", None)
        if not org:
            return Response({"error": "No organisation."}, status=403)

        with set_tenant_context(org):
            try:
                batch = Batch.objects.select_related("farm", "house").get(id=pk)
            except Batch.DoesNotExist:
                return Response({"error": "Batch not found."}, status=404)

        return Response({"data": BatchSerializer(batch).data})


class MortalityLogAPIView(APIView):
    """
    POST /api/v1/batches/<uuid>/mortality/ → Record a mortality event for the batch.
    Live-bird counts are decremented atomically and an audit log entry is written.
    """

    permission_classes = [IsAuthenticated, CanRecord]

    def post(self, request, pk):
        org = getattr(request.user, "org", None)
        if not org:
            return Response({"error": "No organisation."}, status=403)

        with set_tenant_context(org):
            try:
                Batch.objects.get(id=pk)
            except Batch.DoesNotExist:
                return Response({"error": "Batch not found."}, status=404)

        serializer = MortalityLogCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"error": {"fields": serializer.errors}}, status=400)

        cd = serializer.validated_data
        try:
            with set_tenant_context(org):
                log = BatchService(org).log_mortality(
                    batch_id=str(pk),
                    count=cd["count"],
                    cause=cd["cause"],
                    date=cd.get("date"),
                    notes=cd.get("notes", ""),
                )
        except BatchClosedError as exc:
            return Response({"error": {"detail": str(exc)}}, status=422)
        except MortalityExceedsLiveBirdsError as exc:
            return Response({"error": {"detail": str(exc)}}, status=422)

        return Response({"data": MortalityLogSerializer(log).data}, status=201)


class BatchCloseAPIView(APIView):
    """
    POST /api/v1/batches/<uuid>/close/ → Close out an active batch.
    Frees the house and finalises the batch's performance summary.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        org = getattr(request.user, "org", None)
        if not org:
            return Response({"error": "No organisation."}, status=403)

        try:
            with set_tenant_context(org):
                batch = BatchService(org).close_batch(
                    batch_id=str(pk),
                    notes=request.data.get("notes", ""),
                )
        except Batch.DoesNotExist:
            return Response({"error": "Batch not found."}, status=404)
        except BatchAlreadyClosedError as exc:
            return Response({"error": {"detail": str(exc)}}, status=422)
        except ValueError as exc:
            return Response({"error": {"detail": str(exc)}}, status=404)

        return Response({"data": BatchSerializer(batch).data})
