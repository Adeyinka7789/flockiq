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

        # (type label, total matching count, per-type cap) — used to tell the
        # template which result groups were truncated.
        counts = []

        with set_tenant_context(org):
            from apps.farm.farms.models import Farm, House

            farms_qs = Farm.objects.filter(name__icontains=query, is_active=True)
            farms_total = farms_qs.count()
            farms = farms_qs[:5]
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
            counts.append(("Farm", farms_total, 5))

            houses_qs = House.objects.filter(name__icontains=query).select_related(
                "farm"
            )
            houses_total = houses_qs.count()
            houses = houses_qs[:5]
            for house in houses:
                results.append(
                    {
                        "type": "House",
                        "title": house.name,
                        "subtitle": f'{house.farm.name} · Capacity: {house.capacity or "—"}',
                        "url": f"/farms/{house.farm.pk}/",
                        "icon": "house",
                        "color": "#234280",
                    }
                )
            counts.append(("House", houses_total, 5))

            from apps.farm.flocks.models import Batch

            batches_qs = Batch.objects.filter(
                batch_name__icontains=query
            ).select_related("farm")
            batches_total = batches_qs.count()
            batches = batches_qs[:5]
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
            counts.append(("Batch", batches_total, 5))

            if role in ["owner", "manager", "supervisor", "data_entry", "vet_advisor"]:
                from apps.health.health.models import VaccinationSchedule

                vaccs_qs = VaccinationSchedule.objects.filter(
                    vaccine_name__icontains=query
                ).select_related("batch__farm")
                vaccs_total = vaccs_qs.count()
                vaccs = vaccs_qs[:3]
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
                counts.append(("Vaccination", vaccs_total, 3))

            if role in ["owner", "manager", "supervisor", "vet_advisor"]:
                from apps.health.health.models import (
                    MedicationRecord,
                    OutbreakAlert,
                )

                meds_qs = MedicationRecord.objects.filter(
                    drug_name__icontains=query
                ).select_related("batch__farm")
                meds_total = meds_qs.count()
                meds = meds_qs[:3]
                for med in meds:
                    results.append(
                        {
                            "type": "Medication",
                            "title": med.drug_name,
                            "subtitle": f"{med.batch.batch_name} · {med.batch.farm.name}",
                            "url": f"/batches/{med.batch.pk}/",
                            "icon": "medication",
                            "color": "#7c3aed",
                        }
                    )
                counts.append(("Medication", meds_total, 3))

                outbreaks_qs = OutbreakAlert.objects.filter(
                    disease_name__icontains=query
                ).select_related("farm")
                outbreaks_total = outbreaks_qs.count()
                outbreaks = outbreaks_qs[:3]
                for outbreak in outbreaks:
                    results.append(
                        {
                            "type": "Outbreak Alert",
                            "title": outbreak.disease_name,
                            "subtitle": f"{outbreak.farm.name}",
                            "url": "/health/outbreaks/",
                            "icon": "alert",
                            "color": "#dc2626",
                        }
                    )
                counts.append(("Outbreak Alert", outbreaks_total, 3))

            from apps.farm.tasks.models import FarmTask

            tasks_qs = FarmTask.objects.filter(title__icontains=query).select_related(
                "farm"
            )
            tasks_total = tasks_qs.count()
            tasks = tasks_qs[:3]
            for task in tasks:
                results.append(
                    {
                        "type": "Task",
                        "title": task.title,
                        "subtitle": f"{task.farm.name} · {task.status.title()}"
                        if task.farm
                        else task.status.title(),
                        "url": "/tasks/",
                        "icon": "task",
                        "color": "#f59e0b",
                    }
                )
            counts.append(("Task", tasks_total, 3))

            if role in ["owner", "manager", "supervisor", "data_entry"]:
                from apps.finance.expenses.models import ExpenseRecord

                expenses_qs = ExpenseRecord.objects.filter(
                    description__icontains=query
                ).select_related("farm", "batch")
                expenses_total = expenses_qs.count()
                expenses = expenses_qs[:3]
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
                counts.append(("Expense", expenses_total, 3))

            if role in ["owner", "manager", "supervisor"]:
                from apps.finance.finance.models import SalesRecord

                sales_qs = SalesRecord.objects.filter(
                    buyer_name__icontains=query
                ).select_related("batch__farm")
                sales_total = sales_qs.count()
                sales = sales_qs[:3]
                for sale in sales:
                    results.append(
                        {
                            "type": "Sale",
                            "title": f"Sale to {sale.buyer_name}",
                            "subtitle": f"{sale.batch.batch_name} · {sale.batch.farm.name}",
                            "url": f"/batches/{sale.batch.pk}/",
                            "icon": "sale",
                            "color": "#16a34a",
                        }
                    )
                counts.append(("Sale", sales_total, 3))

            if role in ["owner", "manager"]:
                from django.contrib.auth import get_user_model
                from django.db.models import Q

                User = get_user_model()
                members_qs = User.tenant_objects.filter(
                    Q(first_name__icontains=query)
                    | Q(last_name__icontains=query)
                    | Q(email__icontains=query)
                )
                members_total = members_qs.count()
                members = members_qs[:3]
                for member in members:
                    results.append(
                        {
                            "type": "Team Member",
                            "title": member.get_full_name() or member.email,
                            "subtitle": f"{member.get_role_display()} · {member.email}",
                            "url": "/team/",
                            "icon": "user",
                            "color": "#336a28",
                        }
                    )
                counts.append(("Team Member", members_total, 3))

        truncated_types = [label for label, total, shown in counts if total > shown]

        return render(
            request,
            "partials/_search_results.html",
            {
                "results": results,
                "query": query,
                "truncated_types": truncated_types,
            },
        )
