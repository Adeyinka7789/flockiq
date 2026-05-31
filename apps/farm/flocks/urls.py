from django.urls import path

from .views import (
    BatchCloseAPIView,
    BatchCloseView,
    BatchCreateView,
    BatchDetailAPIView,
    BatchDetailView,
    BatchListAPIView,
    BatchListView,
    BatchMetricsCardView,
    MortalityLogAPIView,
    MortalityLogView,
    WeightRecordView,
)

app_name = "flocks"

urlpatterns = [
    # HTMX views
    path("batches/", BatchListView.as_view(), name="list"),
    path("batches/<uuid:pk>/", BatchDetailView.as_view(), name="detail"),
    path("batches/<uuid:pk>/mortality/", MortalityLogView.as_view(), name="mortality"),
    path("batches/<uuid:pk>/weight/", WeightRecordView.as_view(), name="weight"),
    path("batches/<uuid:pk>/close/", BatchCloseView.as_view(), name="close"),
    path("batches/<uuid:pk>/metrics/", BatchMetricsCardView.as_view(), name="metrics"),
    path("farms/<uuid:farm_pk>/batches/create/", BatchCreateView.as_view(), name="create"),
    # DRF API
    path("api/v1/flocks/batches/", BatchListAPIView.as_view(), name="api_list"),
    path("api/v1/flocks/batches/<uuid:pk>/", BatchDetailAPIView.as_view(), name="api_detail"),
    path(
        "api/v1/flocks/batches/<uuid:pk>/mortality/",
        MortalityLogAPIView.as_view(),
        name="api_mortality",
    ),
    path(
        "api/v1/flocks/batches/<uuid:pk>/close/",
        BatchCloseAPIView.as_view(),
        name="api_close",
    ),
]
