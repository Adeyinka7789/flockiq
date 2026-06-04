from django.urls import path
from .views import (
    BankTransferNotifyView,
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
    path("billing/bank-transfer/notify/", BankTransferNotifyView.as_view(), name="bank_transfer_notify"),
    path("api/v1/billing/summary/", BillingAPIView.as_view(), name="api_summary"),
]
