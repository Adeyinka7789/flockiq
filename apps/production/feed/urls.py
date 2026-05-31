from django.urls import path

from . import views

app_name = "feed"

urlpatterns = [
    path(
        "production/feed/<uuid:batch_pk>/log/",
        views.FeedLogView.as_view(),
        name="log",
    ),
    path(
        "production/feed/<uuid:batch_pk>/table/",
        views.FeedTableView.as_view(),
        name="table",
    ),
    path(
        "production/feed/<uuid:batch_pk>/summary/",
        views.FeedSummaryCardView.as_view(),
        name="summary",
    ),
    path(
        "production/feed/<uuid:batch_pk>/chart/",
        views.FeedChartView.as_view(),
        name="chart",
    ),
    path(
        "production/feed/<uuid:farm_pk>/stock/",
        views.FeedStockView.as_view(),
        name="stock",
    ),
    path(
        "api/v1/feed/log/",
        views.FeedLogAPIView.as_view(),
        name="api_log",
    ),
]
