import datetime

import structlog
from django.db import transaction
from django.db.models import Case, IntegerField, Value, When
from django.utils import timezone

from apps.infrastructure.core.services import BaseService

logger = structlog.get_logger(__name__)


class TaskService(BaseService):

    def generate_daily_tasks(self, date=None) -> int:
        from apps.farm.flocks.models import Batch
        from apps.farm.tasks.models import FarmTask, TaskTemplate

        target_date = date or datetime.date.today()
        created_count = 0

        active_batches = list(
            Batch.objects.filter(status="active").select_related("farm")
        )

        daily_templates = list(TaskTemplate.objects.filter(is_active=True, frequency="daily"))

        for batch in active_batches:
            batch_cycle_day = (target_date - batch.placement_date).days

            applicable = [
                t for t in daily_templates
                if t.breed_applicable in (batch.bird_type, "both")
            ]

            one_time = list(
                TaskTemplate.objects.filter(
                    is_active=True,
                    frequency="one_time",
                    cycle_day=batch_cycle_day,
                )
            )
            applicable += one_time

            for template in applicable:
                _, created = FarmTask.objects.get_or_create(
                    org=self.org,
                    batch=batch,
                    farm=batch.farm,
                    template=template,
                    due_date=target_date,
                    defaults={
                        "title": template.name,
                        "description": template.description,
                        "priority": FarmTask.Priority.MEDIUM,
                        "status": FarmTask.Status.PENDING,
                    },
                )
                if created:
                    created_count += 1

        logger.info(
            "tasks.daily_generated",
            org_id=str(self.org.id),
            date=str(target_date),
            count=created_count,
        )
        return created_count

    def complete_task(self, task_id: str, user) -> "FarmTask":
        from apps.farm.tasks.models import FarmTask

        try:
            task = FarmTask.objects.get(id=task_id, org=self.org)
        except FarmTask.DoesNotExist:
            raise ValueError(f"Task {task_id} not found.")

        with transaction.atomic():
            task.status = FarmTask.Status.COMPLETE
            task.completed_at = timezone.now()
            task.completed_by = user
            task.save(update_fields=["status", "completed_at", "completed_by", "updated_at"])

        logger.info("tasks.task_completed", task_id=str(task.id))
        return task

    def get_todays_tasks(self, farm_id=None):
        from apps.farm.tasks.models import FarmTask

        qs = FarmTask.objects.filter(
            org=self.org,
            due_date=datetime.date.today(),
        ).select_related("batch", "farm", "template", "assigned_to")

        if farm_id:
            qs = qs.filter(farm_id=farm_id)

        priority_order = Case(
            When(priority="high", then=Value(3)),
            When(priority="medium", then=Value(2)),
            When(priority="low", then=Value(1)),
            default=Value(0),
            output_field=IntegerField(),
        )
        return qs.annotate(priority_val=priority_order).order_by("-priority_val")

    def get_overdue_tasks(self):
        from apps.farm.tasks.models import FarmTask

        today = datetime.date.today()
        FarmTask.objects.filter(
            org=self.org,
            status=FarmTask.Status.PENDING,
            due_date__lt=today,
        ).update(status=FarmTask.Status.OVERDUE)

        return FarmTask.objects.filter(
            org=self.org,
            status=FarmTask.Status.OVERDUE,
        ).select_related("batch", "farm", "template")

    def get_task_summary(self) -> dict:
        from apps.farm.tasks.models import FarmTask

        today = datetime.date.today()

        pending_count = FarmTask.objects.filter(
            org=self.org,
            status=FarmTask.Status.PENDING,
            due_date=today,
        ).count()

        overdue_count = FarmTask.objects.filter(
            org=self.org,
            status=FarmTask.Status.OVERDUE,
        ).count()
        overdue_count += FarmTask.objects.filter(
            org=self.org,
            status=FarmTask.Status.PENDING,
            due_date__lt=today,
        ).count()

        completed_today_count = FarmTask.objects.filter(
            org=self.org,
            status=FarmTask.Status.COMPLETE,
            completed_at__date=today,
        ).count()

        return {
            "pending_count": pending_count,
            "overdue_count": overdue_count,
            "completed_today_count": completed_today_count,
        }

    def send_incomplete_report(self) -> None:
        from apps.farm.tasks.models import FarmTask
        from apps.infrastructure.notifications.services import NotificationService

        today = datetime.date.today()
        incomplete = FarmTask.objects.filter(
            org=self.org,
            status__in=[FarmTask.Status.OVERDUE, FarmTask.Status.PENDING],
            due_date__lte=today,
        )

        if not incomplete.exists():
            return

        for farm_name, farm_id in incomplete.values_list("farm__name", "farm_id").distinct():
            count = incomplete.filter(farm_id=farm_id).count()
            try:
                with transaction.atomic():
                    NotificationService(self.org).send(
                        event_type="incomplete_tasks",
                        context={
                            "farm_name": farm_name or "",
                            "count": count,
                            "date": str(today),
                        },
                    )
            except Exception:
                logger.exception("tasks.incomplete_report_failed", farm_id=str(farm_id))
