import structlog
from django.db.models.signals import post_save
from django.dispatch import receiver

logger = structlog.get_logger(__name__)


@receiver(post_save, sender="tenants.Organization", dispatch_uid="tenants.on_organization_created")
def on_organization_created(sender, instance, created, **kwargs):
    if not created:
        return
    logger.info(
        "org.created",
        org_id=str(instance.id),
        subdomain=instance.subdomain,
        plan_tier=instance.plan_tier,
    )
    # AlertRule seeding is handled by notifications.signals.seed_alert_rules
    # registered via NotificationsConfig.ready()


@receiver(post_save, sender="tenants.Organization", dispatch_uid="tenants.on_plan_activated")
def on_plan_activated(sender, instance, created, **kwargs):
    if created:
        return

    # Only fire when subscription_status was explicitly saved (programmatic upgrades).
    # update_fields is None for Django admin saves, so those are excluded here.
    update_fields = kwargs.get("update_fields")
    if not update_fields or "subscription_status" not in update_fields:
        return

    if instance.subscription_status != "active":
        return

    owner = instance.users.filter(role="owner").first()
    if not owner:
        return

    try:
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.infrastructure.notifications.models import NotificationLog
        with set_tenant_context(instance):
            NotificationLog.objects.create(
                org=instance,
                recipient=owner,
                event_type="plan_activated",
                title="\U0001f389 Your plan is now active!",
                body=(
                    f"Your {instance.plan_tier.title()} plan has been activated. "
                    f"Enjoy full access to FlockIQ."
                ),
                severity="info",
                channel="in_app",
                is_read=False,
            )
        logger.info("billing.plan_activated_notification_sent", org_id=str(instance.id))
    except Exception as exc:
        logger.error("billing.plan_activated_notification_failed", org_id=str(instance.id), error=str(exc))
