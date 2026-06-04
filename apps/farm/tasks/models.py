import uuid

from django.db import models

from apps.infrastructure.core.models import TenantAwareModel


class TaskTemplate(models.Model):
    """Admin-managed global task definition. RLS DISABLED — shared across all tenants."""

    class BreedApplicable(models.TextChoices):
        LAYER = "layer", "Layer"
        BROILER = "broiler", "Broiler"
        BOTH = "both", "Both"

    class Frequency(models.TextChoices):
        DAILY = "daily", "Daily"
        WEEKLY = "weekly", "Weekly"
        ONE_TIME = "one_time", "One-Time"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    breed_applicable = models.CharField(
        max_length=10,
        choices=BreedApplicable.choices,
        default=BreedApplicable.BOTH,
    )
    frequency = models.CharField(max_length=10, choices=Frequency.choices)
    cycle_day = models.IntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "tasks_tasktemplate"

    def __str__(self):
        return self.name


CATEGORY_CHOICES = [
    ("medication", "Medication"),
    ("nutrition", "Nutrition"),
    ("maintenance", "Maintenance"),
    ("environmental", "Environmental"),
    ("health", "Health"),
    ("production", "Production"),
    ("finance", "Finance"),
    ("other", "Other"),
]


class FarmTask(TenantAwareModel):
    """A farm work item — auto-generated daily or created manually."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        IN_PROGRESS = "in_progress", "In Progress"
        COMPLETE = "complete", "Complete"
        OVERDUE = "overdue", "Overdue"

    class Priority(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"

    batch = models.ForeignKey(
        "flocks.Batch",
        on_delete=models.CASCADE,
        related_name="tasks",
        null=True,
        blank=True,
    )
    farm = models.ForeignKey(
        "farms.Farm",
        on_delete=models.CASCADE,
        related_name="tasks",
        null=True,
        blank=True,
    )
    template = models.ForeignKey(
        TaskTemplate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="generated_tasks",
    )
    assigned_to = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_tasks",
    )
    created_by = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_tasks",
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    due_date = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=15,
        choices=Status.choices,
        default=Status.PENDING,
    )
    category = models.CharField(
        max_length=30,
        choices=CATEGORY_CHOICES,
        default="other",
        blank=True,
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="completed_tasks",
    )
    priority = models.CharField(
        max_length=10,
        choices=Priority.choices,
        default=Priority.MEDIUM,
    )

    class Meta:
        db_table = "tasks_farmtask"
        indexes = [
            models.Index(fields=["org", "status", "due_date"], name="tasks_ft_org_status_due"),
            models.Index(fields=["org", "assigned_to", "status"], name="tasks_ft_org_assigned"),
        ]

    def __str__(self):
        return f"{self.title} ({self.status})"

    @property
    def is_overdue(self):
        import datetime
        if not self.due_date:
            return False
        return (
            self.due_date < datetime.date.today()
            and self.status in (self.Status.PENDING, self.Status.OVERDUE)
        )
