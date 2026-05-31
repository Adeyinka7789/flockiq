from django.urls import path

from . import views

app_name = "tenants"

urlpatterns = [
    path("api/v1/onboarding/", views.TenantOnboardingView.as_view(), name="onboarding"),
]
