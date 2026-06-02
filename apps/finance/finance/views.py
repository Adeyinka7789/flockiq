import datetime

import structlog
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404
from django.shortcuts import render
from django.views import View
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.infrastructure.core.rls import set_tenant_context

from .services import FinanceService

logger = structlog.get_logger(__name__)


def _get_org(request):
    org = getattr(request.user, "org", None)
    if org is None:
        raise Http404("No organisation found for this user.")
    return org


class PLSummaryView(LoginRequiredMixin, View):
    """GET /finance/pl/<uuid:batch_pk>/"""

    def get(self, request, batch_pk):
        org = _get_org(request)
        with set_tenant_context(org):
            try:
                summary = FinanceService(org).get_pl_summary(str(batch_pk))
            except ValueError as exc:
                raise Http404(str(exc))
        return render(request, "finance/_pl_summary_card.html", {"summary": summary, "batch_pk": batch_pk})


class SaleLogView(LoginRequiredMixin, View):
    """GET+POST /finance/sales/<uuid:batch_pk>/log/"""

    def get(self, request, batch_pk):
        import datetime
        from apps.farm.flocks.models import Batch
        from django.shortcuts import get_object_or_404
        from .models import SalesRecord

        org = _get_org(request)
        with set_tenant_context(org):
            batch = get_object_or_404(Batch, pk=batch_pk, org=org)
        return render(request, "finance/_sale_log_form.html", {
            "batch": batch,
            "batch_pk": batch_pk,
            "today": datetime.date.today(),
            "product_types": SalesRecord.PRODUCT_TYPE_CHOICES,
            "units": SalesRecord.UNIT_CHOICES,
        })

    def post(self, request, batch_pk):
        from .models import SalesRecord

        org = _get_org(request)
        data = request.POST

        def _error(msg, status=422):
            return render(request, "finance/_sale_log_form.html", {
                "error": msg,
                "batch_pk": batch_pk,
                "today": datetime.date.today(),
                "product_types": SalesRecord.PRODUCT_TYPE_CHOICES,
                "units": SalesRecord.UNIT_CHOICES,
            }, status=status)

        for field in ["product_type", "quantity", "unit", "unit_price"]:
            if not data.get(field):
                return _error(f"{field} is required.")

        try:
            quantity = float(data["quantity"])
            unit_price_kobo = int(float(data["unit_price"]) * 100)
        except (ValueError, TypeError):
            return _error("Invalid quantity or price.")

        sale_date_str = data.get("sale_date")
        sale_date = datetime.date.today()
        if sale_date_str:
            try:
                sale_date = datetime.date.fromisoformat(sale_date_str)
            except ValueError:
                pass

        with set_tenant_context(org):
            try:
                record = FinanceService(org).record_sale(
                    batch_id=str(batch_pk),
                    sale_date=sale_date,
                    product_type=data["product_type"],
                    quantity=quantity,
                    unit=data["unit"],
                    unit_price_kobo=unit_price_kobo,
                    buyer_name=data.get("buyer_name", ""),
                    notes=data.get("notes", ""),
                    recorded_by=request.user,
                )
            except ValueError as exc:
                return _error(str(exc))

        response = render(
            request,
            "finance/_sale_log_form.html",
            {"success": True, "record": record, "batch_pk": batch_pk},
        )
        response["HX-Trigger"] = '{"saleAdded": true}'
        return response


class SaleTableView(LoginRequiredMixin, View):
    """GET /finance/sales/<uuid:batch_pk>/table/"""

    def get(self, request, batch_pk):
        org = _get_org(request)
        with set_tenant_context(org):
            from .models import SalesRecord
            sales = SalesRecord.objects.filter(
                batch_id=batch_pk, org=org
            ).order_by("-sale_date")
        return render(request, "finance/_sale_table.html", {"sales": sales, "batch_pk": batch_pk})


class BreakEvenView(LoginRequiredMixin, View):
    """GET /finance/breakeven/<uuid:batch_pk>/"""

    def get(self, request, batch_pk):
        org = _get_org(request)
        with set_tenant_context(org):
            try:
                data = FinanceService(org).calculate_break_even(str(batch_pk))
            except ValueError as exc:
                raise Http404(str(exc))
        return render(request, "finance/_break_even_widget.html", {"data": data, "batch_pk": batch_pk})


class ROICalculatorView(LoginRequiredMixin, View):
    """GET /finance/roi/<uuid:batch_pk>/"""

    def get(self, request, batch_pk):
        org = _get_org(request)
        with set_tenant_context(org):
            try:
                data = FinanceService(org).get_roi_calculator_data(str(batch_pk))
            except ValueError as exc:
                raise Http404(str(exc))
        return render(request, "finance/_roi_calculator.html", {"data": data, "batch_pk": batch_pk})


class FinanceSummaryAPIView(APIView):
    """GET /api/v1/finance/summary/"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        org = _get_org(request)
        batch_id = request.query_params.get("batch_id")
        if not batch_id:
            return Response({"error": "batch_id is required"}, status=400)
        with set_tenant_context(org):
            try:
                summary = FinanceService(org).get_pl_summary(batch_id)
            except ValueError as exc:
                return Response({"error": str(exc)}, status=404)
        return Response({"data": summary})


class SalesAPIView(APIView):
    """GET+POST /api/v1/finance/sales/"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        org = _get_org(request)
        batch_id = request.query_params.get("batch_id")
        with set_tenant_context(org):
            from .models import SalesRecord
            qs = SalesRecord.objects.filter(org=org)
            if batch_id:
                qs = qs.filter(batch_id=batch_id)
            data = [
                {
                    "id": str(s.id),
                    "sale_date": s.sale_date.isoformat(),
                    "product_type": s.product_type,
                    "quantity": float(s.quantity),
                    "unit": s.unit,
                    "unit_price_naira": s.unit_price_naira,
                    "total_revenue_naira": s.total_revenue_naira,
                    "buyer_name": s.buyer_name,
                }
                for s in qs.order_by("-sale_date")
            ]
        return Response({"data": data})

    def post(self, request):
        org = _get_org(request)
        d = request.data
        try:
            unit_price_kobo = int(float(d.get("unit_price_naira", 0)) * 100)
            with set_tenant_context(org):
                record = FinanceService(org).record_sale(
                    batch_id=d.get("batch_id", ""),
                    sale_date=datetime.date.fromisoformat(d.get("sale_date", datetime.date.today().isoformat())),
                    product_type=d.get("product_type", ""),
                    quantity=float(d.get("quantity", 0)),
                    unit=d.get("unit", "birds"),
                    unit_price_kobo=unit_price_kobo,
                    buyer_name=d.get("buyer_name", ""),
                    notes=d.get("notes", ""),
                    recorded_by=request.user,
                )
        except (ValueError, KeyError) as exc:
            return Response({"error": str(exc)}, status=400)
        return Response({"id": str(record.id), "total_revenue_naira": record.total_revenue_naira}, status=201)


class BreakEvenAPIView(APIView):
    """GET /api/v1/finance/breakeven/<uuid:batch_pk>/"""

    permission_classes = [IsAuthenticated]

    def get(self, request, batch_pk):
        org = _get_org(request)
        with set_tenant_context(org):
            try:
                data = FinanceService(org).calculate_break_even(str(batch_pk))
            except ValueError as exc:
                return Response({"error": str(exc)}, status=404)
        return Response({"data": data})
