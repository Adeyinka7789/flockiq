from django.core.management.base import BaseCommand

from apps.infrastructure.core.rls import set_tenant_context
from apps.infrastructure.notifications.models import DEFAULT_ALERT_RULES, AlertRule
from apps.infrastructure.tenants.models import Organization


class Command(BaseCommand):
    help = 'Seeds default AlertRule records for all active orgs'

    def handle(self, *args, **kwargs):
        orgs = list(Organization.objects.filter(is_active=True))
        created_total = 0
        updated_total = 0

        for org in orgs:
            with set_tenant_context(org):
                for rule_def in DEFAULT_ALERT_RULES:
                    obj, was_created = AlertRule.objects.get_or_create(
                        org=org,
                        event_type=rule_def['event_type'],
                        defaults={
                            'notify_roles': rule_def['notify_roles'],
                            'channels': rule_def['channels'],
                            'min_severity': rule_def['min_severity'],
                            'cooldown_minutes': rule_def['cooldown_minutes'],
                            'is_active': True,
                        },
                    )
                    if was_created:
                        created_total += 1
                    else:
                        # Backfill any missing fields on existing rules
                        changed = False
                        for field in ('notify_roles', 'channels',
                                      'min_severity', 'cooldown_minutes'):
                            current = getattr(obj, field)
                            default = rule_def[field]
                            if not current or current != default:
                                setattr(obj, field, default)
                                changed = True
                        if changed:
                            obj.save(update_fields=[
                                'notify_roles', 'channels',
                                'min_severity', 'cooldown_minutes',
                            ])
                            updated_total += 1

        self.stdout.write(self.style.SUCCESS(
            f'AlertRules: {created_total} created, '
            f'{updated_total} updated across {len(orgs)} org(s).'
        ))
