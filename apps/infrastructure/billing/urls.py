from django.urls import path
from .views import BillingAPIView, BillingPageView, PaystackWebhookView

app_name = "billing"

urlpatterns = [
    path("billing/webhook/paystack/", PaystackWebhookView.as_view(), name="webhook"),
    path("billing/", BillingPageView.as_view(), name="billing_page"),
    path("api/v1/billing/summary/", BillingAPIView.as_view(), name="api_summary"),
]
