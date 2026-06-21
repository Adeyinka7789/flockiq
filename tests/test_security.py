"""Content Security Policy (CSP) header tests.

CSP is configured in config/settings/base.py via django-csp and shipped in
REPORT_ONLY mode: every response carries a Content-Security-Policy-Report-Only
header (NOT Content-Security-Policy), so nothing is ever blocked until the
directives are confirmed safe and enforcement is switched on post-launch.

These tests assert the header is present and carries the key directives. They do
NOT assert blocking behaviour — report-only mode never blocks, by design.
"""

import pytest
from django.test import Client

pytestmark = pytest.mark.django_db

REPORT_ONLY_HEADER = "Content-Security-Policy-Report-Only"
ENFORCED_HEADER = "Content-Security-Policy"


def _csp(response):
    """Return the report-only CSP header value, asserting it exists."""
    assert REPORT_ONLY_HEADER in response, (
        f"missing {REPORT_ONLY_HEADER} header; "
        f"headers present: {list(response.headers)}"
    )
    return response[REPORT_ONLY_HEADER]


def test_landing_sends_report_only_header():
    """An anonymous GET / carries the report-only header, not the enforced one."""
    resp = Client().get("/")
    assert resp.status_code == 200
    assert REPORT_ONLY_HEADER in resp
    # We are explicitly in report-only mode — the enforcing header must be absent.
    assert ENFORCED_HEADER not in resp


def test_csp_contains_core_directives():
    """The policy carries the locked-down base directives."""
    policy = _csp(Client().get("/"))
    assert "default-src 'self'" in policy
    assert "object-src 'none'" in policy
    assert "base-uri 'self'" in policy


def test_csp_allows_known_frontend_sources():
    """Alpine.js (unsafe-eval) and the Chart.js CDN are whitelisted in script-src."""
    policy = _csp(Client().get("/"))
    assert "'unsafe-eval'" in policy        # Alpine.js x-data evaluation
    assert "'unsafe-inline'" in policy      # HTMX inline handlers / inline styles
    assert "https://cdnjs.cloudflare.com" in policy  # Chart.js


def test_dashboard_loads_with_csp_header(test_org, tenant_user):
    """The authenticated dashboard loads and carries the report-only header.

    Report-only never blocks, so a 200 here just confirms the header rides along
    with a normal authenticated response.
    """
    client = Client()
    client.force_login(tenant_user)
    resp = client.get("/")
    assert resp.status_code == 200
    assert REPORT_ONLY_HEADER in resp


def test_farms_page_sends_csp_header(test_org, tenant_user):
    """/farms/ (authenticated) carries the CSP report-only header."""
    client = Client()
    client.force_login(tenant_user)
    resp = client.get("/farms/")
    assert resp.status_code == 200
    assert REPORT_ONLY_HEADER in resp


def test_batches_page_sends_csp_header(test_org, tenant_user):
    """/batches/ (authenticated) carries the CSP report-only header."""
    client = Client()
    client.force_login(tenant_user)
    resp = client.get("/batches/")
    assert resp.status_code == 200
    assert REPORT_ONLY_HEADER in resp
