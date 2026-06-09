"""Per-request timezone activation.

Activates the authenticated user's timezone for the duration of each request.
With USE_TZ=True Django auto-converts every datetime rendered in a template to
the *currently active* timezone, so activating the user's zone here is what makes
dashboards, batch detail, billing dates etc. display in their local time.

Resolution order: user.timezone → user.org.timezone → Africa/Lagos.

Uses the stdlib ``zoneinfo`` (Django 5 / Python 3.9+), NOT pytz. pytz is not a
project dependency and ``timezone.activate()`` accepts any ``tzinfo`` instance,
so ZoneInfo is the lighter, modern choice.
"""

from zoneinfo import ZoneInfo

from django.utils import timezone

DEFAULT_TZ = "Africa/Lagos"


class TimezoneMiddleware:
    """Activate the request user's timezone, falling back to Africa/Lagos.

    Placed after AuthenticationMiddleware (and ImpersonationMiddleware) so that
    ``request.user`` is populated — and, during an impersonation session, so the
    impersonated user's timezone is the one that is honoured.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        tzname = None
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            tzname = getattr(user, "timezone", None)
            if not tzname:
                org = getattr(user, "org", None)
                if org is not None:
                    tzname = getattr(org, "timezone", None)

        try:
            timezone.activate(ZoneInfo(tzname or DEFAULT_TZ))
        except (KeyError, ValueError):
            # Unknown / malformed IANA name → fall back to the server default.
            timezone.activate(ZoneInfo(DEFAULT_TZ))

        try:
            return self.get_response(request)
        finally:
            # Always clear so the thread/worker does not leak this request's tz
            # into the next request it serves.
            timezone.deactivate()
