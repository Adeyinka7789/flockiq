import json
from datetime import date, timedelta

import structlog
from django.contrib.auth.mixins import LoginRequiredMixin
from apps.infrastructure.core.views import TenantRequiredMixin
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.views import View
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.infrastructure.core.rls import set_tenant_context

from .services import HealthService

logger = structlog.get_logger(__name__)


def _get_org(request):
    org = getattr(request.user, "org", None)
    if org is None:
        raise Http404("No organisation found for this user.")
    return org


class VaccinationCalendarView(TenantRequiredMixin, View):
    """GET /health/vaccinations/ — Full vaccination calendar across all farms."""

    def get(self, request):
        from apps.farm.farms.models import Farm
        from .models import VaccinationSchedule

        today = date.today()
        org = _get_org(request)

        status_filter = request.GET.get("status", "upcoming")
        farm_id = request.GET.get("farm")
        days_ahead = int(request.GET.get("days_ahead", 30))

        with set_tenant_context(org):
            qs = VaccinationSchedule.objects.select_related(
                "batch__farm", "batch__house"
            ).order_by("due_date")

            if farm_id:
                qs = qs.filter(batch__farm_id=farm_id)

            if status_filter == "overdue":
                qs = qs.filter(status="scheduled", due_date__lt=today)
            elif status_filter == "today":
                qs = qs.filter(status="scheduled", due_date=today)
            elif status_filter == "this_week":
                qs = qs.filter(
                    status="scheduled",
                    due_date__gte=today,
                    due_date__lte=today + timedelta(days=7),
                )
            elif status_filter == "completed":
                qs = qs.filter(status="completed")
            else:
                qs = qs.filter(
                    Q(status="scheduled", due_date__lt=today)
                    | Q(status="scheduled", due_date__lte=today + timedelta(days=days_ahead))
                )

            vaccinations = list(qs)

            overdue_count = VaccinationSchedule.objects.filter(
                status="scheduled", due_date__lt=today
            ).count()
            due_this_week = VaccinationSchedule.objects.filter(
                status="scheduled",
                due_date__gte=today,
                due_date__lte=today + timedelta(days=7),
            ).count()
            completed_month = VaccinationSchedule.objects.filter(
                status="completed",
                administered_date__gte=today.replace(day=1),
            ).count()
            total_scheduled = VaccinationSchedule.objects.filter(status="scheduled").count()

            farms = Farm.objects.filter(is_active=True)

            for v in vaccinations:
                delta = (v.due_date - today).days
                if v.status == "completed":
                    v.urgency = "completed"
                    v.days_label = "Done"
                elif delta < 0:
                    v.urgency = "overdue"
                    v.days_label = f"{abs(delta)}d overdue"
                elif delta == 0:
                    v.urgency = "today"
                    v.days_label = "Today!"
                elif delta <= 3:
                    v.urgency = "soon"
                    v.days_label = f"In {delta}d"
                else:
                    v.urgency = "upcoming"
                    v.days_label = f"In {delta}d"

        context = {
            "vaccinations": vaccinations,
            "overdue_count": overdue_count,
            "due_this_week": due_this_week,
            "completed_month": completed_month,
            "total_scheduled": total_scheduled,
            "farms": farms,
            "active_status": status_filter,
            "active_farm": farm_id,
            "today": today,
        }

        if request.headers.get("HX-Request"):
            return render(request, "health/_vaccination_table.html", context)
        return render(request, "health/vaccination_calendar.html", context)


class VaccinationCalendarPDFExportView(TenantRequiredMixin, View):
    """GET /health/vaccinations/export/pdf/ → Waffle-gated PDF of vaccination calendar."""

    def get(self, request):
        from waffle import flag_is_active
        if not flag_is_active(request, 'pdf_export'):
            return HttpResponse('PDF export requires an upgraded plan.', status=403)

        org = _get_org(request)
        today = date.today()
        with set_tenant_context(org):
            from .models import VaccinationSchedule
            vaccinations = list(
                VaccinationSchedule.objects.select_related('batch__farm', 'batch__house')
                .order_by('due_date')
            )
            for v in vaccinations:
                delta = (v.due_date - today).days
                if v.status == 'completed':
                    v.days_label = 'Done'
                elif delta < 0:
                    v.days_label = f'{abs(delta)}d overdue'
                elif delta == 0:
                    v.days_label = 'Today!'
                else:
                    v.days_label = f'In {delta}d'

        from apps.infrastructure.core.exports import generate_vaccination_calendar_pdf
        pdf_bytes = generate_vaccination_calendar_pdf(vaccinations, today)
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="vaccination-calendar-{today}.pdf"'
        return response


class VaccinationCalendarExcelExportView(TenantRequiredMixin, View):
    """GET /health/vaccinations/export/excel/ → Waffle-gated Excel of vaccination calendar."""

    def get(self, request):
        from waffle import flag_is_active
        if not flag_is_active(request, 'excel_export'):
            return HttpResponse('Excel export requires an upgraded plan.', status=403)

        org = _get_org(request)
        today = date.today()
        with set_tenant_context(org):
            from .models import VaccinationSchedule
            vaccinations = list(
                VaccinationSchedule.objects.select_related('batch__farm', 'batch__house')
                .order_by('due_date')
            )
            for v in vaccinations:
                delta = (v.due_date - today).days
                if v.status == 'completed':
                    v.days_label = 'Done'
                elif delta < 0:
                    v.days_label = f'{abs(delta)}d overdue'
                elif delta == 0:
                    v.days_label = 'Today!'
                else:
                    v.days_label = f'In {delta}d'

        from apps.infrastructure.core.exports import generate_vaccination_calendar_excel
        xlsx_bytes = generate_vaccination_calendar_excel(vaccinations, today)
        response = HttpResponse(
            xlsx_bytes,
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        response['Content-Disposition'] = f'attachment; filename="vaccination-calendar-{today}.xlsx"'
        return response


class VaccinationCompleteView(LoginRequiredMixin, View):
    """POST /health/vaccinations/<uuid>/complete/ — Marks vaccination administered."""

    def post(self, request, pk):
        org = _get_org(request)

        with set_tenant_context(org):
            try:
                svc = HealthService(org)
                vacc = svc.record_vaccination(
                    vaccination_id=pk,
                    administered_by=request.user,
                    notes=request.POST.get("notes", ""),
                )
            except ValueError as exc:
                return render(
                    request,
                    "health/_vaccination_row.html",
                    {"vacc": None, "error": str(exc)},
                    status=422,
                )

        vacc.urgency = "completed"
        vacc.days_label = "Done"

        response = render(
            request,
            "health/_vaccination_row.html",
            {"vacc": vacc},
        )
        response["HX-Trigger"] = json.dumps(
            {"showToast": {"message": "Vaccination recorded.", "type": "success"}}
        )
        return response


class MedicationLogView(LoginRequiredMixin, View):
    """GET+POST /health/medications/<uuid:batch_pk>/log/ — Records medication."""

    def get(self, request, batch_pk):
        return render(request, "health/_medication_modal.html", {"batch_pk": batch_pk})

    def post(self, request, batch_pk):
        import datetime
        from decimal import Decimal

        org = _get_org(request)
        data = request.POST

        required = ["drug_name", "drug_type", "start_date", "duration_days",
                    "dosage", "quantity_used", "unit"]
        for field in required:
            if not data.get(field):
                return render(
                    request,
                    "health/_medication_modal.html",
                    {"error": f"{field} is required.", "batch_pk": batch_pk},
                )

        try:
            with set_tenant_context(org):
                svc = HealthService(org)
                record = svc.record_medication(
                    batch_id=str(batch_pk),
                    drug_name=data["drug_name"],
                    drug_type=data["drug_type"],
                    start_date=datetime.date.fromisoformat(data["start_date"]),
                    duration_days=int(data["duration_days"]),
                    withdrawal_period_days=int(data.get("withdrawal_period_days", 0)),
                    dosage=data["dosage"],
                    quantity_used=Decimal(data["quantity_used"]),
                    unit=data["unit"],
                    cost=Decimal(data.get("cost", "0") or "0"),
                    vet_name=data.get("vet_name", ""),
                    reason=data.get("reason", "reactive"),
                    notes=data.get("notes", ""),
                )
        except ValueError as exc:
            return render(
                request,
                "health/_medication_modal.html",
                {"error": str(exc), "batch_pk": batch_pk},
            )

        response = HttpResponse('')
        response["HX-Trigger"] = json.dumps({
            "showToast": {"message": "Medication recorded.", "type": "success"},
            "medicationLogged": {},
        })
        return response


class MedicationListView(LoginRequiredMixin, View):
    """GET /health/medications/<uuid:batch_pk>/list/ → HTMX medication list fragment."""

    def get(self, request, batch_pk):
        org = _get_org(request)
        with set_tenant_context(org):
            meds = HealthService(org).get_health_summary(str(batch_pk))["active_medications"]
        return render(
            request,
            "health/_medication_list.html",
            {"medications": meds, "batch_pk": batch_pk},
        )


_SYMPTOM_CHOICES = [
    ("lethargy", "Lethargy"),
    ("reduced_feed", "Reduced Feed"),
    ("nasal_discharge", "Nasal Discharge"),
    ("coughing", "Coughing"),
    ("diarrhoea", "Diarrhoea"),
    ("ruffled_feathers", "Ruffled Feathers"),
    ("swollen_eyes", "Swollen Eyes"),
    ("sudden_death", "Sudden Death"),
    ("reduced_laying", "Reduced Laying"),
    ("lameness", "Lameness"),
]


class SymptomLogView(LoginRequiredMixin, View):
    """GET+POST /health/symptoms/<uuid:batch_pk>/log/ — Records symptoms."""

    def get(self, request, batch_pk):
        return render(request, "health/_symptom_modal.html", {
            "batch_pk": batch_pk,
            "symptoms_choices": _SYMPTOM_CHOICES,
        })

    def post(self, request, batch_pk):
        org = _get_org(request)
        data = request.POST

        symptoms = data.getlist("symptoms")
        severity = data.get("severity", "mild")
        affected_count = data.get("affected_count")

        if not affected_count:
            return render(
                request,
                "health/_symptom_modal.html",
                {"error": "affected_count is required.", "batch_pk": batch_pk,
                 "symptoms_choices": _SYMPTOM_CHOICES},
            )

        try:
            with set_tenant_context(org):
                HealthService(org).log_symptoms(
                    batch_id=str(batch_pk),
                    affected_count=int(affected_count),
                    symptoms=symptoms,
                    severity=severity,
                    treatment_notes=data.get("treatment_notes", ""),
                    recorded_by=request.user,
                )
        except ValueError as exc:
            return render(
                request,
                "health/_symptom_modal.html",
                {"error": str(exc), "batch_pk": batch_pk,
                 "symptoms_choices": _SYMPTOM_CHOICES},
            )

        response = HttpResponse('')
        response["HX-Trigger"] = json.dumps(
            {"showToast": {"message": "Symptoms logged.", "type": "success"}}
        )
        return response


class HealthSummaryView(LoginRequiredMixin, View):
    """GET /health/summary/<uuid:batch_pk>/ — HTMX fragment for batch health tab."""

    def get(self, request, batch_pk):
        org = _get_org(request)

        with set_tenant_context(org):
            summary = HealthService(org).get_health_summary(str(batch_pk))

        return render(
            request,
            "health/_health_summary.html",
            {**summary, "batch_pk": batch_pk},
        )


class OutbreakAlertView(TenantRequiredMixin, View):
    """GET /health/outbreaks/ — Lists active outbreak alerts."""

    def get(self, request):
        from .models import OutbreakAlert

        org = _get_org(request)

        with set_tenant_context(org):
            alerts = list(
                OutbreakAlert.objects.filter(is_active=True)
                .select_related("farm")
                .order_by("-created_at")
            )

        return render(
            request,
            "health/outbreaks.html",
            {"alerts": alerts},
        )


# ── DRF API ──────────────────────────────────────────────────────────────────


class VaccinationAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        org = getattr(request.user, "org", None)
        if not org:
            return Response({"error": "No organisation."}, status=403)

        days_ahead = int(request.query_params.get("days_ahead", 30))
        with set_tenant_context(org):
            vaccinations = HealthService(org).get_vaccination_calendar(days_ahead=days_ahead)

        data = [
            {
                "id": str(v.id),
                "vaccine_name": v.vaccine_name,
                "batch": str(v.batch),
                "farm": str(v.farm),
                "due_date": str(v.due_date),
                "status": v.status,
                "route": v.route,
                "is_overdue": v.is_overdue,
                "days_until_due": v.days_until_due,
            }
            for v in vaccinations
        ]
        return Response({"data": data})

    def post(self, request):
        org = getattr(request.user, "org", None)
        if not org:
            return Response({"error": "No organisation."}, status=403)

        from .models import VaccinationSchedule
        import datetime

        required = ["batch_id", "vaccine_name", "due_date"]
        for field in required:
            if field not in request.data:
                return Response({"error": {"detail": f"{field} is required."}}, status=400)

        try:
            from apps.farm.flocks.models import Batch
            with set_tenant_context(org):
                batch = Batch.objects.get(id=request.data["batch_id"], org=org)
                vacc = VaccinationSchedule.objects.create(
                    org=org,
                    batch=batch,
                    farm=batch.farm,
                    vaccine_name=request.data["vaccine_name"],
                    due_date=datetime.date.fromisoformat(request.data["due_date"]),
                    route=request.data.get("route", "oral"),
                    notes=request.data.get("notes", ""),
                )
        except Exception as exc:
            return Response({"error": {"detail": str(exc)}}, status=400)

        return Response(
            {"data": {"id": str(vacc.id), "vaccine_name": vacc.vaccine_name}},
            status=201,
        )


class VaccinationCompleteAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        org = getattr(request.user, "org", None)
        if not org:
            return Response({"error": "No organisation."}, status=403)

        import datetime

        try:
            with set_tenant_context(org):
                vacc = HealthService(org).record_vaccination(
                    vaccination_id=pk,
                    administered_by=request.user,
                    administered_date=(
                        datetime.date.fromisoformat(request.data["administered_date"])
                        if request.data.get("administered_date")
                        else None
                    ),
                    notes=request.data.get("notes", ""),
                )
        except ValueError as exc:
            return Response({"error": {"detail": str(exc)}}, status=400)

        return Response(
            {
                "data": {
                    "id": str(vacc.id),
                    "status": vacc.status,
                    "administered_date": str(vacc.administered_date),
                }
            }
        )


class MedicationAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        import datetime
        from decimal import Decimal

        org = getattr(request.user, "org", None)
        if not org:
            return Response({"error": "No organisation."}, status=403)

        required = ["batch_id", "drug_name", "drug_type", "start_date",
                    "duration_days", "dosage", "quantity_used", "unit"]
        for field in required:
            if field not in request.data:
                return Response({"error": {"detail": f"{field} is required."}}, status=400)

        try:
            with set_tenant_context(org):
                record = HealthService(org).record_medication(
                    batch_id=request.data["batch_id"],
                    drug_name=request.data["drug_name"],
                    drug_type=request.data["drug_type"],
                    start_date=datetime.date.fromisoformat(request.data["start_date"]),
                    duration_days=int(request.data["duration_days"]),
                    withdrawal_period_days=int(request.data.get("withdrawal_period_days", 0)),
                    dosage=request.data["dosage"],
                    quantity_used=Decimal(str(request.data["quantity_used"])),
                    unit=request.data["unit"],
                    cost=Decimal(str(request.data.get("cost", "0") or "0")),
                    vet_name=request.data.get("vet_name", ""),
                    reason=request.data.get("reason", "reactive"),
                    notes=request.data.get("notes", ""),
                )
        except (ValueError, Exception) as exc:
            return Response({"error": {"detail": str(exc)}}, status=400)

        return Response(
            {
                "data": {
                    "id": str(record.id),
                    "drug_name": record.drug_name,
                    "end_date": str(record.end_date),
                    "withdrawal_cleared_date": str(record.withdrawal_cleared_date),
                }
            },
            status=201,
        )


class SymptomAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        org = getattr(request.user, "org", None)
        if not org:
            return Response({"error": "No organisation."}, status=403)

        required = ["batch_id", "affected_count", "symptoms", "severity"]
        for field in required:
            if field not in request.data:
                return Response({"error": {"detail": f"{field} is required."}}, status=400)

        try:
            with set_tenant_context(org):
                log = HealthService(org).log_symptoms(
                    batch_id=request.data["batch_id"],
                    affected_count=int(request.data["affected_count"]),
                    symptoms=request.data["symptoms"],
                    severity=request.data["severity"],
                    treatment_notes=request.data.get("treatment_notes", ""),
                    recorded_by=request.user,
                )
        except ValueError as exc:
            return Response({"error": {"detail": str(exc)}}, status=400)

        return Response(
            {
                "data": {
                    "id": str(log.id),
                    "severity": log.severity,
                    "affected_count": log.affected_count,
                    "record_date": str(log.record_date),
                }
            },
            status=201,
        )
