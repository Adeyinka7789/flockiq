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
    """Org lifecycle: creation, suspension, reactivation, and owner resolution."""

    @staticmethod
    def create_organization(
        org_name: str,
        subdomain: str,
        owner_email: str,
        owner_password: str | None = None,
        owner_name: str = "",
        owner_first_name: str = "",
        owner_last_name: str = "",
        owner_phone: str = "",
        country: str = "Nigeria",
        state_region: str = "",
        timezone: str | None = None,
        trial_days: int = 14,
    ) -> tuple:
        """Single authoritative path for creating a tenant org + its owner user.

        Both the web signup flow (SignupView) and the API onboarding flow
        (TenantOnboardingView) call this so field defaults, the trial window,
        and country-scoping stay identical regardless of entry point.

        ``country`` is written to BOTH the Organization and the owner user, so
        community market data is scoped correctly for non-Nigerian tenants no
        matter which entry point they signed up through.

        If ``owner_password`` is falsy a temporary password is generated and
        returned (the API onboarding path surfaces it to the caller); when a
        password is supplied the third tuple element is ``None``.

        Returns: ``(org, user, temp_password_if_generated)``
        """
        import secrets
        from datetime import timedelta

        from django.db import transaction
        from django.utils import timezone as dj_timezone

        from apps.infrastructure.accounts.constants import timezone_for_country
        from apps.infrastructure.accounts.models import CustomUser

        from .models import Organization

        country = country or "Nigeria"
        if timezone is None:
            timezone = timezone_for_country(country)

        # Derive first/last from owner_name when not supplied explicitly.
        if not owner_first_name and not owner_last_name and owner_name:
            parts = owner_name.split()
            owner_first_name = parts[0] if parts else ""
            owner_last_name = " ".join(parts[1:]) if len(parts) > 1 else ""

        temp_password = None
        if not owner_password:
            temp_password = secrets.token_urlsafe(12)
            owner_password = temp_password

        with transaction.atomic():
            org = Organization.objects.create(
                name=org_name,
                subdomain=subdomain,
                owner_name=owner_name,
                owner_email=owner_email,
                owner_phone=owner_phone,
                country=country,
                plan_tier="trial",
                subscription_status="trial",
                trial_ends_at=dj_timezone.now() + timedelta(days=trial_days),
                is_active=True,
            )
            user = CustomUser.objects.create_user(
                email=owner_email,
                username=owner_email,
                password=owner_password,
                first_name=owner_first_name,
                last_name=owner_last_name,
                phone=owner_phone,
                country=country,
                state_region=state_region,
                timezone=timezone,
                org=org,
                role="owner",
                is_active=True,
            )

        logger.info(
            "tenant.created",
            org_id=str(org.pk),
            owner_email=owner_email,
            country=country,
        )

        return org, user, temp_password

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
