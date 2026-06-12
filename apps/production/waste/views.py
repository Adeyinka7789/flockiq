import json

import structlog
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import render
from django.views import View

from apps.infrastructure.core.helpers import get_org_or_404
from apps.infrastructure.core.mixins import RoleRequiredMixin
from apps.infrastructure.core.rls import set_tenant_context

from .services import WasteService

logger = structlog.get_logger(__name__)


class WasteLogView(RoleRequiredMixin, View):
    """POST /production/waste/<farm_pk>/log/ → Returns updated waste table.

    Recording production data — vet_advisor (read-only) is excluded.
    """

    allowed_roles = ["owner", "manager", "supervisor", "data_entry"]

    def post(self, request, farm_pk):
        from .forms import WasteLogForm

        form = WasteLogForm(request.POST)
        org = get_org_or_404(request)

        if form.is_valid():
            cd = form.cleaned_data
            try:
                with set_tenant_context(org):
                    svc = WasteService(org)
                    svc.log_waste(
                        farm_id=str(farm_pk),
                        record_date=cd["record_date"],
                        waste_type=cd["waste_type"],
                        quantity_kg=cd["quantity_kg"],
                        disposal_method=cd["disposal_method"],
                        cost=cd.get("cost"),
                        notes=cd.get("notes", ""),
                    )
                    summary = svc.get_waste_summary(str(farm_pk))
            except ValueError as exc:
                form.add_error(None, str(exc))
                return render(
                    request,
                    "production/waste/_waste_log_form.html",
                    {"form": form, "farm_pk": farm_pk},
                    status=422,
                )

            response = render(
                request,
                "production/waste/_waste_table.html",
                {**summary, "farm_pk": farm_pk},
            )
            response["HX-Trigger"] = json.dumps(
                {"showToast": {"message": "Waste logged.", "type": "success"}}
            )
            return response

        return render(
            request,
            "production/waste/_waste_log_form.html",
            {"form": form, "farm_pk": farm_pk},
            status=422,
        )


class WasteTableView(LoginRequiredMixin, View):
    """GET /production/waste/<farm_pk>/table/ → Returns waste table partial."""

    def get(self, request, farm_pk):
        from .models import WasteLog

        org = get_org_or_404(request)
        page = int(request.GET.get("page", 1))

        with set_tenant_context(org):
            from django.core.paginator import Paginator
            qs = (
                WasteLog.objects
                .filter(farm_id=farm_pk)
                .order_by("-record_date")
            )
            page_obj = Paginator(qs, 20).get_page(page)

        return render(
            request,
            "production/waste/_waste_table.html",
            {"page_obj": page_obj, "farm_pk": farm_pk},
        )
