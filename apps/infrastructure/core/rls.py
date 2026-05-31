"""
Row-Level Security context management.

ARCHITECTURE NOTE — why transaction.atomic() is required here:
    set_config('app.current_org_id', value, TRUE) uses is_local=TRUE, which means
    the setting is transaction-scoped (SET LOCAL semantics in PostgreSQL).
    In Django's autocommit mode, each cursor.execute() runs in its own implicit
    micro-transaction that commits immediately — so the setting would be cleared
    before any subsequent query could see it.
    Wrapping in transaction.atomic() opens a real transaction (or savepoint if
    nested), keeping the setting alive for the entire block.
    With PgBouncer in transaction mode, connections are shared between tenants.
    is_local=TRUE ensures the setting cannot leak to the next tenant's transaction
    even if PgBouncer reuses the same backend connection.
"""

import threading
import uuid as _uuid_module
from contextlib import contextmanager

import structlog
from django.db import connection, transaction

logger = structlog.get_logger(__name__)

_thread_local = threading.local()


# ── Public accessors ────────────────────────────────────────────────────────

def get_current_org():
    """Returns the Organization instance bound to the current thread, or None."""
    return getattr(_thread_local, "current_org", None)


def get_current_org_id():
    """Returns str(org.id) for the current tenant, or None."""
    org = get_current_org()
    return str(org.id) if org else None


# ── Context managers ────────────────────────────────────────────────────────

@contextmanager
def set_tenant_context(org):
    """
    Sets the RLS context for the duration of the block.
    Accepts an Organization instance or a UUID (str or uuid.UUID).

    HTTP middleware usage (automatic — called by TenantMiddleware):
        with set_tenant_context(org):
            response = get_response(request)

    Celery task usage (explicit — MUST wrap all DB ops):
        with set_tenant_context(org_id):
            org = Organization.objects.get(id=org_id)
            SomeService(org).do_work()

    Wraps body in transaction.atomic() so set_config(is_local=TRUE) is
    genuinely transaction-scoped — see module docstring for rationale.
    """
    # Inline import: tenants app is built in Phase 1C; avoids import-time circular dep
    from apps.infrastructure.tenants.models import Organization  # noqa: PLC0415

    if not isinstance(org, Organization):
        # Celery pattern: receive org_id string, fetch org object.
        # Organization has RLS disabled — safe to query without an active context.
        org = Organization.objects.get(id=str(org))

    previous = getattr(_thread_local, "current_org", None)
    _thread_local.current_org = org

    try:
        with transaction.atomic():
            _set_pg_org_id(str(org.id))
            yield org
    finally:
        # Restore previous context (supports nested set_tenant_context calls,
        # though nesting is strongly discouraged in production code).
        _thread_local.current_org = previous
        # The DB session variable is cleared automatically when transaction.atomic()
        # commits or rolls back (is_local=TRUE). No explicit clear needed here.


@contextmanager
def no_tenant_context():
    """
    Explicitly marks a block as intentionally cross-tenant.

    Use ONLY in:
    - Celery Beat fan-out tasks that read org IDs from the Organization table
    - Management commands performing cross-tenant aggregation
    - Celery tasks that iterate all active orgs before dispatching per-org subtasks

    The Organization table has RLS DISABLED — it is the only table safe to query
    inside this block. Never query a TenantAwareModel here; you will get all rows.
    """
    previous = getattr(_thread_local, "current_org", None)
    _thread_local.current_org = None

    try:
        with transaction.atomic():
            _set_pg_org_id("")
            yield
    finally:
        _thread_local.current_org = previous


# ── Assertion helper ────────────────────────────────────────────────────────

def assert_tenant_context():
    """
    Guards against accidentally querying tenant tables without a context.
    Call at the start of any service method that must be tenant-scoped.

    Behaviour:
        DEBUG=True  → raises RuntimeError immediately (surface the bug early)
        DEBUG=False → logs error (fail-safe; do not crash production on misconfiguration)

    Skipped on SQLite (dev fallback without full PostgreSQL RLS support).
    """
    if "sqlite" in connection.vendor:
        return

    with connection.cursor() as cursor:
        cursor.execute("SELECT current_setting('app.current_org_id', TRUE)")
        value = cursor.fetchone()[0]

    if not value:
        msg = "Tenant context not set — query would return empty resultset or all rows."
        from django.conf import settings
        if settings.DEBUG:
            raise RuntimeError(msg)
        else:
            logger.error("tenant_context.missing", hint="Ensure set_tenant_context() wraps all DB ops in Celery tasks")


# ── Internal helpers ────────────────────────────────────────────────────────

def _set_pg_org_id(org_id_str: str) -> None:
    """Execute SET LOCAL for app.current_org_id. No-op on SQLite."""
    if "sqlite" in connection.vendor:
        return
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT set_config('app.current_org_id', %s, TRUE)",
            [org_id_str],
        )
