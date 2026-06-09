"""Tests for DRF throttling on the JSON auth API.

django-axes guards the *web* login form; these throttles guard the JWT API
login endpoint. We assert the throttle blocks once its limit is exceeded.
"""

import uuid
from types import SimpleNamespace

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.test import RequestFactory, override_settings
from rest_framework.test import APIRequestFactory

# Isolated in-memory cache so throttle counters don't touch Redis and don't
# bleed between tests.
LOCMEM_CACHE = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "throttle-tests",
    },
}


@pytest.fixture(autouse=True)
def clear_throttle_cache():
    """Start (and leave) every throttle test with an empty throttle cache.

    LocMemCache shares its backing store process-wide by LOCATION, so without an
    explicit teardown clear a test that records throttle hits leaves stale
    counters behind and the next test could inherit them. Clearing on both sides
    keeps each test order-independent. (The tests also use a fresh ident per run
    for true isolation; this is belt-and-suspenders.)
    """
    cache.clear()
    yield
    cache.clear()


@override_settings(CACHES=LOCMEM_CACHE)
def test_login_throttle_blocks_after_limit():
    """The LoginRateThrottle allows up to `num_requests`, then returns False."""
    from apps.infrastructure.accounts.throttles import LoginRateThrottle

    cache.clear()
    throttle = LoginRateThrottle()
    # Force a tiny limit so the test is fast and independent of the prod rate.
    throttle.rate = "3/min"
    throttle.num_requests, throttle.duration = throttle.parse_rate(throttle.rate)

    request = RequestFactory().post("/api/v1/auth/login/")
    request.META["REMOTE_ADDR"] = "203.0.113.7"
    request.user = AnonymousUser()  # AnonRateThrottle only throttles anon

    decisions = [throttle.allow_request(request, None) for _ in range(4)]
    assert decisions == [True, True, True, False]


@override_settings(CACHES=LOCMEM_CACHE)
def test_user_rate_throttle_blocks_after_limit():
    """UserRateThrottle (the blanket per-user API ceiling) allows up to its
    limit, then blocks the next request.

    Tested directly on the throttle class rather than through an HTTP endpoint:
    going through a view makes the result depend on auth ordering, the response
    a bad request happens to return, AND on DRF re-reading DEFAULT_THROTTLE_RATES
    (it doesn't — SimpleRateThrottle.THROTTLE_RATES is bound at import, so an
    override_settings rate change never reaches the live throttle). Setting the
    rate on the instance sidesteps all of that and is deterministic.
    """
    from rest_framework.throttling import UserRateThrottle

    cache.clear()
    throttle = UserRateThrottle()
    # Force a tiny limit on the instance — independent of the configured rate.
    throttle.rate = "2/min"
    throttle.num_requests, throttle.duration = throttle.parse_rate(throttle.rate)

    request = APIRequestFactory().get("/")
    # A fresh pk per run → a private cache key (throttle_user_<pk>), so this
    # test's counter can't inherit stale state from another test or run.
    request.user = SimpleNamespace(is_authenticated=True, pk=uuid.uuid4())

    decisions = [throttle.allow_request(request, None) for _ in range(3)]
    assert decisions == [True, True, False]
