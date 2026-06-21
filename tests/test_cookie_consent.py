"""NDPR cookie consent banner tests.

The banner is a single partial (templates/partials/cookie_consent.html) included
before </body> in both landing_base.html (marketing) and base.html (app shell).
It is localStorage-based with no external library.
"""

import pytest
from django.template.loader import render_to_string
from django.test import Client

pytestmark = pytest.mark.django_db


def test_cookie_banner_partial_has_policy_links():
    """The partial renders standalone and links to the privacy + cookie pages."""
    html = render_to_string("partials/cookie_consent.html")
    assert 'id="cookie-banner"' in html
    assert 'href="/privacy/"' in html
    assert 'href="/cookie-policy/"' in html
    # Accept handler + localStorage key that permanently dismisses the banner.
    assert "acceptCookies" in html
    assert "cookie_consent" in html


def test_landing_page_shows_cookie_banner_for_anonymous():
    """An anonymous visitor on the landing page (landing_base.html) sees it."""
    resp = Client().get("/")
    assert resp.status_code == 200
    content = resp.content.decode()
    assert 'id="cookie-banner"' in content
    assert "/privacy/" in content
    assert "/cookie-policy/" in content


def test_app_shell_shows_cookie_banner_for_authenticated(test_org, tenant_user):
    """The logged-in dashboard (base.html) includes the same banner."""
    client = Client()
    client.force_login(tenant_user)
    resp = client.get("/")
    assert resp.status_code == 200
    assert b'id="cookie-banner"' in resp.content
