import structlog
from django.conf import settings as django_settings
from django.db import transaction
from django.urls import reverse

logger = structlog.get_logger(__name__)

VALID_STATUSES = ("open", "in_progress", "resolved")


class SupportTicketService:
    """
    Single authoritative path for all support ticket operations.

    Both the tenant-side reply flow (notifications/views.py) and the
    superadmin-side reply flow (superadmin/views.py) call this service —
    ensuring consistent notification behaviour regardless of who replies.
    A feature added here (e.g. Termii SMS on reply) automatically applies
    to both sides instead of having to be added independently.
    """

    @staticmethod
    def add_reply(ticket, author, message, new_status=None):
        """
        Add a reply to a support ticket.

        Handles, in a single atomic transaction:
          - Creating the SupportTicketReply record
          - Notifying superadmins (AdminNotification) when a tenant replies
          - Notifying the tenant submitter (email + bell) when a superadmin replies
          - Status transition (only when author is a superadmin)

        Args:
            ticket: SupportTicket instance
            author: CustomUser adding the reply
            message: reply text
            new_status: optional new ticket status ('open', 'in_progress',
                'resolved') — only applied when author.is_superuser

        Returns:
            The created SupportTicketReply.
        """
        from apps.infrastructure.accounts.models import CustomUser
        from apps.infrastructure.core.email_service import EmailService
        from apps.infrastructure.core.rls import set_tenant_context
        from .models import AdminNotification, SupportTicketReply
        from .services import NotificationService

        with transaction.atomic():
            # 1. Create the reply.
            reply = SupportTicketReply.objects.create(
                ticket=ticket,
                author=author,
                message=message,
            )

            # 2. Status transition (superadmin only).
            if (new_status and author.is_superuser
                    and new_status in VALID_STATUSES):
                ticket.status = new_status
                ticket.save(update_fields=["status", "updated_at"])

            # 3. Notify superadmins when a tenant replies.
            if not author.is_superuser:
                followup_url = reverse(
                    "superadmin:support_ticket_detail",
                    kwargs={"pk": ticket.pk},
                )
                for su in CustomUser.objects.filter(is_superuser=True):
                    AdminNotification.objects.create(
                        recipient=su,
                        title=f"[Support follow-up] {ticket.subject} | {ticket.org.name}",
                        body=f"{author.email}: {message[:200]}",
                        action_url=followup_url,
                    )

            # 4. Notify the tenant submitter when a superadmin replies.
            elif author.is_superuser and ticket.submitted_by:
                # Email — failure must not roll back the reply / status change.
                try:
                    base_url = getattr(
                        django_settings, "SITE_URL", "https://app.flockiq.com"
                    )
                    ticket_url = (
                        f"{base_url.rstrip('/')}/support/my-tickets/{ticket.pk}/"
                    )
                    EmailService.send_support_reply(
                        recipient_email=ticket.submitted_by.email,
                        owner_name=(
                            ticket.submitted_by.get_full_name()
                            or ticket.submitted_by.email
                        ),
                        subject=ticket.subject,
                        reply_message=message,
                        ticket_url=ticket_url,
                    )
                except Exception:
                    logger.exception(
                        "ticket.reply_email_failed",
                        ticket_id=str(ticket.pk),
                    )

                # Bell notification — NotificationLog is RLS-protected, so the
                # write must run inside the ticket's tenant context. Routed
                # through notify() for the _should_receive gate.
                with set_tenant_context(ticket.org):
                    NotificationService(ticket.org).notify(
                        recipient=ticket.submitted_by,
                        event_type="support_reply",
                        title=f"Support ticket update — {ticket.subject}",
                        body=f"Admin replied: {message[:200]}",
                        severity="info",
                        action_url=reverse(
                            "notifications:support_ticket_detail",
                            kwargs={"pk": ticket.pk},
                        ),
                    )

        return reply
