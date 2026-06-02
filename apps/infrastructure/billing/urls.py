from django.urls import path
from .views import (
    BillingAPIView,
    BillingPageView,
    PaystackCallbackView,
    PaystackWebhookView,
    UpgradeRequestView,
)

app_name = "billing"

urlpatterns = [
    path("billing/webhook/paystack/", PaystackWebhookView.as_view(), name="webhook"),
    path("billing/", BillingPageView.as_view(), name="billing_page"),
    path("billing/upgrade/", UpgradeRequestView.as_view(), name="upgrade_request"),
    path("billing/verify/", PaystackCallbackView.as_view(), name="paystack_callback"),
    path("api/v1/billing/summary/", BillingAPIView.as_view(), name="api_summary"),
]
