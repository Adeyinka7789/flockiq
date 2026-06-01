import uuid

from django.contrib.auth.mixins import LoginRequiredMixin
from django.views import View
from django.shortcuts import get_object_or_404
from django.http import HttpResponse
from django.template.loader import render_to_string

from .services import NotificationService


class NotificationBellView(LoginRequiredMixin, View):
    def get(self, request):
        if not request.user.org:
            return HttpResponse("0")
        svc = NotificationService(request.user.org)
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
        svc = NotificationService(request.user.org)
        notifications = svc.get_notifications(request.user)
        html = render_to_string(
            "notifications/_dropdown.html",
            {"notifications": notifications},
            request=request,
        )
        return HttpResponse(html)


class MarkReadView(LoginRequiredMixin, View):
    def post(self, request, pk):
        svc = NotificationService(request.user.org)
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
        NotificationLog.objects.filter(
            org=request.user.org,
            recipient=request.user,
            is_read=False,
        ).update(is_read=True, read_at=timezone.now())

        svc = NotificationService(request.user.org)
        notifications = svc.get_notifications(request.user)
        html = render_to_string(
            "notifications/_dropdown.html",
            {"notifications": notifications},
            request=request,
        )
        return HttpResponse(html)
