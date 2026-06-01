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

from .services import ExpenseService

logger = structlog.get_logger(__name__)


def _get_org(request):
    org = getattr(request.user, "org", None)
    if org is None:
        raise Http404("No organisation found for this user.")
    return org


class ExpenseLogView(LoginRequiredMixin, View):
    """POST /finance/expenses/<uuid:batch_pk>/log/"""

    def post(self, request, batch_pk):
        org = _get_org(request)
        data = request.POST

        for field in ["category", "amount", "description"]:
            if not data.get(field):
                return render(
                    request,
                    "expenses/_expense_log_form.html",
                    {"error": f"{field} is required.", "batch_pk": batch_pk},
                    status=422,
                )

        try:
            amount_naira = float(data["amount"])
            amount_kobo = int(amount_naira * 100)
        except (ValueError, TypeError):
            return render(
                request,
                "expenses/_expense_log_form.html",
                {"error": "Invalid amount.", "batch_pk": batch_pk},
                status=422,
            )

        expense_date_str = data.get("expense_date")
        expense_date = None
        if expense_date_str:
            try:
                expense_date = datetime.date.fromisoformat(expense_date_str)
            except ValueError:
                pass

        farm_id = data.get("farm_id", "")

        with set_tenant_context(org):
            try:
                record = ExpenseService(org).record_expense(
                    farm_id=farm_id,
                    category=data["category"],
                    amount_kobo=amount_kobo,
                    description=data["description"],
                    expense_date=expense_date,
                    batch_id=str(batch_pk),
                    receipt_ref=data.get("receipt_ref", ""),
                    notes=data.get("notes", ""),
                    recorded_by=request.user,
                )
            except ValueError as exc:
                return render(
                    request,
                    "expenses/_expense_log_form.html",
                    {"error": str(exc), "batch_pk": batch_pk},
                    status=422,
                )

        response = render(
            request,
            "expenses/_expense_log_form.html",
            {"success": True, "record": record, "batch_pk": batch_pk},
        )
        response["HX-Trigger"] = '{"expenseAdded": true}'
        return response


class ExpenseTableView(LoginRequiredMixin, View):
    """GET /finance/expenses/<uuid:batch_pk>/table/"""

    def get(self, request, batch_pk):
        org = _get_org(request)
        with set_tenant_context(org):
            expenses = ExpenseService(org).get_batch_expenses(str(batch_pk))
        return render(
            request,
            "expenses/_expense_table.html",
            {"expenses": expenses, "batch_pk": batch_pk},
        )


class ExpenseBreakdownView(LoginRequiredMixin, View):
    """GET /finance/expenses/<uuid:batch_pk>/breakdown/"""

    def get(self, request, batch_pk):
        org = _get_org(request)
        with set_tenant_context(org):
            breakdown = ExpenseService(org).get_expense_breakdown(batch_id=str(batch_pk))
        return render(
            request,
            "expenses/_expense_breakdown_chart.html",
            {"breakdown": breakdown, "batch_pk": batch_pk},
        )


class ExpenseFarmSummaryView(LoginRequiredMixin, View):
    """GET /finance/expenses/farm/<uuid:farm_pk>/summary/"""

    def get(self, request, farm_pk):
        org = _get_org(request)
        month = request.GET.get("month")
        with set_tenant_context(org):
            summary = ExpenseService(org).get_farm_expenses_summary(
                farm_id=str(farm_pk),
                month=int(month) if month else None,
            )
        return render(
            request,
            "expenses/_farm_expense_summary.html",
            {"summary": summary, "farm_pk": farm_pk},
        )


class ExpenseAPIView(APIView):
    """GET+POST /api/v1/expenses/"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        org = _get_org(request)
        batch_id = request.query_params.get("batch_id")
        with set_tenant_context(org):
            svc = ExpenseService(org)
            if batch_id:
                expenses = svc.get_batch_expenses(batch_id)
                data = [
                    {
                        "id": str(e.id),
                        "category": e.category,
                        "amount_naira": e.amount_naira,
                        "description": e.description,
                        "expense_date": e.expense_date.isoformat(),
                    }
                    for e in expenses
                ]
            else:
                data = []
        return Response({"data": data})

    def post(self, request):
        org = _get_org(request)
        d = request.data

        try:
            amount_kobo = int(float(d.get("amount_naira", 0)) * 100)
            with set_tenant_context(org):
                record = ExpenseService(org).record_expense(
                    farm_id=d.get("farm_id", ""),
                    category=d.get("category", ""),
                    amount_kobo=amount_kobo,
                    description=d.get("description", ""),
                    batch_id=d.get("batch_id"),
                    receipt_ref=d.get("receipt_ref", ""),
                    notes=d.get("notes", ""),
                    recorded_by=request.user,
                )
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)

        return Response(
            {
                "id": str(record.id),
                "category": record.category,
                "amount_naira": record.amount_naira,
            },
            status=201,
        )
