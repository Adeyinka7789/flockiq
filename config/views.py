import structlog
from django.conf import settings
from django.core.mail import send_mail
from django.shortcuts import render

logger = structlog.get_logger(__name__)


def case_study_detail(request, slug):
    return render(request, "case-study-details.html", {"slug": slug})


def contact(request):
    if request.method != 'POST':
        return render(request, 'contact.html')

    subject = request.POST.get('subject', '').strip()
    message = request.POST.get('message', '').strip()
    name = request.POST.get('name', '').strip()
    email = request.POST.get('email', '').strip()

    if not subject or not message:
        return render(request, 'contact.html', {'error': 'Subject and message are required.'}, status=400)

    from apps.infrastructure.notifications.models import AdminNotification, ContactMessage
    from apps.infrastructure.accounts.models import CustomUser

    sender = request.user if request.user.is_authenticated else None
    resolved_email = email or (sender.email if sender else '')

    ContactMessage.objects.create(
        sender=sender,
        name=name,
        email=resolved_email,
        subject=subject,
        message=message,
    )

    try:
        send_mail(
            subject=f"[FlockIQ Contact] {subject}",
            message=f"From: {name} <{resolved_email}>\n\n{message}",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[settings.ADMIN_EMAIL],
            fail_silently=True,
        )
    except Exception:
        logger.exception("contact.email_send_failed")

    superusers = CustomUser.objects.filter(is_superuser=True)
    for su in superusers:
        AdminNotification.objects.create(
            recipient=su,
            title=f"New contact message: {subject}",
            body=f"From: {name} <{resolved_email}>\n\n{message}",
        )

    return render(request, 'contact.html', {'success': True})
