from django.urls import path

from .ai_insights_view import AIInsightsDeepDiveView
from .views import (
    AIAnalyticsPageView,
    AlertAcknowledgeAPIView,
    AlertListAPIView,
    AnomalyFeedView,
    AnomalyResolveView,
    DiagnosisView,
    ForecastAPIView,
    ForecastChartView,
    SaleTimingAPIView,
    SaleTimingView,
    TheftAPIView,
    TheftReportView,
)

app_name = "analytics"

urlpatterns = [
    # AI Analytics dashboard page
    path("analytics/", AIAnalyticsPageView.as_view(), name="analytics"),
    path("ai/insights/<uuid:batch_pk>/", AIInsightsDeepDiveView.as_view(), name="deep_dive"),
    # HTMX partials
    path("analytics/forecast/<uuid:batch_pk>/", ForecastChartView.as_view(), name="forecast"),
    path("analytics/anomalies/<uuid:batch_pk>/", AnomalyFeedView.as_view(), name="anomalies"),
    path("analytics/anomalies/<uuid:pk>/resolve/", AnomalyResolveView.as_view(), name="resolve"),
    path("analytics/theft/<uuid:batch_pk>/", TheftReportView.as_view(), name="theft"),
    path("analytics/sale-timing/<uuid:batch_pk>/", SaleTimingView.as_view(), name="sale_timing"),
    path("analytics/diagnose/", DiagnosisView.as_view(), name="diagnose"),
    # DRF API
    path("api/v1/analytics/alerts/", AlertListAPIView.as_view(), name="api_alerts"),
    path(
        "api/v1/analytics/alerts/<uuid:pk>/acknowledge/",
        AlertAcknowledgeAPIView.as_view(),
        name="api_acknowledge",
    ),
    path(
        "api/v1/analytics/forecast/<uuid:batch_pk>/",
        ForecastAPIView.as_view(),
        name="api_forecast",
    ),
    path(
        "api/v1/analytics/theft/<uuid:batch_pk>/",
        TheftAPIView.as_view(),
        name="api_theft",
    ),
    path(
        "api/v1/analytics/sale-timing/<uuid:batch_pk>/",
        SaleTimingAPIView.as_view(),
        name="api_sale_timing",
    ),
]
