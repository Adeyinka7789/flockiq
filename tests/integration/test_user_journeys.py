"""
End-to-end user journeys: registration → verify → onboarding → dashboard,
and the full suspension → kick-out → email → reactivation flow.

Host note: requests use the test client's default ``testserver`` host so that
TenantMiddleware resolves the tenant from ``request.user.org`` and enforces the
suspension kick-out. See tests/integration/conftest.py.
"""
import datetime

import pytest
from django.core import mail

from apps.infrastructure.accounts.models import CustomUser
from apps.infrastructure.tenants.models import Organization


@pytest.mark.django_db(transaction=True)
class TestRegistrationJourney:
    """Full signup → verify → onboarding → dashboard flow."""

    def test_registration_creates_org_and_user(self, client):
        client.post('/signup/', {
            'org_name': 'Journey Farm',
            'owner_name': 'Test Owner',
            'email': 'owner@journeyfarm.com',
            'phone': '08012345678',
            'subdomain': 'journeyfarm',
            'country': 'Nigeria',
            'state_region': 'Lagos',
            'password': 'SecurePass123!',
            'confirm_password': 'SecurePass123!',
        })
        assert Organization.objects.filter(
            subdomain='journeyfarm'
        ).exists()
        assert CustomUser.objects.filter(
            email='owner@journeyfarm.com'
        ).exists()

    def test_registration_sends_verification_email(self, client):
        mail.outbox = []
        client.post('/signup/', {
            'org_name': 'Email Farm',
            'owner_name': 'Test Owner',
            'email': 'owner@emailfarm.com',
            'subdomain': 'emailfarm',
            'country': 'Nigeria',
            'state_region': 'Lagos',
            'password': 'SecurePass123!',
            'confirm_password': 'SecurePass123!',
        })
        assert len(mail.outbox) == 1
        assert 'verify' in mail.outbox[0].subject.lower()
        assert 'owner@emailfarm.com' in mail.outbox[0].to

    def test_unverified_user_cannot_login(self, client, make_org):
        org, user = make_org(subdomain='unverified')
        user.email_verified = False
        user.save()
        response = client.post('/login/', {
            'email': user.email,
            'password': 'TestPass123!',
        })
        assert response.status_code in [200, 401, 403]
        assert '_auth_user_id' not in client.session

    def test_verified_user_can_login(self, client, make_org):
        org, user = make_org(subdomain='verified')
        client.post('/login/', {
            'email': user.email,
            'password': 'TestPass123!',
        })
        assert '_auth_user_id' in client.session

    def test_new_user_redirected_to_onboarding(self, client, make_org):
        org, user = make_org(subdomain='newuser')
        client.force_login(user)
        response = client.get('/')
        assert response.status_code == 302
        assert '/onboarding/' in response['Location']

    def test_onboarding_complete_reaches_dashboard(self, client, make_org,
                                                   make_farm):
        org, user = make_org(subdomain='complete')
        make_farm(org)
        org.onboarding_complete = True
        org.save()
        client.force_login(user)
        response = client.get('/')
        assert response.status_code == 200

    def test_email_verification_link_activates_account(self, client, make_org):
        org, user = make_org(subdomain='activate')
        user.email_verified = False
        user.save()
        token = user.email_verification_token
        client.get(f'/accounts/verify/{token}/')
        user.refresh_from_db()
        assert user.email_verified is True
        assert '_auth_user_id' in client.session


@pytest.mark.django_db(transaction=True)
class TestSuspensionJourney:
    """Full suspension → kick-out → email → reactivation flow."""

    def test_suspended_user_cannot_login(self, client, make_org):
        org, user = make_org(subdomain='suspended1', is_active=False)
        client.post('/login/', {
            'email': user.email,
            'password': 'TestPass123!',
        })
        assert '_auth_user_id' not in client.session

    def test_active_session_kicked_on_suspension(self, client, make_org,
                                                 make_farm):
        org, user = make_org(subdomain='kicktest')
        make_farm(org)
        org.onboarding_complete = True
        org.save()

        # User logs in and reaches the dashboard.
        client.force_login(user)
        response = client.get('/')
        assert response.status_code == 200

        # Admin suspends org and invalidates the middleware cache.
        org.is_active = False
        org.suspension_reason = 'Non-payment'
        org.save()
        from django.core.cache import cache
        cache.delete(f'org_active:{org.id}')

        # Next request kicks the user out to the login page.
        response = client.get('/')
        assert response.status_code == 302
        assert '/login/' in response['Location']

    def test_suspension_sends_email_to_owner(self, superadmin_client, make_org):
        sc, admin = superadmin_client
        org, user = make_org(subdomain='emailtest')
        mail.outbox = []

        sc.post(
            f'/superadmin/tenants/{org.id}/suspend/',
            {'suspension_reason': 'Overdue payment'},
        )
        assert len(mail.outbox) == 1
        assert org.name in mail.outbox[0].body
        assert 'Overdue payment' in mail.outbox[0].body
        assert user.email in mail.outbox[0].to

    def test_reactivation_sends_email(self, superadmin_client, make_org):
        sc, admin = superadmin_client
        org, user = make_org(subdomain='reacttest', is_active=False)
        mail.outbox = []

        # Reactivation is the "activate" action on the tenant-action endpoint.
        sc.post(f'/superadmin/tenants/{org.id}/action/', {'action': 'activate'})
        org.refresh_from_db()
        assert org.is_active is True
        assert len(mail.outbox) == 1
        assert 'reactivated' in mail.outbox[0].subject.lower()

    def test_all_org_users_blocked_on_suspension(self, client, make_org):
        from django.test import Client

        org, owner = make_org(subdomain='allusers')
        manager = CustomUser.objects.create_user(
            email='manager@allusers.com',
            username='manager@allusers.com',
            password='TestPass123!',
            org=org,
            role='manager',
            email_verified=True,
        )
        org.is_active = False
        org.save()

        for user in [owner, manager]:
            c = Client()
            c.post('/login/', {
                'email': user.email,
                'password': 'TestPass123!',
            })
            assert '_auth_user_id' not in c.session

    def test_superadmin_not_affected_by_suspension(self, superadmin_client,
                                                   make_org):
        sc, admin = superadmin_client
        org, user = make_org(subdomain='supertest', is_active=False)
        response = sc.get('/superadmin/')
        assert response.status_code == 200
