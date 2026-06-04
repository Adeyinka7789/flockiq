from django.core.mail import send_mass_mail
from django.conf import settings

from apps.infrastructure.accounts.models import CustomUser
from apps.infrastructure.notifications.models import NotificationLog, BroadcastNotification


def get_broadcast_recipients(audience: str):
    qs = CustomUser.objects.filter(is_active=True).exclude(role='super_admin')
    if audience == 'owners':
        qs = qs.filter(role='owner')
    elif audience == 'managers':
        qs = qs.filter(role='manager')
    elif audience == 'owners_managers':
        qs = qs.filter(role__in=['owner', 'manager'])
    return qs


def send_broadcast(broadcast: BroadcastNotification) -> int:
    recipients = get_broadcast_recipients(broadcast.audience)
    count = 0

    for user in recipients:
        if not user.org_id:
            continue
        if broadcast.channel in ('in_app', 'both'):
            NotificationLog.objects.create(
                org=user.org,
                event_type='announcement',
                title=broadcast.title,
                body=broadcast.message,
                severity='info',
                channel='in_app',
                recipient=user,
            )
        count += 1

    if broadcast.channel in ('email', 'both'):
        emails = [
            (
                f'[FlockIQ] {broadcast.title}',
                broadcast.message,
                settings.DEFAULT_FROM_EMAIL,
                [user.email],
            )
            for user in recipients
            if user.email
        ]
        if emails:
            try:
                send_mass_mail(emails, fail_silently=True)
            except Exception:
                pass

    broadcast.recipient_count = count
    broadcast.save(update_fields=['recipient_count'])
    return count
