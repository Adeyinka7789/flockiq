from django.urls import path

from .views import (
    BatchCloseAPIView,
    BatchCloseView,
    BatchCreateSelectView,
    BatchCreateView,
    BatchDeleteView,
    BatchDetailAPIView,
    BatchDetailView,
    BatchEditView,
    BatchExcelExportView,
    BatchListAPIView,
    BatchListView,
    BatchMetricsCardView,
    BatchPDFExportView,
    BatchValuationAPIView,
    ExitOptimizerPartialView,
    LossDocumentationReportView,
    MortalityLogAPIView,
    MortalityLogDeleteView,
    MortalityLogView,
    MortalityRecentView,
    ValuationOverrideView,
    WeightRecordDeleteView,
    WeightRecordView,
)

app_name = "flocks"

urlpatterns = [
    # HTMX views
    path("batches/", BatchListView.as_view(), name="list"),
    path("batches/<uuid:pk>/", BatchDetailView.as_view(), name="detail"),
    path("batches/<uuid:pk>/edit/", BatchEditView.as_view(), name="edit"),
    path("batches/<uuid:pk>/mortality/", MortalityLogView.as_view(), name="mortality"),
    path("batches/<uuid:pk>/mortality/recent/", MortalityRecentView.as_view(), name="mortality_recent"),
    path("batches/<uuid:pk>/weight/", WeightRecordView.as_view(), name="weight"),
    path("batches/<uuid:pk>/delete/", BatchDeleteView.as_view(), name="delete"),
    path(
        "batches/mortality/<uuid:pk>/delete/",
        MortalityLogDeleteView.as_view(),
        name="mortality_delete",
    ),
    path(
        "batches/weight/<uuid:pk>/delete/",
        WeightRecordDeleteView.as_view(),
        name="weight_delete",
    ),
    path("batches/<uuid:pk>/close/", BatchCloseView.as_view(), name="close"),
    path("batches/<uuid:pk>/exit-optimizer/", ExitOptimizerPartialView.as_view(), name="exit_optimizer_partial"),
    path("batches/<uuid:pk>/metrics/", BatchMetricsCardView.as_view(), name="metrics"),
    path("batches/<uuid:pk>/loss-report/", LossDocumentationReportView.as_view(), name="loss_report"),
    path("batches/<uuid:pk>/valuation-override/", ValuationOverrideView.as_view(), name="valuation_override"),
    path("batches/<uuid:pk>/export/pdf/", BatchPDFExportView.as_view(), name="export_pdf"),
    path("batches/<uuid:pk>/export/excel/", BatchExcelExportView.as_view(), name="export_excel"),
    path("batches/create/", BatchCreateSelectView.as_view(), name="create_select"),
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
    path(
        "api/v1/flocks/batches/<uuid:pk>/valuation/",
        BatchValuationAPIView.as_view(),
        name="api_valuation",
    ),
]
