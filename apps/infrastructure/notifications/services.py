from datetime import date, timedelta

import structlog
from django.utils import timezone

from apps.infrastructure.core.services import BaseService
from .models import AlertRule, NotificationLog, OutboxEvent

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Role floor for sensitive notifications.
#
# These event types carry financial / security-sensitive information and must
# NEVER be routed to data_entry or vet_advisor, regardless of how an org's
# AlertRule.notify_roles is configured. This is a code-level guard so a
# misconfigured rule cannot leak financial data to a restricted role.
# Both the canonical event names and the billing-prefixed aliases are listed
# so the floor holds whichever naming a caller uses.
# ---------------------------------------------------------------------------
FINANCIAL_EVENT_TYPES = {
    "billing_plan_activated",
    "billing_plan_expired",
    "plan_expired",
    "plan_activated",
    "payment_failed",
    "payment_success",
    # Billing notices routed through notify() (formerly direct NotificationLog
    # creates). Membership here means the RBAC floor below applies so they can
    # never reach data_entry / vet_advisor.
    "billing_upgrade_request",
    "billing_upgrade_scheduled",
    "billing_expiry_reminder",
    "trial_expiry_reminder",
    "theft_suspected",
    "sale_timing",
    "credit_score_updated",
}

RESTRICTED_ROLES = {"data_entry", "vet_advisor"}

# ---------------------------------------------------------------------------
# Account-critical events that bypass the *personal preference* mute.
#
# A farmer who toggles off "financial reports" must still be told when a
# payment fails or their plan / trial is about to expire — otherwise an account
# can silently lapse (real revenue + access risk). These events still respect
# the RBAC floor above (they are in FINANCIAL_EVENT_TYPES, so data_entry /
# vet_advisor are still excluded); they only bypass the category-mute layer.
# ---------------------------------------------------------------------------
ALWAYS_DELIVER_EVENT_TYPES = {
    "payment_failed",
    "billing_expiry_reminder",
    "trial_expiry_reminder",
}

# ---------------------------------------------------------------------------
# Category mapping for personal notification preferences.
#
# Each event type is grouped under the category toggle a user can mute on the
# notification preferences page. Event names here must match the keys emitted
# by NotificationService.send() callers (see MESSAGE_TEMPLATES) and the
# domain-event vocabulary used across the apps.
# ---------------------------------------------------------------------------
HEALTH_EVENT_TYPES = {
    "mortality_spike",
    "mortality_alert",
    "vaccination_due",
    "vaccination_overdue",
    "vaccination_reminder",
    "disease_outbreak",
    "health_alert",
    "medication_withdrawal",
}
PRODUCTION_EVENT_TYPES = {
    "production_drop",
    "water_drop",
    "feed_efficiency",
    "harvest_timing",
    "production_insight",
    "farm_memory",
    "weekly_summary",
}
SYSTEM_EVENT_TYPES = {
    "system",
    "platform_update",
    "maintenance",
}


def _should_receive(user, event_type: str) -> bool:
    """Decide whether a notification should reach a given user.

    Three layers of gating, in order:
      1. RBAC floor — financial/sensitive events can never reach a restricted
         role (data_entry / vet_advisor), regardless of anything below.
      2. Always-deliver floor — account-critical events (payment failure, plan/
         trial expiry) bypass the personal category mute so an account cannot
         silently lapse. They have already passed the RBAC floor above.
      3. Personal category preferences — a user who has muted a category does
         not receive its events.
    """
    # 1. RBAC floor (cannot be overridden by anything).
    if event_type in FINANCIAL_EVENT_TYPES and user.role in RESTRICTED_ROLES:
        return False

    # 2. Always-deliver floor — account-critical, not muteable by preference.
    if event_type in ALWAYS_DELIVER_EVENT_TYPES:
        return True

    # 3. Personal category preferences.
    if event_type in HEALTH_EVENT_TYPES and not user.notify_health_alerts:
        return False
    if event_type in PRODUCTION_EVENT_TYPES and not user.notify_production_insights:
        return False
    if event_type in FINANCIAL_EVENT_TYPES and not user.notify_financial_reports:
        return False
    if event_type in SYSTEM_EVENT_TYPES and not user.notify_system_updates:
        return False

    return True


# ---------------------------------------------------------------------------
# Message templates for all 15 event types.
# Keys: sms, email_subject, email_body, in_app_title, in_app_body
# Placeholders: {farm_name}, {batch_name}, {count}, {date}, {value}, {normal}
# ---------------------------------------------------------------------------
MESSAGE_TEMPLATES = {
    "mortality_spike": {
        "sms": "ALERT: Unusual mortality at {farm_name}. {count} deaths today vs normal {normal}. Check flock immediately.",
        "email_subject": "Mortality Alert — {farm_name}",
        "email_body": "Unusual mortality detected at {farm_name} ({batch_name}).\n{count} deaths recorded today vs normal threshold of {normal}.\nPlease inspect your flock immediately.",
        "in_app_title": "Mortality Spike Detected",
        "in_app_body": "{count} deaths recorded at {farm_name} — above normal threshold of {normal}.",
    },
    "water_drop": {
        "sms": "WARNING: Water consumption drop at {farm_name}. Current: {value}L. Check water system.",
        "email_subject": "Water Drop Alert — {farm_name}",
        "email_body": "Water consumption has dropped significantly at {farm_name} ({batch_name}).\nCurrent: {value}L. Please check your water supply and nipple drinkers.",
        "in_app_title": "Water Consumption Drop",
        "in_app_body": "Water consumption at {farm_name} has dropped to {value}L. Inspect water system.",
    },
    "production_drop": {
        "sms": "INFO: Egg production drop at {farm_name}. Current: {value} trays. Check flock health.",
        "email_subject": "Production Drop — {farm_name}",
        "email_body": "Egg production has dropped at {farm_name} ({batch_name}).\nCurrent production: {value} trays. Previous: {normal}. Review flock health and feed quality.",
        "in_app_title": "Egg Production Drop",
        "in_app_body": "Production at {farm_name} fell to {value} trays (was {normal}). Review flock.",
    },
    "vaccination_due": {
        "sms": "REMINDER: Vaccination due for {batch_name} at {farm_name} on {date}. Prepare vaccines.",
        "email_subject": "Vaccination Due — {batch_name}",
        "email_body": "Vaccination is due for batch {batch_name} at {farm_name}.\nScheduled date: {date}.\nPlease prepare vaccines and schedule your vet.",
        "in_app_title": "Vaccination Due",
        "in_app_body": "Batch {batch_name} at {farm_name} is due for vaccination on {date}.",
    },
    "vaccination_overdue": {
        "sms": "URGENT: Vaccination OVERDUE for {batch_name} at {farm_name}. Administer immediately.",
        "email_subject": "Vaccination Overdue — {batch_name}",
        "email_body": "URGENT: Vaccination is overdue for batch {batch_name} at {farm_name}.\nScheduled date was {date}.\nAdminister vaccines immediately to prevent disease outbreak.",
        "in_app_title": "Vaccination Overdue",
        "in_app_body": "URGENT: {batch_name} at {farm_name} vaccination is overdue since {date}.",
    },
    "theft_suspected": {
        "sms": "SECURITY ALERT: Possible theft detected at {farm_name}. Stock discrepancy: {count} birds. Verify inventory.",
        "email_subject": "Theft Alert — {farm_name}",
        "email_body": "A stock discrepancy has been detected at {farm_name} ({batch_name}).\nDiscrepancy: {count} birds unaccounted for.\nPlease verify your inventory and review security footage.",
        "in_app_title": "Theft Suspected",
        "in_app_body": "Stock discrepancy of {count} birds at {farm_name}. Verify inventory immediately.",
    },
    "heat_stress": {
        "sms": "CRITICAL: Heat stress conditions at {farm_name}. Temperature: {value}°C. Cool birds immediately.",
        "email_subject": "Heat Stress Alert — {farm_name}",
        "email_body": "Critical heat stress conditions detected at {farm_name}.\nTemperature: {value}°C — above safe threshold.\nActivate cooling systems and increase water supply immediately.",
        "in_app_title": "Heat Stress Alert",
        "in_app_body": "Temperature at {farm_name} is {value}°C — heat stress risk. Activate cooling.",
    },
    "heavy_rain": {
        "sms": "WEATHER: Heavy rain forecast near {farm_name}. Secure housing and check drainage.",
        "email_subject": "Heavy Rain Alert — {farm_name}",
        "email_body": "Heavy rain is forecast near {farm_name}.\nEnsure housing is secure, drainage channels are clear, and litter is protected from moisture.",
        "in_app_title": "Heavy Rain Forecast",
        "in_app_body": "Heavy rain expected near {farm_name}. Secure housing and drainage.",
    },
    "high_humidity": {
        "sms": "WARNING: High humidity at {farm_name} — {value}%. Improve ventilation to prevent disease.",
        "email_subject": "High Humidity Alert — {farm_name}",
        "email_body": "High humidity levels detected at {farm_name}.\nHumidity: {value}%.\nImprove ventilation and check litter condition to prevent respiratory disease.",
        "in_app_title": "High Humidity Detected",
        "in_app_body": "Humidity at {farm_name} is {value}% — above threshold. Improve ventilation.",
    },
    "batch_closed": {
        "sms": "Batch {batch_name} at {farm_name} has been closed on {date}.",
        "email_subject": "Batch Closed — {batch_name}",
        "email_body": "Batch {batch_name} at {farm_name} was closed on {date}.\nFinal summary and performance report are now available in your FlockIQ dashboard.",
        "in_app_title": "Batch Closed",
        "in_app_body": "Batch {batch_name} at {farm_name} was closed on {date}. View final report.",
    },
    "sale_timing": {
        "sms": "AI TIP: Optimal sale window for {batch_name} at {farm_name}. Market price: ₦{value}/kg. Consider selling now.",
        "email_subject": "Sale Timing Recommendation — {batch_name}",
        "email_body": "Our AI has identified a good sale window for batch {batch_name} at {farm_name}.\nCurrent market rate: ₦{value}/kg.\nReview your production data and market conditions before deciding.",
        "in_app_title": "Sale Timing Recommendation",
        "in_app_body": "Good sale window for {batch_name}. Current rate: ₦{value}/kg. Check market.",
    },
    "weekly_summary": {
        "sms": "FlockIQ Weekly: {farm_name} — {count} birds active, {value} trays eggs, week ending {date}.",
        "email_subject": "Weekly Farm Summary — {farm_name}",
        "email_body": "Weekly summary for {farm_name} — week ending {date}.\n\nActive birds: {count}\nEgg production: {value} trays\n\nView full report in your FlockIQ dashboard.",
        "in_app_title": "Weekly Summary Ready",
        "in_app_body": "Your weekly summary for {farm_name} (w/e {date}) is ready. Tap to view.",
    },
    "incomplete_tasks": {
        "sms": "REMINDER: {count} incomplete tasks at {farm_name} today ({date}). Check your task list.",
        "email_subject": "Incomplete Tasks — {farm_name}",
        "email_body": "{count} farm tasks remain incomplete at {farm_name} for {date}.\nPlease log in to FlockIQ and complete or reschedule these tasks.",
        "in_app_title": "Incomplete Tasks Today",
        "in_app_body": "{count} tasks incomplete at {farm_name} for {date}. Review your task list.",
    },
    "disease_outbreak": {
        "sms": "CRITICAL: Disease outbreak reported near {farm_name}. Increase biosecurity immediately. Contact vet.",
        "email_subject": "Disease Outbreak Alert — {farm_name}",
        "email_body": "A disease outbreak has been reported in the region near {farm_name}.\nIncrease biosecurity measures immediately:\n- Restrict farm access\n- Disinfect entry points\n- Monitor flock closely\n- Contact your vet advisor",
        "in_app_title": "Regional Disease Alert",
        "in_app_body": "Disease outbreak near {farm_name}. Increase biosecurity and contact your vet.",
    },
    "medication_withdrawal": {
        "sms": "REMINDER: Medication withdrawal period ending for {batch_name} at {farm_name} on {date}. Safe to sell after this date.",
        "email_subject": "Medication Withdrawal Period Ending — {batch_name}",
        "email_body": "The medication withdrawal period for batch {batch_name} at {farm_name} ends on {date}.\nBirds will be safe for sale/consumption after this date.\nDo not sell before the withdrawal period ends.",
        "in_app_title": "Withdrawal Period Ending",
        "in_app_body": "{batch_name} medication withdrawal ends {date}. Safe to sell after this date.",
    },
}


class NotificationService(BaseService):
    def send(self, event_type, context, severity="info", farm=None, batch=None):
        """
        Main entry point. Always called INSIDE an existing transaction.atomic() block —
        OutboxEvent creation is atomic with the domain write.
        """
        try:
            rule = AlertRule.objects.get(org=self.org, event_type=event_type, is_active=True)
        except AlertRule.DoesNotExist:
            self.logger.debug("notification.no_rule", event_type=event_type)
            return 0

        if rule.cooldown_minutes > 0:
            cutoff = timezone.now() - timedelta(minutes=rule.cooldown_minutes)
            duplicate = OutboxEvent.objects.filter(
                org_id=self.org.id,
                event_type=event_type,
                status="delivered",
                delivered_at__gte=cutoff,
            ).exists()
            if duplicate:
                self.logger.info("notification.cooldown_skipped", event_type=event_type)
                return 0

        from apps.infrastructure.accounts.models import CustomUser
        recipients = CustomUser.tenant_objects.filter(
            role__in=rule.notify_roles,
            is_active=True,
        )

        # Code-level floor: financial/sensitive events can never reach
        # data_entry or vet_advisor, even if the AlertRule lists them.
        recipients = [u for u in recipients if _should_receive(u, event_type)]

        today = date.today().isoformat()
        created = 0
        for user in recipients:
            for channel in rule.channels:
                subject, body_text, body_html = self._render_message(event_type, channel, context)
                idempotency_key = f"{event_type}:{self.org.id}:{user.id}:{today}:{channel}"
                if OutboxEvent.objects.filter(idempotency_key=idempotency_key).exists():
                    continue

                OutboxEvent.objects.create(
                    org_id=self.org.id,
                    event_type=event_type,
                    recipient_user_id=user.id,
                    recipient_phone=getattr(user, "phone", ""),
                    recipient_email=user.email,
                    subject=subject,
                    body=body_text,
                    body_html=body_html,
                    channel=channel,
                    idempotency_key=idempotency_key,
                    status="pending",
                )
                created += 1

        self.logger.info("notification.outbox_created", event_type=event_type, count=created)
        return created

    def _render_message(self, event_type, channel, context):
        template = MESSAGE_TEMPLATES.get(event_type, {})
        safe_ctx = {k: (v if v is not None else "") for k, v in context.items()}
        try:
            if channel == "sms":
                body = template.get("sms", event_type).format(**safe_ctx)
                return "", body, ""
            elif channel == "email":
                subject = template.get("email_subject", event_type).format(**safe_ctx)
                body = template.get("email_body", event_type).format(**safe_ctx)
                body_html = f"<p>{body.replace(chr(10), '</p><p>')}</p>"
                return subject, body, body_html
            else:  # in_app
                title = template.get("in_app_title", event_type).format(**safe_ctx)
                body = template.get("in_app_body", event_type).format(**safe_ctx)
                return title, body, ""
        except KeyError:
            fallback = f"{event_type} event occurred"
            return event_type, fallback, ""

    def notify(
        self,
        recipient,
        event_type,
        title,
        body,
        severity="info",
        channel="in_app",
        action_url="",
        batch_reference="",
        outbox_event_id=None,
    ):
        """Create a targeted in-app NotificationLog for a *specific* recipient,
        gated by _should_receive() (RBAC floor + personal category preferences).

        This is the sanctioned replacement for direct
        NotificationLog.objects.create() calls that target a known recipient.

        It is deliberately NOT the same as send(): send() is the AlertRule-driven
        fan-out that derives recipients by role and writes OutboxEvent rows for
        the delivery pipeline. notify() writes the in-app NotificationLog row
        directly for one already-chosen user — but, unlike a raw create(), it
        runs the same _should_receive() gate send() applies, so a restricted role
        or a muted category is honoured.

        Returns the created NotificationLog, or None if the recipient's role /
        preferences filter the event out.

        Must be called inside set_tenant_context(self.org) — NotificationLog is
        RLS-protected, exactly as the previous direct create() calls required.
        """
        if not _should_receive(recipient, event_type):
            self.logger.info(
                "notification.suppressed",
                event_type=event_type,
                recipient_id=str(recipient.id),
                role=recipient.role,
            )
            return None

        return NotificationLog.objects.create(
            org=self.org,
            recipient=recipient,
            event_type=event_type,
            title=title,
            body=body,
            severity=severity,
            channel=channel,
            action_url=action_url,
            batch_reference=batch_reference,
            outbox_event_id=outbox_event_id,
        )

    def mark_read(self, notification_log_id, user):
        updated = NotificationLog.objects.filter(
            id=notification_log_id,
            recipient=user,
        ).update(is_read=True, read_at=timezone.now())
        if not updated:
            self.logger.warning("notification.mark_read_denied",
                                id=str(notification_log_id),
                                user_id=str(user.id))
        return updated

    def get_unread_count(self, user) -> int:
        return NotificationLog.objects.filter(
            org=self.org,
            recipient=user,
            is_read=False,
        ).count()

    def get_notifications(self, user, limit=20):
        return NotificationLog.objects.filter(
            org=self.org,
            recipient=user,
        ).order_by("-created_at")[:limit]
