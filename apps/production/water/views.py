import json

import structlog
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404
from django.shortcuts import render
from django.views import View

from apps.infrastructure.core.rls import set_tenant_context

from .services import WaterService

logger = structlog.get_logger(__name__)


def _get_org(request):
    org = getattr(request.user, "org", None)
    if org is None:
        raise Http404("No organisation found for this user.")
    return org


class WaterLogView(LoginRequiredMixin, View):
    """POST /production/water/<batch_pk>/log/ → Returns updated water summary card."""

    def post(self, request, batch_pk):
        from .forms import WaterLogForm

        form = WaterLogForm(request.POST)
        org = _get_org(request)

        if form.is_valid():
            cd = form.cleaned_data
            try:
                with set_tenant_context(org):
                    svc = WaterService(org)
                    svc.log_water(
                        batch_id=str(batch_pk),
                        record_date=cd["record_date"],
                        litres_consumed=cd["litres_consumed"],
                        notes=cd.get("notes", ""),
                        recorded_by=request.user,
                    )
                    summary = svc.get_water_summary(str(batch_pk))
            except ValueError as exc:
                form.add_error(None, str(exc))
                return render(
                    request,
                    "production/water/_water_log_form.html",
                    {"form": form, "batch_pk": batch_pk},
                    status=422,
                )

            response = render(
                request,
                "production/water/_water_summary_card.html",
                {**summary, "batch_pk": batch_pk},
            )
            response["HX-Trigger"] = json.dumps(
                {"showToast": {"message": "Water logged.", "type": "success"}}
            )
            return response

        return render(
            request,
            "production/water/_water_log_form.html",
            {"form": form, "batch_pk": batch_pk},
            status=422,
        )


class WaterTableView(LoginRequiredMixin, View):
    """GET /production/water/<batch_pk>/table/ → Returns water table partial."""

    def get(self, request, batch_pk):
        from .models import WaterLog

        org = _get_org(request)
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
        org = _get_org(request)

        with set_tenant_context(org):
            summary = WaterService(org).get_water_summary(str(batch_pk))

        return render(
            request,
            "production/water/_water_summary_card.html",
            {**summary, "batch_pk": batch_pk},
        )
