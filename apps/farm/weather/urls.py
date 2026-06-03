from django.urls import path

from . import views

app_name = "weather"

urlpatterns = [
    path("weather/", views.WeatherAlertsPageView.as_view(), name="alerts"),
    path("weather/farm/<uuid:farm_pk>/strip/", views.WeatherStripView.as_view(), name="strip"),
    path("weather/alerts/<uuid:pk>/acknowledge/", views.WeatherAlertAcknowledgeView.as_view(), name="acknowledge"),
]
