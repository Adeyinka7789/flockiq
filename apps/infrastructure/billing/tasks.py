import structlog
from celery import shared_task
from django.utils import timezone

logger = structlog.get_logger(__name__)


@shared_task(name="billing.send_subscription_expiry_reminders")
def send_subscription_expiry_reminders():
    """
    Celery Beat — 08:00 daily.
    Email + in-app reminder to org owners at 7, 3, and 1 days before their paid
    plan expires. Trial orgs are excluded (they get the separate trial banner).
    """
    from apps.infrastructure.core.rls import no_tenant_context, set_tenant_context
    from apps.infrastructure.tenants.models import Organization

    now = timezone.now()
    reminder_days = {7, 3, 1}

    with no_tenant_context():
        org_ids = list(
            Organization.objects.filter(
                is_active=True,
                plan_tier__in=["monthly", "yearly", "cycle"],
                plan_expires_at__isnull=False,
            ).values_list("id", flat=True)
        )

    sent = 0
    for org_id in org_ids:
        try:
            with set_tenant_context(str(org_id)):
                org = Organization.objects.get(id=org_id)
                days_left = (org.plan_expires_at - now).days
                if days_left in reminder_days:
                    _send_expiry_reminder(org, days_left)
                    sent += 1
        except Exception as exc:
            logger.error("billing.expiry_reminder_error", org_id=str(org_id), error=str(exc))

    logger.info("billing.expiry_reminders_sent", count=sent, scanned=len(org_ids))


def _send_expiry_reminder(org, days_left: int) -> None:
    """Send one expiry reminder. Must run inside set_tenant_context(org)."""
    from apps.infrastructure.core.email_service import EmailService
    from apps.infrastructure.notifications.models import NotificationLog

    owner = org.users.filter(role="owner").first()
    if not owner:
        return

    urgency = "today" if days_left <= 1 else f"in {days_left} days"

    EmailService.send_expiry_reminder(owner, org, days_left)

    NotificationLog.objects.create(
        org=org,
        recipient=owner,
        event_type="billing_expiry_reminder",
        title=f"Plan expires {urgency}",
        body=(
            f"Your {org.plan_tier.title()} plan expires {urgency}. "
            f"Renew now to avoid interruption."
        ),
        severity="warning",
        channel="in_app",
        action_url="/billing/",
    )


@shared_task(name="billing.send_trial_expiry_reminders")
def send_trial_expiry_reminders():
    """
    Celery Beat — 08:30 daily.
    Email + in-app reminder to trial org owners at 7, 3, and 1 days before
    trial_ends_at. Separate from the paid-plan reminder task, which skips trials.
    """
    from apps.infrastructure.core.rls import no_tenant_context, set_tenant_context
    from apps.infrastructure.tenants.models import Organization

    now = timezone.now()
    reminder_days = {7, 3, 1}

    with no_tenant_context():
        org_ids = list(
            Organization.objects.filter(
                is_active=True,
                plan_tier="trial",
                trial_ends_at__isnull=False,
            ).values_list("id", flat=True)
        )

    sent = 0
    for org_id in org_ids:
        try:
            with set_tenant_context(str(org_id)):
                org = Organization.objects.get(id=org_id)
                days_left = (org.trial_ends_at - now).days
                if days_left in reminder_days:
                    _send_trial_expiry_reminder(org, days_left)
                    sent += 1
        except Exception as exc:
            logger.error("billing.trial_reminder_error", org_id=str(org_id), error=str(exc))

    logger.info("billing.trial_reminders_sent", count=sent, scanned=len(org_ids))


def _send_trial_expiry_reminder(org, days_left: int) -> None:
    """Send one trial expiry email + in-app notification. Runs inside set_tenant_context(org)."""
    from apps.infrastructure.core.email_service import EmailService
    from apps.infrastructure.notifications.models import NotificationLog

    owner = org.users.filter(role="owner").first()
    if not owner:
        return

    urgency = "today" if days_left <= 1 else f"in {days_left} days"

    EmailService.send_trial_ending(
        owner_email=owner.email,
        owner_name=owner.get_full_name() or owner.email,
        org_name=org.name,
        days_left=days_left,
    )

    NotificationLog.objects.create(
        org=org,
        recipient=owner,
        event_type="trial_expiry_reminder",
        title=f"Your trial expires {urgency}",
        body=(
            f"Your free trial for {org.name} expires {urgency}. "
            f"Upgrade now to keep access to all features."
        ),
        severity="warning" if days_left <= 3 else "info",
        channel="in_app",
        action_url="/billing/",
    )


@shared_task(name="billing.activate_cycle_subscription")
def activate_cycle_subscription(org_id: str, batch_id: str):
    """Called from flocks signal when a new broiler batch is placed."""
    from apps.infrastructure.core.rls import set_tenant_context
    from apps.infrastructure.tenants.models import Organization
    from .services import BillingService

    with set_tenant_context(org_id):
        org = Organization.objects.get(id=org_id)
        svc = BillingService(org)
        sub = svc.activate_cycle_subscription(batch_id)
        logger.info("billing.task.cycle_sub_activated", org_id=org_id, batch_id=batch_id, sub_id=str(sub.id))


@shared_task(name="billing.deactivate_cycle_subscription")
def deactivate_cycle_subscription(cycle_sub_id: str):
    """Called from flocks signal when a batch is closed."""
    from apps.infrastructure.billing.models import CycleSubscription
    from apps.infrastructure.core.rls import set_tenant_context
    from apps.infrastructure.tenants.models import Organization
    from .services import BillingService

    try:
        sub = CycleSubscription.objects.get(id=cycle_sub_id)
    except CycleSubscription.DoesNotExist:
        logger.warning("billing.task.cycle_sub_not_found", id=cycle_sub_id)
        return

    with set_tenant_context(str(sub.org_id)):
        org = Organization.objects.get(id=sub.org_id)
        svc = BillingService(org)
        svc.deactivate_cycle_subscription(sub.batch_id)
        logger.info("billing.task.cycle_sub_deactivated", cycle_sub_id=cycle_sub_id)


@shared_task(name="billing.process_monthly_billing_cycle")
def process_monthly_billing_cycle():
    """
    Celery Beat — 1st of every month.
    Fan-out: verify Paystack subscription status for all monthly orgs.
    Runs cross-tenant via no_tenant_context(); only safe to query Organization here.
    """
    from apps.infrastructure.core.rls import no_tenant_context, set_tenant_context
    from apps.infrastructure.tenants.models import Organization
    from .services import BillingService, PaystackService
    from .models import CycleSubscription

    ps = PaystackService()

    with no_tenant_context():
        org_ids = list(
            Organization.objects.filter(
                subscription_status="active",
                plan_tier__in=["monthly", "yearly"],
                is_active=True,
            ).values_list("id", flat=True)
        )

    logger.info("billing.monthly_cycle_start", org_count=len(org_ids))

    for org_id in org_ids:
        try:
            with set_tenant_context(str(org_id)):
                from apps.infrastructure.tenants.models import Organization as Org
                org = Org.objects.get(id=org_id)
                # Verify active cycle subscriptions with Paystack
                active_subs = CycleSubscription.objects.filter(
                    org=org,
                    status="active",
                ).exclude(paystack_subscription_code="")

                for sub in active_subs:
                    result = ps.get_subscription(sub.paystack_subscription_code)
                    ps_status = (result.get("data") or {}).get("status")
                    if ps_status == "non-renewing":
                        sub.status = "paused"
                        sub.save(update_fields=["status"])
                        logger.warning("billing.sub_paused_by_paystack", sub_id=str(sub.id))
        except Exception as exc:
            logger.error("billing.monthly_cycle_error", org_id=str(org_id), error=str(exc))
