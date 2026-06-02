from django.urls import path

from . import views
from .onboarding import OnboardingWizardView

app_name = "tenants"

urlpatterns = [
    path("api/v1/onboarding/", views.TenantOnboardingView.as_view(), name="onboarding"),
    path("onboarding/", OnboardingWizardView.as_view(), name="onboarding_wizard"),
]
