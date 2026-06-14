import uuid

from django.db import models

from apps.infrastructure.accounts.constants import COUNTRY_CHOICES


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

    # Custom domain — a tenant may point their own domain (e.g.
    # app.obasanjofarm.com) at FlockIQ. Verified via a DNS TXT record before
    # TenantMiddleware will resolve requests for it. See domain_views.py.
    custom_domain = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        unique=True,
        db_index=True,
        help_text="e.g. app.obasanjofarm.com",
    )
    custom_domain_verified = models.BooleanField(default=False)
    custom_domain_verification_token = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="TXT record value for DNS verification",
    )
    custom_domain_verified_at = models.DateTimeField(null=True, blank=True)

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
            ("past_due", "Past Due"),
            ("lapsed", "Lapsed"),
        ],
        default="trial",
    )
    trial_ends_at = models.DateTimeField(null=True, blank=True)
    plan_expires_at = models.DateTimeField(
        null=True, blank=True,
        help_text="When the current paid plan lapses. Set on activation/renewal.")
    plan_renewal_preference = models.CharField(
        max_length=20,
        choices=[
            ("auto", "Auto-renew"),
            ("manual", "Manual renewal"),
        ],
        default="manual",
    )
    upgrade_pending = models.CharField(
        max_length=20,
        choices=[
            ("", "No pending upgrade"),
            ("monthly", "Monthly"),
            ("yearly", "Yearly"),
            ("cycle", "Cycle"),
        ],
        blank=True, default="",
        help_text="Plan the org has scheduled to switch to at next renewal.")
    upgrade_timing = models.CharField(
        max_length=20,
        choices=[
            ("immediate", "Immediate"),
            ("on_renewal", "At next renewal"),
        ],
        blank=True, default="",
    )
    max_users = models.PositiveIntegerField(default=5)
    storage_quota_gb = models.PositiveIntegerField(default=5)
    grace_period_ends_at = models.DateTimeField(
        null=True, blank=True,
        help_text='If set, org has billing grace period until this date')
    paystack_subscription_code = models.CharField(
        max_length=100, blank=True, default="",
        help_text=(
            "Parking slot for a subscription.create webhook that arrives "
            "before the create_subscription API response is processed; "
            "consumed by BillingService.activate_cycle_subscription."
        ),
    )

    # Contact
    owner_name = models.CharField(max_length=200, blank=True)
    owner_phone = models.CharField(max_length=20, blank=True)
    owner_email = models.EmailField(blank=True)

    # Locale — drives country-scoping of community market data (market prices,
    # hatcheries, feed price reports). Copied from the owner's CustomUser.country
    # at signup. See accounts.constants.COUNTRY_CHOICES.
    country = models.CharField(
        max_length=50,
        choices=COUNTRY_CHOICES,
        default="Nigeria",
    )

    # Per-org configuration stored as JSONB.
    # Expected keys: currency, timezone, sms_alerts_enabled,
    #                email_alerts_enabled, white_label_enabled
    settings = models.JSONField(default=dict, blank=True)

    # Meta
    is_active = models.BooleanField(default=True)
    suspension_reason = models.CharField(
        max_length=500, blank=True,
        help_text="Reason shown to the org owner when the account is suspended")
    onboarding_complete = models.BooleanField(default=False)
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
    def is_lapsed(self) -> bool:
        """
        A paid org whose plan has expired and was not renewed. Trial orgs are
        never "lapsed" — their expiry is handled by the trial banner instead.
        Lapsed orgs keep read access but lose write access (see
        billing.features.can_write_data).

        Purely date-based: subscription_status is NOT consulted, so lapse
        takes effect the moment plan_expires_at passes — no Celery task or
        status flip required. billing.mark_lapsed_orgs updates the status
        field daily for reporting only.
        """
        from django.utils import timezone
        if self.plan_tier == "trial":
            return False
        if not self.plan_expires_at:
            return False
        return self.plan_expires_at < timezone.now()

    @property
    def sms_alerts_enabled(self):
        return self.settings.get("sms_alerts_enabled", True)

    @property
    def email_alerts_enabled(self):
        return self.settings.get("email_alerts_enabled", True)

    @property
    def white_label_enabled(self):
        return self.settings.get("white_label_enabled", False)
