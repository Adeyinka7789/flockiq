import uuid

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models

from apps.infrastructure.accounts.impersonation import ImpersonationLog  # noqa: F401


class TenantUserManager(models.Manager):
    """
    Tenant-scoped manager for CustomUser.

    Use this (tenant_objects) for any query that lists or counts users belonging
    to the current org: team management pages, notification recipient resolution,
    analytics owner lookups.

    DO NOT use for auth flows (login, session reload, password reset, email
    verification, impersonation lookups). Those must use the default `objects`
    manager which is unscoped.

    Why RLS is intentionally omitted from accounts_user:
        Django's authentication backend calls User._default_manager.get(pk=...)
        and get_by_natural_key(email) without any tenant context. The session
        middleware also calls User.objects.get(pk=...) on every request before
        TenantMiddleware has had a chance to set app.current_org_id. Enabling
        RLS on this table would break login and session management entirely.
        This manager provides the ORM-layer tenant guard without requiring
        DB-level RLS.
    """

    def get_queryset(self):
        from apps.infrastructure.core.rls import get_current_org
        org = get_current_org()
        if org is None:
            return super().get_queryset().none()
        return super().get_queryset().filter(org=org)


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email)
        extra_fields.setdefault("is_active", True)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", "super_admin")
        if extra_fields.get("username") is None:
            extra_fields["username"] = email
        return self.create_user(email, password, **extra_fields)


class CustomUser(AbstractUser):
    ROLE_CHOICES = [
        ("owner", "Owner"),
        ("manager", "Manager"),
        ("supervisor", "Supervisor"),
        ("data_entry", "Data Entry"),
        ("vet_advisor", "Vet Advisor"),
        ("super_admin", "Super Admin"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey(
        "tenants.Organization",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="users",
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="data_entry")
    phone = models.CharField(max_length=20, blank=True)
    bio = models.TextField(blank=True, default="")

    # Location / locale — captured at registration, editable on the profile page.
    country = models.CharField(max_length=100, blank=True)
    state_region = models.CharField(max_length=100, blank=True)
    timezone = models.CharField(max_length=50, blank=True)  # auto-set from country
    language_code = models.CharField(max_length=10, blank=True, default="en")

    email_verified = models.BooleanField(default=False)
    email_verification_token = models.UUIDField(default=uuid.uuid4, editable=False)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    email = models.EmailField(unique=True)

    objects = UserManager()           # default — used by Django auth; unscoped
    tenant_objects = TenantUserManager()  # use for all tenant-scoped user queries

    class Meta:
        db_table = "accounts_user"

    def __str__(self):
        return f"{self.email} ({self.role})"

    @property
    def is_owner(self):
        return self.role == "owner"

    @property
    def is_manager(self):
        return self.role == "manager"

    @property
    def is_supervisor_or_above(self):
        return self.role in ("owner", "manager", "supervisor")

    @property
    def full_name(self):
        return self.get_full_name() or self.email
