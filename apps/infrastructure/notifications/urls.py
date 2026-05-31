from django.urls import path
from .views import (
    NotificationBellView,
    NotificationDropdownView,
    MarkReadView,
    MarkAllReadView,
)

app_name = "notifications"

urlpatterns = [
    path("notifications/bell/", NotificationBellView.as_view(), name="bell"),
    path("notifications/dropdown/", NotificationDropdownView.as_view(), name="dropdown"),
    path("notifications/<uuid:pk>/read/", MarkReadView.as_view(), name="mark_read"),
    path("notifications/read-all/", MarkAllReadView.as_view(), name="mark_all_read"),
]
