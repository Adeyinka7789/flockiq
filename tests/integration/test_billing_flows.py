"""
Billing / plan-gating journeys.

Note: ``has_feature`` keys off ``org.plan_tier`` only (see
apps/infrastructure/billing/features.py). ``advanced_ai`` is not a real feature
key — these tests use ``ai_daily_brief`` (False on trial, True on yearly).
"""
import datetime

import pytest


@pytest.mark.django_db(transaction=True)
class TestBillingJourney:

    def test_trial_org_can_access_basic_features(self, tenant_client, make_farm):
        client, org, user = tenant_client
        make_farm(org)
        assert org.plan_tier == 'trial'
        response = client.get('/')
        assert response.status_code == 200

    def test_expired_trial_gates_premium_features(self, make_org, make_farm):
        from django.utils import timezone
        org, user = make_org(subdomain='expiredtrial')
        org.trial_ends_at = (timezone.now() - datetime.timedelta(days=1))
        org.onboarding_complete = True
        org.save()
        make_farm(org)

        from apps.infrastructure.billing.features import has_feature
        assert has_feature(org, 'ai_daily_brief') is False

    def test_yearly_plan_has_all_features(self, make_org):
        org, user = make_org(subdomain='yearlyplan', plan='yearly')
        from apps.infrastructure.billing.features import has_feature
        assert has_feature(org, 'ai_daily_brief') is True
        assert has_feature(org, 'pdf_export') is True
