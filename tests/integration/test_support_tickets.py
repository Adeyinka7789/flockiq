"""
Support-ticket journeys: tenant submits a ticket → superadmin is notified
(in-app + email), admin replies → tenant is emailed, and org auto-capture.
"""
import pytest
from django.core import mail

from apps.infrastructure.core.rls import set_tenant_context


@pytest.mark.django_db(transaction=True)
class TestSupportTicketJourney:

    def test_tenant_submits_ticket_admin_notified(self, tenant_client,
                                                   superadmin):
        client, org, user = tenant_client
        mail.outbox = []

        # Superadmins are notified in-app via AdminNotification (recipient FK).
        from apps.infrastructure.notifications.models import AdminNotification
        before = AdminNotification.objects.filter(
            recipient=superadmin
        ).count()

        response = client.post(
            '/support/ticket/submit/',
            {
                'subject': 'My birds are dying',
                'message': 'Need help urgently',
                'priority': 'high',
            },
        )
        assert response.status_code == 200

        # Email sent to the admin inbox.
        assert len(mail.outbox) >= 1
        assert any(
            'My birds are dying' in m.subject
            for m in mail.outbox
        )

        # In-app notification created for the superadmin.
        after = AdminNotification.objects.filter(
            recipient=superadmin
        ).count()
        assert after > before

    def test_admin_reply_notifies_tenant(self, tenant_client, superadmin_client):
        tc, org, user = tenant_client
        sc, admin = superadmin_client

        from apps.infrastructure.notifications.models import SupportTicket
        ticket = SupportTicket.objects.create(
            org=org,
            submitted_by=user,
            subject='Test ticket',
            message='Test message',
            priority='medium',
        )

        mail.outbox = []
        response = sc.post(
            f'/superadmin/support-tickets/{ticket.id}/reply/',
            {'message': 'We are looking into this'},
        )
        assert response.status_code == 200
        assert any(
            user.email in m.to
            for m in mail.outbox
        )

    def test_unauthenticated_cannot_submit_ticket(self, client):
        response = client.post('/support/ticket/submit/', {
            'subject': 'Test',
            'message': 'Test',
            'priority': 'low',
        })
        assert response.status_code in [302, 401]

    def test_tenant_org_auto_captured(self, tenant_client):
        client, org, user = tenant_client
        client.post(
            '/support/ticket/submit/',
            {
                'subject': 'Auto capture test',
                'message': 'Testing org capture',
                'priority': 'low',
            },
        )
        from apps.infrastructure.notifications.models import SupportTicket
        with set_tenant_context(org):
            ticket = SupportTicket.objects.filter(
                subject='Auto capture test'
            ).first()
        assert ticket is not None
        assert ticket.org == org
        assert ticket.submitted_by == user
