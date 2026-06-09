"""Tests for TimezoneMiddleware — per-request timezone activation."""

from types import SimpleNamespace

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory
from django.utils import timezone

from apps.infrastructure.core.timezone_middleware import (
    DEFAULT_TZ,
    TimezoneMiddleware,
)


def _run_middleware(user):
    """Run the middleware for `user` and capture the timezone active *inside*
    the request, plus the timezone left active *after* it returns."""
    captured = {}

    def get_response(request):
        captured["during"] = timezone.get_current_timezone_name()
        return "response"

    middleware = TimezoneMiddleware(get_response)
    request = RequestFactory().get("/")
    request.user = user
    result = middleware(request)

    captured["after"] = timezone.get_current_timezone_name()
    captured["result"] = result
    return captured


def test_activates_user_timezone_for_nigerian_user():
    user = SimpleNamespace(
        is_authenticated=True, timezone="Africa/Lagos", org=None
    )
    captured = _run_middleware(user)
    assert captured["during"] == "Africa/Lagos"


def test_activates_non_default_user_timezone():
    # A user well outside Lagos proves the middleware honours the user value
    # (and is not just falling through to the server default which is Lagos).
    user = SimpleNamespace(
        is_authenticated=True, timezone="America/New_York", org=None
    )
    captured = _run_middleware(user)
    assert captured["during"] == "America/New_York"


def test_falls_back_to_lagos_for_unknown_timezone():
    user = SimpleNamespace(
        is_authenticated=True, timezone="Not/ARealZone", org=None
    )
    captured = _run_middleware(user)
    assert captured["during"] == DEFAULT_TZ == "Africa/Lagos"


def test_falls_back_to_org_timezone_when_user_has_none():
    org = SimpleNamespace(timezone="Africa/Accra")
    user = SimpleNamespace(is_authenticated=True, timezone="", org=org)
    captured = _run_middleware(user)
    assert captured["during"] == "Africa/Accra"


def test_anonymous_user_gets_default_timezone():
    captured = _run_middleware(AnonymousUser())
    assert captured["during"] == DEFAULT_TZ


def test_deactivates_after_request():
    # Activate a sentinel zone first; after the request the middleware must have
    # deactivated, reverting the current zone to the settings default (Lagos).
    timezone.activate("America/New_York")
    try:
        user = SimpleNamespace(
            is_authenticated=True, timezone="America/New_York", org=None
        )
        captured = _run_middleware(user)
        # deactivate() drops the override → current tz is the settings default.
        assert captured["after"] == "Africa/Lagos"
        assert captured["result"] == "response"
    finally:
        timezone.deactivate()
