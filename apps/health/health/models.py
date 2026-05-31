import datetime

from django.db import models

from apps.infrastructure.core.models import TenantAwareModel


ROUTE_CHOICES = [
    ("oral", "Oral"),
    ("injection", "Injection"),
    ("spray", "Spray"),
    ("eye_drop", "Eye Drop"),
    ("wing_web", "Wing Web"),
]

VACCINATION_STATUS_CHOICES = [
    ("scheduled", "Scheduled"),
    ("completed", "Completed"),
    ("missed", "Missed"),
    ("skipped", "Skipped"),
]

DRUG_TYPE_CHOICES = [
    ("antibiotic", "Antibiotic"),
    ("antiviral", "Antiviral"),
    ("antifungal", "Antifungal"),
    ("antiparasitic", "Antiparasitic"),
    ("vitamin", "Vitamin"),
    ("vaccine", "Vaccine"),
    ("other", "Other"),
]

UNIT_CHOICES = [
    ("ml", "ml"),
    ("g", "g"),
    ("tablets", "Tablets"),
    ("sachets", "Sachets"),
]

SEVERITY_CHOICES = [
    ("mild", "Mild"),
    ("moderate", "Moderate"),
    ("severe", "Severe"),
]

ALERT_SOURCE_CHOICES = [
    ("admin", "Admin"),
    ("ai", "AI"),
]

ALERT_SEVERITY_CHOICES = [
    ("info", "Info"),
    ("warning", "Warning"),
    ("critical", "Critical"),
]


class VaccinationSchedule(TenantAwareModel):
    batch = models.ForeignKey(
        "flocks.Batch",
        on_delete=models.PROTECT,
        related_name="vaccinations",
    )
    farm = models.ForeignKey("farms.Farm", on_delete=models.PROTECT, related_name="+")
    vaccine_name = models.CharField(max_length=200)
    due_date = models.DateField()
    administered_date = models.DateField(null=True, blank=True)
    administered_by = models.ForeignKey(
        "accounts.CustomUser",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    route = models.CharField(max_length=20, choices=ROUTE_CHOICES, default="oral")
    status = models.CharField(
        max_length=20, choices=VACCINATION_STATUS_CHOICES, default="scheduled"
    )
    notes = models.TextField(blank=True)
    reminder_sent = models.BooleanField(default=False)

    class Meta:
        db_table = "health_vaccinationschedule"
        indexes = [
            models.Index(
                fields=["org", "due_date", "status"],
                name="health_vacc_due_status_idx",
            ),
            models.Index(
                fields=["org", "batch", "status"],
                name="health_vacc_batch_status_idx",
            ),
        ]

    @property
    def is_overdue(self):
        return self.due_date < datetime.date.today() and self.status == "scheduled"

    @property
    def days_until_due(self):
        return (self.due_date - datetime.date.today()).days

    def __str__(self):
        return f"{self.vaccine_name} — {self.batch} — {self.due_date}"


class MedicationRecord(TenantAwareModel):
    batch = models.ForeignKey(
        "flocks.Batch",
        on_delete=models.PROTECT,
        related_name="medications",
    )
    farm = models.ForeignKey("farms.Farm", on_delete=models.PROTECT, related_name="+")
    drug_name = models.CharField(max_length=200)
    drug_type = models.CharField(
        max_length=20, choices=DRUG_TYPE_CHOICES, default="antibiotic"
    )
    start_date = models.DateField()
    duration_days = models.IntegerField()
    end_date = models.DateField(editable=False)
    withdrawal_period_days = models.IntegerField(default=0)
    withdrawal_cleared_date = models.DateField(null=True, editable=False)
    dosage = models.CharField(max_length=200)
    quantity_used = models.DecimalField(max_digits=8, decimal_places=2)
    unit = models.CharField(max_length=20, choices=UNIT_CHOICES, default="ml")
    cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    vet_name = models.CharField(max_length=200, blank=True)
    reason = models.CharField(
        max_length=20,
        choices=[("preventive", "Preventive"), ("reactive", "Reactive")],
        default="reactive",
    )
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "health_medicationrecord"
        indexes = [
            models.Index(
                fields=["org", "batch", "start_date"],
                name="health_med_org_batch_start_idx",
            )
        ]

    def save(self, *args, **kwargs):
        self.end_date = self.start_date + datetime.timedelta(days=self.duration_days)
        if self.withdrawal_period_days:
            self.withdrawal_cleared_date = self.end_date + datetime.timedelta(
                days=self.withdrawal_period_days
            )
        else:
            self.withdrawal_cleared_date = self.end_date
        super().save(*args, **kwargs)

    @property
    def is_active(self):
        today = datetime.date.today()
        return self.start_date <= today <= self.end_date

    @property
    def withdrawal_active(self):
        if not self.withdrawal_cleared_date:
            return False
        return datetime.date.today() <= self.withdrawal_cleared_date

    @property
    def days_until_clear(self):
        if self.withdrawal_active and self.withdrawal_cleared_date:
            return (self.withdrawal_cleared_date - datetime.date.today()).days
        return 0

    def __str__(self):
        return f"{self.drug_name} — {self.batch} — {self.start_date}"


class SymptomLog(TenantAwareModel):
    batch = models.ForeignKey(
        "flocks.Batch",
        on_delete=models.PROTECT,
        related_name="symptom_logs",
    )
    farm = models.ForeignKey("farms.Farm", on_delete=models.PROTECT, related_name="+")
    record_date = models.DateField(default=datetime.date.today)
    affected_count = models.IntegerField()
    symptoms = models.JSONField(default=list)
    diagnosis_result = models.CharField(max_length=300, blank=True)
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default="mild")
    treatment_notes = models.TextField(blank=True)
    recorded_by = models.ForeignKey(
        "accounts.CustomUser",
        null=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        db_table = "health_symptomlog"
        indexes = [
            models.Index(
                fields=["org", "batch", "record_date"],
                name="health_sym_org_batch_date_idx",
            )
        ]

    def __str__(self):
        return f"Symptoms — {self.batch} — {self.record_date}"


class OutbreakAlert(TenantAwareModel):
    farm = models.ForeignKey("farms.Farm", on_delete=models.PROTECT, related_name="+")
    disease_name = models.CharField(max_length=200)
    source = models.CharField(max_length=10, choices=ALERT_SOURCE_CHOICES, default="admin")
    severity = models.CharField(max_length=10, choices=ALERT_SEVERITY_CHOICES)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "health_outbreakalert"
        indexes = [
            models.Index(
                fields=["org", "is_active", "created_at"],
                name="health_alert_org_active_idx",
            )
        ]

    def __str__(self):
        return f"{self.disease_name} — {self.farm}"
