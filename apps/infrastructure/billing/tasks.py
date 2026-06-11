import structlog
from celery import shared_task
from django.utils import timezone

logger = structlog.get_logger(__name__)

REMINDER_DAYS = {7, 3, 1}


@shared_task(name="billing.send_subscription_expiry_reminders")
def send_subscription_expiry_reminders():
    """
    Celery Beat — 08:00 daily.
    Fan-out: dispatch a per-org subtask for every paid org whose plan expires
    in exactly 7, 3 or 1 days. Trial orgs are excluded (separate trial banner).

    Day math is calendar-date based, NOT timedelta based: (expiry - now).days
    truncates, so an org activated at 07:00 and checked at 08:00 reads 6 days
    instead of 7 and silently misses its reminder.
    """
    from apps.infrastructure.core.rls import no_tenant_context
    from apps.infrastructure.tenants.models import Organization

    # localdate/localtime: calendar days in the platform timezone
    # (Africa/Lagos), not UTC — datetimes are stored in UTC.
    today = timezone.localdate()

    with no_tenant_context():
        rows = list(
            Organization.objects.filter(
                is_active=True,
                plan_tier__in=["monthly", "yearly", "cycle"],
                plan_expires_at__isnull=False,
            ).values_list("id", "plan_expires_at")
        )

    dispatched = 0
    for org_id, expires_at in rows:
        days_left = (timezone.localtime(expires_at).date() - today).days
        if days_left in REMINDER_DAYS:
            send_expiry_reminder_for_org.delay(str(org_id), days_left)
            dispatched += 1

    logger.info("billing.expiry_reminders_dispatched", count=dispatched, scanned=len(rows))


@shared_task(
    name="billing.send_expiry_reminder_for_org",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def send_expiry_reminder_for_org(self, org_id: str, days_left: int):
    """Send one paid-plan expiry reminder. Per-org so one failure retries alone."""
    from apps.infrastructure.core.rls import set_tenant_context
    from apps.infrastructure.tenants.models import Organization

    try:
        org = Organization.objects.get(id=org_id)
    except Organization.DoesNotExist:
        return

    try:
        with set_tenant_context(org):
            _send_expiry_reminder(org, days_left)
    except Exception as exc:
        logger.error("billing.expiry_reminder_error", org_id=org_id, error=str(exc))
        raise self.retry(exc=exc)


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


@shared_task(name="billing.mark_lapsed_orgs")
def mark_lapsed_orgs():
    """
    Celery Beat — 00:30 daily.
    Sets subscription_status='lapsed' on paid orgs whose plan_expires_at has
    passed. Access control does NOT depend on this task: Organization.is_lapsed
    is purely date-based, so writes are blocked the moment the plan expires.
    This keeps subscription_status accurate for reporting and admin filters.
    """
    from django.utils import timezone

    from apps.infrastructure.core.rls import no_tenant_context
    from apps.infrastructure.tenants.models import Organization

    with no_tenant_context():
        # Date-based: an org whose plan expires later today is not flagged
        # until tomorrow's run — only fully past calendar dates count.
        # localdate() matches the __date lookup, which converts the stored UTC
        # datetime to TIME_ZONE (Africa/Lagos) before taking the date.
        count = Organization.objects.filter(
            is_active=True,
            plan_tier__in=["monthly", "cycle", "yearly"],
            plan_expires_at__date__lt=timezone.localdate(),
            subscription_status="active",
        ).update(subscription_status="lapsed")

    if count:
        logger.info("billing.mark_lapsed_orgs", count=count)


@shared_task(name="billing.send_trial_expiry_reminders")
def send_trial_expiry_reminders():
    """
    Celery Beat — 08:30 daily.
    Fan-out: dispatch a per-org subtask for every trial org whose trial ends in
    exactly 7, 3 or 1 days. Separate from the paid-plan reminder task, which
    skips trials. Day math is calendar-date based — see
    send_subscription_expiry_reminders for why timedelta .days is wrong here.
    """
    from apps.infrastructure.core.rls import no_tenant_context
    from apps.infrastructure.tenants.models import Organization

    today = timezone.localdate()

    with no_tenant_context():
        rows = list(
            Organization.objects.filter(
                is_active=True,
                plan_tier="trial",
                trial_ends_at__isnull=False,
            ).values_list("id", "trial_ends_at")
        )

    dispatched = 0
    for org_id, trial_ends_at in rows:
        days_left = (timezone.localtime(trial_ends_at).date() - today).days
        if days_left in REMINDER_DAYS:
            send_trial_reminder_for_org.delay(str(org_id), days_left)
            dispatched += 1

    logger.info("billing.trial_reminders_dispatched", count=dispatched, scanned=len(rows))


@shared_task(
    name="billing.send_trial_reminder_for_org",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def send_trial_reminder_for_org(self, org_id: str, days_left: int):
    """Send one trial expiry reminder. Per-org so one failure retries alone."""
    from apps.infrastructure.core.rls import set_tenant_context
    from apps.infrastructure.tenants.models import Organization

    try:
        org = Organization.objects.get(id=org_id)
    except Organization.DoesNotExist:
        return

    try:
        with set_tenant_context(org):
            _send_trial_expiry_reminder(org, days_left)
    except Exception as exc:
        logger.error("billing.trial_reminder_error", org_id=org_id, error=str(exc))
        raise self.retry(exc=exc)


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
    Fan-out only: dispatch a per-org subtask for every active paid org. The
    Paystack verification (slow HTTP per subscription) happens in
    process_billing_for_org, so this parent finishes in seconds regardless of
    org count and never hits the 180s soft time limit.
    """
    from apps.infrastructure.core.rls import no_tenant_context
    from apps.infrastructure.tenants.models import Organization

    with no_tenant_context():
        org_ids = list(
            Organization.objects.filter(
                subscription_status="active",
                plan_tier__in=["monthly", "yearly"],
                is_active=True,
            ).values_list("id", flat=True)
        )

    for org_id in org_ids:
        process_billing_for_org.delay(str(org_id))

    logger.info("billing.fan_out_dispatched", count=len(org_ids))


@shared_task(
    name="billing.process_billing_for_org",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def process_billing_for_org(self, org_id: str):
    """Verify Paystack subscription status for a single org, with retries."""
    from apps.infrastructure.core.rls import set_tenant_context
    from apps.infrastructure.tenants.models import Organization
    from .models import CycleSubscription
    from .services import PaystackService

    try:
        org = Organization.objects.get(id=org_id)
    except Organization.DoesNotExist:
        return

    ps = PaystackService()
    try:
        with set_tenant_context(org):
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
        logger.error("billing.monthly_cycle_error", org_id=org_id, error=str(exc))
        raise self.retry(exc=exc)
