from django.urls import path
from .views import (
    AcknowledgeNotificationView,
    MarkAdminNotificationReadView,
    NotificationBellView,
    NotificationDropdownView,
    NotificationListAPIView,
    NotificationMarkAllReadAPIView,
    NotificationMarkReadAPIView,
    NotificationsPageView,
    MarkReadView,
    MarkAllReadView,
    MarkAllReadPageView,
    ReadRedirectView,
    MySupportTicketsView,
    SupportTicketDetailUserView,
    SupportTicketFormView,
    SubmitSupportTicketView,
)

app_name = "notifications"

urlpatterns = [
    path("notifications/", NotificationsPageView.as_view(), name="notifications_page"),
    path("notifications/bell/", NotificationBellView.as_view(), name="bell"),
    path("notifications/dropdown/", NotificationDropdownView.as_view(), name="dropdown"),
    path("notifications/<uuid:pk>/read/", MarkReadView.as_view(), name="mark_read"),
    path("notifications/<uuid:pk>/redirect/", ReadRedirectView.as_view(), name="read_redirect"),
    path("notifications/admin/<int:pk>/read/", MarkAdminNotificationReadView.as_view(), name="mark_admin_read"),
    path("notifications/<uuid:pk>/acknowledge/", AcknowledgeNotificationView.as_view(), name="acknowledge"),
    path("notifications/read-all/", MarkAllReadView.as_view(), name="mark_all_read"),
    path("notifications/mark-all-read-page/", MarkAllReadPageView.as_view(), name="mark_all_read_page"),
    path("support/ticket/form/", SupportTicketFormView.as_view(), name="support_form"),
    path("support/ticket/submit/", SubmitSupportTicketView.as_view(), name="submit_support_ticket"),
    path("support/my-tickets/", MySupportTicketsView.as_view(), name="my_support_tickets"),
    path("support/my-tickets/<int:pk>/", SupportTicketDetailUserView.as_view(), name="support_ticket_detail"),
    # DRF API (mobile)
    path("api/v1/notifications/", NotificationListAPIView.as_view(), name="api_notification_list"),
    path("api/v1/notifications/read-all/", NotificationMarkAllReadAPIView.as_view(), name="api_notification_read_all"),
    path("api/v1/notifications/<uuid:pk>/read/", NotificationMarkReadAPIView.as_view(), name="api_notification_mark_read"),
]
