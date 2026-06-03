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
        features = get_plan_features(request.user.org.plan_tier)
        return {
            'plan_features': features,
            'user_plan': request.user.org.plan_tier,
        }
    return {
        'plan_features': {},
        'user_plan': None,
    }
