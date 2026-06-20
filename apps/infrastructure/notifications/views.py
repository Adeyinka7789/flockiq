import calendar as _cal
import json
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import structlog
from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.http import HttpResponse
from django.template.loader import render_to_string
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.infrastructure.core.email_service import EmailService
from apps.infrastructure.core.helpers import get_org_or_404
from apps.infrastructure.core.rls import set_tenant_context
from .serializers import NotificationLogSerializer
from .services import NotificationService

logger = structlog.get_logger(__name__)

# ─── Notification page helpers ────────────────────────────────────────────────

_TYPE_GROUPS = {
    "ai_alert": {
        "label": "AI Alerts",
        "filter": lambda qs: qs.filter(event_type__icontains="ai"),
    },
    "health": {
        "label": "Health",
        "filter": lambda qs: qs.filter(
            event_type__in=["vaccination", "health", "mortality_alert",
                            "vaccination_due", "vaccination_overdue",
                            "medication_withdrawal", "disease_outbreak"]
        ),
    },
    "production": {
        "label": "Production",
        "filter": lambda qs: qs.filter(
            event_type__in=["feed", "water", "egg", "production",
                            "production_drop", "water_drop", "heavy_rain",
                            "high_humidity", "heat_stress", "batch_closed"]
        ),
    },
    "finance": {
        "label": "Finance",
        "filter": lambda qs: qs.filter(event_type__icontains="billing"),
    },
    "system": {
        "label": "System",
        "filter": lambda qs: qs.filter(
            event_type__in=["system", "support", "platform",
                            "weekly_summary", "incomplete_tasks",
                            "announcement", "support_reply"]
        ),
    },
}


def _apply_date_filter(qs, days_filter):
    if not days_filter:
        days_filter = "30"
    if days_filter.startswith("month-"):
        parts = days_filter.split("-")
        try:
            return qs.filter(created_at__year=int(parts[1]), created_at__month=int(parts[2]))
        except (IndexError, ValueError):
            return qs
    if days_filter.startswith("year-"):
        parts = days_filter.split("-")
        try:
            return qs.filter(created_at__year=int(parts[1]))
        except (IndexError, ValueError):
            return qs
    try:
        days = int(days_filter)
    except (ValueError, TypeError):
        days = 30
    if days >= 365:
        return qs
    return qs.filter(created_at__gte=timezone.now() - timedelta(days=days))


def _group_notifications_by_date(notifications):
    today = timezone.localdate()
    yesterday = today - timedelta(days=1)
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    seen_labels, groups = [], {}
    for notif in notifications:
        local_date = timezone.localtime(notif.created_at).date()
        if local_date == today:
            label = "Today"
        elif local_date == yesterday:
            label = "Yesterday"
        elif local_date >= week_start:
            label = "This Week"
        elif local_date >= month_start:
            label = "This Month"
        else:
            label = local_date.strftime("%B %Y")
        if label not in groups:
            groups[label] = []
            seen_labels.append(label)
        groups[label].append(notif)
    return [(lbl, groups[lbl]) for lbl in seen_labels]


def _build_date_options(earliest_dt):
    today = timezone.localdate()
    quick = [
        {"value": "7", "label": "Last 7 days"},
        {"value": "30", "label": "Last 30 days"},
        {"value": "90", "label": "Last 90 days"},
    ]
    if earliest_dt is None:
        return {"quick": quick, "year_groups": [], "all_time": {"value": "365", "label": "All time"}}
    earliest_local = timezone.localtime(earliest_dt).date()
    current_year = today.year
    earliest_year = earliest_local.year
    year_groups = []
    for year in range(current_year, earliest_year - 1, -1):
        if year == current_year:
            months = [
                {"value": f"month-{year}-{m:02d}", "label": f"{_cal.month_name[m]} {year}"}
                for m in range(today.month, 0, -1)
            ]
            year_groups.append({"year": year, "months": months, "single": False})
        else:
            year_groups.append({
                "year": year,
                "months": [{"value": f"year-{year}", "label": f"All of {year}"}],
                "single": True,
            })
    return {"quick": quick, "year_groups": year_groups, "all_time": {"value": "365", "label": "All time"}}


def _build_notifications_context(request, params=None):
    from .models import NotificationLog
    if params is None:
        params = request.GET
    type_filter = params.get("type", "all")
    q = params.get("q", "").strip()
    days_filter = params.get("days", "30")

    with set_tenant_context(request.user.org):
        base_qs = NotificationLog.objects.filter(recipient=request.user)
        unread_count = base_qs.filter(is_read=False).count()
        total_count = base_qs.count()

        # Date + search filtered qs (without type filter) — used for tab counts
        date_qs = _apply_date_filter(base_qs, days_filter)
        if q:
            date_qs = date_qs.filter(Q(title__icontains=q) | Q(body__icontains=q))

        filter_tabs = [{"value": "all", "label": "All", "count": date_qs.count()}]
        for key, group in _TYPE_GROUPS.items():
            filter_tabs.append({
                "value": key,
                "label": group["label"],
                "count": group["filter"](date_qs).count(),
            })

        # Apply type filter for the actual list
        final_qs = date_qs
        if type_filter != "all" and type_filter in _TYPE_GROUPS:
            final_qs = _TYPE_GROUPS[type_filter]["filter"](final_qs)

        notifications = list(final_qs.order_by("-created_at")[:200])
        earliest_dt = base_qs.order_by("created_at").values_list("created_at", flat=True).first()
        date_options = _build_date_options(earliest_dt)

    return {
        "grouped_notifications": _group_notifications_by_date(notifications),
        "unread_count": unread_count,
        "total_count": total_count,
        "filter_tabs": filter_tabs,
        "current_type": type_filter,
        "days": days_filter,
        "q": q,
        "date_options": date_options,
    }


class NotificationBellView(LoginRequiredMixin, View):
    def get(self, request):
        if request.user.is_superuser:
            from .models import AdminNotification
            count = AdminNotification.objects.filter(
                recipient=request.user,
                is_read=False,
            ).count()
        elif not request.user.org:
            count = 0
        else:
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
        if request.user.is_superuser:
            from .models import AdminNotification
            notifications = list(
                AdminNotification.objects.filter(
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
        context = _build_notifications_context(request)
        if request.headers.get("HX-Request"):
            return render(request, "notifications/_notifications_list.html", context)
        return render(request, "notifications/notifications_page.html", context)


class MarkReadView(LoginRequiredMixin, View):
    def get(self, request, pk):
        """Mark a single notification read; return the updated card fragment for HTMX."""
        if not getattr(request.user, "org", None):
            return HttpResponse(status=400)
        from .models import NotificationLog
        with set_tenant_context(request.user.org):
            try:
                notif = NotificationLog.objects.get(pk=pk, recipient=request.user)
            except NotificationLog.DoesNotExist:
                return HttpResponse(status=404)
            if not notif.is_read:
                notif.is_read = True
                notif.read_at = timezone.now()
                notif.save(update_fields=["is_read", "read_at"])
        html = render_to_string(
            "notifications/_notification_card.html",
            {"notif": notif},
            request=request,
        )
        response = HttpResponse(html)
        response["HX-Trigger"] = json.dumps({"refreshBell": True})
        return response

    def post(self, request, pk):
        if request.user.is_superuser:
            from .models import AdminNotification
            AdminNotification.objects.filter(
                pk=pk, recipient=request.user
            ).update(is_read=True)
            count = AdminNotification.objects.filter(
                recipient=request.user, is_read=False
            ).count()
        else:
            if not getattr(request.user, 'org', None):
                return HttpResponse(status=400)
            svc = NotificationService(request.user.org)
            with set_tenant_context(request.user.org):
                svc.mark_read(pk, request.user)
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
        if request.user.is_superuser:
            from .models import AdminNotification
            AdminNotification.objects.filter(
                recipient=request.user, is_read=False
            ).update(is_read=True)
        else:
            if not getattr(request.user, 'org', None):
                return HttpResponse(status=400)
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
        response = HttpResponse(html)
        response["HX-Trigger"] = json.dumps({"refreshBell": True})
        return response


class MarkAdminNotificationReadView(LoginRequiredMixin, View):
    """POST /notifications/admin/<int:pk>/read/ — mark an AdminNotification as read."""

    def post(self, request, pk):
        from .models import AdminNotification
        AdminNotification.objects.filter(pk=pk, recipient=request.user).update(is_read=True)
        return HttpResponse(status=204)


class AcknowledgeNotificationView(LoginRequiredMixin, View):
    """POST /notifications/<uuid>/acknowledge/ — Acknowledge a critical/warning alert."""

    def post(self, request, pk):
        from .models import NotificationLog

        if not getattr(request.user, 'org', None):
            return HttpResponse(status=400)
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
        from .models import NotificationLog
        with set_tenant_context(request.user.org):
            NotificationLog.objects.filter(
                org=request.user.org,
                recipient=request.user,
                is_read=False,
            ).update(is_read=True, read_at=timezone.now())
        # Preserve current filters from the page URL sent by HTMX
        current_url = request.META.get("HTTP_HX_CURRENT_URL", "")
        params = {}
        if current_url:
            parsed = urlparse(current_url)
            params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        context = _build_notifications_context(request, params)
        response = render(request, "notifications/_notifications_list.html", context)
        response["HX-Trigger"] = json.dumps({
            "showToast": {"message": "All notifications marked as read", "type": "success"},
            "refreshBell": True,
        })
        return response


class ReadRedirectView(LoginRequiredMixin, View):
    """GET /notifications/<uuid>/redirect/ — mark read then redirect to action_url."""

    def get(self, request, pk):
        if not getattr(request.user, "org", None):
            return redirect("/")
        from .models import NotificationLog
        with set_tenant_context(request.user.org):
            try:
                notif = NotificationLog.objects.get(pk=pk, recipient=request.user)
            except NotificationLog.DoesNotExist:
                return redirect(reverse("notifications:notifications_page"))
            if not notif.is_read:
                notif.is_read = True
                notif.read_at = timezone.now()
                notif.save(update_fields=["is_read", "read_at"])
            action_url = notif.action_url
        return redirect(action_url if action_url else reverse("notifications:notifications_page"))


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
        from .models import SupportTicket
        from .ticket_service import SupportTicketService

        ticket = get_object_or_404(SupportTicket, pk=pk, submitted_by=request.user)
        message = request.POST.get("message", "").strip()

        if not message or ticket.status == "resolved":
            replies = ticket.replies.select_related("author").all()
            return render(request, "support/ticket_detail.html", {
                "ticket": ticket,
                "replies": replies,
                "error": "Cannot reply — message is empty or ticket is resolved.",
            }, status=422)

        SupportTicketService.add_reply(
            ticket=ticket,
            author=request.user,
            message=message,
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
        ticket_url = reverse('superadmin:support_ticket_detail', kwargs={'pk': ticket.pk})
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
                action_url=ticket_url,
            )

        try:
            EmailService.send_support_ticket(
                admin_email=settings.ADMIN_EMAIL,
                org_name=org.name,
                user_email=request.user.email,
                priority=priority,
                subject=subject,
                message=message,
                submitted_at=ticket.created_at.strftime('%Y-%m-%d %H:%M UTC'),
            )
        except Exception:
            logger.exception("support_ticket.email_send_failed", ticket_id=ticket.pk)

        return render(request, "support/_ticket_success.html", {})


# ─── Mobile API ───────────────────────────────────────────────────────────────


class NotificationListAPIView(APIView):
    """
    GET /api/v1/notifications/ → List the current user's notifications, newest first.

    Query params:
      ?unread=true  — filter to unread only
      ?limit=20     — number of results (default 20, max 50)

    Scoped to the current organisation via RLS. Used by the mobile notification
    feed/bell.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .models import NotificationLog

        org = getattr(request.user, "org", None)
        if not org:
            return Response({"error": "No organisation."}, status=403)

        try:
            limit = min(int(request.query_params.get("limit", 20)), 50)
        except (ValueError, TypeError):
            limit = 20
        if limit < 1:
            limit = 20

        with set_tenant_context(org):
            qs = NotificationLog.objects.filter(
                recipient=request.user
            ).order_by("-created_at")
            if request.query_params.get("unread") == "true":
                qs = qs.filter(is_read=False)
            notifications = list(qs[:limit])
            serializer = NotificationLogSerializer(notifications, many=True)
            return Response({"data": serializer.data})


class NotificationMarkReadAPIView(APIView):
    """POST /api/v1/notifications/<uuid>/read/ → Mark a single notification read. Returns 204."""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        from .models import NotificationLog

        org = getattr(request.user, "org", None)
        if not org:
            return Response({"error": "No organisation."}, status=403)

        with set_tenant_context(org):
            try:
                notif = NotificationLog.objects.get(pk=pk, recipient=request.user)
            except NotificationLog.DoesNotExist:
                return Response({"error": "Notification not found."}, status=404)
            if not notif.is_read:
                notif.is_read = True
                notif.read_at = timezone.now()
                notif.save(update_fields=["is_read", "read_at"])
        return Response(status=204)


class NotificationMarkAllReadAPIView(APIView):
    """POST /api/v1/notifications/read-all/ → Mark all of the user's unread notifications read. Returns 204."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        from .models import NotificationLog

        org = getattr(request.user, "org", None)
        if not org:
            return Response({"error": "No organisation."}, status=403)

        with set_tenant_context(org):
            NotificationLog.objects.filter(
                recipient=request.user,
                is_read=False,
            ).update(is_read=True, read_at=timezone.now())
        return Response(status=204)
