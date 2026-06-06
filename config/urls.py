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

from django.views.generic import TemplateView
from . import views

from apps.infrastructure.accounts.views import WebLoginView, WebLogoutView, SignupView
from apps.infrastructure.core.views import DashboardView, SessionCheckView
from apps.infrastructure.core.search import GlobalSearchView
from apps.infrastructure.superadmin import urls as superadmin_urls

urlpatterns = [
    # Public pages (static content)
    path("about/", TemplateView.as_view(template_name="about-us.html"), name="about"),
    path("case-studies/", TemplateView.as_view(template_name="case-studies.html"), name="case_studies"),
    path("case-studies/<slug:slug>/", TemplateView.as_view(template_name="case-study-details.html"), name="case_study_detail"),
    path("contact/", TemplateView.as_view(template_name="contact.html"), name="contact"),
    path("privacy/", TemplateView.as_view(template_name="privacy.html"), name="privacy_policy"),
    path("cookie-policy/", TemplateView.as_view(template_name="cookie.html"), name="cookie_policy"),
    path("ai-disclaimer/", TemplateView.as_view(template_name="disclaimer.html"), name="disclaimer"),
    path("case-studies/<slug:slug>/", views.case_study_detail, name="case_study_detail"),
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
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/auth/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("api/auth/token/verify/", TokenVerifyView.as_view(), name="token_verify"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
