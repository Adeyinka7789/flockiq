def support_contact(request):
    from django.conf import settings
    return {
        'support_email': getattr(settings, 'SUPPORT_EMAIL', 'support@flockiq.com'),
        'support_phone': getattr(settings, 'SUPPORT_PHONE', '+234 000 000 0000'),
    }


def trial_status(request):
    """
    Exposes trial countdown / expiry state to all templates so the
    global trial banner (templates/base.html) can render.

    Returns:
        trial_days_remaining: int  — whole days left (0 once expired)
        trial_expired:        bool — True when a trial org's window has passed
        on_trial:             bool — True while a trial org is still within its window
    """
    empty = {
        "trial_days_remaining": 0,
        "trial_expired": False,
        "on_trial": False,
        "is_lapsed": False,
    }

    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return empty

    # Platform super-admins have no tenant org and never see trial UI.
    if user.is_superuser or getattr(user, "role", "") == "super_admin":
        return empty

    org = getattr(user, "org", None)
    if not org:
        return empty

    # Lapsed applies to paid orgs whose plan expired without renewal. It is
    # mutually exclusive with the trial states below (which only fire for
    # plan_tier == "trial").
    is_lapsed = org.is_lapsed

    if org.plan_tier != "trial" or not org.trial_ends_at:
        return {**empty, "is_lapsed": is_lapsed}

    from django.utils import timezone

    delta = org.trial_ends_at - timezone.now()
    expired = delta.total_seconds() <= 0
    return {
        "trial_days_remaining": max(0, delta.days),
        "trial_expired": expired,
        "on_trial": not expired,
        "is_lapsed": is_lapsed,
    }


def plan_features(request):
    """
    Makes plan_features available in all templates.
    Usage: {% if plan_features.ai_anomaly_detection %}
    """
    if (hasattr(request, 'user') and
            request.user.is_authenticated and
            hasattr(request.user, 'org') and
            request.user.org):
        from apps.infrastructure.billing.features import get_plan_features
        from apps.infrastructure.core.config import PlatformConfig
        features = get_plan_features(request.user.org.plan_tier)
        config = PlatformConfig.get()
        return {
            'plan_features': features,
            'user_plan': request.user.org.plan_tier,
            'platform_config': config,
        }
    return {
        'plan_features': {},
        'user_plan': None,
        'platform_config': None,
    }
