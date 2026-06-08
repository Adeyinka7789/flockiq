"""
Notification-pipeline journeys: a water anomaly fans out to the outbox, the
HTMX bell renders, and mark-all-read clears the unread count.
"""
import datetime

import pytest

from apps.infrastructure.core.rls import set_tenant_context


@pytest.mark.django_db(transaction=True)
class TestNotificationFlow:

    def test_water_anomaly_creates_outbox_event(self, make_org, make_farm):
        org, user = make_org(subdomain='watertest')
        farm, house, batch = make_farm(org)

        from apps.production.water.models import WaterLog
        from apps.infrastructure.notifications.models import OutboxEvent

        before = OutboxEvent.objects.count()
        # litres far below the calculated requirement → the water signal flags an
        # anomaly and NotificationService fans the alert out to the outbox.
        with set_tenant_context(org):
            WaterLog.objects.create(
                org=org,
                farm=farm,
                batch=batch,
                record_date=datetime.date.today(),
                litres_consumed=5,
            )
        after = OutboxEvent.objects.count()
        assert after > before

    def test_notification_bell_returns_fragment(self, tenant_client):
        client, org, user = tenant_client
        response = client.get(
            '/notifications/bell/',
            HTTP_HX_REQUEST='true',
        )
        assert response.status_code == 200

    def test_mark_all_read_clears_unread_count(self, tenant_client):
        client, org, user = tenant_client
        from apps.infrastructure.notifications.models import NotificationLog

        with set_tenant_context(org):
            NotificationLog.objects.create(
                org=org,
                recipient=user,
                event_type='announcement',
                title='Test notification',
                body='Test',
                severity='info',
                channel='in_app',
                is_read=False,
            )

        response = client.post(
            '/notifications/read-all/',
            HTTP_HX_REQUEST='true',
        )
        assert response.status_code == 200

        with set_tenant_context(org):
            unread = NotificationLog.objects.filter(
                recipient=user, is_read=False
            ).count()
        assert unread == 0
