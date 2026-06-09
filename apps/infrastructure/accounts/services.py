"""Account-level business logic for NDPR compliance (data export + deletion).

Per architecture rule #3, all business logic lives here rather than in views.

NDPR (Nigeria Data Protection Regulation) gives users two rights this module
implements:
  - Right to data portability → build_data_export()
  - Right to erasure        → delete_organisation() / a plain user.delete()
"""
from __future__ import annotations

import structlog
from django.apps import apps
from django.db import transaction
from django.db.models import ProtectedError
from django.utils import timezone

from apps.infrastructure.core.rls import set_tenant_context

logger = structlog.get_logger(__name__)


# ── Data export ──────────────────────────────────────────────────────────────

def build_data_export(user, org) -> dict:
    """Compile every piece of personal + organisation data tied to ``user``.

    Returns a JSON-serialisable dict (datetimes/UUIDs/Decimals are left as-is and
    rendered by json.dumps(default=str) at the call site). Org-level collections
    are only included when the user owns the organisation.
    """
    # Local imports keep this module import-light and avoid app-load cycles.
    from axes.models import AccessLog

    from apps.infrastructure.notifications.models import NotificationLog, SupportTicket

    data: dict = {"exported_at": timezone.now().isoformat()}

    with set_tenant_context(org):
        # ── User data ──────────────────────────────────────────────────────
        data["user"] = {
            "email": user.email,
            "name": user.get_full_name(),
            "phone": getattr(user, "phone", ""),
            "country": getattr(user, "country", ""),
            "state_region": getattr(user, "state_region", ""),
            "role": user.role,
            "joined": str(user.date_joined),
            "timezone": getattr(user, "timezone", ""),
        }

        # Login history — last 10 records from django-axes (not org-scoped).
        data["login_history"] = list(
            AccessLog.objects.filter(username=user.email)
            .order_by("-attempt_time")
            .values("attempt_time", "ip_address", "user_agent")[:10]
        )

        # Support tickets the user submitted.
        data["support_tickets"] = list(
            SupportTicket.objects.filter(submitted_by=user).values(
                "subject", "message", "priority", "status", "created_at"
            )
        )

        # In-app notifications the user received.
        data["notifications"] = list(
            NotificationLog.objects.filter(recipient=user).values(
                "title", "body", "event_type", "severity", "is_read", "created_at"
            )
        )

        # ── Organisation data (owner only) ─────────────────────────────────
        if user.role == "owner":
            from apps.farm.farms.models import Farm, House
            from apps.farm.flocks.models import Batch, MortalityLog
            from apps.finance.expenses.models import ExpenseRecord
            from apps.finance.finance.models import SalesRecord
            from apps.health.health.models import VaccinationSchedule
            from apps.infrastructure.billing.models import PaymentRecord
            from apps.production.feed.models import FeedLog
            from apps.production.production.models import EggProductionLog
            from apps.production.water.models import WaterLog

            data["organisation"] = {
                "name": org.name,
                "subdomain": org.subdomain,
                "plan": org.plan_tier,
                "subscription_status": org.subscription_status,
                "created": str(org.created_at),
            }
            data["farms"] = list(Farm.objects.values())
            data["houses"] = list(House.objects.values())
            data["batches"] = list(Batch.objects.values())
            data["mortality_logs"] = list(MortalityLog.objects.values())
            data["feed_logs"] = list(FeedLog.objects.values())
            data["egg_production_logs"] = list(EggProductionLog.objects.values())
            data["water_logs"] = list(WaterLog.objects.values())
            data["vaccination_schedules"] = list(VaccinationSchedule.objects.values())
            data["expenses"] = list(ExpenseRecord.objects.values())
            data["sales"] = list(SalesRecord.objects.values())
            data["payments"] = list(PaymentRecord.objects.values())

    return data


# ── Account / organisation deletion ──────────────────────────────────────────

def _org_scoped_models() -> list:
    """Every concrete model with a direct FK named ``org`` to Organization."""
    from apps.infrastructure.tenants.models import Organization

    models = []
    for model in apps.get_models():
        try:
            field = model._meta.get_field("org")
        except Exception:
            continue
        if field.is_relation and field.related_model is Organization:
            models.append(model)
    return models


def delete_organisation(org) -> None:
    """Permanently delete an organisation and every row that belongs to it.

    Every tenant FK uses ``on_delete=PROTECT`` (see TenantAwareModel), and
    CustomUser.org is PROTECT too — so a plain ``org.delete()`` raises
    ProtectedError. We instead clear each org-scoped model inside the tenant RLS
    context, retrying in passes: a model still referenced by an un-deleted child
    (another PROTECT FK between tenant models) simply gets deferred to a later
    pass once that child is gone. Once nothing references the org, the
    Organization row itself is removed.
    """
    models = _org_scoped_models()

    with set_tenant_context(org):
        pending = list(models)
        # Worst case a dependency chain needs one pass per model to unwind.
        for _ in range(len(pending) + 1):
            if not pending:
                break
            blocked = []
            for model in pending:
                try:
                    with transaction.atomic():  # savepoint: isolate PROTECT failures
                        model._base_manager.filter(org=org).delete()
                except ProtectedError:
                    blocked.append(model)
            if len(blocked) == len(pending):
                # No progress this pass — a PROTECT cycle we can't resolve.
                names = ", ".join(m.__name__ for m in blocked)
                raise RuntimeError(f"Could not delete org data — blocked models: {names}")
            pending = blocked

    # Organization has RLS disabled and is now unreferenced — safe to delete.
    org.delete()
    logger.info("organisation_deleted", org_id=str(org.id))
