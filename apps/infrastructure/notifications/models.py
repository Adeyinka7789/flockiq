import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.infrastructure.core.models import TenantAwareModel


EVENT_TYPE_CHOICES = [
    ("mortality_spike", "Mortality Spike"),
    ("water_drop", "Water Drop"),
    ("production_drop", "Production Drop"),
    ("vaccination_due", "Vaccination Due"),
    ("vaccination_overdue", "Vaccination Overdue"),
    ("theft_suspected", "Theft Suspected"),
    ("heat_stress", "Heat Stress"),
    ("heavy_rain", "Heavy Rain"),
    ("high_humidity", "High Humidity"),
    ("batch_closed", "Batch Closed"),
    ("sale_timing", "Sale Timing"),
    ("weekly_summary", "Weekly Summary"),
    ("incomplete_tasks", "Incomplete Tasks"),
    ("disease_outbreak", "Disease Outbreak"),
    ("medication_withdrawal", "Medication Withdrawal"),
]

SEVERITY_CHOICES = [
    ("info", "Info"),
    ("warning", "Warning"),
    ("critical", "Critical"),
]

CHANNEL_CHOICES = [
    ("sms", "SMS"),
    ("email", "Email"),
    ("in_app", "In-App"),
]

STATUS_CHOICES = [
    ("pending", "Pending"),
    ("processing", "Processing"),
    ("delivered", "Delivered"),
    ("failed", "Failed"),
    ("skipped", "Skipped"),
]


class AlertRule(TenantAwareModel):
    event_type = models.CharField(max_length=60, choices=EVENT_TYPE_CHOICES)
    notify_roles = models.JSONField(default=list)
    channels = models.JSONField(default=list)
    is_active = models.BooleanField(default=True)
    min_severity = models.CharField(max_length=10, choices=SEVERITY_CHOICES, default="info")
    cooldown_minutes = models.IntegerField(default=60)

    class Meta:
        db_table = "notifications_alertrule"
        unique_together = [("org", "event_type")]

    def __str__(self):
        return f"{self.event_type} → {self.channels} ({self.org})"


class OutboxEvent(models.Model):
    """
    Cross-tenant outbox table — RLS DISABLED.
    Workers poll this table across all orgs. Storing org_id as UUID (not FK)
    prevents Django from attempting tenant-scoped joins during worker processing.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org_id = models.UUIDField(db_index=True)
    event_type = models.CharField(max_length=60)
    recipient_user_id = models.UUIDField()
    recipient_phone = models.CharField(max_length=20, blank=True)
    recipient_email = models.EmailField(blank=True)
    subject = models.CharField(max_length=200)
    body = models.TextField()
    body_html = models.TextField(blank=True)
    channel = models.CharField(max_length=10, choices=CHANNEL_CHOICES)
    idempotency_key = models.CharField(max_length=100, unique=True)
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default="pending")
    attempts = models.IntegerField(default=0)
    max_attempts = models.IntegerField(default=3)
    last_attempted_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    error_detail = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "notifications_outboxevent"
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["idempotency_key"]),
            models.Index(fields=["org_id", "event_type"]),
        ]

    def __str__(self):
        return f"{self.event_type}/{self.channel} → {self.status}"


class NotificationLog(TenantAwareModel):
    event_type = models.CharField(max_length=60)
    title = models.CharField(max_length=200)
    body = models.TextField()
    severity = models.CharField(max_length=10, choices=SEVERITY_CHOICES)
    channel = models.CharField(max_length=10, choices=CHANNEL_CHOICES)
    recipient = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.CASCADE,
        related_name="notification_logs",
    )
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    outbox_event_id = models.UUIDField(null=True, blank=True)
    acknowledged = models.BooleanField(default=False)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="acknowledged_notifications",
    )
    # farm and batch FKs added in 0002_add_farm_batch_fks.py once those apps land

    class Meta:
        db_table = "notifications_notificationlog"
        indexes = [
            models.Index(fields=["org", "is_read", "created_at"]),
        ]

    def __str__(self):
        return f"{self.title} → {self.recipient} ({'read' if self.is_read else 'unread'})"


DEFAULT_ALERT_RULES = [
    {"event_type": "mortality_spike",       "notify_roles": ["owner", "manager"],                    "channels": ["sms", "in_app"],   "min_severity": "warning",  "cooldown_minutes": 120},
    {"event_type": "water_drop",            "notify_roles": ["owner", "manager"],                    "channels": ["sms", "in_app"],   "min_severity": "warning",  "cooldown_minutes": 60},
    {"event_type": "production_drop",       "notify_roles": ["owner", "manager"],                    "channels": ["in_app"],          "min_severity": "info",     "cooldown_minutes": 60},
    {"event_type": "vaccination_due",       "notify_roles": ["owner", "manager", "supervisor"],      "channels": ["sms", "in_app"],   "min_severity": "info",     "cooldown_minutes": 1440},
    {"event_type": "vaccination_overdue",   "notify_roles": ["owner", "manager"],                    "channels": ["sms", "in_app"],   "min_severity": "critical", "cooldown_minutes": 360},
    {"event_type": "theft_suspected",       "notify_roles": ["owner"],                               "channels": ["sms", "in_app"],   "min_severity": "critical", "cooldown_minutes": 1440},
    {"event_type": "heat_stress",           "notify_roles": ["owner", "manager", "supervisor"],      "channels": ["sms", "in_app"],   "min_severity": "critical", "cooldown_minutes": 360},
    {"event_type": "heavy_rain",            "notify_roles": ["owner", "manager"],                    "channels": ["in_app"],          "min_severity": "info",     "cooldown_minutes": 360},
    {"event_type": "high_humidity",         "notify_roles": ["owner", "manager"],                    "channels": ["in_app"],          "min_severity": "warning",  "cooldown_minutes": 360},
    {"event_type": "batch_closed",          "notify_roles": ["owner"],                               "channels": ["in_app"],          "min_severity": "info",     "cooldown_minutes": 0},
    {"event_type": "sale_timing",           "notify_roles": ["owner", "manager"],                    "channels": ["sms", "in_app"],   "min_severity": "info",     "cooldown_minutes": 1440},
    {"event_type": "weekly_summary",        "notify_roles": ["owner"],                               "channels": ["email", "in_app"], "min_severity": "info",     "cooldown_minutes": 0},
    {"event_type": "incomplete_tasks",      "notify_roles": ["owner", "manager"],                    "channels": ["in_app"],          "min_severity": "info",     "cooldown_minutes": 0},
    {"event_type": "disease_outbreak",      "notify_roles": ["owner", "manager"],                    "channels": ["sms", "in_app"],   "min_severity": "critical", "cooldown_minutes": 720},
    {"event_type": "medication_withdrawal", "notify_roles": ["owner", "manager"],                    "channels": ["in_app"],          "min_severity": "warning",  "cooldown_minutes": 1440},
]
