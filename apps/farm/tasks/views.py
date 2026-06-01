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
    """GET /tasks/ → Full task list page with sectioned pending/overdue/completed cards."""

    def get(self, request):
        from apps.farm.tasks.models import FarmTask

        org = _get_org(request)
        today = datetime.date.today()

        with set_tenant_context(org):
            service = TaskService(org)

            overdue_tasks = list(service.get_overdue_tasks())

            pending_tasks = list(
                service.get_todays_tasks().filter(status=FarmTask.Status.PENDING)
            )

            completed_tasks = list(
                FarmTask.objects.filter(
                    org=org,
                    status=FarmTask.Status.COMPLETE,
                    completed_at__date=today,
                ).select_related("farm", "batch", "completed_by")
            )

            summary = service.get_task_summary()

        context = {
            "today": today,
            "pending_tasks": pending_tasks,
            "overdue_tasks": overdue_tasks,
            "completed_tasks": completed_tasks,
            "summary": summary,
        }
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
