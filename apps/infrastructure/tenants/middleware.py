from django.shortcuts import redirect


class TrialEnforcementMiddleware:
    """
    Blocks access when trial has expired and no active subscription.
    Redirects to the billing page with ?expired=1.
    Exempt paths: login, logout, signup, billing, static, admin, API auth,
    onboarding, password reset.
    """

    EXEMPT_PATHS = [
        '/login/', '/logout/', '/signup/', '/billing/',
        '/api/v1/auth/', '/admin/', '/static/', '/media/',
        '/onboarding/', '/forgot-password/', '/reset-password/',
    ]

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.user.is_authenticated:
            return self.get_response(request)

        if not hasattr(request.user, 'org') or not request.user.org:
            return self.get_response(request)

        if request.user.is_superuser or request.user.role == 'super_admin':
            return self.get_response(request)

        for path in self.EXEMPT_PATHS:
            if request.path.startswith(path):
                return self.get_response(request)

        org = request.user.org

        if org.subscription_status == 'active':
            return self.get_response(request)

        if org.plan_tier == 'trial' and org.subscription_status == 'trial':
            from django.utils import timezone
            # None means trial expiry not yet configured — allow access (new org)
            if org.trial_ends_at is None or org.trial_ends_at > timezone.now():
                return self.get_response(request)
            else:
                return redirect('/billing/?expired=1')

        if org.subscription_status in ['suspended', 'cancelled']:
            return redirect('/billing/?expired=1')

        return self.get_response(request)
