# Skill: Celery Tasks & Background Processing

## Configuration

```python
# config/celery.py
import os
from celery import Celery
from celery.schedules import crontab

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.production')
app = Celery('flockiq')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

app.conf.beat_schedule = {
    'daily-egg-forecast': {
        'task': 'apps.analytics.tasks.run_egg_forecasting_all_tenants',
        'schedule': crontab(hour=1, minute=0),
    },
    'mortality-anomaly-check': {
        'task': 'apps.analytics.tasks.check_mortality_anomalies_all_tenants',
        'schedule': crontab(minute=0, hour='*/6'),
    },
    'vaccination-reminders': {
        'task': 'apps.health.tasks.send_vaccination_reminders',
        'schedule': crontab(hour=7, minute=0),
    },
    'feeding-schedule-monitor': {
        'task': 'apps.feed.tasks.monitor_feeding_schedules',
        'schedule': crontab(minute=0, hour='*/2'),
    },
    'process-outbox': {
        'task': 'apps.notifications.tasks.process_outbox',
        'schedule': 30.0,
    },
    'weather-refresh': {
        'task': 'apps.weather.tasks.refresh_all_farm_weather',
        'schedule': crontab(minute=0, hour='*/6'),
    },
    'water-anomaly-check': {
        'task': 'apps.water.tasks.check_water_anomalies',
        'schedule': crontab(hour=8, minute=0),
    },
    'task-generation': {
        'task': 'apps.tasks.tasks.generate_daily_tasks',
        'schedule': crontab(hour=0, minute=0),
    },
    'incomplete-task-report': {
        'task': 'apps.tasks.tasks.send_incomplete_task_report',
        'schedule': crontab(hour=18, minute=0),
    },
    'weekly-reports': {
        'task': 'apps.finance.tasks.generate_weekly_reports',
        'schedule': crontab(day_of_week=0, hour=0, minute=0),
    },
    'seasonal-market-alert': {
        'task': 'apps.market.tasks.check_seasonal_alerts',
        'schedule': crontab(day_of_month=1, hour=9, minute=0),
    },
}
```

---

## Tenant Context Helper — Use in EVERY Task

```python
# apps/core/tasks.py

from django.db import connection
import logging

logger = logging.getLogger(__name__)


def set_tenant_context(org_id: str) -> None:
    """
    Sets PostgreSQL RLS context for the current task.
    MUST be called at the start of every task that touches tenant data.
    Uses transaction-local scope (true) — safe for connection pooling.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT set_config('app.current_tenant_id', %s, true)",
            [str(org_id)]
        )


def get_all_active_tenant_ids() -> list[str]:
    """Returns list of all active tenant org_id strings for fan-out tasks."""
    from apps.tenants.models import Organization
    return list(
        Organization.objects.filter(is_active=True)
        .values_list('id', flat=True)
        .values_list('id', flat=True)
    )
```

---

## Task 1: Egg Production Forecasting

```python
# apps/analytics/tasks.py

from celery import shared_task
from apps.core.tasks import set_tenant_context, get_all_active_tenant_ids
import logging

logger = logging.getLogger(__name__)


@shared_task
def run_egg_forecasting_all_tenants():
    """Fan-out: schedule per-tenant forecast for all active tenants."""
    for org_id in get_all_active_tenant_ids():
        run_egg_forecasting_for_tenant.delay(str(org_id))


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def run_egg_forecasting_for_tenant(self, org_id: str):
    """Run Prophet egg forecast for all active layer batches in this tenant."""
    try:
        set_tenant_context(org_id)
        from apps.flocks.models import Batch
        from apps.production.models import EggProductionLog
        from apps.analytics.ml.forecasting import EggForecaster

        active_batches = Batch.objects.filter(
            bird_type='layer', status='active')

        forecaster = EggForecaster()
        for batch in active_batches:
            logs = list(EggProductionLog.objects.filter(
                batch=batch
            ).order_by('record_date').values('record_date', 'total_eggs'))

            if len(logs) < 14:
                logger.info(f"Skipping forecast for batch {batch.id} — insufficient data")
                continue

            results = forecaster.forecast(logs, periods=30)
            forecaster.save_results(org_id, str(batch.id), results)

    except Exception as exc:
        logger.error(f"Forecast failed for org {org_id}: {exc}")
        raise self.retry(exc=exc)
```

---

## Task 2: Mortality Anomaly Detection

```python
@shared_task
def check_mortality_anomalies_all_tenants():
    for org_id in get_all_active_tenant_ids():
        check_mortality_anomalies_for_tenant.delay(str(org_id))


@shared_task(bind=True, max_retries=3)
def check_mortality_anomalies_for_tenant(self, org_id: str):
    try:
        set_tenant_context(org_id)
        from apps.flocks.models import Batch, MortalityLog
        from apps.analytics.models import AnomalyAlert
        import numpy as np

        for batch in Batch.objects.filter(status='active'):
            logs = list(MortalityLog.objects.filter(
                batch=batch
            ).order_by('record_date').values_list('count', flat=True))

            if len(logs) < 8:
                continue

            rates = [c / batch.current_count * 100 for c in logs]
            window = rates[-8:-1]  # last 7 days
            latest = rates[-1]

            mean = np.mean(window)
            std = np.std(window)

            if std == 0:
                continue

            z_score = (latest - mean) / std
            if z_score > 2.5:
                AnomalyAlert.objects.create(
                    org_id=org_id,
                    batch=batch,
                    farm=batch.farm,
                    alert_type='mortality_spike',
                    severity='critical' if z_score > 4 else 'high',
                    message=f"Mortality spike detected. Today: {latest:.1f}% vs 7-day avg: {mean:.1f}%",
                    recommended_action="Isolate affected birds immediately. Contact veterinarian. Check ventilation and water.",
                )
                # Push to outbox for SMS
                from apps.notifications.models import OutboxEvent
                OutboxEvent.objects.create(
                    org_id=org_id,
                    topic='MortalitySpike',
                    payload={'batch_id': str(batch.id), 'rate': latest, 'avg': mean}
                )
    except Exception as exc:
        logger.error(f"Anomaly check failed for org {org_id}: {exc}")
        raise self.retry(exc=exc)
```

---

## Task 3: Vaccination Reminders

```python
# apps/health/tasks.py

@shared_task
def send_vaccination_reminders():
    """
    Send SMS reminders 3 days before and on the day of scheduled vaccinations.
    FRD MED-02.
    """
    from django.utils import timezone
    from datetime import timedelta
    from apps.health.models import VaccinationSchedule
    from apps.notifications.models import OutboxEvent

    today = timezone.now().date()
    three_days = today + timedelta(days=3)

    # Due today
    due_today = VaccinationSchedule.objects.filter(
        due_date=today, status='pending', sms_reminder_sent=False)

    # Due in 3 days
    due_soon = VaccinationSchedule.objects.filter(
        due_date=three_days, status='pending')

    for vacc in list(due_today) + list(due_soon):
        days_label = "today" if vacc.due_date == today else "in 3 days"
        OutboxEvent.objects.create(
            org_id=vacc.org_id,
            topic='VaccinationReminder',
            payload={
                'vaccination_id': str(vacc.id),
                'vaccine_name': vacc.vaccine_name,
                'batch_id': str(vacc.batch_id),
                'due_date': str(vacc.due_date),
                'days_label': days_label,
            }
        )
        if vacc.due_date == today:
            vacc.sms_reminder_sent = True
            vacc.save(update_fields=['sms_reminder_sent'])
```

---

## Task 4: Weather Refresh

```python
# apps/weather/tasks.py
import requests
from django.conf import settings
from django.utils import timezone
from datetime import timedelta

@shared_task
def refresh_all_farm_weather():
    """Fetch weather for all farms every 6 hours. No RLS needed — uses farm_id directly."""
    from apps.farms.models import Farm
    from apps.weather.models import WeatherCache

    for farm in Farm.objects.all().values('id', 'latitude', 'longitude', 'org_id'):
        # Check cache first
        cached = WeatherCache.objects.filter(
            farm_id=farm['id'],
            expires_at__gt=timezone.now()
        ).first()

        if cached:
            continue

        fetch_farm_weather.delay(
            str(farm['id']),
            str(farm['latitude']),
            str(farm['longitude']),
            str(farm['org_id'])
        )


@shared_task(bind=True, max_retries=2)
def fetch_farm_weather(self, farm_id: str, lat: str, lng: str, org_id: str):
    try:
        response = requests.get(
            f"{settings.OPENWEATHERMAP_BASE_URL}/forecast",
            params={
                'lat': lat, 'lon': lng,
                'appid': settings.OPENWEATHERMAP_API_KEY,
                'units': 'metric', 'cnt': 8  # 24 hours in 3hr intervals
            },
            timeout=10
        )
        response.raise_for_status()
        data = response.json()

        current_temp = data['list'][0]['main']['temp']
        humidity = data['list'][0]['main']['humidity']

        from apps.weather.models import WeatherCache, WeatherAlert
        from apps.notifications.models import OutboxEvent

        WeatherCache.objects.update_or_create(
            farm_id=farm_id,
            defaults={
                'expires_at': timezone.now() + timedelta(hours=6),
                'raw_response': data,
                'current_temp_c': current_temp,
                'humidity_pct': humidity,
                'forecast_summary': _build_summary(data),
            }
        )

        # Check thresholds — set tenant context for alert creation
        set_tenant_context(org_id)

        if current_temp > 32:
            _create_weather_alert(org_id, farm_id, 'heat_stress', current_temp, humidity,
                f"Heat stress risk: {current_temp:.1f}°C. Increase ventilation and water supply.")
        if humidity > 85:
            _create_weather_alert(org_id, farm_id, 'high_humidity', current_temp, humidity,
                f"High humidity: {humidity:.0f}%. Check feed storage for mould risk.")

    except Exception as exc:
        logger.error(f"Weather fetch failed for farm {farm_id}: {exc}")
        raise self.retry(exc=exc)


def _build_summary(data: dict) -> str:
    temps = [item['main']['temp'] for item in data['list'][:8]]
    return f"Next 24h: {min(temps):.0f}°C - {max(temps):.0f}°C"


def _create_weather_alert(org_id, farm_id, alert_type, temp, humidity, message):
    from apps.weather.models import WeatherAlert
    from django.utils import timezone
    WeatherAlert.objects.create(
        org_id=org_id, farm_id=farm_id,
        alert_type=alert_type,
        temperature_c=temp, humidity_pct=humidity,
        description=message,
        forecast_date=timezone.now().date()
    )
```

---

## Task 5: Outbox Processor (SMS via Termii)

```python
# apps/notifications/tasks.py

@shared_task
def process_outbox():
    """
    Process pending outbox events. Cross-tenant — no RLS.
    Sets tenant context per-event before touching tenant data.
    """
    from apps.notifications.models import OutboxEvent
    from django.db import transaction
    from django.utils import timezone

    events = OutboxEvent.objects.select_for_update(skip_locked=True).filter(
        processed_at__isnull=True
    ).order_by('created_at')[:20]

    for event in events:
        try:
            set_tenant_context(str(event.org_id))
            _dispatch_event(event)
            event.processed_at = timezone.now()
            event.save(update_fields=['processed_at'])
        except Exception as exc:
            logger.error(f"Failed to process outbox event {event.id}: {exc}")


def _dispatch_event(event):
    """Route event to appropriate handler."""
    handlers = {
        'VaccinationReminder': _handle_vaccination_reminder,
        'MortalitySpike': _handle_mortality_spike,
        'WeatherAlert': _handle_weather_alert,
        'TaskIncompleteReport': _handle_task_report,
    }
    handler = handlers.get(event.topic)
    if handler:
        handler(event.org_id, event.payload)


def _send_sms(phone: str, message: str) -> bool:
    """Send SMS via Termii API."""
    import requests
    from django.conf import settings

    try:
        response = requests.post(
            f"{settings.TERMII_BASE_URL}/sms/send",
            json={
                'to': phone,
                'from': settings.TERMII_SENDER_ID,
                'sms': message,
                'type': 'plain',
                'channel': 'generic',
                'api_key': settings.TERMII_API_KEY,
            },
            timeout=15
        )
        return response.status_code == 200
    except Exception as exc:
        logger.error(f"Termii SMS failed: {exc}")
        return False
```

---

## Task 6: Daily Task Generation

```python
# apps/tasks/tasks.py

@shared_task
def generate_daily_tasks():
    """Generate daily tasks for all active batches across all tenants."""
    for org_id in get_all_active_tenant_ids():
        generate_daily_tasks_for_tenant.delay(str(org_id))


@shared_task
def generate_daily_tasks_for_tenant(org_id: str):
    set_tenant_context(org_id)
    from apps.flocks.models import Batch
    from apps.tasks.models import Task, TaskTemplate, WorkerAssignment
    from django.utils import timezone

    today = timezone.now().date()
    templates = TaskTemplate.objects.filter(is_recurring=True)

    for batch in Batch.objects.filter(status='active'):
        batch_templates = templates.filter(
            models.Q(bird_type=batch.bird_type) | models.Q(bird_type__isnull=True)
        )
        for template in batch_templates:
            Task.objects.get_or_create(
                org_id=org_id,
                batch=batch,
                house=batch.house,
                template=template,
                due_date=today,
                defaults={
                    'task_name': template.name,
                    'due_time': template.default_time,
                    'status': 'pending',
                }
            )
```

---

## Task 7: Symptom Diagnosis (Rule-Based)

```python
# apps/health/tasks.py

DISEASE_RULES = {
    'Newcastle Disease': {
        'symptoms': ['respiratory', 'nervous'],
        'notes': 'Highly contagious. Notify vet immediately. Isolate flock.',
        'treatment': 'No cure. Supportive care. Cull severely affected birds. Biosecurity lockdown.',
    },
    'Infectious Bursal Disease (Gumboro)': {
        'symptoms': ['digestive', 'reduced_feed'],
        'notes': 'Affects young birds 3-6 weeks. Check vaccination records.',
        'treatment': 'Supportive: electrolytes, vitamins. Ensure adequate water intake.',
    },
    'Infectious Bronchitis': {
        'symptoms': ['respiratory'],
        'notes': 'Respiratory signs + production drop in layers.',
        'treatment': 'Supportive care. Antibiotics for secondary bacterial infections.',
    },
    'Coccidiosis': {
        'symptoms': ['digestive', 'reduced_feed', 'reduced_water'],
        'notes': 'Bloody or watery diarrhoea. Common in 3-6 week chicks.',
        'treatment': 'Amprolium or sulphonamides in drinking water for 5-7 days.',
    },
    'Fowl Typhoid': {
        'symptoms': ['digestive', 'sudden_drop_production', 'reduced_feed'],
        'notes': 'Can cause rapid flock death. Report to vet.',
        'treatment': 'Oxytetracycline or enrofloxacin. Check withdrawal period before sale.',
    },
}


@shared_task
def run_symptom_diagnosis(org_id: str, symptom_log_id: str):
    set_tenant_context(org_id)
    from apps.health.models import SymptomLog, SymptomDiagnosis

    try:
        log = SymptomLog.objects.get(id=symptom_log_id)
    except SymptomLog.DoesNotExist:
        return

    observed = {
        'respiratory': log.respiratory,
        'nervous': log.nervous,
        'digestive': log.digestive,
        'skin_lesions': log.skin_lesions,
        'reduced_feed': log.reduced_feed,
        'reduced_water': log.reduced_water,
        'sudden_drop_production': log.sudden_drop_production,
    }
    active_symptoms = [k for k, v in observed.items() if v]

    diagnoses = []
    for disease, rule in DISEASE_RULES.items():
        matches = sum(1 for s in rule['symptoms'] if s in active_symptoms)
        if matches > 0:
            confidence = round(matches / len(rule['symptoms']) * 100, 1)
            diagnoses.append((disease, confidence, rule))

    diagnoses.sort(key=lambda x: x[1], reverse=True)

    for disease, confidence, rule in diagnoses[:3]:
        SymptomDiagnosis.objects.create(
            org_id=org_id,
            symptom_log=log,
            suggested_disease=disease,
            confidence_score=confidence,
            treatment_protocol=rule['treatment'],
            source='rule_based',
        )
```
