from django import template

register = template.Library()


@register.filter
def unread_notification_count(user):
    if not user.is_authenticated or not getattr(user, "org", None):
        return 0
    try:
        from apps.infrastructure.notifications.models import NotificationLog
        from apps.infrastructure.core.rls import set_tenant_context
        with set_tenant_context(user.org):
            return NotificationLog.objects.filter(
                recipient=user,
                is_read=False,
            ).count()
    except Exception:
        return 0


@register.simple_tag(takes_context=True)
def can_manage(context):
    user = context.get("request", None)
    if user is None:
        return False
    user = user.user
    return user.is_authenticated and user.role in ("owner", "manager")


@register.simple_tag(takes_context=True)
def is_owner(context):
    user = context.get("request", None)
    if user is None:
        return False
    user = user.user
    return user.is_authenticated and user.role == "owner"


@register.simple_tag(takes_context=True)
def can_record(context):
    user = context.get("request", None)
    if user is None:
        return False
    user = user.user
    return user.is_authenticated and user.role != "vet_advisor"


@register.simple_tag(takes_context=True)
def is_super_admin(context):
    user = context.get("request", None)
    if user is None:
        return False
    user = user.user
    return user.is_authenticated and user.role == "super_admin"
