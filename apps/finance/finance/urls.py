from django.urls import path

from . import views

app_name = "finance"

urlpatterns = [
    path(
        "finance/pl/<uuid:batch_pk>/",
        views.PLSummaryView.as_view(),
        name="pl",
    ),
    path(
        "finance/sales/<uuid:batch_pk>/log/",
        views.SaleLogView.as_view(),
        name="sale_log",
    ),
    path(
        "finance/sales/<uuid:batch_pk>/table/",
        views.SaleTableView.as_view(),
        name="sale_table",
    ),
    path(
        "finance/breakeven/<uuid:batch_pk>/",
        views.BreakEvenView.as_view(),
        name="breakeven",
    ),
    path(
        "finance/roi/<uuid:batch_pk>/",
        views.ROICalculatorView.as_view(),
        name="roi",
    ),
    path(
        "api/v1/finance/summary/",
        views.FinanceSummaryAPIView.as_view(),
        name="api_summary",
    ),
    path(
        "api/v1/finance/sales/",
        views.SalesAPIView.as_view(),
        name="api_sales",
    ),
    path(
        "api/v1/finance/breakeven/<uuid:batch_pk>/",
        views.BreakEvenAPIView.as_view(),
        name="api_breakeven",
    ),
]
