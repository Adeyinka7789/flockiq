from django.urls import path

from . import views

app_name = "expenses"

urlpatterns = [
    path(
        "expenses/",
        views.ExpenseOverviewView.as_view(),
        name="overview",
    ),
    path(
        "finance/expenses/<uuid:batch_pk>/log/",
        views.ExpenseLogView.as_view(),
        name="log",
    ),
    path(
        "finance/expenses/<uuid:batch_pk>/table/",
        views.ExpenseTableView.as_view(),
        name="table",
    ),
    path(
        "finance/expenses/<uuid:batch_pk>/breakdown/",
        views.ExpenseBreakdownView.as_view(),
        name="breakdown",
    ),
    path(
        "finance/expenses/farm/<uuid:farm_pk>/summary/",
        views.ExpenseFarmSummaryView.as_view(),
        name="farm_summary",
    ),
    path(
        "api/v1/expenses/",
        views.ExpenseAPIView.as_view(),
        name="api_list",
    ),
    path(
        "batches/<uuid:batch_pk>/finance/export/pdf/",
        views.FinancePDFExportView.as_view(),
        name="finance_pdf",
    ),
    path(
        "batches/<uuid:batch_pk>/finance/export/excel/",
        views.FinanceExcelExportView.as_view(),
        name="finance_excel",
    ),
]
