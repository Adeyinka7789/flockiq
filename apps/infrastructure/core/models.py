import uuid

from django.db import models

from .managers import TenantAwareManager


class UUIDModel(models.Model):
    """Abstract base: replaces Django's integer PK with a UUID."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class TimeStampedModel(models.Model):
    """Abstract base: automatic created_at / updated_at timestamps."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class TenantAwareModel(UUIDModel, TimeStampedModel):
    """
    Abstract base for every tenant-scoped model in FlockIQ.

    ARCHITECTURE INVARIANTS (never violate):
    1. Every subclass must have a migration that calls enable_rls() from
       apps/infrastructure/core/migrations/rls_helpers.py.
    2. All business logic touching this model goes in services.py,
       never in the model itself or in views.
    3. Celery tasks must call set_tenant_context(org_id) before any ORM query.

    Uses a string reference 'tenants.Organization' to avoid circular imports —
    the tenants app is loaded after core in INSTALLED_APPS.
    """

    org = models.ForeignKey(
        "tenants.Organization",
        on_delete=models.PROTECT,
        related_name="+",  # No reverse relation — prevents accidental cross-tenant traversal
        db_index=True,
    )

    objects = TenantAwareManager()

    class Meta:
        abstract = True
