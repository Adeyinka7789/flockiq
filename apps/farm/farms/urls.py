from django.urls import path

from .views import (
    FarmCreateView,
    FarmDashboardAPIView,
    FarmDeleteView,
    FarmDetailAPIView,
    FarmDetailView,
    FarmListAPIView,
    FarmListView,
    FarmSummaryCardView,
    HouseCreateView,
    HouseDeleteView,
    HouseListAPIView,
)

app_name = "farms"

urlpatterns = [
    # HTMX views
    path("farms/", FarmListView.as_view(), name="list"),
    path("farms/create/", FarmCreateView.as_view(), name="create"),
    path("farms/<uuid:pk>/", FarmDetailView.as_view(), name="detail"),
    path("farms/<uuid:pk>/houses/create/", HouseCreateView.as_view(), name="house_create"),
    path("farms/<uuid:pk>/delete/", FarmDeleteView.as_view(), name="delete"),
    path(
        "farms/<uuid:pk>/houses/<uuid:house_pk>/delete/",
        HouseDeleteView.as_view(),
        name="house_delete",
    ),
    path("farms/<uuid:pk>/summary-card/", FarmSummaryCardView.as_view(), name="summary_card"),
    # DRF API
    path("api/v1/farms/", FarmListAPIView.as_view(), name="api_list"),
    path("api/v1/farms/<uuid:pk>/", FarmDetailAPIView.as_view(), name="api_detail"),
    path("api/v1/farms/<uuid:pk>/houses/", HouseListAPIView.as_view(), name="api_house_list"),
    path("api/v1/farms/<uuid:pk>/dashboard/", FarmDashboardAPIView.as_view(), name="api_dashboard"),
]
