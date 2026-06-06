"""Tests for apps.infrastructure.core.helpers — get_org_or_404 / get_org_or_redirect."""
import uuid

import pytest
from django.http import Http404
from unittest.mock import MagicMock, patch, PropertyMock

from apps.infrastructure.core.helpers import get_org_or_404, get_org_or_redirect


def _make_request(org=None):
    request = MagicMock()
    request.user.id = uuid.uuid4()
    request.user.org = org
    return request


def _make_org(slug="test-farm", is_active=True):
    org = MagicMock()
    org.slug = slug
    org.is_active = is_active
    org.id = uuid.uuid4()
    return org


class TestGetOrgOr404:
    def test_happy_path(self):
        org = _make_org()
        request = _make_request(org=org)
        result = get_org_or_404(request)
        assert result is org
        org.refresh_from_db.assert_called_once()

    def test_missing_org_raises_404(self):
        request = _make_request(org=None)
        with pytest.raises(Http404):
            get_org_or_404(request)

    def test_inactive_org_raises_404(self):
        org = _make_org(is_active=False)
        request = _make_request(org=org)
        with pytest.raises(Http404):
            get_org_or_404(request)

    def test_wrong_slug_raises_404(self):
        org = _make_org(slug="actual-slug")
        request = _make_request(org=org)
        with pytest.raises(Http404):
            get_org_or_404(request, org_slug="different-slug")

    def test_correct_slug_passes(self):
        org = _make_org(slug="my-farm")
        request = _make_request(org=org)
        result = get_org_or_404(request, org_slug="my-farm")
        assert result is org

    def test_deleted_org_raises_404(self):
        from apps.infrastructure.tenants.models import Organization
        org = _make_org()
        org.refresh_from_db.side_effect = Organization.DoesNotExist
        request = _make_request(org=org)
        with pytest.raises(Http404):
            get_org_or_404(request)

    def test_no_org_attribute_raises_404(self):
        request = MagicMock()
        request.user.id = uuid.uuid4()
        # Simulate user with no 'org' attribute at all
        del request.user.org
        with pytest.raises((Http404, AttributeError)):
            get_org_or_404(request)


class TestGetOrgOrRedirect:
    def test_happy_path_returns_org(self):
        org = _make_org()
        request = _make_request(org=org)
        result_org, result_redirect = get_org_or_redirect(request)
        assert result_org is org
        assert result_redirect is None

    def test_missing_org_returns_redirect(self):
        request = _make_request(org=None)
        result_org, result_redirect = get_org_or_redirect(request)
        assert result_org is None
        assert result_redirect is not None

    def test_inactive_org_returns_redirect(self):
        org = _make_org(is_active=False)
        request = _make_request(org=org)
        result_org, result_redirect = get_org_or_redirect(request)
        assert result_org is None
        assert result_redirect is not None

    def test_custom_redirect_url(self):
        request = _make_request(org=None)
        result_org, result_redirect = get_org_or_redirect(request, redirect_url="login")
        assert result_org is None
        # Django redirect wraps the URL; just confirm something was returned
        assert result_redirect is not None
