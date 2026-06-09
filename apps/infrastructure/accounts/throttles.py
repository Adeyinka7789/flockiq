"""Scoped throttles for the JSON auth endpoints.

These sit on top of django-axes (which protects the *web* login form). The API
login endpoint is a separate JWT surface that axes does not cover, so we rate
limit it here. Rates are defined under REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]
in settings, keyed by the ``scope`` below.
"""

from rest_framework.throttling import AnonRateThrottle


class LoginRateThrottle(AnonRateThrottle):
    scope = "login"


class SignupRateThrottle(AnonRateThrottle):
    scope = "signup"
