import datetime
import json

import structlog
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views import View
from django.utils import timezone

from apps.infrastructure.core.helpers import get_org_or_404
from apps.infrastructure.core.rls import set_tenant_context
from apps.infrastructure.core.views import TenantRequiredMixin

from .services import TaskService

logger = structlog.get_logger(__name__)


class TaskListView(TenantRequiredMixin, View):
    """GET /tasks/ — Kanban board with To Do / In Progress / Completed columns."""

    def get(self, request):
        from apps.farm.tasks.models import FarmTask, TaskTemplate

        org = get_org_or_404(request)
        today = datetime.date.today()
        tab = request.GET.get("tab", "all")

        with set_tenant_context(org):
            base_qs = FarmTask.objects.filter(org=org).select_related(
                "farm", "batch", "assigned_to", "completed_by"
            ).order_by("due_date", "-priority")

            if tab == "high_priority":
                base_qs = base_qs.filter(priority="high")
            elif tab == "my_assignments":
                base_qs = base_qs.filter(assigned_to=request.user)

            # Include legacy 'overdue' status in the To Do column
            todo = list(base_qs.filter(status__in=["pending", "overdue"]))
            in_progress = list(base_qs.filter(status="in_progress"))
            completed = list(
                base_qs.filter(status="complete").order_by("-completed_at")[:20]
            )

            cycles = list(TaskTemplate.objects.filter(is_active=True)[:6])

        context = {
            "todo": todo,
            "in_progress": in_progress,
            "completed": completed,
            "todo_count": len(todo),
            "in_progress_count": len(in_progress),
            "completed_count": len(completed),
            "active_tab": tab,
            "cycles": cycles,
            "today": today,
        }
        return render(request, "tasks/task_list.html", context)


class TaskCreateView(TenantRequiredMixin, View):
    """GET → form fragment; POST → create task and refresh."""

    def get(self, request):
        from apps.farm.farms.models import Farm
        from apps.farm.flocks.models import Batch

        org = get_org_or_404(request)
        with set_tenant_context(org):
            farms = list(Farm.objects.filter(is_active=True))
            batches = list(Batch.objects.filter(status="active").select_related("farm"))
            team = list(
                request.user.__class__.objects.filter(org=org, is_active=True)
            )

        return render(request, "tasks/_task_create_form.html", {
            "farms": farms,
            "batches": batches,
            "team": team,
            "today": datetime.date.today(),
        })

    def post(self, request):
        from apps.farm.tasks.models import FarmTask

        org = get_org_or_404(request)
        title = request.POST.get("title", "").strip()
        description = request.POST.get("description", "").strip()
        due_date_str = request.POST.get("due_date", "")
        priority = request.POST.get("priority", "medium")
        category = request.POST.get("category", "other")
        assigned_to_id = request.POST.get("assigned_to")
        farm_id = request.POST.get("farm")
        batch_id = request.POST.get("batch")

        if not title:
            return render(request, "tasks/_task_create_form.html", {
                "error": "Title is required.",
                "today": datetime.date.today(),
            })

        with set_tenant_context(org):
            task = FarmTask(
                org=org,
                title=title,
                description=description,
                priority=priority,
                category=category,
                status="pending",
                created_by=request.user,
            )
            if due_date_str:
                try:
                    task.due_date = datetime.datetime.strptime(due_date_str, "%Y-%m-%d").date()
                except ValueError:
                    pass
            if assigned_to_id:
                task.assigned_to_id = assigned_to_id
            if farm_id:
                task.farm_id = farm_id
            if batch_id:
                task.batch_id = batch_id
            task.save()

        response = HttpResponse(status=204)
        response["HX-Trigger"] = json.dumps({
            "showToast": {"message": f'Task "{title}" created', "type": "success"},
            "close-modal": True,
        })
        response["HX-Refresh"] = "true"
        return response


class TaskStatusView(TenantRequiredMixin, View):
    """POST /tasks/<pk>/status/ — move task between Kanban columns."""

    def post(self, request, pk):
        from apps.farm.tasks.models import FarmTask

        new_status = request.POST.get("status")
        if new_status not in ("pending", "in_progress", "complete"):
            return HttpResponse(status=400)

        org = get_org_or_404(request)
        with set_tenant_context(org):
            task = get_object_or_404(FarmTask, pk=pk, org=org)
            task.status = new_status
            if new_status == "complete":
                task.completed_at = timezone.now()
                task.completed_by = request.user
            task.save()

        label = new_status.replace("_", " ").title()
        response = HttpResponse(status=204)
        response["HX-Trigger"] = json.dumps({
            "showToast": {"message": f"Task moved to {label}", "type": "success"},
        })
        response["HX-Refresh"] = "true"
        return response


class TaskDeleteView(TenantRequiredMixin, View):
    """POST /tasks/<pk>/delete/ — permanently remove a task."""

    def post(self, request, pk):
        from apps.farm.tasks.models import FarmTask

        org = get_org_or_404(request)
        with set_tenant_context(org):
            task = get_object_or_404(FarmTask, pk=pk, org=org)
            task.delete()

        response = HttpResponse(status=204)
        response["HX-Trigger"] = json.dumps({
            "showToast": {"message": "Task deleted", "type": "success"},
        })
        response["HX-Refresh"] = "true"
        return response


class TaskCompleteView(LoginRequiredMixin, View):
    """POST /tasks/<uuid>/complete/ — mark task done, refresh Kanban."""

    def post(self, request, pk):
        org = get_org_or_404(request)

        with set_tenant_context(org):
            try:
                task = TaskService(org).complete_task(str(pk), request.user)
            except ValueError as exc:
                raise Http404(str(exc))

            # Render inside the RLS scope — the template reads task.farm.name,
            # task.batch.batch_name and task.completed_by (lazy relations).
            response = render(request, "tasks/_task_row.html", {"task": task})
        response["HX-Trigger"] = json.dumps(
            {"showToast": {"message": "Task completed", "type": "success"}}
        )
        response["HX-Refresh"] = "true"
        return response


class TaskSummaryWidget(LoginRequiredMixin, View):
    """GET /tasks/summary/ — HTMX dashboard widget fragment."""

    EMPTY = {"pending_count": 0, "overdue_count": 0, "completed_today": 0}

    def get(self, request):
        org = getattr(request.user, "org", None)
        if not org:
            return render(request, "tasks/_task_summary_widget.html", self.EMPTY)

        with set_tenant_context(org):
            summary = TaskService(org).get_task_summary()

        return render(request, "tasks/_task_summary_widget.html", summary or self.EMPTY)
