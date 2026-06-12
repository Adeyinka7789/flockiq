import json

import structlog
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views import View

from apps.infrastructure.core.delete_views import SoftDeleteView
from apps.infrastructure.core.helpers import get_org_or_404
from apps.infrastructure.core.mixins import RoleRequiredMixin
from apps.infrastructure.core.rls import set_tenant_context

from .models import WaterLog
from .services import WaterService

logger = structlog.get_logger(__name__)


class WaterLogDeleteView(SoftDeleteView):
    """Soft-delete a water log (owner, manager, supervisor). Simple confirm."""

    model = WaterLog
    allowed_roles = ["owner", "manager", "supervisor"]

    def get_success_url(self, obj):
        return f"/batches/{obj.batch_id}/"


class WaterLogView(RoleRequiredMixin, View):
    """GET/POST /production/water/<batch_pk>/log/ → Modal form or log water.

    Recording production data — vet_advisor (read-only) is excluded.
    """

    allowed_roles = ["owner", "manager", "supervisor", "data_entry"]

    def get(self, request, batch_pk):
        from datetime import date
        from .forms import WaterLogForm
        from apps.farm.flocks.models import Batch

        org = get_org_or_404(request)
        with set_tenant_context(org):
            batch = get_object_or_404(Batch, pk=batch_pk)
        return render(request, "production/water/_water_log_form.html", {
            "form": WaterLogForm(),
            "batch": batch,
            "today": date.today(),
        })

    def post(self, request, batch_pk):
        from datetime import date
        from .forms import WaterLogForm
        from apps.farm.flocks.models import Batch

        form = WaterLogForm(request.POST)
        org = get_org_or_404(request)

        from apps.infrastructure.core.helpers import write_blocked_response
        blocked = write_blocked_response(request, org)
        if blocked is not None:
            return blocked

        def _error(f, status=422):
            with set_tenant_context(org):
                batch = get_object_or_404(Batch, pk=batch_pk)
            return render(request, "production/water/_water_log_form.html",
                {"form": f, "batch": batch, "today": date.today()}, status=status)

        if form.is_valid():
            cd = form.cleaned_data
            try:
                with set_tenant_context(org):
                    WaterService(org).log_water(
                        batch_id=str(batch_pk),
                        record_date=cd["record_date"],
                        litres_consumed=cd["litres_consumed"],
                        notes=cd.get("notes", ""),
                        recorded_by=request.user,
                    )
            except ValueError as exc:
                form.add_error(None, str(exc))
                return _error(form)

            response = HttpResponse('')
            response["HX-Trigger"] = json.dumps({
                "showToast": {"message": "Water logged.", "type": "success"},
                "close-modal": True,
                "waterLogged": True,
            })
            return response

        return _error(form)


class WaterTableView(LoginRequiredMixin, View):
    """GET /production/water/<batch_pk>/table/ → Returns water table partial."""

    def get(self, request, batch_pk):
        from .models import WaterLog

        org = get_org_or_404(request)
        page = int(request.GET.get("page", 1))

        with set_tenant_context(org):
            from django.core.paginator import Paginator
            qs = (
                WaterLog.objects
                .filter(batch_id=batch_pk)
                .select_related("recorded_by")
                .order_by("-record_date")
            )
            page_obj = Paginator(qs, 20).get_page(page)

        return render(
            request,
            "production/water/_water_table.html",
            {"page_obj": page_obj, "batch_pk": batch_pk},
        )


class WaterSummaryCardView(LoginRequiredMixin, View):
    """GET /production/water/<batch_pk>/summary/ → Returns summary card fragment."""

    def get(self, request, batch_pk):
        org = get_org_or_404(request)

        with set_tenant_context(org):
            summary = WaterService(org).get_water_summary(str(batch_pk))

        return render(
            request,
            "production/water/_water_summary_card.html",
            {**summary, "batch_pk": batch_pk},
        )
