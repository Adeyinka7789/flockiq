import uuid

from django.db import models

from apps.infrastructure.core.models import TenantAwareModel


PLAN_TIER_CHOICES = [
    ("trial", "Trial"),
    ("monthly", "Monthly"),
    ("cycle", "Cycle"),
    ("yearly", "Yearly"),
]

BILLING_INTERVAL_CHOICES = [
    ("monthly", "Monthly"),
    ("annually", "Annually"),
    ("per_cycle", "Per Cycle"),
]

SUBSCRIPTION_STATUS_CHOICES = [
    ("pending", "Pending"),
    ("active", "Active"),
    ("paused", "Paused"),
    ("cancelled", "Cancelled"),
]

PAYMENT_STATUS_CHOICES = [
    ("pending", "Pending"),
    ("success", "Success"),
    ("failed", "Failed"),
]


class BillingPlan(models.Model):
    """
    Global admin-managed plan catalogue. RLS DISABLED — any tenant can read it.
    The plan_tier matches Organization.plan_tier to determine which plan is active.
    """

    name = models.CharField(max_length=100)
    plan_tier = models.CharField(max_length=20, choices=PLAN_TIER_CHOICES)
    paystack_plan_code = models.CharField(max_length=100, blank=True)
    amount_kobo = models.IntegerField()
    billing_interval = models.CharField(max_length=20, choices=BILLING_INTERVAL_CHOICES)
    features = models.JSONField(default=list)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "billing_plans"
        ordering = ["amount_kobo"]

    def __str__(self):
        return f"{self.name} ({self.plan_tier})"

    @property
    def amount_naira(self):
        return self.amount_kobo / 100


class CycleSubscription(TenantAwareModel):
    """
    One record per active broiler batch for cycle-based billing.
    batch FK to flocks.Batch deferred to 0002 — stored as UUID for now.
    """

    # FK to flocks.Batch added in 0002_add_batch_fk once flocks app is built
    batch_id = models.UUIDField(unique=True, null=True, blank=True)
    plan = models.ForeignKey(BillingPlan, on_delete=models.PROTECT, related_name="cycle_subscriptions")
    paystack_subscription_code = models.CharField(max_length=100, blank=True)
    paystack_email_token = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=15, choices=SUBSCRIPTION_STATUS_CHOICES, default="pending")
    activated_at = models.DateTimeField(null=True, blank=True)
    deactivated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "billing_cyclesubscription"

    def __str__(self):
        return f"CycleSubscription(batch={self.batch_id}, status={self.status})"


class PaymentRecord(TenantAwareModel):
    reference = models.CharField(max_length=100, unique=True)
    amount_kobo = models.IntegerField()
    status = models.CharField(max_length=10, choices=PAYMENT_STATUS_CHOICES)
    channel = models.CharField(max_length=50, blank=True)
    paystack_transaction_id = models.CharField(max_length=100, blank=True)
    authorization_code = models.CharField(max_length=100, blank=True)
    plan = models.ForeignKey(BillingPlan, null=True, on_delete=models.SET_NULL, related_name="payments")
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "billing_paymentrecord"
        indexes = [
            models.Index(fields=["reference"]),
            models.Index(fields=["status", "created_at"]),
        ]

    def __str__(self):
        return f"Payment({self.reference}, {self.status})"


class PaystackWebhookLog(models.Model):
    """Audit trail for all Paystack webhook calls. RLS DISABLED — cross-tenant."""

    event_type = models.CharField(max_length=100)
    payload = models.JSONField()
    signature_valid = models.BooleanField()
    processed = models.BooleanField(default=False)
    error = models.TextField(blank=True)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "billing_paystackwebhooklog"
        ordering = ["-received_at"]

    def __str__(self):
        return f"{self.event_type} — {'valid' if self.signature_valid else 'INVALID'} @ {self.received_at}"
