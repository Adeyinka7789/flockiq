"""
RLS isolation tests — run after every model change:
  pytest tests/rls/test_rls_isolation.py -v

Phase 1A: placeholder — real tests added in Phase 1C when TenantAwareModel lands.
"""
import pytest


@pytest.mark.django_db
def test_placeholder_rls_isolation():
    """Placeholder — replace with real cross-tenant isolation assertions in Phase 1C."""
    assert True
