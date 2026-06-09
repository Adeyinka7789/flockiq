import structlog
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.infrastructure.core.rls import set_tenant_context
from apps.infrastructure.tenants.models import Organization
from .models import AlertRule, DEFAULT_ALERT_RULES

logger = structlog.get_logger(__name__)


@receiver(post_save, sender=Organization, dispatch_uid="notifications.seed_alert_rules")
def seed_alert_rules(sender, instance, created, **kwargs):
    if not created:
        return
    with set_tenant_context(instance):
        for rule_data in DEFAULT_ALERT_RULES:
            AlertRule.objects.get_or_create(
                org_id=instance.id,
                event_type=rule_data["event_type"],
                defaults={k: v for k, v in rule_data.items() if k != "event_type"},
            )
    logger.info("notifications.alert_rules_seeded", org_id=str(instance.id), count=len(DEFAULT_ALERT_RULES))
