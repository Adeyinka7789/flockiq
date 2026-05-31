# Skill: Paystack Billing — Subscription + Cycle Plans

## Four Plan Types
1. trial — free, time-limited (14 days), no card required
2. monthly — recurring monthly charge
3. cycle — activates on batch placement, deactivates on batch closure (~6 weeks)
4. yearly — annual recurring charge

## Paystack Integration

```python
# apps/billing/services.py
import requests
import hashlib
import hmac
from django.conf import settings

PAYSTACK_BASE = 'https://api.paystack.co'
HEADERS = {
    'Authorization': f'Bearer {settings.PAYSTACK_SECRET_KEY}',
    'Content-Type': 'application/json',
}


def create_subscription(email: str, plan_code: str, authorization_code: str) -> dict:
    """Create a recurring Paystack subscription."""
    response = requests.post(f'{PAYSTACK_BASE}/subscription', headers=HEADERS, json={
        'customer': email,
        'plan': plan_code,
        'authorization': authorization_code,
    })
    return response.json()


def cancel_subscription(subscription_code: str, token: str) -> dict:
    """Cancel/pause a Paystack subscription (used for cycle plan on batch closure)."""
    response = requests.post(f'{PAYSTACK_BASE}/subscription/disable', headers=HEADERS, json={
        'code': subscription_code,
        'token': token,
    })
    return response.json()


def verify_webhook_signature(payload: bytes, signature: str) -> bool:
    """Verify Paystack webhook signature."""
    expected = hmac.new(
        settings.PAYSTACK_WEBHOOK_SECRET.encode('utf-8'),
        payload,
        hashlib.sha512
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
```

## Cycle Subscription Logic

```python
# apps/billing/models.py

class CycleSubscription(TenantModel):
    """One record per active broiler batch for cycle-based billing."""
    batch = models.OneToOneField('flocks.Batch', on_delete=models.CASCADE)
    paystack_subscription_code = models.CharField(max_length=100)
    paystack_email_token = models.CharField(max_length=255)
    status = models.CharField(max_length=20, default='active',
        choices=[('active','Active'),('paused','Paused'),('cancelled','Cancelled')])
    activated_at = models.DateTimeField(auto_now_add=True)
    deactivated_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        db_table = 'cycle_subscriptions'


# Signal: activate on batch placement
from django.db.models.signals import post_save
from django.dispatch import receiver

@receiver(post_save, sender=Batch)
def handle_batch_lifecycle(sender, instance, created, **kwargs):
    if created and instance.bird_type == 'broiler':
        if instance.org.plan == 'cycle':
            from apps.billing.tasks import activate_cycle_subscription
            activate_cycle_subscription.delay(str(instance.org_id), str(instance.id))

    if not created and instance.status == 'completed':
        try:
            cycle_sub = CycleSubscription.objects.get(batch=instance)
            from apps.billing.tasks import deactivate_cycle_subscription
            deactivate_cycle_subscription.delay(str(cycle_sub.id))
        except CycleSubscription.DoesNotExist:
            pass
```

## Webhook Handler

```python
# apps/billing/views.py

from django.views.decorators.csrf import csrf_exempt
from django.http import HttpResponse, HttpResponseBadRequest
import json

@csrf_exempt
def paystack_webhook(request):
    if request.method != 'POST':
        return HttpResponseBadRequest()

    payload = request.body
    signature = request.headers.get('X-Paystack-Signature', '')

    if not verify_webhook_signature(payload, signature):
        return HttpResponseBadRequest('Invalid signature')

    data = json.loads(payload)
    event = data.get('event')

    handlers = {
        'charge.success': handle_charge_success,
        'subscription.disable': handle_subscription_disabled,
        'subscription.create': handle_subscription_created,
        'invoice.create': handle_invoice_created,
    }

    handler = handlers.get(event)
    if handler:
        handler(data['data'])

    return HttpResponse(status=200)
```

## Settings
```python
PAYSTACK_SECRET_KEY = env('PAYSTACK_SECRET_KEY')
PAYSTACK_PUBLIC_KEY = env('PAYSTACK_PUBLIC_KEY')
PAYSTACK_WEBHOOK_SECRET = env('PAYSTACK_WEBHOOK_SECRET')

PAYSTACK_PLAN_CODES = {
    'monthly': env('PAYSTACK_MONTHLY_PLAN_CODE', default=''),
    'cycle': env('PAYSTACK_CYCLE_PLAN_CODE', default=''),
    'yearly': env('PAYSTACK_YEARLY_PLAN_CODE', default=''),
}
```
