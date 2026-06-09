import datetime
import json

import structlog
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404
from django.shortcuts import render
from django.views import View
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.infrastructure.core.helpers import get_org_or_404
from apps.infrastructure.core.rls import set_tenant_context

from .services import FinanceService

logger = structlog.get_logger(__name__)


class PLSummaryView(LoginRequiredMixin, View):
    """GET /finance/pl/<uuid:batch_pk>/"""

    def get(self, request, batch_pk):
        org = get_org_or_404(request)
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

        org = get_org_or_404(request)
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

        org = get_org_or_404(request)
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
        response["HX-Trigger"] = json.dumps({
            "saleAdded": True,
            "close-modal": True,
            "showToast": {"message": "Sale recorded.", "type": "success"},
        })
        return response


class SaleTableView(LoginRequiredMixin, View):
    """GET /finance/sales/<uuid:batch_pk>/table/"""

    def get(self, request, batch_pk):
        org = get_org_or_404(request)
        with set_tenant_context(org):
            from .models import SalesRecord
            sales = SalesRecord.objects.filter(
                batch_id=batch_pk, org=org
            ).order_by("-sale_date")
        return render(request, "finance/_sale_table.html", {"sales": sales, "batch_pk": batch_pk})


class BreakEvenView(LoginRequiredMixin, View):
    """GET /finance/breakeven/<uuid:batch_pk>/"""

    def get(self, request, batch_pk):
        org = get_org_or_404(request)
        with set_tenant_context(org):
            try:
                data = FinanceService(org).calculate_break_even(str(batch_pk))
            except ValueError as exc:
                raise Http404(str(exc))
        return render(request, "finance/_break_even_widget.html", {"data": data, "batch_pk": batch_pk})


class ROICalculatorView(LoginRequiredMixin, View):
    """GET /finance/roi/<uuid:batch_pk>/"""

    def get(self, request, batch_pk):
        org = get_org_or_404(request)
        with set_tenant_context(org):
            try:
                data = FinanceService(org).get_roi_calculator_data(str(batch_pk))
            except ValueError as exc:
                raise Http404(str(exc))
        return render(request, "finance/_roi_calculator.html", {"data": data, "batch_pk": batch_pk})


class ROIReportView(LoginRequiredMixin, View):
    """GET /finance/roi/ — full-page FlockIQ value delivery report."""

    def get(self, request):
        from apps.farm.flocks.models import Batch
        from apps.infrastructure.billing.features import has_feature
        from .roi_service import ROICalculatorService

        org = get_org_or_404(request)

        with set_tenant_context(org):
            batches = list(
                Batch.objects.filter(org=org)
                .select_related("farm")
                .order_by("-placement_date")
            )

        selected_batch = None
        batch_pk = request.GET.get("batch")
        if batch_pk:
            selected_batch = next(
                (b for b in batches if str(b.pk) == batch_pk), None
            )
        if selected_batch is None and batches:
            selected_batch = batches[0]

        feature_locked = not has_feature(org, "roi_calculator")

        roi_data = {}
        if not feature_locked and selected_batch is not None:
            with set_tenant_context(org):
                roi_data = ROICalculatorService(org, selected_batch).calculate()
        elif feature_locked:
            roi_data = {"has_data": False}

        if request.headers.get("HX-Request"):
            return render(request, "finance/_roi_report.html", {
                "feature_locked": feature_locked,
                "roi_data": roi_data,
                "selected_batch": selected_batch,
            })

        return render(request, "finance/roi_report.html", {
            "batches": batches,
            "selected_batch": selected_batch,
            "feature_locked": feature_locked,
            "roi_data": roi_data,
        })


class ROIReportBatchView(LoginRequiredMixin, View):
    """GET /finance/roi/batch/<uuid:batch_pk>/ — HTMX partial for batch switching."""

    def get(self, request, batch_pk):
        from apps.farm.flocks.models import Batch
        from apps.infrastructure.billing.features import has_feature
        from .roi_service import ROICalculatorService
        from django.shortcuts import get_object_or_404

        org = get_org_or_404(request)
        feature_locked = not has_feature(org, "roi_calculator")

        roi_data = {"has_data": False}
        selected_batch = None

        if not feature_locked:
            with set_tenant_context(org):
                selected_batch = get_object_or_404(Batch, pk=batch_pk, org=org)
                roi_data = ROICalculatorService(org, selected_batch).calculate()

        return render(request, "finance/_roi_report.html", {
            "feature_locked": feature_locked,
            "roi_data": roi_data,
            "selected_batch": selected_batch,
        })


class FinanceSummaryAPIView(APIView):
    """GET /api/v1/finance/summary/"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        org = get_org_or_404(request)
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
        org = get_org_or_404(request)
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
        org = get_org_or_404(request)
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
        org = get_org_or_404(request)
        with set_tenant_context(org):
            try:
                data = FinanceService(org).calculate_break_even(str(batch_pk))
            except ValueError as exc:
                return Response({"error": str(exc)}, status=404)
        return Response({"data": data})


class CreditScoreDetailView(LoginRequiredMixin, View):
    """GET /finance/credit-score/"""

    def get(self, request):
        import json

        from apps.finance.finance.models import FarmCreditScore
        from apps.infrastructure.core.credit_scoring import CreditScoringService

        org = get_org_or_404(request)
        with set_tenant_context(org):
            credit_score = CreditScoringService.get_latest(org)
            history = list(
                FarmCreditScore.objects.filter(org=org)
                .order_by("-computed_at")[:6]
            )
        history_reversed = list(reversed(history))

        breakdown = []
        improvement_tips = []
        if credit_score:
            breakdown = [
                {
                    "label": "Financial Health",
                    "value": credit_score.financial_health_score,
                    "tip": "Log your sales records after every harvest to improve your financial health score.",
                },
                {
                    "label": "Operations",
                    "value": credit_score.operational_consistency_score,
                    "tip": "Log mortality and feed data daily — even zero deaths is important to record.",
                },
                {
                    "label": "Mortality Management",
                    "value": credit_score.mortality_management_score,
                    "tip": "Your mortality rate is above benchmark. Review your vaccination schedule.",
                },
                {
                    "label": "Feed Efficiency",
                    "value": credit_score.feed_efficiency_score,
                    "tip": "Track feed usage carefully and weigh your birds weekly to improve FCR accuracy.",
                },
                {
                    "label": "Platform Engagement",
                    "value": credit_score.platform_engagement_score,
                    "tip": "Consistent subscription payments signal commitment to lenders.",
                },
                {
                    "label": "Payment History",
                    "value": credit_score.payment_history_score,
                    "tip": "Upgrade to a yearly plan to show long-term commitment.",
                },
            ]
            for item in breakdown:
                if item["value"] < 60:
                    improvement_tips.append(item)

        industry_avg = {
            "mortality_rate": "5%",
            "fcr": "1.9",
            "profit_margin": "20%",
        }

        history_labels = json.dumps(
            [h.computed_at.strftime("%d %b") for h in history_reversed]
        )
        history_scores = json.dumps([h.score for h in history_reversed])

        return render(request, "finance/credit_score.html", {
            "credit_score": credit_score,
            "breakdown": breakdown,
            "improvement_tips": improvement_tips,
            "industry_avg": industry_avg,
            "history_labels": history_labels,
            "history_scores": history_scores,
            "history": history_reversed,
        })


class CreditScorePDFView(LoginRequiredMixin, View):
    """GET /finance/credit-score/pdf/"""

    def get(self, request):
        from django.http import HttpResponse

        from apps.infrastructure.core.credit_scoring import CreditScoringService
        from apps.infrastructure.core.exports import generate_credit_score_pdf

        org = get_org_or_404(request)
        with set_tenant_context(org):
            credit_score = CreditScoringService.get_latest(org)

        if not credit_score:
            from django.http import Http404
            raise Http404("No credit score available yet.")

        pdf_bytes = generate_credit_score_pdf(org, credit_score)
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = (
            f'attachment; filename="FlockIQ_Credit_Report_{org.name}.pdf"'
        )
        return response
