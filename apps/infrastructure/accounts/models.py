import uuid

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models

from apps.infrastructure.accounts.impersonation import ImpersonationLog  # noqa: F401


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

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    email = models.EmailField(unique=True)

    objects = UserManager()

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
