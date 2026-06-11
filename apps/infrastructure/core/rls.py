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

import uuid as _uuid_module
from contextvars import ContextVar
from contextlib import contextmanager

import structlog
from django.db import DatabaseError, connection, transaction

logger = structlog.get_logger(__name__)

NO_TENANT_UUID = "00000000-0000-0000-0000-000000000000"
_current_org = ContextVar("current_org", default=None)
# True while execution is inside a set_tenant_context()/no_tenant_context() block,
# i.e. inside a transaction that has applied the RLS GUC (Layer 2). bind_org()
# deliberately leaves this False: it sets only the Layer-1 ContextVar without a
# transaction/GUC. Used to tell a correctly-scoped query apart from a "straggler"
# that is bound to an org but running outside any RLS GUC scope.
_rls_active = ContextVar("rls_active", default=False)


# ── Public accessors ────────────────────────────────────────────────────────

def get_current_org():
    """Returns the Organization instance bound to the current thread, or None."""
    return _current_org.get()


def get_current_org_id():
    """Returns str(org.id) for the current tenant, or None."""
    org = get_current_org()
    return str(org.id) if org else None


def is_rls_scope_active():
    """True when inside a set_tenant_context()/no_tenant_context() block.

    False when only bind_org() is active (Layer-1 ContextVar set, but no
    transaction/RLS GUC). Lets callers distinguish a properly-scoped query from
    a straggler running outside any RLS GUC scope.
    """
    return _rls_active.get()


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

    token = _current_org.set(org)
    active_token = _rls_active.set(True)

    try:
        with transaction.atomic():
            _set_pg_org_id(str(org.id))
            yield org
    finally:
        # Restore previous context (supports nested set_tenant_context calls).
        _rls_active.reset(active_token)
        _current_org.reset(token)
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
    token = _current_org.set(None)
    active_token = _rls_active.set(True)

    try:
        with transaction.atomic():
            _set_pg_org_id(NO_TENANT_UUID)
            yield
    finally:
        _rls_active.reset(active_token)
        _current_org.reset(token)


@contextmanager
def bind_org(org):
    """
    Bind the tenant ContextVar (Layer 1) WITHOUT opening a transaction or setting
    the PostgreSQL RLS GUC (Layer 2).

    Used by TenantMiddleware so a request is no longer wrapped in one long-lived
    transaction. The old per-request set_tenant_context() held transaction.atomic()
    open for the entire request — including external HTTP calls (Paystack, weather,
    PDF) — which pinned a PgBouncer backend connection for the whole request.

    bind_org() sets only the thread/context org so TenantAwareManager keeps filtering
    by org for the whole request. Each view/task still opens its own short-lived
    set_tenant_context() block around its actual DB work, which supplies the GUC
    (Layer-2 RLS) inside a short transaction that is released before any external call.

    Accepts an Organization instance, a UUID, or None.
    """
    from apps.infrastructure.tenants.models import Organization  # noqa: PLC0415

    if org is not None and not isinstance(org, Organization):
        # Organization has RLS disabled — safe to query without an active context.
        org = Organization.objects.get(id=str(org))

    token = _current_org.set(org)
    try:
        yield org
    finally:
        _current_org.reset(token)


# ── Assertion helper ────────────────────────────────────────────────────────

def assert_tenant_context():
    """
    Guards against accidentally querying tenant tables without a context.
    Call at the start of any service method that must be tenant-scoped.

    Behaviour:
        DEBUG=True  → raises RuntimeError immediately (surface the bug early)
        DEBUG=False → Sentry alert + error log (fail-safe; do not crash
                      production, but never fail silently — a missing context
                      means RLS returns empty rows and pages render blank)

    Skipped on SQLite (dev fallback without full PostgreSQL RLS support).
    """
    if "sqlite" in connection.vendor:
        return

    with connection.cursor() as cursor:
        cursor.execute("SELECT current_setting('app.current_org_id', TRUE)")
        value = cursor.fetchone()[0]

    if not value:
        import sentry_sdk
        from django.conf import settings

        sentry_sdk.capture_message(
            "assert_tenant_context: no tenant context active",
            level="error",
        )
        logger.error(
            "tenant_context.missing",
            stack_info=True,
            hint="Ensure set_tenant_context() wraps all DB ops in Celery tasks",
        )
        if settings.DEBUG:
            raise RuntimeError(
                "No tenant context active. "
                "Wrap this call in set_tenant_context()."
            )


# ── Internal helpers ────────────────────────────────────────────────────────

def _set_pg_org_id(org_id_str: str) -> None:
    """Execute SET LOCAL for app.current_org_id. No-op on SQLite."""
    if "sqlite" in connection.vendor:
        return
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT set_config('app.current_org_id', %s, TRUE)",
                [org_id_str],
            )
    except DatabaseError:
        logger.exception("tenant_context.pg_set_failed", org_id=org_id_str)
        raise
