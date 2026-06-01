import json

import structlog
from django.contrib.auth.mixins import LoginRequiredMixin
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


class TaskListView(LoginRequiredMixin, View):
    """GET /tasks/ → Full task list page with HTMX filter tabs."""

    def get(self, request):
        org = _get_org(request)
        is_htmx = request.headers.get("HX-Request") == "true"
        status_filter = request.GET.get("status", "all")

        with set_tenant_context(org):
            service = TaskService(org)
            qs = service.get_todays_tasks()
            if status_filter != "all":
                qs = qs.filter(status=status_filter)
            tasks = list(qs)

        context = {"tasks": tasks, "status_filter": status_filter}

        if is_htmx:
            return render(request, "tasks/_task_list_partial.html", context)
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
