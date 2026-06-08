from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
    SpectacularRedocView,
)
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
    TokenVerifyView,
)
from rest_framework.permissions import AllowAny

from django.views.generic import TemplateView
from . import views

from apps.infrastructure.accounts.views import WebLoginView, WebLogoutView, SignupView
from apps.infrastructure.core.views import DashboardView, SessionCheckView, custom_404, custom_500
from apps.infrastructure.core.search import GlobalSearchView
from apps.infrastructure.superadmin import urls as superadmin_urls

handler404 = 'apps.infrastructure.core.views.custom_404'
handler500 = 'apps.infrastructure.core.views.custom_500'

urlpatterns = [
    # Public pages (static content)
    path("about/", TemplateView.as_view(template_name="about-us.html"), name="about"),
    path("case-studies/", views.case_studies_list, name="case_studies"),
    path("case-studies/<slug:slug>/", views.case_study_detail, name="case_study_detail"),
    path("contact/", views.contact, name="contact"),
    path("privacy/", TemplateView.as_view(template_name="privacy.html"), name="privacy_policy"),
    path("cookie-policy/", TemplateView.as_view(template_name="cookie.html"), name="cookie_policy"),
    path("ai-disclaimer/", TemplateView.as_view(template_name="disclaimer.html"), name="disclaimer"),
    path("terms/", TemplateView.as_view(template_name="terms.html"), name="terms"),
    path("security/", TemplateView.as_view(template_name="security.html"), name="security"),
    path("help/", TemplateView.as_view(template_name="help.html"), name="help"),
    path("roi-calculator/", TemplateView.as_view(template_name="roi-calculator.html"), name="roi_calculator"),
    # ── Web app shell (must be first) ────────────────────────────────────────
    path("", DashboardView.as_view(), name="dashboard"),
    path("api/session/check/", SessionCheckView.as_view(), name="session_check"),
    path("search/", GlobalSearchView.as_view(), name="global_search"),
    path("login/", WebLoginView.as_view(), name="login"),
    path("logout/", WebLogoutView.as_view(), name="logout"),
    path("signup/", SignupView.as_view(), name="signup"),

    # ── App URLs ──────────────────────────────────────────────────────────────
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
    path("", include(superadmin_urls)),
    path("admin/", admin.site.urls),
    path("api/auth/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("api/auth/token/verify/", TokenVerifyView.as_view(), name="token_verify"),
]

if settings.DEBUG:
    # API documentation — only exposed outside production. AllowAny lets the
    # docs be browsed freely in development; the Swagger "Authorize" button still
    # lets you supply a JWT to exercise authenticated endpoints.
    urlpatterns += [
        # Schema (raw OpenAPI JSON/YAML)
        path(
            "api/schema/",
            SpectacularAPIView.as_view(permission_classes=[AllowAny]),
            name="schema",
        ),
        # Swagger UI — interactive browser docs
        path(
            "api/docs/",
            SpectacularSwaggerView.as_view(
                url_name="schema", permission_classes=[AllowAny]
            ),
            name="swagger-ui",
        ),
        # ReDoc — alternative cleaner read-only docs
        path(
            "api/redoc/",
            SpectacularRedocView.as_view(
                url_name="schema", permission_classes=[AllowAny]
            ),
            name="redoc",
        ),
    ]
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
