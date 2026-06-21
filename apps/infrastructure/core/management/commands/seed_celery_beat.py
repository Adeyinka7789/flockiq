"""
Seeds the Celery Beat schedule (django_celery_beat PeriodicTask rows).

Run on every deploy (scripts/deploy.sh) — safe to re-run; it creates missing
rows, repairs rows whose task name is stale, and removes rows this project
no longer seeds.

WHY task names matter here:
    Every @shared_task in this project registers an EXPLICIT short name
    (e.g. ``tasks.generate_daily_tasks_all_orgs``,
    ``weather.refresh_weather_cache_all_farms``). Celery workers resolve
    tasks by that registered name only. Earlier versions of this command
    seeded the full module path (``apps.farm.tasks.tasks.generate_daily_
    tasks_all_orgs``), which is NOT in the worker registry.

    Symptom of the broken rows in production: Beat dispatches on schedule,
    but the worker rejects every message with
        "Received unregistered task of type 'apps.farm.tasks.tasks....'"
    in the celery worker log (deploy/supervisor/flockiq-celery.conf →
    celery.log), and NONE of these jobs actually run: daily task
    generation, weather cache refresh, egg forecasts, vaccination
    reminders, notification outbox processing, incomplete-task reports,
    theft detection, monthly billing cycle, daily briefs, proactive
    alerts.

    To verify after deploying this fix:
        1. python manage.py seed_celery_beat   (deploy.sh does this)
           — output should show [~] Repaired for each stale row.
        2. Check celery.log: the "Received unregistered task" lines stop.
        3. Within a minute the outbox row should fire:
           "Process notification outbox" runs every 30s.

NOTE: Three rows previously seeded here pointed at functions that have
never existed in the codebase (no implementation under any name):
    - apps.health.analytics.tasks.check_mortality_anomaly_all_orgs
    - apps.production.feed.tasks.generate_feed_requirements_today
    - apps.farm.tasks.tasks.generate_weekly_performance_summary_all_orgs
They are removed by this command. Implementing those features is separate
work — re-add a seed entry only once a real @shared_task exists.
"""
import json

from django.core.management.base import BaseCommand
from django_celery_beat.models import CrontabSchedule, IntervalSchedule, PeriodicTask

# PeriodicTask.name of rows seeded by older versions of this command whose
# task function never existed. Deleted on every run so a stale DB row cannot
# outlive its (nonexistent) implementation.
REMOVED_TASK_ROW_NAMES = [
    'Check mortality anomaly all orgs',
    'Generate feed requirements today',
    'Generate weekly performance summary',
]


class Command(BaseCommand):
    help = (
        'Seeds the 11 Celery Beat scheduled tasks into the database '
        '(creates, repairs stale task names, prunes removed rows)'
    )

    def handle(self, *args, **kwargs):
        midnight, _ = CrontabSchedule.objects.get_or_create(
            minute='0', hour='0', day_of_week='*',
            day_of_month='*', month_of_year='*'
        )
        every6h, _ = CrontabSchedule.objects.get_or_create(
            minute='0', hour='*/6', day_of_week='*',
            day_of_month='*', month_of_year='*'
        )
        at615am, _ = CrontabSchedule.objects.get_or_create(
            minute='15', hour='6', day_of_week='*',
            day_of_month='*', month_of_year='*'
        )
        at7am, _ = CrontabSchedule.objects.get_or_create(
            minute='0', hour='7', day_of_week='*',
            day_of_month='*', month_of_year='*'
        )
        every30s, _ = IntervalSchedule.objects.get_or_create(
            every=30, period=IntervalSchedule.SECONDS
        )
        at6pm, _ = CrontabSchedule.objects.get_or_create(
            minute='0', hour='18', day_of_week='*',
            day_of_month='*', month_of_year='*'
        )
        sunday, _ = CrontabSchedule.objects.get_or_create(
            minute='0', hour='0', day_of_week='0',
            day_of_month='*', month_of_year='*'
        )
        monthly1st, _ = CrontabSchedule.objects.get_or_create(
            minute='0', hour='1', day_of_week='*',
            day_of_month='1', month_of_year='*'
        )
        at630am, _ = CrontabSchedule.objects.get_or_create(
            minute='30', hour='6', day_of_week='*',
            day_of_month='*', month_of_year='*'
        )
        at4am, _ = CrontabSchedule.objects.get_or_create(
            minute='0', hour='4', day_of_week='*',
            day_of_month='*', month_of_year='*'
        )

        # 'task' MUST be the registered Celery name (the explicit name= on the
        # @shared_task decorator), NOT the Python module path — see module
        # docstring.
        tasks = [
            {
                'name': 'Generate daily tasks for all orgs',
                'task': 'tasks.generate_daily_tasks_all_orgs',
                'schedule': midnight,
                'schedule_type': 'crontab',
            },
            {
                'name': 'Refresh weather cache',
                'task': 'weather.refresh_weather_cache_all_farms',
                'schedule': every6h,
                'schedule_type': 'crontab',
            },
            {
                'name': 'Run egg forecast all batches',
                'task': 'analytics.run_egg_forecast_all_active_batches',
                'schedule': at615am,
                'schedule_type': 'crontab',
            },
            {
                'name': 'Send vaccination reminders',
                'task': 'health.send_vaccination_reminders_all_orgs',
                'schedule': at7am,
                'schedule_type': 'crontab',
            },
            {
                'name': 'Process notification outbox',
                'task': 'notifications.process_outbox',
                'schedule': every30s,
                'schedule_type': 'interval',
            },
            {
                'name': 'Send incomplete task report',
                'task': 'tasks.send_incomplete_task_report_all_orgs',
                'schedule': at6pm,
                'schedule_type': 'crontab',
            },
            {
                'name': 'Run theft detection all orgs',
                'task': 'analytics.run_theft_detection_all_orgs',
                'schedule': sunday,
                'schedule_type': 'crontab',
            },
            {
                'name': 'Process monthly billing cycle',
                'task': 'billing.process_monthly_billing_cycle',
                'schedule': monthly1st,
                'schedule_type': 'crontab',
            },
            {
                'name': 'Generate daily brief all orgs',
                'task': 'analytics.generate_daily_brief_all_orgs',
                'schedule': at630am,
                'schedule_type': 'crontab',
            },
            {
                'name': 'Run proactive alerts all orgs',
                'task': 'analytics.run_proactive_alerts_all_orgs',
                'schedule': every6h,
                'schedule_type': 'crontab',
            },
            {
                'name': 'Cleanup lapsed accounts (daily 04:00)',
                'task': 'billing.cleanup_lapsed_accounts',
                'schedule': at4am,
                'schedule_type': 'crontab',
            },
        ]

        pruned, _ = PeriodicTask.objects.filter(
            name__in=REMOVED_TASK_ROW_NAMES
        ).delete()
        if pruned:
            self.stdout.write(
                f'  [-] Pruned {pruned} row(s) whose task was never implemented'
            )

        created = 0
        repaired = 0
        for t in tasks:
            schedule_type = t.pop('schedule_type')
            schedule = t.pop('schedule')

            if schedule_type == 'interval':
                obj, is_new = PeriodicTask.objects.get_or_create(
                    name=t['name'],
                    defaults={
                        'task': t['task'],
                        'interval': schedule,
                        'args': json.dumps([]),
                    }
                )
            else:
                obj, is_new = PeriodicTask.objects.get_or_create(
                    name=t['name'],
                    defaults={
                        'task': t['task'],
                        'crontab': schedule,
                        'args': json.dumps([]),
                    }
                )
            if is_new:
                created += 1
                self.stdout.write(f'  [+] Created: {obj.name}')
            elif obj.task != t['task']:
                # Row seeded by an older version with the unregistered
                # module-path name — repair in place, keep schedule/enabled.
                old = obj.task
                obj.task = t['task']
                obj.save(update_fields=['task'])
                repaired += 1
                self.stdout.write(
                    f'  [~] Repaired: {obj.name} ({old} -> {obj.task})'
                )
            else:
                self.stdout.write(f'  [=] Exists:  {obj.name}')

        self.stdout.write(
            self.style.SUCCESS(
                f'\nDone. {created} created, {repaired} repaired, '
                f'{pruned} pruned, '
                f'{len(tasks) - created - repaired} already correct.'
            )
        )
