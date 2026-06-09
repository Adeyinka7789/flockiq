"""Centralised HTML email sending for FlockIQ.

Every email in the platform should go through EmailService. Content lives in
templates/emails/ (extending emails/base_email.html); this module is the single
place that renders those templates and hands them to Django's mail backend.

Convention: each `send_*` helper builds the template context and delegates to
`EmailService.send()`, which injects shared context (support_email, site_url),
renders the HTML, derives a plain-text fallback, and dispatches a
multipart/alternative message.
"""
from __future__ import annotations

import structlog
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags

logger = structlog.get_logger(__name__)


class EmailService:
    """Single entry point for all transactional email in FlockIQ."""

    @staticmethod
    def send(
        template_name: str,
        subject: str,
        recipient_email: str,
        context: dict | None = None,
        fail_silently: bool = True,
    ) -> bool:
        """Render an HTML email template and send it.

        Args:
            template_name: Path relative to templates/emails/
                           e.g. 'billing/plan_activated.html'
            subject: Email subject line.
            recipient_email: Recipient email address.
            context: Template context variables.
            fail_silently: Whether to suppress send errors.

        Returns:
            True if sent successfully, False otherwise.
        """
        if not recipient_email:
            logger.warning("email.no_recipient", template=template_name)
            return False

        ctx = {
            "support_email": settings.SUPPORT_EMAIL,
            "site_url": settings.SITE_URL,
            **(context or {}),
        }

        try:
            html_content = render_to_string(f"emails/{template_name}", ctx)
            # Plain-text fallback derived from the rendered HTML.
            text_content = strip_tags(html_content).strip()

            msg = EmailMultiAlternatives(
                subject=subject,
                body=text_content,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[recipient_email],
            )
            msg.attach_alternative(html_content, "text/html")
            msg.send(fail_silently=fail_silently)
            logger.info(
                "email.sent", template=template_name, recipient=recipient_email
            )
            return True
        except Exception as exc:
            logger.error(
                "email.send_failed",
                template=template_name,
                recipient=recipient_email,
                error=str(exc),
            )
            if not fail_silently:
                raise
            return False

    # ------------------------------------------------------------------
    # Accounts
    # ------------------------------------------------------------------
    @staticmethod
    def send_verification(user, verification_url: str) -> bool:
        return EmailService.send(
            template_name="accounts/email_verification.html",
            subject="Verify your FlockIQ account",
            recipient_email=user.email,
            context={"user": user, "verification_url": verification_url},
        )

    @staticmethod
    def send_password_reset(user, reset_url: str) -> bool:
        return EmailService.send(
            template_name="accounts/password_reset.html",
            subject="Reset your FlockIQ password",
            recipient_email=user.email,
            context={"user": user, "reset_url": reset_url},
        )

    @staticmethod
    def send_account_deleted(user, org=None) -> bool:
        """Farewell email sent after a user deletes their account (NDPR erasure)."""
        return EmailService.send(
            template_name="accounts/account_deleted.html",
            subject="Your FlockIQ account has been deleted",
            recipient_email=user.email,
            context={
                "user_name": user.get_full_name() or user.email,
                "org_name": org.name if org else "",
                "is_owner": org is not None,
            },
        )

    @staticmethod
    def send_team_invite(
        recipient_email: str,
        first_name: str,
        org_name: str,
        temp_password: str,
        login_url: str,
    ) -> bool:
        return EmailService.send(
            template_name="accounts/team_invite.html",
            subject=f"You've been invited to {org_name} on FlockIQ",
            recipient_email=recipient_email,
            context={
                "first_name": first_name,
                "org_name": org_name,
                "login_email": recipient_email,
                "temp_password": temp_password,
                "login_url": login_url,
            },
        )

    # ------------------------------------------------------------------
    # Billing
    # ------------------------------------------------------------------
    @staticmethod
    def send_plan_activated(
        owner,
        org,
        plan_name: str,
        expires_at,
        action: str,
        activated_by: str,
    ) -> bool:
        return EmailService.send(
            template_name="billing/plan_activated.html",
            subject=f"Your FlockIQ plan has been {action}",
            recipient_email=owner.email,
            context={
                "owner_name": owner.get_full_name() or owner.email,
                "org_name": org.name,
                "plan_name": plan_name.title(),
                "expires_at": expires_at,
                "action": action,
                "activated_by": activated_by,
            },
        )

    @staticmethod
    def send_expiry_reminder(owner, org, days_left: int) -> bool:
        urgency = "today" if days_left <= 1 else f"in {days_left} days"
        return EmailService.send(
            template_name="billing/plan_expiry_reminder.html",
            subject=f"Your FlockIQ plan expires {urgency}",
            recipient_email=owner.email,
            context={
                "owner_name": owner.get_full_name() or owner.email,
                "org_name": org.name,
                "plan_name": org.plan_tier.title(),
                "expires_at": org.plan_expires_at,
                "days_left": days_left,
                "urgency": urgency,
            },
        )

    @staticmethod
    def send_trial_ending(owner_email: str, owner_name: str, org_name: str,
                          days_left: int) -> bool:
        return EmailService.send(
            template_name="billing/trial_ending.html",
            subject=f"Your FlockIQ trial ends in {days_left} days",
            recipient_email=owner_email,
            context={
                "owner_name": owner_name,
                "org_name": org_name,
                "days_left": days_left,
            },
        )

    @staticmethod
    def send_upgrade_request_admin(org, plan_tier: str, plan,
                                   owner_email: str) -> bool:
        return EmailService.send(
            template_name="billing/upgrade_request_admin.html",
            subject=f"[FlockIQ] Upgrade Request — {org.name}",
            recipient_email=settings.ADMIN_EMAIL,
            context={
                "org_name": org.name,
                "subdomain": org.subdomain,
                "owner_email": owner_email,
                "plan_name": plan_tier.title(),
                "plan_tier": plan_tier,
                "plan_price": f"{plan.amount_kobo // 100:,}",
            },
        )

    @staticmethod
    def send_upgrade_request_received(owner_email: str, owner_name: str,
                                      org_name: str, plan_tier: str) -> bool:
        return EmailService.send(
            template_name="billing/upgrade_request_received.html",
            subject="Your FlockIQ upgrade request has been received",
            recipient_email=owner_email,
            context={
                "owner_name": owner_name,
                "org_name": org_name,
                "plan_name": plan_tier.title(),
            },
        )

    # ------------------------------------------------------------------
    # Tenants (suspension / reactivation)
    # ------------------------------------------------------------------
    @staticmethod
    def send_suspension(recipient_email: str, owner_name: str, org_name: str,
                        reason: str) -> bool:
        return EmailService.send(
            template_name="tenants/suspension.html",
            subject="Your FlockIQ account has been suspended",
            recipient_email=recipient_email,
            context={
                "owner_name": owner_name,
                "org_name": org_name,
                "reason": reason,
            },
        )

    @staticmethod
    def send_reactivation(recipient_email: str, owner_name: str,
                          org_name: str, login_url: str) -> bool:
        return EmailService.send(
            template_name="tenants/reactivation.html",
            subject="Your FlockIQ account has been reactivated",
            recipient_email=recipient_email,
            context={
                "owner_name": owner_name,
                "org_name": org_name,
                "login_url": login_url,
            },
        )

    # ------------------------------------------------------------------
    # Support tickets
    # ------------------------------------------------------------------
    @staticmethod
    def send_support_ticket(admin_email: str, org_name: str, user_email: str,
                            priority: str, subject: str, message: str,
                            submitted_at) -> bool:
        return EmailService.send(
            template_name="support/ticket_received.html",
            subject=(
                f"[FlockIQ Support] {priority.upper()} — {subject} | {org_name}"
            ),
            recipient_email=admin_email,
            context={
                "org_name": org_name,
                "user_email": user_email,
                "priority": priority.upper(),
                "subject": subject,
                "message": message,
                "submitted_at": submitted_at,
            },
        )

    @staticmethod
    def send_support_reply(recipient_email: str, owner_name: str, subject: str,
                           reply_message: str, ticket_url: str) -> bool:
        return EmailService.send(
            template_name="support/ticket_reply.html",
            subject=f"Re: {subject} — FlockIQ Support",
            recipient_email=recipient_email,
            context={
                "owner_name": owner_name,
                "subject": subject,
                "reply_message": reply_message,
                "ticket_url": ticket_url,
            },
        )
