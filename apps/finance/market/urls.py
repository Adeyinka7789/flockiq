from django.urls import path

from . import views

app_name = "market"

urlpatterns = [
    path("market/prices/", views.MarketPriceView.as_view(), name="prices"),
    path("market/prices/record/", views.RecordMarketPriceView.as_view(), name="record_price"),
    path("market/seasonal/", views.SeasonalForecastView.as_view(), name="seasonal"),
    path("market/mvp/<uuid:batch_pk>/", views.MinViablePriceView.as_view(), name="mvp"),
]
