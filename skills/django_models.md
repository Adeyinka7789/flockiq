# Skill: Django Models — FlockIQ v2 Complete Reference

## Base Model (use for every tenant-scoped model)
```python
# apps/core/models.py
import uuid
from django.db import models

class TenantModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey('tenants.Organization', on_delete=models.CASCADE, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        unique_together = [('org', 'id')]
        indexes = [models.Index(fields=['org'])]
```

---

## apps/tenants/models.py
```python
class Organization(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True)
    plan = models.CharField(max_length=20, default='trial',
        choices=[('trial','Trial'),('monthly','Monthly'),('cycle','Cycle'),('yearly','Yearly')])
    is_active = models.BooleanField(default=True)
    white_label_domain = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    trial_ends_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'organizations'

    def __str__(self):
        return self.name

    @property
    def is_trial_expired(self):
        from django.utils import timezone
        return self.plan == 'trial' and self.trial_ends_at and self.trial_ends_at < timezone.now()
```

---

## apps/accounts/models.py
```python
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin

class UserManager(BaseUserManager):
    def create_user(self, email, org, password=None, **extra_fields):
        email = self.normalize_email(email)
        user = self.model(email=email, org=org, **extra_fields)
        user.set_password(password)
        user.save()
        return user

class User(AbstractBaseUser, PermissionsMixin):
    ROLES = [('owner','Owner'),('manager','Manager'),('supervisor','Supervisor'),
             ('data_entry','Data Entry'),('vet','Veterinary Advisor')]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey('tenants.Organization', on_delete=models.CASCADE)
    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=255)
    phone = models.CharField(max_length=20, blank=True)
    role = models.CharField(max_length=20, choices=ROLES, default='data_entry')
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    last_login = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = UserManager()
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['full_name']

    class Meta:
        db_table = 'users'

    def can_manage(self):
        return self.role in ['owner', 'manager']

    def can_record(self):
        return self.role in ['owner', 'manager', 'supervisor', 'data_entry']

    def is_owner(self):
        return self.role == 'owner'
```

---

## apps/farms/models.py
```python
class Farm(TenantModel):
    name = models.CharField(max_length=255)
    location = models.TextField(blank=True)
    latitude = models.DecimalField(max_digits=10, decimal_places=7,
        help_text="Required for weather API integration")
    longitude = models.DecimalField(max_digits=10, decimal_places=7,
        help_text="Required for weather API integration")

    class Meta(TenantModel.Meta):
        db_table = 'farms'

    def __str__(self):
        return self.name

    def get_weather_cache_key(self):
        return f"weather:{self.id}"


class House(TenantModel):
    HOUSE_TYPES = [('broiler','Broiler'),('layer','Layer')]

    farm = models.ForeignKey(Farm, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    house_type = models.CharField(max_length=20, choices=HOUSE_TYPES)
    capacity = models.IntegerField()

    class Meta(TenantModel.Meta):
        db_table = 'houses'
        unique_together = [('org', 'farm', 'id')]

    def save(self, *args, **kwargs):
        if self.farm.org_id != self.org_id:
            raise ValueError("Farm does not belong to this organization")
        super().save(*args, **kwargs)
```

---

## apps/flocks/models.py
```python
class Batch(TenantModel):
    BIRD_TYPES = [('broiler','Broiler'),('layer','Layer')]
    STAGES = [('starter','Starter'),('grower','Grower'),('finisher','Finisher'),
              ('laying','Laying'),('declining','Declining'),('depleted','Depleted')]
    STATUS = [('active','Active'),('completed','Completed'),('archived','Archived')]

    farm = models.ForeignKey('farms.Farm', on_delete=models.CASCADE)
    house = models.ForeignKey('farms.House', on_delete=models.CASCADE)
    batch_number = models.CharField(max_length=50)
    bird_type = models.CharField(max_length=20, choices=BIRD_TYPES)
    breed = models.CharField(max_length=100, blank=True)
    source = models.CharField(max_length=255, blank=True)
    placement_date = models.DateField()
    initial_count = models.IntegerField()
    current_count = models.IntegerField()
    stage = models.CharField(max_length=20, choices=STAGES, default='starter')
    status = models.CharField(max_length=20, choices=STATUS, default='active')
    closed_at = models.DateField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        db_table = 'batches'
        unique_together = [('org', 'farm', 'id')]

    @property
    def age_days(self):
        from django.utils import timezone
        return (timezone.now().date() - self.placement_date).days

    @property
    def age_weeks(self):
        return self.age_days // 7

    def update_stage(self):
        """Auto-advance stage based on age. Call on each mortality/weight log save."""
        if self.bird_type == 'broiler':
            if self.age_days <= 13:
                self.stage = 'starter'
            elif self.age_days <= 27:
                self.stage = 'grower'
            elif self.age_days <= 42:
                self.stage = 'finisher'
            else:
                self.stage = 'depleted'
        elif self.bird_type == 'layer':
            if self.age_weeks <= 8:
                self.stage = 'starter'
            elif self.age_weeks <= 17:
                self.stage = 'grower'
            elif self.age_weeks <= 59:
                self.stage = 'laying'
            else:
                self.stage = 'declining'
        self.save(update_fields=['stage'])


class MortalityLog(TenantModel):
    CAUSES = [('disease','Disease'),('culling','Culling'),
              ('unknown','Unknown'),('theft_suspected','Theft Suspected')]

    batch = models.ForeignKey(Batch, on_delete=models.CASCADE)
    farm = models.ForeignKey('farms.Farm', on_delete=models.CASCADE)
    record_date = models.DateField(auto_now_add=True)
    count = models.IntegerField()
    cause = models.CharField(max_length=30, choices=CAUSES)
    cumulative_rate = models.DecimalField(max_digits=5, decimal_places=2, null=True)
    notes = models.TextField(blank=True)
    recorded_by = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True)

    class Meta(TenantModel.Meta):
        db_table = 'mortality_logs'
        unique_together = [('batch', 'record_date')]

    def save(self, *args, **kwargs):
        # Auto-decrement batch current_count
        self.batch.current_count = max(0, self.batch.current_count - self.count)
        self.batch.save(update_fields=['current_count'])
        # Auto-calculate cumulative rate
        total_deaths = MortalityLog.objects.filter(
            batch=self.batch).aggregate(
            total=models.Sum('count'))['total'] or 0
        total_deaths += self.count
        self.cumulative_rate = round(total_deaths / self.batch.initial_count * 100, 2)
        super().save(*args, **kwargs)
        # Update batch stage
        self.batch.update_stage()


class WeightRecord(TenantModel):
    batch = models.ForeignKey(Batch, on_delete=models.CASCADE)
    sample_date = models.DateField()
    sample_count = models.IntegerField()
    avg_weight_grams = models.DecimalField(max_digits=8, decimal_places=2)
    target_weight_grams = models.DecimalField(max_digits=8, decimal_places=2, null=True)
    deviation_pct = models.DecimalField(max_digits=5, decimal_places=2, null=True)

    class Meta(TenantModel.Meta):
        db_table = 'weight_records'

    def save(self, *args, **kwargs):
        if self.target_weight_grams:
            self.deviation_pct = round(
                (float(self.avg_weight_grams) - float(self.target_weight_grams))
                / float(self.target_weight_grams) * 100, 2)
        super().save(*args, **kwargs)
```

---

## apps/production/models.py
```python
class EggProductionLog(TenantModel):
    batch = models.ForeignKey('flocks.Batch', on_delete=models.CASCADE)
    farm = models.ForeignKey('farms.Farm', on_delete=models.CASCADE)
    record_date = models.DateField()
    total_eggs = models.IntegerField()
    grade_a = models.IntegerField(default=0)
    grade_b = models.IntegerField(default=0)
    cracked = models.IntegerField(default=0)
    dirty = models.IntegerField(default=0)
    live_hen_count = models.IntegerField()
    hen_day_pct = models.DecimalField(max_digits=5, decimal_places=2, null=True)
    crates = models.DecimalField(max_digits=8, decimal_places=2, null=True)

    class Meta(TenantModel.Meta):
        db_table = 'egg_production_logs'
        unique_together = [('batch', 'record_date')]

    def save(self, *args, **kwargs):
        if self.live_hen_count and self.live_hen_count > 0:
            self.hen_day_pct = round(self.total_eggs / self.live_hen_count * 100, 2)
        self.crates = round(self.total_eggs / 30, 2)
        super().save(*args, **kwargs)
        # Update crate inventory
        CrateInventory.objects.update_or_create(
            org=self.org, farm=self.farm, record_date=self.record_date,
            defaults={'crates_in': self.crates or 0}
        )


class CrateInventory(TenantModel):
    farm = models.ForeignKey('farms.Farm', on_delete=models.CASCADE)
    record_date = models.DateField()
    crates_in = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    crates_sold = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    crates_balance = models.DecimalField(max_digits=8, decimal_places=2, default=0)

    class Meta(TenantModel.Meta):
        db_table = 'crate_inventory'
        unique_together = [('org', 'farm', 'record_date')]
```

---

## apps/water/models.py
```python
class WaterConsumptionLog(TenantModel):
    batch = models.ForeignKey('flocks.Batch', on_delete=models.CASCADE)
    farm = models.ForeignKey('farms.Farm', on_delete=models.CASCADE)
    record_date = models.DateField()
    litres_consumed = models.DecimalField(max_digits=8, decimal_places=2)
    auto_requirement_litres = models.DecimalField(max_digits=8, decimal_places=2, null=True)
    water_source = models.CharField(max_length=30, blank=True,
        choices=[('borehole','Borehole'),('municipal','Municipal'),
                 ('purchased','Purchased'),('pond','Pond')])
    cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    cumulative_litres_per_bird = models.DecimalField(max_digits=8, decimal_places=2, null=True)

    class Meta(TenantModel.Meta):
        db_table = 'water_consumption_logs'
        unique_together = [('batch', 'record_date')]

    def save(self, *args, **kwargs):
        # Auto-calculate requirement from reference table
        from apps.feed.services import get_daily_water_requirement
        self.auto_requirement_litres = get_daily_water_requirement(
            self.batch.bird_type, self.batch.age_days, self.batch.current_count)
        # Calculate cumulative per bird (for broiler 8L lifetime tracking)
        total = WaterConsumptionLog.objects.filter(
            batch=self.batch).aggregate(
            t=models.Sum('litres_consumed'))['t'] or 0
        total += float(self.litres_consumed)
        if self.batch.initial_count > 0:
            self.cumulative_litres_per_bird = round(total / self.batch.initial_count, 2)
        super().save(*args, **kwargs)
```

---

## apps/health/models.py
```python
class VaccinationSchedule(TenantModel):
    ROUTES = [('drinking_water','Drinking Water'),('spray','Spray'),
              ('injection','Injection'),('eye_drop','Eye Drop'),('wing_web','Wing Web')]
    REASONS = [('preventive','Preventive'),('reactive','Reactive')]
    STATUS = [('pending','Pending'),('completed','Completed'),
              ('skipped','Skipped'),('overdue','Overdue')]

    batch = models.ForeignKey('flocks.Batch', on_delete=models.CASCADE)
    vaccine_name = models.CharField(max_length=255)
    brand = models.CharField(max_length=255, blank=True)
    due_date = models.DateField()
    dose = models.CharField(max_length=100, blank=True)
    route = models.CharField(max_length=30, choices=ROUTES, blank=True)
    reason = models.CharField(max_length=20, choices=REASONS, default='preventive')
    status = models.CharField(max_length=20, choices=STATUS, default='pending')
    completed_date = models.DateField(null=True, blank=True)
    sms_reminder_sent = models.BooleanField(default=False)

    class Meta(TenantModel.Meta):
        db_table = 'vaccination_schedules'


class MedicationLog(TenantModel):
    DRUG_TYPES = [('antibiotic','Antibiotic'),('vitamin','Vitamin'),
                  ('electrolyte','Electrolyte'),('growth_enhancer','Growth Enhancer'),
                  ('antifungal','Antifungal'),('other','Other')]
    REASONS = [('preventive','Preventive'),('reactive','Reactive')]

    batch = models.ForeignKey('flocks.Batch', on_delete=models.CASCADE)
    drug_name = models.CharField(max_length=255)
    drug_type = models.CharField(max_length=30, choices=DRUG_TYPES)
    quantity_used = models.DecimalField(max_digits=10, decimal_places=3)
    unit = models.CharField(max_length=10,
        choices=[('ml','ml'),('g','g'),('tablet','tablet'),('sachet','sachet')])
    cost = models.DecimalField(max_digits=10, decimal_places=2)
    supplier = models.CharField(max_length=255, blank=True)
    start_date = models.DateField()
    duration_days = models.IntegerField()
    withdrawal_period_days = models.IntegerField(default=0)
    safe_to_sell_date = models.DateField(null=True)
    reason = models.CharField(max_length=20, choices=REASONS)

    class Meta(TenantModel.Meta):
        db_table = 'medication_logs'

    def save(self, *args, **kwargs):
        from datetime import timedelta
        self.safe_to_sell_date = (self.start_date +
            timedelta(days=self.duration_days + self.withdrawal_period_days))
        super().save(*args, **kwargs)


class SymptomLog(TenantModel):
    batch = models.ForeignKey('flocks.Batch', on_delete=models.CASCADE)
    observation_date = models.DateField(auto_now_add=True)
    respiratory = models.BooleanField(default=False)
    nervous = models.BooleanField(default=False)
    digestive = models.BooleanField(default=False)
    skin_lesions = models.BooleanField(default=False)
    reduced_feed = models.BooleanField(default=False)
    reduced_water = models.BooleanField(default=False)
    sudden_drop_production = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    recorded_by = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True)

    class Meta(TenantModel.Meta):
        db_table = 'symptom_logs'

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Trigger diagnosis task after save
        from apps.health.tasks import run_symptom_diagnosis
        run_symptom_diagnosis.delay(str(self.org_id), str(self.id))


class SymptomDiagnosis(TenantModel):
    symptom_log = models.ForeignKey(SymptomLog, on_delete=models.CASCADE,
        related_name='diagnoses')
    suggested_disease = models.CharField(max_length=255)
    confidence_score = models.DecimalField(max_digits=5, decimal_places=2)
    treatment_protocol = models.TextField()
    source = models.CharField(max_length=20,
        choices=[('rule_based','Rule Based'),('ml_model','ML Model')])

    class Meta(TenantModel.Meta):
        db_table = 'symptom_diagnoses'
```

---

## apps/expenses/models.py
```python
class ExpenseRecord(TenantModel):
    CATEGORIES = [
        ('feed','Feed Purchase'),('medication','Medication'),
        ('supplement','Supplements'),('labour','Labour/Salary'),
        ('transportation','Transportation'),('utilities','Utilities'),
        ('equipment','Equipment Maintenance'),('water','Water'),('other','Other'),
    ]

    batch = models.ForeignKey('flocks.Batch', on_delete=models.CASCADE,
        null=True, blank=True)
    farm = models.ForeignKey('farms.Farm', on_delete=models.CASCADE)
    expense_date = models.DateField()
    category = models.CharField(max_length=30, choices=CATEGORIES)
    description = models.TextField()
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    vendor_name = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True)

    class Meta(TenantModel.Meta):
        db_table = 'expense_records'
```

---

## apps/weather/models.py
```python
class WeatherAlert(TenantModel):
    ALERT_TYPES = [
        ('heat_stress','Heat Stress'),('heavy_rain','Heavy Rain'),
        ('high_humidity','High Humidity'),('frost','Frost'),('storm','Storm'),
    ]
    farm = models.ForeignKey('farms.Farm', on_delete=models.CASCADE)
    alert_type = models.CharField(max_length=30, choices=ALERT_TYPES)
    temperature_c = models.DecimalField(max_digits=5, decimal_places=2, null=True)
    humidity_pct = models.DecimalField(max_digits=5, decimal_places=2, null=True)
    description = models.TextField()
    forecast_date = models.DateField()
    triggered_at = models.DateTimeField(auto_now_add=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        db_table = 'weather_alerts'


class WeatherCache(models.Model):
    """NO RLS — infrastructure table accessed cross-tenant by Celery worker."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    farm_id = models.UUIDField(db_index=True)
    fetched_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    raw_response = models.JSONField()
    current_temp_c = models.DecimalField(max_digits=5, decimal_places=2)
    humidity_pct = models.DecimalField(max_digits=5, decimal_places=2)
    forecast_summary = models.TextField()

    class Meta:
        db_table = 'weather_cache'
        indexes = [models.Index(fields=['farm_id', 'expires_at'])]
```

---

## apps/tasks/models.py
```python
class TaskTemplate(models.Model):
    """NO RLS — shared templates across all tenants."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    bird_type = models.CharField(max_length=20, null=True, blank=True)
    default_time = models.TimeField()
    is_recurring = models.BooleanField(default=True)
    description = models.TextField(blank=True)

    class Meta:
        db_table = 'task_templates'


class Task(TenantModel):
    STATUS = [('pending','Pending'),('completed','Completed'),
              ('skipped','Skipped'),('overdue','Overdue')]

    batch = models.ForeignKey('flocks.Batch', on_delete=models.CASCADE,
        null=True, blank=True)
    house = models.ForeignKey('farms.House', on_delete=models.CASCADE,
        null=True, blank=True)
    template = models.ForeignKey(TaskTemplate, on_delete=models.SET_NULL,
        null=True, blank=True)
    task_name = models.CharField(max_length=255)
    assigned_to = models.ForeignKey('accounts.User', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='assigned_tasks')
    due_date = models.DateField()
    due_time = models.TimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS, default='pending')
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey('accounts.User', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='completed_tasks')
    notes = models.TextField(blank=True)

    class Meta(TenantModel.Meta):
        db_table = 'tasks'
        indexes = [
            models.Index(fields=['org', 'due_date'],
                condition=models.Q(status='pending'),
                name='idx_tasks_pending')
        ]
```

---

## apps/notifications/models.py
```python
class OutboxEvent(models.Model):
    """NO RLS — workers poll cross-tenant. org_id is payload metadata only."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org_id = models.UUIDField()  # Not FK — intentional, no CASCADE
    topic = models.CharField(max_length=100)
    payload = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'outbox_events'
        indexes = [
            models.Index(fields=['processed_at'],
                condition=models.Q(processed_at__isnull=True),
                name='idx_outbox_pending')
        ]
```
