"""
ProactiveAlertEngine
Uses mortality trends and FCR data to warn farmers
3-5 days before problems become critical.
Fires through NotificationLog (in-app) with daily dedup.
"""
from datetime import date, timedelta
from django.db.models import Avg


class ProactiveAlertEngine:

    MORT_RATE_WARNING = 0.8
    MORT_RATE_CRITICAL = 1.5
    PRODUCTION_DROP_WARNING = 10
    PRODUCTION_DROP_CRITICAL = 20

    def __init__(self, org):
        self.org = org

    def check_mortality_trajectory(self, batch) -> dict | None:
        from apps.farm.flocks.models import MortalityLog
        from apps.infrastructure.core.rls import set_tenant_context

        today = date.today()

        with set_tenant_context(self.org):
            seven_day = MortalityLog.objects.filter(
                batch=batch,
                date__gte=today - timedelta(days=7),
                date__lt=today - timedelta(days=3),
            ).aggregate(avg=Avg('count'))['avg'] or 0

            three_day = MortalityLog.objects.filter(
                batch=batch,
                date__gte=today - timedelta(days=3),
            ).aggregate(avg=Avg('count'))['avg'] or 0

            if seven_day == 0 or three_day == 0:
                return None

            trend_ratio = three_day / seven_day
            daily_rate_pct = three_day / max(batch.current_count, 1) * 100

            if (trend_ratio >= 2.5 or
                    daily_rate_pct >= self.MORT_RATE_CRITICAL):
                severity = 'critical'
                title = f'CRITICAL: Mortality Spike in {batch.batch_name}'
                body = (
                    f'Daily mortality has increased {trend_ratio:.1f}x '
                    f'in the last 3 days ({three_day:.1f} birds/day vs '
                    f'{seven_day:.1f} avg). Immediate intervention required.')
            elif (trend_ratio >= 1.8 or
                  daily_rate_pct >= self.MORT_RATE_WARNING):
                severity = 'warning'
                title = f'Early Warning: Rising Mortality — {batch.batch_name}'
                body = (
                    f'Mortality trending upward over last 3 days '
                    f'({three_day:.1f} birds/day). Monitor closely. '
                    f'Check ventilation, water, and feed quality.')
            else:
                return None

            return {
                'batch': batch,
                'severity': severity,
                'title': title,
                'body': body,
                'trend_ratio': round(trend_ratio, 2),
                'daily_rate_pct': round(daily_rate_pct, 2),
                'type': 'mortality_trajectory',
            }

    def check_egg_production_drop(self, batch) -> dict | None:
        if batch.bird_type != 'layer':
            return None

        from apps.production.production.models import EggProductionLog
        from apps.infrastructure.core.rls import set_tenant_context

        today = date.today()

        with set_tenant_context(self.org):
            avg_14 = EggProductionLog.objects.filter(
                batch=batch,
                record_date__gte=today - timedelta(days=14),
                record_date__lt=today - timedelta(days=3),
            ).aggregate(avg=Avg('total_eggs'))['avg'] or 0

            avg_3 = EggProductionLog.objects.filter(
                batch=batch,
                record_date__gte=today - timedelta(days=3),
            ).aggregate(avg=Avg('total_eggs'))['avg'] or 0

            if avg_14 == 0 or avg_3 == 0:
                return None

            drop_pct = round((avg_14 - avg_3) / avg_14 * 100, 1)

            if drop_pct >= self.PRODUCTION_DROP_CRITICAL:
                severity = 'critical'
                title = f'Critical Production Drop — {batch.batch_name}'
                body = (
                    f'Egg production dropped {drop_pct}% in last 3 days '
                    f'({avg_3:.0f} vs {avg_14:.0f} avg). '
                    f'Check lighting schedule, feed quality, and stress '
                    f'factors immediately.')
            elif drop_pct >= self.PRODUCTION_DROP_WARNING:
                severity = 'warning'
                title = f'Production Drop Detected — {batch.batch_name}'
                body = (
                    f'Egg production down {drop_pct}% vs 14-day average. '
                    f'Monitor hen-day % and review recent management changes.')
            else:
                return None

            return {
                'batch': batch,
                'severity': severity,
                'title': title,
                'body': body,
                'drop_pct': drop_pct,
                'type': 'production_drop',
            }

    def check_fcr_drift(self, batch) -> dict | None:
        try:
            from apps.health.analytics.feed_efficiency import FeedEfficiencyService
            svc = FeedEfficiencyService(self.org, batch)
            fcr_data = svc.compute_current_fcr()

            fcr = fcr_data.get('fcr')
            target = fcr_data.get('target_fcr')
            status = fcr_data.get('status')

            if not fcr or status in ('no_data', 'good', 'acceptable'):
                return None

            return {
                'batch': batch,
                'severity': 'warning',
                'title': f'High FCR Alert — {batch.batch_name}',
                'body': (
                    f'Feed conversion ratio ({fcr}) is significantly above '
                    f'{fcr_data["breed"]} target ({target}). '
                    f'Review feed quality, waste, and bird health.'),
                'fcr': fcr,
                'target': target,
                'type': 'fcr_drift',
            }
        except Exception:
            return None

    def run_all_checks(self) -> list:
        from apps.farm.flocks.models import Batch
        from apps.infrastructure.core.rls import set_tenant_context

        alerts = []
        with set_tenant_context(self.org):
            active_batches = list(
                Batch.objects.filter(
                    status='active',
                ).select_related('farm')[:20]
            )

        for batch in active_batches:
            alert = self.check_mortality_trajectory(batch)
            if alert:
                alerts.append(alert)

            alert = self.check_egg_production_drop(batch)
            if alert:
                alerts.append(alert)

            if batch.bird_type == 'broiler':
                alert = self.check_fcr_drift(batch)
                if alert:
                    alerts.append(alert)

        return alerts

    def fire_alerts(self) -> int:
        from apps.infrastructure.notifications.models import NotificationLog
        from apps.infrastructure.accounts.models import CustomUser
        from apps.infrastructure.core.rls import set_tenant_context

        alerts = self.run_all_checks()
        fired = 0
        today = date.today()

        with set_tenant_context(self.org):
            owner = CustomUser.tenant_objects.filter(
                role__in=['owner', 'manager'],
                is_active=True,
            ).first()

        if not owner:
            return 0

        for alert in alerts:
            try:
                batch = alert['batch']
                with set_tenant_context(self.org):
                    exists = NotificationLog.objects.filter(
                        org=self.org,
                        event_type='ai_anomaly',
                        batch_reference=str(batch.pk),
                        created_at__date=today,
                    ).exists()
                    if exists:
                        continue

                    NotificationLog.objects.create(
                        org=self.org,
                        recipient=owner,
                        event_type='ai_anomaly',
                        title=alert['title'],
                        body=alert['body'],
                        severity=alert['severity'],
                        channel='in_app',
                        batch_reference=str(batch.pk),
                        is_read=False,
                    )
                    fired += 1
            except Exception:
                pass

        return fired
