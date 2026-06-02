from django.urls import path
from .views import (
    AcknowledgeNotificationView,
    NotificationBellView,
    NotificationDropdownView,
    NotificationsPageView,
    MarkReadView,
    MarkAllReadView,
    MarkAllReadPageView,
)

app_name = "notifications"

urlpatterns = [
    path("notifications/", NotificationsPageView.as_view(), name="notifications_page"),
    path("notifications/bell/", NotificationBellView.as_view(), name="bell"),
    path("notifications/dropdown/", NotificationDropdownView.as_view(), name="dropdown"),
    path("notifications/<uuid:pk>/read/", MarkReadView.as_view(), name="mark_read"),
    path("notifications/<uuid:pk>/acknowledge/", AcknowledgeNotificationView.as_view(), name="acknowledge"),
    path("notifications/read-all/", MarkAllReadView.as_view(), name="mark_all_read"),
    path("notifications/mark-all-read-page/", MarkAllReadPageView.as_view(), name="mark_all_read_page"),
]
