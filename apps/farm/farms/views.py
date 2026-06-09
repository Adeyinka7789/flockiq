import json

import structlog
from django.contrib.auth.mixins import LoginRequiredMixin
from apps.infrastructure.core.views import TenantRequiredMixin
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views import View
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.infrastructure.core.helpers import get_org_or_404
from apps.infrastructure.core.rls import set_tenant_context

from .forms import FarmCreateForm, HouseCreateForm
from .models import Farm, House
from .serializers import (
    FarmCreateSerializer,
    FarmSerializer,
    FarmSummarySerializer,
    HouseCreateSerializer,
)
from .services import FarmService

logger = structlog.get_logger(__name__)




# ── HTMX views ────────────────────────────────────────────────────────────────

class FarmListView(TenantRequiredMixin, View):
    """
    GET  /farms/      → Full farm list page (or HTMX partial if HX-Request).
    """

    def get(self, request):
        from datetime import date, timedelta

        from django.db.models import Count, Q, Sum

        from apps.farm.flocks.models import MortalityLog

        org = get_org_or_404(request)
        is_htmx = request.headers.get("HX-Request") == "true"

        search_query = request.GET.get("q", "").strip()
        active_farm_type = request.GET.get("farm_type", "").strip()

        with set_tenant_context(org):
            farms = Farm.objects.filter(is_active=True)

            if search_query:
                farms = farms.filter(
                    Q(name__icontains=search_query)
                    | Q(location__icontains=search_query)
                )
            if active_farm_type:
                farms = farms.filter(farm_type=active_farm_type)

            farms = farms.annotate(
                live_birds=Sum(
                    "batches__current_count",
                    filter=Q(batches__status="active"),
                ),
                active_batches=Count(
                    "batches",
                    filter=Q(batches__status="active"),
                ),
                house_count=Count("houses", distinct=True),
                total_capacity=Sum("houses__capacity"),
            ).order_by("-created_at")

            farm_list = []
            today = date.today()
            last_30 = today - timedelta(days=30)

            for farm in farms:
                weekly_mort = []
                for i in range(6, -1, -1):
                    day = today - timedelta(days=i)
                    cnt = MortalityLog.objects.filter(
                        farm=farm, date=day
                    ).aggregate(total=Sum("count"))["total"] or 0
                    weekly_mort.append(cnt)

                total_mort = MortalityLog.objects.filter(
                    farm=farm, date__gte=last_30
                ).aggregate(total=Sum("count"))["total"] or 0

                live = farm.live_birds or 0
                mort_rate = round((total_mort / max(live, 1)) * 100, 1) if live > 0 else 0

                if mort_rate > 5:
                    status, status_label = "critical", "NEEDS REVIEW"
                elif mort_rate > 2:
                    status, status_label = "warning", "MONITOR"
                elif live > 0:
                    status, status_label = "optimal", "OPTIMAL"
                else:
                    status, status_label = "new", "NEW ENTRY"

                farm_list.append({
                    "farm": farm,
                    "live_birds": live,
                    "active_batches": farm.active_batches or 0,
                    "house_count": farm.house_count or 0,
                    "total_capacity": farm.total_capacity or 0,
                    "weekly_mort": weekly_mort,
                    "max_weekly_mort": max(weekly_mort) if any(weekly_mort) else 1,
                    "mort_rate": mort_rate,
                    "status": status,
                    "status_label": status_label,
                })

            total_live = sum(f["live_birds"] for f in farm_list)
            total_capacity = sum(f["total_capacity"] for f in farm_list)

        context = {
            "farm_list": farm_list,
            "total_live": total_live,
            "total_capacity": total_capacity,
            "total_farms": len(farm_list),
            "org": org,
            "form": FarmCreateForm(),
            "search_query": search_query,
            "active_farm_type": active_farm_type,
            "farm_type_choices": Farm.FarmType.choices,
        }

        if is_htmx:
            return render(request, "farms/_farm_grid.html", context)
        return render(request, "farms/farm_list.html", context)


class FarmCreateView(LoginRequiredMixin, View):
    """
    GET  /farms/create/  → Returns modal form fragment (HTMX only).
    POST /farms/create/  → Creates farm; returns card fragment + toast trigger.
    """

    def get(self, request):
        form = FarmCreateForm()
        return render(request, "farms/_farm_create_modal.html", {"form": form})

    def post(self, request):
        form = FarmCreateForm(request.POST)
        org = get_org_or_404(request)
        is_htmx = request.headers.get("HX-Request") == "true"

        from apps.infrastructure.billing.features import get_plan_features
        features = get_plan_features(org.plan_tier)
        with set_tenant_context(org):
            current_farms = Farm.objects.filter(is_active=True).count()
        if current_farms >= features['max_farms']:
            response = HttpResponse(status=403)
            response['HX-Trigger'] = json.dumps({
                'showToast': {
                    'message': (
                        f'Your {org.plan_tier} plan allows {features["max_farms"]} farm(s). '
                        f'Upgrade to add more.'
                    ),
                    'type': 'error',
                }
            })
            return response

        if form.is_valid():
            cd = form.cleaned_data
            with set_tenant_context(org):
                farm = FarmService(org).create_farm(
                    name=cd["name"],
                    location=cd["location"],
                    lat=cd["latitude"],
                    lng=cd["longitude"],
                    farm_type=cd["farm_type"],
                )

            if is_htmx:
                response = HttpResponse(status=204)
                response["HX-Trigger"] = json.dumps({
                    "showToast": {
                        "message": f'Farm "{farm.name}" created successfully.',
                        "type": "success",
                    },
                    "close-modal": True,
                })
                response["HX-Refresh"] = "true"
                return response

            from django.shortcuts import redirect
            return redirect("farms:list")

        # Form invalid
        if is_htmx:
            return render(
                request,
                "farms/_farm_create_modal.html",
                {"form": form},
                status=422,
            )
        return render(request, "farms/farm_list.html", {"form": form})


class FarmDetailView(TenantRequiredMixin, View):
    """GET /farms/<uuid>/  → Farm detail dashboard."""

    def get(self, request, pk):
        from datetime import date, timedelta

        from django.db.models import Count, Q, Sum

        from apps.farm.flocks.models import Batch, MortalityLog
        from apps.health.health.models import VaccinationSchedule
        from apps.infrastructure.notifications.models import NotificationLog
        from apps.production.production.models import EggProductionLog

        org = get_org_or_404(request)

        with set_tenant_context(org):
            try:
                farm = Farm.objects.get(id=pk, org_id=org.id)
            except Farm.DoesNotExist:
                raise Http404("Farm not found.")

            houses = list(
                House.objects.filter(farm=farm, is_active=True).annotate(
                    active_batch_count=Count(
                        "batches", filter=Q(batches__status="active")
                    )
                )
            )

            active_batches = list(
                Batch.objects.filter(farm=farm, status="active").select_related("house")
            )

            total_live = sum(b.current_count for b in active_batches)
            total_capacity = sum(h.capacity for h in houses)

            today = date.today()
            last_30 = today - timedelta(days=30)

            todays_eggs = EggProductionLog.objects.filter(
                farm=farm, record_date=today
            ).aggregate(total=Sum("total_eggs"))["total"] or 0

            total_mort_30 = MortalityLog.objects.filter(
                farm=farm, date__gte=last_30
            ).aggregate(total=Sum("count"))["total"] or 0

            avg_mort_rate = (
                round((total_mort_30 / max(total_live * 30, 1)) * 100, 2)
                if total_live > 0
                else 0
            )

            current_week = []
            prev_week = []
            for i in range(6, -1, -1):
                day = today - timedelta(days=i)
                curr = MortalityLog.objects.filter(
                    farm=farm, date=day
                ).aggregate(total=Sum("count"))["total"] or 0
                prev = MortalityLog.objects.filter(
                    farm=farm, date=day - timedelta(days=7)
                ).aggregate(total=Sum("count"))["total"] or 0
                current_week.append({"day": day.strftime("%a").upper(), "count": curr})
                prev_week.append(prev)

            health_score = 100
            if avg_mort_rate > 5:
                health_score -= 40
            elif avg_mort_rate > 3:
                health_score -= 20
            elif avg_mort_rate > 1:
                health_score -= 10

            total_vacc = VaccinationSchedule.objects.filter(batch__farm=farm).count()
            completed_vacc = VaccinationSchedule.objects.filter(
                batch__farm=farm, status="completed"
            ).count()
            vacc_compliance = round(completed_vacc / total_vacc * 100) if total_vacc > 0 else 100

            critical_alerts = list(
                NotificationLog.objects.filter(
                    org=org, severity__in=["critical", "warning"], is_read=False
                ).order_by("-created_at")[:3]
            )

            layer_count = sum(
                b.current_count for b in active_batches if b.bird_type == "layer"
            )
            broiler_count = sum(
                b.current_count for b in active_batches if b.bird_type == "broiler"
            )

        context = {
            "farm": farm,
            "houses": houses,
            "active_batches": active_batches,
            "total_live": total_live,
            "total_capacity": total_capacity,
            "todays_eggs": todays_eggs,
            "avg_mort_rate": avg_mort_rate,
            "health_score": health_score,
            "vacc_compliance": vacc_compliance,
            "critical_alerts": critical_alerts,
            "current_week": current_week,
            "prev_week": prev_week,
            "layer_count": layer_count,
            "broiler_count": broiler_count,
            "today": today,
        }

        return render(request, "farms/farm_detail.html", context)


class HouseCreateView(LoginRequiredMixin, View):
    """POST /farms/<uuid>/houses/create/ → Creates a house; returns updated houses partial."""

    def get(self, request, pk):
        form = HouseCreateForm()
        return render(request, "farms/_house_create_modal.html", {"form": form, "farm_id": pk})

    def post(self, request, pk):
        form = HouseCreateForm(request.POST)
        org = get_org_or_404(request)
        is_htmx = request.headers.get("HX-Request") == "true"

        if form.is_valid():
            cd = form.cleaned_data
            with set_tenant_context(org):
                try:
                    house = FarmService(org).create_house(
                        farm_id=str(pk),
                        name=cd["name"],
                        capacity=cd["capacity"],
                        house_type=cd["house_type"],
                    )
                    houses = list(
                        House.objects.filter(farm_id=pk, is_active=True).order_by("name")
                    )
                except Farm.DoesNotExist:
                    raise Http404("Farm not found.")

            if is_htmx:
                response = HttpResponse(status=204)
                response["HX-Trigger"] = json.dumps({
                    "showToast": {"message": f'House "{house.name}" added.', "type": "success"},
                    "close-modal": True,
                })
                response["HX-Refresh"] = "true"
                return response

            from django.shortcuts import redirect
            return redirect("farms:detail", pk=pk)

        if is_htmx:
            return render(
                request,
                "farms/_house_create_modal.html",
                {"form": form, "farm_id": pk},
                status=422,
            )
        return render(request, "farms/farm_detail.html", {"form": form})


class FarmSummaryCardView(LoginRequiredMixin, View):
    """GET /farms/<uuid>/summary-card/  → HTMX fragment for dashboard lazy loading."""

    def get(self, request, pk):
        org = get_org_or_404(request)
        with set_tenant_context(org):
            try:
                summary = FarmService(org).get_farm_summary(str(pk))
            except Farm.DoesNotExist:
                raise Http404("Farm not found.")

        return render(request, "farms/_farm_summary_card.html", summary)


# ── DRF API views ──────────────────────────────────────────────────────────────

class FarmListAPIView(APIView):
    """
    GET  /api/v1/farms/  → List farms for the authenticated org.
    POST /api/v1/farms/  → Create a farm.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        org = getattr(request.user, "org", None)
        if not org:
            return Response({"error": "No organization."}, status=403)

        with set_tenant_context(org):
            farms = list(FarmService(org).list_farms(active_only=False))

        serializer = FarmSummarySerializer(farms, many=True)
        return Response({"data": serializer.data})

    def post(self, request):
        org = getattr(request.user, "org", None)
        if not org:
            return Response({"error": "No organization."}, status=403)

        serializer = FarmCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"error": {"fields": serializer.errors}}, status=400)

        cd = serializer.validated_data
        with set_tenant_context(org):
            farm = FarmService(org).create_farm(
                name=cd["name"],
                location=cd["location"],
                lat=cd["latitude"],
                lng=cd["longitude"],
                farm_type=cd.get("farm_type", "mixed"),
            )

        return Response({"data": FarmSerializer(farm).data}, status=201)


class FarmDetailAPIView(APIView):
    """
    GET /api/v1/farms/<uuid>/  → Farm detail with houses.
    PUT /api/v1/farms/<uuid>/  → Update a farm.
    """

    permission_classes = [IsAuthenticated]

    def _get_farm(self, request, pk):
        org = getattr(request.user, "org", None)
        if not org:
            return None, None, Response({"error": "No organization."}, status=403)

        with set_tenant_context(org):
            try:
                farm = Farm.objects.get(id=pk)
            except Farm.DoesNotExist:
                return None, org, Response({"error": "Farm not found."}, status=404)

        return farm, org, None

    def get(self, request, pk):
        farm, org, err = self._get_farm(request, pk)
        if err:
            return err

        with set_tenant_context(org):
            serializer = FarmSerializer(farm)
            data = serializer.data

        return Response({"data": data})

    def put(self, request, pk):
        farm, org, err = self._get_farm(request, pk)
        if err:
            return err

        allowed = {"name", "location", "latitude", "longitude", "farm_type", "is_active", "notes"}
        kwargs = {k: v for k, v in request.data.items() if k in allowed}

        with set_tenant_context(org):
            farm = FarmService(org).update_farm(str(pk), **kwargs)
            serializer = FarmSerializer(farm)
            data = serializer.data

        return Response({"data": data})


class FarmDashboardAPIView(APIView):
    """GET /api/v1/farms/<uuid>/dashboard/  → Per-farm dashboard summary."""

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        org = getattr(request.user, "org", None)
        if not org:
            return Response({"error": "No organization."}, status=403)

        with set_tenant_context(org):
            try:
                summary = FarmService(org).get_farm_summary(str(pk))
            except Farm.DoesNotExist:
                return Response({"error": "Farm not found."}, status=404)

        return Response({
            "data": {
                "farm_id": str(pk),
                "farm_name": summary["farm"].name,
                "total_live_birds": summary["total_live_birds"],
                "active_batches": summary["active_batches"],
                "total_capacity": summary["total_capacity"],
                "occupancy_pct": summary["occupancy_pct"],
                "houses": [
                    {
                        "id": str(h["house"].id),
                        "name": h["house"].name,
                        "capacity": h["house"].capacity,
                        "current_occupancy": h["current_occupancy"],
                        "occupancy_pct": h["occupancy_pct"],
                    }
                    for h in summary["houses"]
                ],
            }
        })
