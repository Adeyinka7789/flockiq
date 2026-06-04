import pytest

pytestmark = pytest.mark.django_db


class TestHealthDashboard:
    def test_health_dashboard_returns_200(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get('/health/')
        assert response.status_code == 200

    def test_health_dashboard_requires_login(self, client):
        response = client.get('/health/')
        assert response.status_code == 302

    def test_health_dashboard_context_keys(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get('/health/')
        ctx = response.context
        assert 'active_alerts' in ctx
        assert 'biosecurity_score' in ctx
        assert 'compliance_pct' in ctx
        assert 'disease_alerts' in ctx
        assert 'state_risk_list' in ctx
        assert 'ai_advice' in ctx

    def test_biosecurity_score_range(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get('/health/')
        score = response.context['biosecurity_score']
        assert 0 <= score <= 100

    def test_compliance_pct_range(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get('/health/')
        pct = response.context['compliance_pct']
        assert 0 <= pct <= 100

    def test_ai_advice_not_empty(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get('/health/')
        advice = response.context['ai_advice']
        assert len(advice) > 0
        assert 'severity' in advice[0]
        assert 'title' in advice[0]
        assert 'text' in advice[0]

    def test_extract_state_osun(self):
        from apps.health.health.views import extract_state
        assert extract_state('Osogbo, Osun State') == 'Osun'

    def test_extract_state_lagos(self):
        from apps.health.health.views import extract_state
        assert extract_state('Ikeja, Lagos') == 'Lagos'

    def test_extract_state_unknown(self):
        from apps.health.health.views import extract_state
        result = extract_state('')
        assert result == 'Unknown'

    def test_generate_health_advice_good(self):
        from datetime import date
        from unittest.mock import MagicMock

        from apps.health.health.views import generate_health_advice

        org = MagicMock()
        advice = generate_health_advice(org, 95, 95, 0, [], date.today())
        assert advice[0]['severity'] == 'good'

    def test_generate_health_advice_critical(self):
        from datetime import date
        from unittest.mock import MagicMock

        from apps.health.health.views import generate_health_advice

        org = MagicMock()
        advice = generate_health_advice(org, 50, 50, 3, [], date.today())
        severities = [a['severity'] for a in advice]
        assert 'critical' in severities
