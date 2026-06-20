import os
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.http import FileResponse, Http404
from apps.infrastructure.core.health import health_check, ping
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
    SpectacularRedocView,
)
from rest_framework_simplejwt.views import (
    TokenRefreshView,
    TokenVerifyView,
)
from rest_framework.permissions import AllowAny

from django.views.generic import TemplateView
from . import views

from apps.infrastructure.accounts.views import (
    SignupView,
    ThrottledTokenObtainPairView,
    WebLoginView,
    WebLogoutView,
)
from apps.infrastructure.core.views import DashboardView, SessionCheckView, user_manual_pdf
from apps.infrastructure.core.search import GlobalSearchView
from apps.infrastructure.superadmin import urls as superadmin_urls

handler404 = 'apps.infrastructure.core.views.custom_404'
handler500 = 'apps.infrastructure.core.views.custom_500'

# View to serve the Service Worker directly from disk bypassing the template loader
def service_worker_view(request):
    # Check root static directory first
    sw_path = os.path.join(settings.BASE_DIR, "static", "sw.js")
    if not os.path.exists(sw_path):
        sw_path = os.path.join(settings.BASE_DIR, "templates", "sw.js")
    if os.path.exists(sw_path):
        return FileResponse(open(sw_path, "rb"), content_type="application/javascript")
    raise Http404("Service worker file not found on disk.")

urlpatterns = [
    # Public pages (static content)
    path("about/", TemplateView.as_view(template_name="about-us.html"), name="about"),
    path("sw.js", service_worker_view, name="service_worker"),
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
    path("docs/user-manual/", user_manual_pdf, name="user_manual_pdf"),

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
    # Served at a non-default, env-configurable path — see RUNBOOK.md "Django Admin".
    path(settings.DJANGO_ADMIN_URL, admin.site.urls),
    # Throttled subclass — stock TokenObtainPairView has no throttle scope,
    # and axes only covers the web login form, not this JWT surface.
    path("api/auth/token/", ThrottledTokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("api/auth/token/verify/", TokenVerifyView.as_view(), name="token_verify"),
    # ── Monitoring (always available, not DEBUG-only) ────────────────────────
    # NOTE: /health/ is already taken by the health app's dashboard, so the
    # monitoring health check is served at /healthz/ (k8s-style convention).
    path("healthz/", health_check, name="health_check"),
    path("ping/", ping, name="ping"),
    
]

# Django Silk profiling UI — wired whenever ENABLE_SILK is on (any environment).
if getattr(settings, "ENABLE_SILK", False):
    from silk import urls as silk_urls

    urlpatterns += [path("silk/", include(silk_urls))]

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
