from django.urls import path

from . import views

app_name = "water"

urlpatterns = [
    path(
        "production/water/<uuid:batch_pk>/log/",
        views.WaterLogView.as_view(),
        name="log",
    ),
    path(
        "production/water/<uuid:batch_pk>/table/",
        views.WaterTableView.as_view(),
        name="table",
    ),
    path(
        "production/water/<uuid:batch_pk>/summary/",
        views.WaterSummaryCardView.as_view(),
        name="summary",
    ),
    path(
        "water-logs/<uuid:pk>/delete/",
        views.WaterLogDeleteView.as_view(),
        name="delete",
    ),
]
