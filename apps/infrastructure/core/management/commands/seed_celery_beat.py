import json

from django.core.management.base import BaseCommand
from django_celery_beat.models import CrontabSchedule, IntervalSchedule, PeriodicTask


class Command(BaseCommand):
    help = 'Seeds the 11 Celery Beat scheduled tasks into the database'

    def handle(self, *args, **kwargs):
        midnight, _ = CrontabSchedule.objects.get_or_create(
            minute='0', hour='0', day_of_week='*',
            day_of_month='*', month_of_year='*'
        )
        every6h, _ = CrontabSchedule.objects.get_or_create(
            minute='0', hour='*/6', day_of_week='*',
            day_of_month='*', month_of_year='*'
        )
        at6am, _ = CrontabSchedule.objects.get_or_create(
            minute='0', hour='6', day_of_week='*',
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
        at8am, _ = CrontabSchedule.objects.get_or_create(
            minute='0', hour='8', day_of_week='*',
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

        tasks = [
            {
                'name': 'Generate daily tasks for all orgs',
                'task': 'apps.farm.tasks.tasks.generate_daily_tasks_all_orgs',
                'schedule': midnight,
                'schedule_type': 'crontab',
            },
            {
                'name': 'Refresh weather cache',
                'task': 'apps.farm.weather.tasks.refresh_weather_cache_all_farms',
                'schedule': every6h,
                'schedule_type': 'crontab',
            },
            {
                'name': 'Check mortality anomaly all orgs',
                'task': 'apps.health.analytics.tasks.check_mortality_anomaly_all_orgs',
                'schedule': at6am,
                'schedule_type': 'crontab',
            },
            {
                'name': 'Run egg forecast all batches',
                'task': 'apps.health.analytics.tasks.run_egg_forecast_all_active_batches',
                'schedule': at615am,
                'schedule_type': 'crontab',
            },
            {
                'name': 'Send vaccination reminders',
                'task': 'apps.health.health.tasks.send_vaccination_reminders_all_orgs',
                'schedule': at7am,
                'schedule_type': 'crontab',
            },
            {
                'name': 'Generate feed requirements today',
                'task': 'apps.production.feed.tasks.generate_feed_requirements_today',
                'schedule': at8am,
                'schedule_type': 'crontab',
            },
            {
                'name': 'Process notification outbox',
                'task': 'apps.infrastructure.notifications.tasks.process_outbox',
                'schedule': every30s,
                'schedule_type': 'interval',
            },
            {
                'name': 'Send incomplete task report',
                'task': 'apps.farm.tasks.tasks.send_incomplete_task_report_all_orgs',
                'schedule': at6pm,
                'schedule_type': 'crontab',
            },
            {
                'name': 'Run theft detection all orgs',
                'task': 'apps.health.analytics.tasks.run_theft_detection_all_orgs',
                'schedule': sunday,
                'schedule_type': 'crontab',
            },
            {
                'name': 'Generate weekly performance summary',
                'task': 'apps.farm.tasks.tasks.generate_weekly_performance_summary_all_orgs',
                'schedule': sunday,
                'schedule_type': 'crontab',
            },
            {
                'name': 'Process monthly billing cycle',
                'task': 'apps.infrastructure.billing.tasks.process_monthly_billing_cycle',
                'schedule': monthly1st,
                'schedule_type': 'crontab',
            },
            {
                'name': 'Generate daily brief all orgs',
                'task': 'apps.health.analytics.tasks.generate_daily_brief_all_orgs',
                'schedule': at630am,
                'schedule_type': 'crontab',
            },
        ]

        created = 0
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
            else:
                self.stdout.write(f'  [=] Exists:  {obj.name}')

        self.stdout.write(
            self.style.SUCCESS(
                f'\nDone. {created} new tasks created, '
                f'{len(tasks) - created} already existed.'
            )
        )
