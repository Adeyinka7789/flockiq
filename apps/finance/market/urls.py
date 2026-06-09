from django.urls import path

from . import views

app_name = "market"

urlpatterns = [
    path("market/prices/", views.MarketPriceView.as_view(), name="prices"),
    path("market/prices/record/", views.RecordMarketPriceView.as_view(), name="record_price"),
    path("market/seasonal/", views.SeasonalForecastView.as_view(), name="seasonal"),
    path("market/mvp/<uuid:batch_pk>/", views.MinViablePriceView.as_view(), name="mvp"),
    # Community Intelligence
    path("market/feed-prices/", views.FeedPricesView.as_view(), name="feed_prices"),
    path("market/feed-prices/submit/", views.SubmitFeedPriceView.as_view(), name="submit_feed_price"),
    path("market/hatcheries/", views.HatcheryDirectoryView.as_view(), name="hatchery_directory"),
    path("market/hatcheries/suggest/", views.SuggestHatcheryView.as_view(), name="suggest_hatchery"),
    path("market/hatcheries/<int:pk>/", views.HatcheryDetailView.as_view(), name="hatchery_detail"),
    path("market/hatcheries/<int:pk>/review/", views.SubmitHatcheryReviewView.as_view(), name="submit_hatchery_review"),
]
