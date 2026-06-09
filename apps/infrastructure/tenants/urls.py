from django.urls import path

from . import views
from .domain_views import (
    CustomDomainSettingsView,
    RemoveCustomDomainView,
    VerifyCustomDomainView,
)
from .onboarding import OnboardingWizardView

app_name = "tenants"

urlpatterns = [
    path("api/v1/onboarding/", views.TenantOnboardingView.as_view(), name="onboarding"),
    path("onboarding/", OnboardingWizardView.as_view(), name="onboarding_wizard"),
    # Custom domain management (owner only)
    path(
        "settings/custom-domain/",
        CustomDomainSettingsView.as_view(),
        name="custom_domain_settings",
    ),
    path(
        "settings/custom-domain/verify/",
        VerifyCustomDomainView.as_view(),
        name="verify_custom_domain",
    ),
    path(
        "settings/custom-domain/remove/",
        RemoveCustomDomainView.as_view(),
        name="remove_custom_domain",
    ),
]
