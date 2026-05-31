from django import template

register = template.Library()


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
