import json
import uuid

from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect, render
from django.views import View
from django.http import HttpResponse
from django.template.loader import render_to_string

from apps.infrastructure.core.rls import set_tenant_context
from .services import NotificationService


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
