import structlog
from datetime import date, timedelta

from apps.infrastructure.core.services import BaseService

logger = structlog.get_logger(__name__)


class DailyBriefService(BaseService):
    """
    Generates a smart daily summary for the dashboard.
    Called once per day via Celery Beat per org.
    Stored in cache for fast dashboard load.
    """

    CACHE_KEY = "daily_brief:{org_id}"
    CACHE_TTL = 3600  # 1 hour

    def generate(self) -> dict:
        from django.db.models import Sum, Avg
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.farm.flocks.models import Batch, MortalityLog
        from apps.production.production.models import EggProductionLog
        from apps.health.health.models import VaccinationSchedule
        from apps.farm.tasks.models import FarmTask

        today = date.today()
        yesterday = today - timedelta(days=1)

        with set_tenant_context(self.org):
            active_batches = list(
                Batch.objects.filter(status="active").select_related("farm", "house")
            )

            insights = []
            alerts = []
            recommendations = []

            for batch in active_batches:
                # Mortality spike check
                yesterday_mort = (
                    MortalityLog.objects.filter(batch=batch, date=yesterday)
                    .aggregate(total=Sum("count"))["total"] or 0
                )
                week_avg = (
                    MortalityLog.objects.filter(
                        batch=batch,
                        date__gte=today - timedelta(days=7),
                        date__lt=yesterday,
                    )
                    .aggregate(avg=Avg("count"))["avg"] or 0
                )

                if yesterday_mort > 0 and week_avg > 0:
                    ratio = yesterday_mort / week_avg
                    if ratio >= 2.5:
                        alerts.append({
                            "type": "critical",
                            "title": f"Mortality spike — {batch.batch_name}",
                            "body": (
                                f"{yesterday_mort} birds died yesterday in "
                                f"{batch.house.name}, {batch.farm.name}. "
                                f"This is {ratio:.1f}× your 7-day average "
                                f"({week_avg:.0f}/day). Possible disease "
                                f"outbreak. Isolate flock and call vet."
                            ),
                            "batch": batch,
                            "severity": "critical",
                        })
                    elif ratio >= 1.5:
                        alerts.append({
                            "type": "warning",
                            "title": f"Elevated mortality — {batch.batch_name}",
                            "body": (
                                f"{yesterday_mort} birds died yesterday. "
                                f"{ratio:.1f}× above average. Monitor closely."
                            ),
                            "batch": batch,
                            "severity": "warning",
                        })

                # Broiler sale timing
                if batch.bird_type == "broiler":
                    day = batch.cycle_day
                    if 35 <= day <= 42:
                        recommendations.append({
                            "type": "sale_timing",
                            "title": f"Sale window — {batch.batch_name}",
                            "body": (
                                f"Day {day} — optimal sale window is open. "
                                f"{batch.current_count} birds ready. "
                                f"Every extra day costs feed without "
                                f"proportional weight gain."
                            ),
                            "batch": batch,
                            "severity": "info",
                            "urgency": "now" if day >= 40 else "soon",
                        })
                    elif day > 42:
                        recommendations.append({
                            "type": "sale_timing",
                            "title": f"Urgent: sell {batch.batch_name}",
                            "body": (
                                f"Day {day} — past optimal window. "
                                f"Daily holding cost now exceeds weight "
                                f"gain value. Sell immediately."
                            ),
                            "batch": batch,
                            "severity": "warning",
                            "urgency": "urgent",
                        })

                # Egg production drop check
                if batch.bird_type == "layer":
                    yesterday_eggs = EggProductionLog.objects.filter(
                        batch=batch, record_date=yesterday
                    ).first()
                    week_avg_eggs = (
                        EggProductionLog.objects.filter(
                            batch=batch,
                            record_date__gte=today - timedelta(days=8),
                            record_date__lt=yesterday,
                        )
                        .aggregate(avg=Avg("total_eggs"))["avg"] or 0
                    )

                    if (
                        yesterday_eggs
                        and week_avg_eggs
                        and yesterday_eggs.total_eggs < week_avg_eggs * 0.85
                    ):
                        drop_pct = round(
                            (1 - yesterday_eggs.total_eggs / week_avg_eggs) * 100
                        )
                        alerts.append({
                            "type": "warning",
                            "title": f"Egg drop — {batch.batch_name}",
                            "body": (
                                f"Yesterday: {yesterday_eggs.total_eggs} eggs "
                                f"({drop_pct}% below 7-day average of "
                                f"{week_avg_eggs:.0f}). Check: feed quality, "
                                f"water supply, stress, lighting."
                            ),
                            "batch": batch,
                            "severity": "warning",
                        })

            # Upcoming vaccinations (next 3 days)
            urgent_vaccs = VaccinationSchedule.objects.filter(
                status="scheduled",
                due_date__gte=today,
                due_date__lte=today + timedelta(days=3),
            ).select_related("batch__farm")[:3]

            for vacc in urgent_vaccs:
                days_until = (vacc.due_date - today).days
                label = (
                    "today"
                    if days_until == 0
                    else f"in {days_until} day{'s' if days_until > 1 else ''}"
                )
                recommendations.append({
                    "type": "vaccination",
                    "title": f"{vacc.vaccine_name} due {label}",
                    "body": (
                        f"{vacc.batch.batch_name} at {vacc.batch.farm.name}. "
                        f"Due: {vacc.due_date.strftime('%d %b %Y')}."
                    ),
                    "batch": vacc.batch,
                    "severity": "info",
                })

            # Overdue tasks
            overdue_tasks = FarmTask.objects.filter(
                status="pending", due_date__lt=today
            ).count()
            if overdue_tasks > 0:
                recommendations.append({
                    "type": "tasks",
                    "title": f"{overdue_tasks} overdue task{'s' if overdue_tasks > 1 else ''}",
                    "body": (
                        f"You have {overdue_tasks} overdue farm "
                        f"task{'s' if overdue_tasks > 1 else ''}. "
                        f"Review and complete them."
                    ),
                    "batch": None,
                    "severity": "warning",
                })

            # Create in-app notifications for alerts (dedup by batch+day)
            self._create_alert_notifications(alerts, today)

        brief = {
            "generated_at": today.isoformat(),
            "active_batches": len(active_batches),
            "farms_normal": max(0, len(active_batches) - len(alerts)),
            "alerts": alerts,
            "recommendations": recommendations,
            "total_issues": len(alerts),
        }
        return brief

    def _create_alert_notifications(self, alerts, today):
        from apps.infrastructure.notifications.models import NotificationLog
        from apps.infrastructure.accounts.models import CustomUser

        owner = CustomUser.objects.filter(
            org=self.org, role__in=["owner", "manager"]
        ).first()
        if not owner:
            return

        for alert in alerts:
            batch = alert.get("batch")
            if not batch:
                continue
            exists = NotificationLog.objects.filter(
                org=self.org,
                event_type="ai_anomaly",
                batch_reference=str(batch.pk),
                created_at__date=today,
            ).exists()
            if not exists:
                try:
                    NotificationLog.objects.create(
                        org=self.org,
                        recipient=owner,
                        event_type="ai_anomaly",
                        title=alert["title"],
                        body=alert["body"],
                        severity=alert["severity"],
                        channel="in_app",
                        batch_reference=str(batch.pk),
                        is_read=False,
                    )
                except Exception as exc:
                    logger.warning("Failed to create alert notification", error=str(exc))

    def get_cached(self) -> dict:
        """Get from cache or generate fresh."""
        from django.core.cache import cache

        key = self.CACHE_KEY.format(org_id=self.org.id)
        brief = cache.get(key)
        if not brief:
            brief = self.generate()
            cache.set(key, brief, timeout=self.CACHE_TTL)
        return brief

    def invalidate(self):
        from django.core.cache import cache

        cache.delete(self.CACHE_KEY.format(org_id=self.org.id))
