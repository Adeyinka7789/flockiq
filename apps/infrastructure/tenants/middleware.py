from django.http import HttpResponse
from django.shortcuts import redirect


class TrialEnforcementMiddleware:
    """
    Blocks access when trial has expired and no active subscription.
    Redirects to the billing page with ?expired=1.
    Exempt paths: login, logout, signup, billing, static, admin, API auth,
    onboarding, password reset, and the global notification widgets (bell /
    dropdown) which are read-only and poll on every page — including billing.
    """

    EXEMPT_PATHS = [
        '/login/', '/logout/', '/signup/', '/billing/',
        '/api/v1/auth/', '/static/', '/media/',
        '/onboarding/', '/forgot-password/', '/reset-password/',
        '/notifications/',
    ]

    def __init__(self, get_response):
        self.get_response = get_response
        # The admin path is env-configurable (settings.DJANGO_ADMIN_URL), so it
        # cannot live in the static EXEMPT_PATHS list above.
        from django.conf import settings
        self.exempt_paths = self.EXEMPT_PATHS + [f"/{settings.DJANGO_ADMIN_URL}"]

    @staticmethod
    def _expired_redirect(request):
        """Bounce an expired/suspended org to the billing page.

        For HTMX requests we must NOT return a plain 302: htmx transparently
        follows the redirect and swaps the resulting full billing-page HTML into
        whatever fragment target made the request (e.g. the notification bell).
        That injected markup re-fires its own ``hx-trigger="load"`` elements,
        producing an infinite redirect→swap loop and a stuck loading spinner.
        Instead, hand htmx an ``HX-Redirect`` header so it performs a real
        top-level browser navigation (handled in base.html).
        """
        if request.headers.get('HX-Request'):
            response = HttpResponse(status=204)
            response['HX-Redirect'] = '/billing/?expired=1'
            return response
        return redirect('/billing/?expired=1')

    def __call__(self, request):
        if not request.user.is_authenticated:
            return self.get_response(request)

        if not hasattr(request.user, 'org') or not request.user.org:
            return self.get_response(request)

        org = request.user.org

        from apps.infrastructure.billing.features import get_plan_features
        request.plan_features = get_plan_features(org.plan_tier)

        if request.user.is_superuser or request.user.role == 'super_admin':
            return self.get_response(request)

        for path in self.exempt_paths:
            if request.path.startswith(path):
                return self.get_response(request)

        if org.subscription_status == 'active':
            return self.get_response(request)

        if org.plan_tier == 'trial' and org.subscription_status == 'trial':
            from django.utils import timezone
            # None means trial expiry not yet configured — allow access (new org)
            if org.trial_ends_at is None or org.trial_ends_at > timezone.now():
                return self.get_response(request)
            else:
                return self._expired_redirect(request)

        if org.subscription_status in ['suspended', 'cancelled']:
            return self._expired_redirect(request)

        return self.get_response(request)
