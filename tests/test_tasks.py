"""
Phase 2C — Tasks app tests.

Coverage:
- TaskService: generate_daily_tasks, complete_task, get_overdue_tasks, get_task_summary
- RLS isolation: FarmTask cross-tenant isolation
- HTMX view: TaskCompleteView returns fragment with HX-Trigger
"""

import datetime
from decimal import Decimal

import pytest

pytestmark = pytest.mark.django_db


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_org(subdomain="testtasks"):
    from apps.infrastructure.tenants.models import Organization
    return Organization.objects.create(name="Test Tasks Org", subdomain=subdomain)


def _make_farm(org, name="Task Farm"):
    from apps.farm.farms.models import Farm
    from apps.infrastructure.core.rls import set_tenant_context
    with set_tenant_context(org):
        farm = Farm(
            org=org,
            name=name,
            location="Lagos",
            latitude=Decimal("6.5244"),
            longitude=Decimal("3.3792"),
            farm_type="broiler",
        )
        farm.clean()
        farm.save()
    return farm


def _make_house(org, farm, capacity=2000, name="House T1"):
    from apps.farm.farms.models import House
    from apps.infrastructure.core.rls import set_tenant_context
    with set_tenant_context(org):
        return House.objects.create(
            org=org, farm=farm, name=name, capacity=capacity, house_type="broiler"
        )


def _make_batch(org, farm, house, bird_type="broiler", days_old=21):
    from apps.farm.flocks.models import Batch
    from apps.infrastructure.core.rls import set_tenant_context
    with set_tenant_context(org):
        return Batch.objects.create(
            org=org,
            farm=farm,
            house=house,
            batch_name=f"Batch-{bird_type}",
            bird_type=bird_type,
            placement_date=datetime.date.today() - datetime.timedelta(days=days_old),
            initial_count=1000,
            current_count=1000,
            status="active",
        )


def _make_template(name="Daily Check", breed="both", frequency="daily", cycle_day=None):
    from apps.farm.tasks.models import TaskTemplate
    return TaskTemplate.objects.create(
        name=name,
        breed_applicable=breed,
        frequency=frequency,
        cycle_day=cycle_day,
        is_active=True,
    )


def _make_task(org, farm, batch=None, status="pending", due_date=None):
    from apps.farm.tasks.models import FarmTask
    from apps.infrastructure.core.rls import set_tenant_context
    with set_tenant_context(org):
        return FarmTask.objects.create(
            org=org,
            farm=farm,
            batch=batch,
            title="Test Task",
            due_date=due_date or datetime.date.today(),
            status=status,
            priority="medium",
        )


def _set_rls(org_id):
    """Context manager to set PostgreSQL RLS context."""
    from apps.infrastructure.core.rls import set_tenant_context
    from apps.infrastructure.tenants.models import Organization
    org = Organization.objects.get(id=org_id)
    return set_tenant_context(org)


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestGenerateDailyTasks:

    def test_daily_tasks_generated_for_active_batch(self):
        org = _make_org("tasks-gen-1")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        template = _make_template("Morning Check", breed="both", frequency="daily")

        from apps.farm.tasks.services import TaskService
        from apps.farm.tasks.models import FarmTask

        with _set_rls(org.id):
            _make_batch(org, farm, house)
            count = TaskService(org).generate_daily_tasks()

        assert count == 1
        with _set_rls(org.id):
            assert FarmTask.objects.filter(template=template).count() == 1

    def test_duplicate_tasks_not_created(self):
        org = _make_org("tasks-dup-1")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        _make_template("Morning Check", breed="both", frequency="daily")

        from apps.farm.tasks.services import TaskService
        from apps.farm.tasks.models import FarmTask

        with _set_rls(org.id):
            _make_batch(org, farm, house)
            count1 = TaskService(org).generate_daily_tasks()
            count2 = TaskService(org).generate_daily_tasks()

        assert count1 == 1
        assert count2 == 0  # Already exists — skip

        with _set_rls(org.id):
            assert FarmTask.objects.count() == 1


class TestCompleteTask:

    def test_task_complete_sets_completed_at(self):
        from apps.infrastructure.accounts.models import CustomUser
        from apps.farm.tasks.models import FarmTask
        from apps.farm.tasks.services import TaskService

        org = _make_org("tasks-complete-1")
        farm = _make_farm(org)

        user = CustomUser.objects.create_user(
            email="worker@tasks.test",
            password="pass",
            username="worker_tasks",
            org=org,
            role="manager",
        )

        with _set_rls(org.id):
            task = _make_task(org, farm)
            task_id = str(task.id)
            completed = TaskService(org).complete_task(task_id, user)

        assert completed.status == FarmTask.Status.COMPLETE
        assert completed.completed_at is not None
        assert completed.completed_by == user


class TestOverdueTasks:

    def test_overdue_tasks_detected(self):
        from apps.farm.tasks.models import FarmTask
        from apps.farm.tasks.services import TaskService

        org = _make_org("tasks-overdue-1")
        farm = _make_farm(org)

        with _set_rls(org.id):
            yesterday = datetime.date.today() - datetime.timedelta(days=1)
            task = _make_task(org, farm, status="pending", due_date=yesterday)

            overdue_qs = TaskService(org).get_overdue_tasks()
            overdue_ids = list(overdue_qs.values_list("id", flat=True))

        assert task.id in overdue_ids

        with _set_rls(org.id):
            task.refresh_from_db()
        assert task.status == FarmTask.Status.OVERDUE


class TestTaskSummary:

    def test_task_summary_counts_correct(self):
        from apps.farm.tasks.models import FarmTask
        from apps.farm.tasks.services import TaskService

        org = _make_org("tasks-summary-1")
        farm = _make_farm(org)

        with _set_rls(org.id):
            _make_task(org, farm, status="pending", due_date=datetime.date.today())
            _make_task(org, farm, status="overdue", due_date=datetime.date.today() - datetime.timedelta(days=1))
            summary = TaskService(org).get_task_summary()

        assert summary["pending_count"] == 1
        assert summary["overdue_count"] >= 1


class TestTaskRLSIsolation:

    def test_task_rls_isolation(self):
        from apps.farm.tasks.models import FarmTask

        org_a = _make_org("tasks-rls-a")
        org_b = _make_org("tasks-rls-b")
        farm_a = _make_farm(org_a, "Farm A")
        farm_b = _make_farm(org_b, "Farm B")

        with _set_rls(org_a.id):
            task_a = _make_task(org_a, farm_a)

        with _set_rls(org_b.id):
            task_b = _make_task(org_b, farm_b)

        with _set_rls(org_a.id):
            ids = list(FarmTask.objects.values_list("id", flat=True))

        assert task_a.id in ids
        assert task_b.id not in ids


class TestTaskCompleteView:

    def test_task_complete_htmx_returns_fragment(self):
        from django.test import Client
        from apps.infrastructure.accounts.models import CustomUser
        from apps.farm.tasks.models import FarmTask

        org = _make_org("tasks-view-1")
        farm = _make_farm(org)
        user = CustomUser.objects.create_user(
            email="mgr@view.test",
            password="testpass",
            username="mgr_view",
            org=org,
            role="manager",
        )

        with _set_rls(org.id):
            task = _make_task(org, farm)
            task_id = str(task.id)

        client = Client()
        client.force_login(user)

        response = client.post(
            f"/tasks/{task_id}/complete/",
            HTTP_HX_REQUEST="true",
        )

        assert response.status_code == 200
        assert "HX-Trigger" in response
        assert b"complete" in response.content.lower() or b"done" in response.content.lower()


# ── TaskService.get_todays_tasks — lines 88-105 ───────────────────────────────

class TestGetTodaysTasks:

    def test_get_todays_tasks_with_farm_filter(self):
        org = _make_org("tasks-today-1")
        farm_a = _make_farm(org, "Farm A")
        farm_b = _make_farm(org, "Farm B")

        with _set_rls(org.id):
            task_a = _make_task(org, farm_a)
            _make_task(org, farm_b)

        from apps.farm.tasks.services import TaskService
        with _set_rls(org.id):
            results = list(TaskService(org).get_todays_tasks(farm_id=farm_a.id))

        assert all(t.farm_id == farm_a.id for t in results)
        assert any(t.id == task_a.id for t in results)

    def test_get_todays_tasks_priority_ordering(self):
        org = _make_org("tasks-today-2")
        farm = _make_farm(org)

        from apps.farm.tasks.models import FarmTask
        with _set_rls(org.id):
            FarmTask.objects.create(
                org=org, farm=farm, title="Low Task",
                due_date=datetime.date.today(), status="pending", priority="low",
            )
            FarmTask.objects.create(
                org=org, farm=farm, title="High Task",
                due_date=datetime.date.today(), status="pending", priority="high",
            )

        from apps.farm.tasks.services import TaskService
        with _set_rls(org.id):
            results = list(TaskService(org).get_todays_tasks())

        priorities = [t.priority for t in results]
        assert priorities.index("high") < priorities.index("low")


# ── TaskService.send_incomplete_report — lines 156-182 ───────────────────────

class TestSendIncompleteReport:

    def test_send_incomplete_report_fires_notification(self):
        from unittest.mock import patch
        from apps.infrastructure.notifications.services import NotificationService

        org = _make_org("tasks-report-1")
        farm = _make_farm(org)

        with _set_rls(org.id):
            _make_task(
                org, farm,
                status="pending",
                due_date=datetime.date.today() - datetime.timedelta(days=1),
            )

        from apps.farm.tasks.services import TaskService
        with _set_rls(org.id), patch.object(NotificationService, "send") as mock_send:
            TaskService(org).send_incomplete_report()

        mock_send.assert_called_once()

    def test_send_incomplete_report_no_tasks_returns_early(self):
        org = _make_org("tasks-report-2")

        from apps.farm.tasks.services import TaskService
        with _set_rls(org.id):
            # No pending/overdue tasks — early return, must not raise
            TaskService(org).send_incomplete_report()
