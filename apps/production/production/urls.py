from django.urls import path

from . import views

app_name = "production"

urlpatterns = [
    path(
        "production/",
        views.ProductionOverviewView.as_view(),
        name="overview",
    ),
    path(
        "production/eggs/<uuid:batch_pk>/log/",
        views.ProductionLogView.as_view(),
        name="log",
    ),
    path(
        "production/eggs/<uuid:batch_pk>/table/",
        views.ProductionTableView.as_view(),
        name="table",
    ),
    path(
        "production/eggs/<uuid:batch_pk>/chart/",
        views.ProductionChartView.as_view(),
        name="chart",
    ),
    path(
        "production/eggs/<uuid:batch_pk>/summary/",
        views.ProductionSummaryCardView.as_view(),
        name="summary",
    ),
    path(
        "api/v1/production/eggs/",
        views.EggProductionAPIView.as_view(),
        name="api_list",
    ),
    path(
        "api/v1/production/eggs/<uuid:batch_pk>/",
        views.EggProductionDetailAPIView.as_view(),
        name="api_detail",
    ),
]
