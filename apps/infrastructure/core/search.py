from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views import View

from apps.infrastructure.core.rls import set_tenant_context


@method_decorator(login_required, name="dispatch")
class GlobalSearchView(View):
    def get(self, request):
        query = request.GET.get("q", "").strip()

        if not query or len(query) < 2:
            return render(
                request,
                "partials/_search_results.html",
                {"results": [], "query": query},
            )

        org = request.user.org
        role = request.user.role
        results = []

        with set_tenant_context(org):
            from apps.farm.farms.models import Farm

            farms = Farm.objects.filter(name__icontains=query, is_active=True)[:5]
            for farm in farms:
                results.append(
                    {
                        "type": "Farm",
                        "title": farm.name,
                        "subtitle": farm.location,
                        "url": f"/farms/{farm.pk}/",
                        "icon": "farm",
                        "color": "#3d5a99",
                    }
                )

            from apps.farm.flocks.models import Batch

            batches = Batch.objects.filter(
                batch_name__icontains=query
            ).select_related("farm")[:5]
            for batch in batches:
                results.append(
                    {
                        "type": "Batch",
                        "title": batch.batch_name,
                        "subtitle": f"{batch.farm.name} · {batch.bird_type.title()} · Day {batch.cycle_day}",
                        "url": f"/batches/{batch.pk}/",
                        "icon": "batch",
                        "color": "#8bc87a",
                    }
                )

            if role in ["owner", "manager", "supervisor", "vet_advisor"]:
                from apps.health.health.models import VaccinationSchedule

                vaccs = VaccinationSchedule.objects.filter(
                    vaccine_name__icontains=query
                ).select_related("batch__farm")[:3]
                for vacc in vaccs:
                    results.append(
                        {
                            "type": "Vaccination",
                            "title": vacc.vaccine_name,
                            "subtitle": f"{vacc.batch.batch_name} · Due {vacc.due_date}",
                            "url": "/health/vaccinations/",
                            "icon": "health",
                            "color": "#6aaa57",
                        }
                    )

            from apps.farm.tasks.models import FarmTask

            tasks = FarmTask.objects.filter(
                title__icontains=query
            ).select_related("farm")[:3]
            for task in tasks:
                results.append(
                    {
                        "type": "Task",
                        "title": task.title,
                        "subtitle": f"{task.farm.name} · {task.status.title()}",
                        "url": "/tasks/",
                        "icon": "task",
                        "color": "#f59e0b",
                    }
                )

            if role in ["owner", "manager"]:
                from apps.finance.expenses.models import ExpenseRecord

                expenses = ExpenseRecord.objects.filter(
                    description__icontains=query
                ).select_related("farm", "batch")[:3]
                for expense in expenses:
                    results.append(
                        {
                            "type": "Expense",
                            "title": expense.description,
                            "subtitle": f"{expense.farm.name} · ₦{expense.amount_kobo // 100:,}",
                            "url": f"/batches/{expense.batch.pk}/"
                            if expense.batch
                            else "/farms/",
                            "icon": "finance",
                            "color": "#5b8dd9",
                        }
                    )

        return render(
            request,
            "partials/_search_results.html",
            {"results": results, "query": query},
        )
