"""Organization lifecycle orchestration.

TenantService owns org-level lifecycle actions — suspension and reactivation —
and the owner-facing email that accompanies each. Every suspension/reactivation
trigger (manual superadmin action, billing webhook, future automation) should
route through here rather than flipping ``org.is_active`` and sending email
inline, so the owner-notification behaviour stays in one place.
"""
from __future__ import annotations

import structlog
from django.conf import settings
from django.core.cache import cache

from apps.infrastructure.core.email_service import EmailService

logger = structlog.get_logger(__name__)


class TenantService:
    """Org lifecycle: suspension, reactivation, and owner resolution."""

    @staticmethod
    def get_org_owner(org):
        """Return the org's owner user (role='owner'), falling back to any member.

        Uses the reverse FK (related_name='users'), whose default manager is
        unscoped — safe here because superadmin / billing callers run without a
        tenant context.
        """
        owner = org.users.filter(role="owner").first()
        if not owner:
            owner = org.users.first()
        return owner

    @staticmethod
    def suspend_org(org, reason: str = "", suspended_by=None) -> None:
        """Suspend an organization — blocks access and notifies the owner.

        Extracted from superadmin/views.py module-level send_suspension_email().
        All suspension triggers (manual superadmin action, billing webhook,
        future automation) should call this method.
        """
        org.is_active = False
        org.suspension_reason = reason
        org.save(update_fields=["is_active", "suspension_reason", "updated_at"])

        # Drop the TenantMiddleware org-active cache so the suspension takes
        # effect on the org's very next request instead of after the TTL.
        cache.delete(f"org_active:{org.id}")

        TenantService._send_suspension_email(org)

        logger.info(
            "tenant.suspended",
            org_id=str(org.pk),
            suspended_by=str(suspended_by.pk) if suspended_by else None,
        )

    @staticmethod
    def reactivate_org(org, reactivated_by=None) -> None:
        """Reactivate a suspended organization and notify the owner.

        Extracted from superadmin/views.py module-level send_reactivation_email().
        """
        org.is_active = True
        org.suspension_reason = ""
        org.save(update_fields=["is_active", "suspension_reason", "updated_at"])

        cache.delete(f"org_active:{org.id}")

        TenantService._send_reactivation_email(org)

        logger.info(
            "tenant.reactivated",
            org_id=str(org.pk),
            reactivated_by=str(reactivated_by.pk) if reactivated_by else None,
        )

    @staticmethod
    def _send_suspension_email(org) -> None:
        """Resolve the org owner and email the suspension notice."""
        owner = TenantService.get_org_owner(org)
        recipient = (owner.email if owner and owner.email else None) or org.owner_email
        if not recipient:
            return
        name = (owner.get_full_name() if owner else "") or recipient
        EmailService.send_suspension(
            recipient_email=recipient,
            owner_name=name,
            org_name=org.name,
            reason=org.suspension_reason,
        )

    @staticmethod
    def _send_reactivation_email(org) -> None:
        """Resolve the org owner and email the reactivation notice."""
        owner = TenantService.get_org_owner(org)
        recipient = (owner.email if owner and owner.email else None) or org.owner_email
        if not recipient:
            return
        name = (owner.get_full_name() if owner else "") or recipient
        login_url = settings.SITE_URL.rstrip("/") + "/login/"
        EmailService.send_reactivation(
            recipient_email=recipient,
            owner_name=name,
            org_name=org.name,
            login_url=login_url,
        )
