import uuid

from django.conf import settings
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


class SoftDeleteMixin(models.Model):
    """
    Abstract mixin giving a model a reversible soft delete.

    Records are never removed from the database by user-facing delete views;
    they are flagged ``is_deleted=True`` with an audit trail (who/when). The
    model's default manager (ActiveManager) hides them; ``all_objects`` exposes
    them for the superadmin restore panel and the 90-day hard-delete sweep.

    A model using this mixin MUST also declare::

        objects = ActiveManager()
        all_objects = AllObjectsManager()

    so the default queryset excludes deleted rows everywhere automatically.
    """

    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deleted_%(class)ss",
    )

    class Meta:
        abstract = True

    def soft_delete(self, user=None):
        """Mark as deleted with audit trail. Idempotent."""
        from django.utils import timezone

        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.deleted_by = user
        self.save(update_fields=["is_deleted", "deleted_at", "deleted_by", "updated_at"])

    def restore(self, user=None):
        """Restore a soft-deleted record."""
        self.is_deleted = False
        self.deleted_at = None
        self.deleted_by = None
        self.save(update_fields=["is_deleted", "deleted_at", "deleted_by", "updated_at"])


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
