from django.urls import path

from . import views

app_name = "waste"

urlpatterns = [
    path(
        "production/waste/<uuid:farm_pk>/log/",
        views.WasteLogView.as_view(),
        name="log",
    ),
    path(
        "production/waste/<uuid:farm_pk>/table/",
        views.WasteTableView.as_view(),
        name="table",
    ),
]
