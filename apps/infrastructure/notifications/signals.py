import structlog
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.infrastructure.tenants.models import Organization
from .models import AlertRule, DEFAULT_ALERT_RULES

logger = structlog.get_logger(__name__)


@receiver(post_save, sender=Organization)
def seed_alert_rules(sender, instance, created, **kwargs):
    if not created:
        return
    for rule_data in DEFAULT_ALERT_RULES:
        # Use unscoped() because this signal fires without a tenant RLS context.
        # The org is freshly created so no rules exist yet; get_or_create prevents
        # duplicates if the signal ever fires more than once for the same org.
        AlertRule.objects.unscoped().get_or_create(
            org=instance,
            event_type=rule_data["event_type"],
            defaults={k: v for k, v in rule_data.items() if k != "event_type"},
        )
    logger.info("notifications.alert_rules_seeded", org_id=str(instance.id), count=len(DEFAULT_ALERT_RULES))
