import json

import structlog
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views import View
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

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


def _get_org(request):
    """Returns the org from the authenticated user. Raises Http404 if none."""
    org = getattr(request.user, "org", None)
    if org is None:
        raise Http404("No organization found for this user.")
    return org


# ── HTMX views ────────────────────────────────────────────────────────────────

class FarmListView(LoginRequiredMixin, View):
    """
    GET  /farms/      → Full farm list page (or HTMX partial if HX-Request).
    """

    def get(self, request):
        org = _get_org(request)
        is_htmx = request.headers.get("HX-Request") == "true"

        with set_tenant_context(org):
            service = FarmService(org)
            farms = list(service.list_farms(active_only=True))
            dashboard = service.get_dashboard_data()

        context = {
            "farms": farms,
            "dashboard": dashboard,
            "form": FarmCreateForm(),
        }

        if is_htmx:
            return render(request, "farms/_farm_list_partial.html", context)
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
        org = _get_org(request)
        is_htmx = request.headers.get("HX-Request") == "true"

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
                response = render(request, "farms/_farm_card.html", {"farm": farm})
                response["HX-Trigger"] = json.dumps({
                    "showToast": {
                        "message": f'Farm "{farm.name}" created successfully.',
                        "type": "success",
                    }
                })
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


class FarmDetailView(LoginRequiredMixin, View):
    """GET /farms/<uuid>/  → Farm detail page with houses."""

    def get(self, request, pk):
        org = _get_org(request)
        with set_tenant_context(org):
            try:
                detail = FarmService(org).get_farm_detail(str(pk))
            except Farm.DoesNotExist:
                raise Http404("Farm not found.")

        return render(request, "farms/farm_detail.html", detail)


class HouseCreateView(LoginRequiredMixin, View):
    """POST /farms/<uuid>/houses/create/ → Creates a house; returns updated houses partial."""

    def get(self, request, pk):
        form = HouseCreateForm()
        return render(request, "farms/_house_create_modal.html", {"form": form, "farm_id": pk})

    def post(self, request, pk):
        form = HouseCreateForm(request.POST)
        org = _get_org(request)
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
                response = render(
                    request,
                    "farms/_house_list_partial.html",
                    {"houses": houses, "farm_id": pk},
                )
                response["HX-Trigger"] = json.dumps({
                    "showToast": {"message": f'House "{house.name}" added.', "type": "success"}
                })
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
        org = _get_org(request)
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
