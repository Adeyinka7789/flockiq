"""Tests for Paystack webhook idempotency.

A retried delivery (same `data.id`) must be acknowledged with 200 but NOT
re-dispatched, so the payment is never processed/activated twice.
"""

import json
from unittest.mock import patch

import pytest
from django.urls import reverse

from apps.infrastructure.billing.models import PaystackWebhookLog
from apps.infrastructure.billing.views import PaystackWebhookView

WEBHOOK_URL = reverse("billing:webhook")

PAYLOAD = {
    "event": "charge.success",
    "data": {
        "id": 99887766,
        "reference": "ref_dup_test",
        "amount": 500000,
        "customer": {"email": "owner@example.com"},
    },
}


@pytest.mark.django_db
@patch(
    "apps.infrastructure.billing.services.PaystackService.verify_webhook_signature",
    return_value=True,
)
def test_duplicate_webhook_returns_200_without_reprocessing(mock_verify, client):
    body = json.dumps(PAYLOAD)

    with patch.object(PaystackWebhookView, "_dispatch") as mock_dispatch:
        first = client.post(
            WEBHOOK_URL, data=body, content_type="application/json"
        )
        second = client.post(
            WEBHOOK_URL, data=body, content_type="application/json"
        )

    # Both acknowledged so Paystack stops retrying.
    assert first.status_code == 200
    assert second.status_code == 200

    # The handler ran exactly once — the duplicate was short-circuited.
    assert mock_dispatch.call_count == 1

    # Both deliveries are audited; only the first is marked processed.
    logs = PaystackWebhookLog.objects.filter(event_id="99887766")
    assert logs.count() == 2
    assert logs.filter(processed=True).count() == 1
    assert logs.filter(error="duplicate: already processed").count() == 1


@pytest.mark.django_db
@patch(
    "apps.infrastructure.billing.services.PaystackService.verify_webhook_signature",
    return_value=True,
)
def test_distinct_events_are_each_processed(mock_verify, client):
    payload_b = json.loads(json.dumps(PAYLOAD))
    payload_b["data"]["id"] = 11223344
    payload_b["data"]["reference"] = "ref_other"

    with patch.object(PaystackWebhookView, "_dispatch") as mock_dispatch:
        client.post(
            WEBHOOK_URL, data=json.dumps(PAYLOAD),
            content_type="application/json",
        )
        client.post(
            WEBHOOK_URL, data=json.dumps(payload_b),
            content_type="application/json",
        )

    # Different event ids → both dispatched.
    assert mock_dispatch.call_count == 2


@pytest.mark.django_db
@patch(
    "apps.infrastructure.billing.services.PaystackService.verify_webhook_signature",
    return_value=False,
)
def test_invalid_signature_rejected_before_idempotency(mock_verify, client):
    resp = client.post(
        WEBHOOK_URL, data=json.dumps(PAYLOAD), content_type="application/json"
    )
    assert resp.status_code == 400
    # Logged for audit, but never processed.
    assert PaystackWebhookLog.objects.filter(
        event_id="99887766", processed=False
    ).exists()
