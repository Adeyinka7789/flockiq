import uuid

from django.db import models


class Organization(models.Model):
    """
    Tenant root. NOT a TenantAwareModel — it IS the tenant.
    RLS must be DISABLED on this table (see migration 0001_initial.py).

    Reasons RLS must be off:
      - TenantMiddleware queries this table to resolve the org BEFORE the context is set
      - Celery Beat fan-out tasks query it cross-tenant using no_tenant_context()
      - Authentication (login) queries it before JWT claims are validated

    From rls_multitenancy.md Common Mistakes #1:
      "outbox table with RLS — Workers get zero results silently, no error."
      Same applies here: if RLS were on, middleware would always get zero rows.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    subdomain = models.SlugField(max_length=63, unique=True)

    # Branding
    logo = models.ImageField(upload_to="org_logos/", null=True, blank=True)
    primary_colour = models.CharField(max_length=7, default="#16a34a")

    # Subscription
    plan_tier = models.CharField(
        max_length=20,
        choices=[
            ("trial", "Trial"),
            ("monthly", "Monthly"),
            ("cycle", "Cycle"),
            ("yearly", "Yearly"),
        ],
        default="trial",
    )
    subscription_status = models.CharField(
        max_length=20,
        choices=[
            ("active", "Active"),
            ("suspended", "Suspended"),
            ("cancelled", "Cancelled"),
            ("trial", "Trial"),
        ],
        default="trial",
    )
    trial_ends_at = models.DateTimeField(null=True, blank=True)

    # Contact
    owner_name = models.CharField(max_length=200, blank=True)
    owner_phone = models.CharField(max_length=20, blank=True)
    owner_email = models.EmailField(blank=True)

    # Per-org configuration stored as JSONB.
    # Expected keys: currency, timezone, sms_alerts_enabled,
    #                email_alerts_enabled, white_label_enabled
    settings = models.JSONField(default=dict, blank=True)

    # Meta
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tenants_organization"
        ordering = ["name"]
        indexes = [
            models.Index(fields=["subdomain"]),
            models.Index(fields=["subscription_status"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.subdomain})"

    @property
    def is_on_trial(self):
        from django.utils import timezone
        return (
            self.plan_tier == "trial"
            and self.trial_ends_at is not None
            and self.trial_ends_at > timezone.now()
        )

    @property
    def sms_alerts_enabled(self):
        return self.settings.get("sms_alerts_enabled", True)

    @property
    def email_alerts_enabled(self):
        return self.settings.get("email_alerts_enabled", True)

    @property
    def white_label_enabled(self):
        return self.settings.get("white_label_enabled", False)
