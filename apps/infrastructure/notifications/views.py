import json
import uuid

import structlog
from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.mail import send_mail
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View
from django.http import HttpResponse
from django.template.loader import render_to_string

from apps.infrastructure.core.helpers import get_org_or_404
from apps.infrastructure.core.rls import set_tenant_context
from .services import NotificationService

logger = structlog.get_logger(__name__)


class NotificationBellView(LoginRequiredMixin, View):
    def get(self, request):
        if not request.user.org:
            return HttpResponse("0")
        svc = NotificationService(request.user.org)
        with set_tenant_context(request.user.org):
            count = svc.get_unread_count(request.user)
        html = render_to_string(
            "notifications/_bell_count.html",
            {"unread_count": count},
            request=request,
        )
        return HttpResponse(html)


class NotificationDropdownView(LoginRequiredMixin, View):
    def get(self, request):
        if not request.user.org:
            return HttpResponse(render_to_string(
                "notifications/_dropdown.html",
                {"notifications": [], "unread_count": 0},
                request=request,
            ))
        with set_tenant_context(request.user.org):
            from .models import NotificationLog
            notifications = list(
                NotificationLog.objects.filter(
                    recipient=request.user,
                    is_read=False,
                ).order_by("-created_at")[:3]
            )
        html = render_to_string(
            "notifications/_dropdown.html",
            {"notifications": notifications},
            request=request,
        )
        return HttpResponse(html)


class NotificationsPageView(LoginRequiredMixin, View):
    def get(self, request):
        if not getattr(request.user, "org", None):
            return redirect("/")
        from .models import NotificationLog
        with set_tenant_context(request.user.org):
            all_notifications = list(
                NotificationLog.objects.filter(
                    recipient=request.user,
                ).order_by("-created_at")[:50]
            )
        unread = [n for n in all_notifications if not n.is_read]
        read = [n for n in all_notifications if n.is_read]
        return render(
            request,
            "notifications/notifications_page.html",
            {"unread": unread, "read": read},
        )


class MarkReadView(LoginRequiredMixin, View):
    def post(self, request, pk):
        svc = NotificationService(request.user.org)
        with set_tenant_context(request.user.org):
            svc.mark_read(pk)
            count = svc.get_unread_count(request.user)
        html = render_to_string(
            "notifications/_bell_count.html",
            {"unread_count": count},
            request=request,
        )
        response = HttpResponse(html)
        response["HX-Trigger"] = "notificationRead"
        return response


class MarkAllReadView(LoginRequiredMixin, View):
    def post(self, request):
        from django.utils import timezone
        from .models import NotificationLog
        with set_tenant_context(request.user.org):
            NotificationLog.objects.filter(
                org=request.user.org,
                recipient=request.user,
                is_read=False,
            ).update(is_read=True, read_at=timezone.now())
        html = render_to_string(
            "notifications/_dropdown.html",
            {"notifications": []},
            request=request,
        )
        return HttpResponse(html)


class AcknowledgeNotificationView(LoginRequiredMixin, View):
    """POST /notifications/<uuid>/acknowledge/ — Acknowledge a critical/warning alert."""

    def post(self, request, pk):
        from .models import NotificationLog

        with set_tenant_context(request.user.org):
            notif = get_object_or_404(NotificationLog, pk=pk, recipient=request.user)
            notif.acknowledged = True
            notif.acknowledged_at = timezone.now()
            notif.acknowledged_by = request.user
            notif.is_read = True
            notif.save(update_fields=["acknowledged", "acknowledged_at", "acknowledged_by", "is_read"])

        response = HttpResponse()
        response["HX-Trigger"] = json.dumps({
            "showToast": {"message": "Alert acknowledged", "type": "success"},
            "refreshBell": True,
        })
        return response


class MarkAllReadPageView(LoginRequiredMixin, View):
    def post(self, request):
        if not getattr(request.user, "org", None):
            return redirect("/")
        from django.utils import timezone
        from .models import NotificationLog
        with set_tenant_context(request.user.org):
            NotificationLog.objects.filter(
                org=request.user.org,
                recipient=request.user,
                is_read=False,
            ).update(is_read=True, read_at=timezone.now())
            all_notifications = list(
                NotificationLog.objects.filter(
                    recipient=request.user,
                ).order_by("-created_at")[:50]
            )
        unread = [n for n in all_notifications if not n.is_read]
        read = [n for n in all_notifications if n.is_read]
        response = render(
            request,
            "notifications/_notifications_list.html",
            {"unread": unread, "read": read},
        )
        response["HX-Trigger"] = json.dumps({
            "showToast": {"message": "All notifications marked as read", "type": "success"},
            "refreshBell": True,
        })
        return response


class MySupportTicketsView(LoginRequiredMixin, View):
    """GET /support/my-tickets/ — lists the current user's support tickets."""

    def get(self, request):
        from .models import SupportTicket
        tickets = SupportTicket.objects.filter(
            submitted_by=request.user
        ).order_by('-created_at')
        return render(request, "support/my_tickets.html", {"tickets": tickets})


class SupportTicketDetailUserView(LoginRequiredMixin, View):
    """GET/POST /support/my-tickets/<pk>/ — user views their ticket thread."""

    def get(self, request, pk):
        from .models import SupportTicket
        ticket = get_object_or_404(SupportTicket, pk=pk, submitted_by=request.user)
        replies = ticket.replies.select_related('author').all()
        return render(request, "support/ticket_detail.html", {
            "ticket": ticket,
            "replies": replies,
        })

    def post(self, request, pk):
        from apps.infrastructure.accounts.models import CustomUser
        from .models import SupportTicket, SupportTicketReply, AdminNotification

        ticket = get_object_or_404(SupportTicket, pk=pk, submitted_by=request.user)
        message = request.POST.get("message", "").strip()

        if not message or ticket.status == "resolved":
            replies = ticket.replies.select_related("author").all()
            return render(request, "support/ticket_detail.html", {
                "ticket": ticket,
                "replies": replies,
                "error": "Cannot reply — message is empty or ticket is resolved.",
            }, status=422)

        SupportTicketReply.objects.create(
            ticket=ticket,
            author=request.user,
            message=message,
        )

        for su in CustomUser.objects.filter(is_superuser=True):
            AdminNotification.objects.create(
                recipient=su,
                title=f"[Support follow-up] {ticket.subject} | {ticket.org.name}",
                body=f"{request.user.email}: {message[:200]}",
            )

        replies = ticket.replies.select_related("author").all()
        return render(request, "support/ticket_detail.html", {
            "ticket": ticket,
            "replies": replies,
        })


class SupportTicketFormView(LoginRequiredMixin, View):
    """GET /support/ticket/form/ — returns the form fragment."""

    def get(self, request):
        return render(request, "support/_ticket_form.html", {})


class SubmitSupportTicketView(LoginRequiredMixin, View):
    """POST /support/ticket/submit/ — saves ticket, notifies admins, sends email."""

    def post(self, request):
        from .models import AdminNotification, SupportTicket
        from apps.infrastructure.accounts.models import CustomUser

        org = get_org_or_404(request)
        subject = request.POST.get("subject", "").strip()
        message = request.POST.get("message", "").strip()
        priority = request.POST.get("priority", "medium").strip()

        if not subject or not message:
            return render(
                request,
                "support/_ticket_form.html",
                {"error": "Subject and message are required.", "priority": priority},
                status=422,
            )

        if priority not in ("low", "medium", "high"):
            priority = "medium"

        ticket = SupportTicket.objects.create(
            org=org,
            submitted_by=request.user,
            subject=subject,
            message=message,
            priority=priority,
        )

        superusers = CustomUser.objects.filter(is_superuser=True)
        for su in superusers:
            AdminNotification.objects.create(
                recipient=su,
                title=f"[Support] {priority.upper()} — {subject} | {org.name}",
                body=(
                    f"From: {request.user.email}\n"
                    f"Org: {org.name}\n"
                    f"Priority: {priority}\n\n"
                    f"{message}"
                ),
            )

        try:
            send_mail(
                subject=f"[FlockIQ Support] {priority.upper()} — {subject} | {org.name}",
                message=(
                    f"Organisation: {org.name}\n"
                    f"Submitted by: {request.user.email}\n"
                    f"Priority: {priority}\n"
                    f"Submitted: {ticket.created_at.strftime('%Y-%m-%d %H:%M UTC')}\n\n"
                    f"{message}"
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[settings.ADMIN_EMAIL],
                fail_silently=True,
            )
        except Exception:
            logger.exception("support_ticket.email_send_failed", ticket_id=ticket.pk)

        return render(request, "support/_ticket_success.html", {})
