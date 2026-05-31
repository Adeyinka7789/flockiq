from django.db import models

from .rls import get_current_org


class TenantAwareManager(models.Manager):
    """
    Default manager for all TenantAwareModel subclasses.

    Automatically scopes querysets to the current tenant set by TenantMiddleware
    (HTTP requests) or set_tenant_context() (Celery tasks).

    If no org context is present this returns qs.none() — the safe fail-closed
    default (Section 1 Prime Directive: no query may execute without an active
    app.current_org_id). This means programming errors surface as empty results,
    not data leaks.

    The two-layer design is intentional:
        Layer 1 — ORM (this manager): filters org=<current_org> before SQL is emitted.
        Layer 2 — PostgreSQL RLS: rejects rows where org_id ≠ current_setting(...).
    An ORM bug cannot leak data because the DB will silently return nothing.
    An RLS misconfiguration will be caught by this filter. Neither layer alone suffices.
    """

    def get_queryset(self):
        qs = super().get_queryset()
        org = get_current_org()
        if org is None:
            # In Celery tasks: context is set explicitly via set_tenant_context().
            # In management commands: use no_tenant_context().
            # Reaching here without a context is a programming error.
            # Return empty queryset rather than leaking all tenants' data.
            return qs.none()
        return qs.filter(org=org)

    def unscoped(self):
        """
        Escape hatch for super-admin / cross-tenant operations ONLY.
        Returns the raw queryset bypassing tenant filtering.

        Permitted uses:
            - Admin views that deliberately show cross-tenant data
            - Celery Beat tasks that fan out across all tenants

        NEVER call this in tenant-scoped views, services, or API endpoints.
        Every call site must have a comment explaining why it is safe.
        """
        return super().get_queryset()
