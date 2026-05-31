import structlog
from django.db.models.signals import post_save
from django.dispatch import receiver

logger = structlog.get_logger(__name__)


@receiver(post_save, sender="tenants.Organization")
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
