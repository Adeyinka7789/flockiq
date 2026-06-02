import datetime
import json

import structlog
from django.contrib.auth.mixins import LoginRequiredMixin
from apps.infrastructure.core.views import TenantRequiredMixin
from django.http import Http404
from django.shortcuts import render
from django.views import View

from apps.infrastructure.core.rls import set_tenant_context

from .services import TaskService

logger = structlog.get_logger(__name__)


def _get_org(request):
    org = getattr(request.user, "org", None)
    if org is None:
        raise Http404("No organisation found for this user.")
    return org


class TaskListView(TenantRequiredMixin, View):
    """GET /tasks/ → Full task list page with farm/status filtering."""

    def get(self, request):
        from apps.farm.tasks.models import FarmTask
        from apps.farm.farms.models import Farm

        org = _get_org(request)
        today = datetime.date.today()
        is_htmx = request.headers.get("HX-Request") == "true"

        farm_id = request.GET.get("farm", "")
        status_filter = request.GET.get("status", "")

        with set_tenant_context(org):
            service = TaskService(org)
            farms = list(Farm.objects.filter(is_active=True))

            overdue_qs = service.get_overdue_tasks()
            pending_qs = service.get_todays_tasks(farm_id=farm_id or None).filter(
                status=FarmTask.Status.PENDING
            )
            completed_qs = FarmTask.objects.filter(
                org=org,
                status=FarmTask.Status.COMPLETE,
                completed_at__date=today,
            ).select_related("farm", "batch", "completed_by")

            if farm_id:
                overdue_qs = overdue_qs.filter(farm_id=farm_id)
                completed_qs = completed_qs.filter(farm_id=farm_id)

            if status_filter == "overdue":
                overdue_tasks = list(overdue_qs)
                pending_tasks = []
                completed_tasks = []
            elif status_filter == "pending":
                overdue_tasks = []
                pending_tasks = list(pending_qs)
                completed_tasks = []
            elif status_filter == "complete":
                overdue_tasks = []
                pending_tasks = []
                completed_tasks = list(completed_qs)
            else:
                overdue_tasks = list(overdue_qs)
                pending_tasks = list(pending_qs)
                completed_tasks = list(completed_qs)

            summary = service.get_task_summary()

        STATUS_TABS = [
            ("", "All", "#6b7280"),
            ("pending", "Pending", "#5b8dd9"),
            ("overdue", "Overdue", "#f87171"),
            ("complete", "Done", "#8bc87a"),
        ]

        context = {
            "today": today,
            "pending_tasks": pending_tasks,
            "overdue_tasks": overdue_tasks,
            "completed_tasks": completed_tasks,
            "summary": summary,
            "farms": farms,
            "active_farm": farm_id,
            "active_status": status_filter,
            "status_tabs": STATUS_TABS,
        }

        if is_htmx:
            return render(request, "tasks/_task_sections.html", context)
        return render(request, "tasks/task_list.html", context)


class TaskCompleteView(LoginRequiredMixin, View):
    """POST /tasks/<uuid>/complete/ → Mark task done, return updated row fragment."""

    def post(self, request, pk):
        org = _get_org(request)

        with set_tenant_context(org):
            try:
                task = TaskService(org).complete_task(str(pk), request.user)
            except ValueError as exc:
                raise Http404(str(exc))

        response = render(request, "tasks/_task_row.html", {"task": task})
        response["HX-Trigger"] = json.dumps(
            {"showToast": {"message": "Task completed", "type": "success"}}
        )
        return response


class TaskSummaryWidget(LoginRequiredMixin, View):
    """GET /tasks/summary/ → HTMX dashboard widget fragment."""

    EMPTY = {"pending_count": 0, "overdue_count": 0, "completed_today": 0}

    def get(self, request):
        org = getattr(request.user, "org", None)
        if not org:
            return render(request, "tasks/_task_summary_widget.html", self.EMPTY)

        with set_tenant_context(org):
            summary = TaskService(org).get_task_summary()

        return render(request, "tasks/_task_summary_widget.html", summary or self.EMPTY)
