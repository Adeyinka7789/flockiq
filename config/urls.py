from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
    TokenVerifyView,
)

urlpatterns = [
    path("", include("apps.infrastructure.tenants.urls")),
    path("", include("apps.infrastructure.accounts.urls")),
    path("", include("apps.infrastructure.notifications.urls")),
    path("", include("apps.infrastructure.billing.urls")),
    path("", include("apps.farm.farms.urls")),
    path("", include("apps.farm.flocks.urls")),
    path("", include("apps.farm.tasks.urls")),
    path("", include("apps.farm.weather.urls")),
    path("", include("apps.production.production.urls")),
    path("", include("apps.production.feed.urls")),
    path("", include("apps.production.water.urls")),
    path("", include("apps.production.waste.urls")),
    path("", include("apps.health.health.urls")),
    path("", include("apps.health.analytics.urls")),
    path("", include("apps.finance.expenses.urls")),
    path("", include("apps.finance.finance.urls")),
    path("", include("apps.finance.market.urls")),
    path("admin/", admin.site.urls),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/auth/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("api/auth/token/verify/", TokenVerifyView.as_view(), name="token_verify"),
]

if settings.DEBUG:
    import debug_toolbar
    urlpatterns = [
        path("__debug__/", include(debug_toolbar.urls)),
    ] + urlpatterns
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
