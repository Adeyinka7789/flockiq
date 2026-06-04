import json
from datetime import date, timedelta

import structlog
from django.contrib.auth.mixins import LoginRequiredMixin
from apps.infrastructure.core.views import TenantRequiredMixin
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
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
            "close-modal": True,
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
        from django.utils import timezone

        from .models import OutbreakAlert

        org = _get_org(request)
        this_month = date.today().replace(day=1)

        with set_tenant_context(org):
            alerts = list(
                OutbreakAlert.objects.filter(is_active=True)
                .select_related("farm")
                .order_by("-created_at")
            )
            resolved_count = OutbreakAlert.objects.filter(
                org=org,
                is_active=False,
                resolved_at__date__gte=this_month,
            ).count()

        return render(
            request,
            "health/outbreaks.html",
            {"alerts": alerts, "resolved_count": resolved_count},
        )


class OutbreakReportView(TenantRequiredMixin, View):
    """GET+POST /health/outbreaks/report/ — Report a new outbreak."""

    def get(self, request):
        from apps.farm.farms.models import Farm

        org = _get_org(request)
        with set_tenant_context(org):
            farms = list(Farm.objects.filter(org=org, is_active=True))
        return render(
            request,
            "health/_outbreak_report_form.html",
            {"farms": farms, "today": date.today()},
        )

    def post(self, request):
        import json as _json

        from apps.farm.farms.models import Farm

        from .models import OutbreakAlert

        org = _get_org(request)
        farm_id = request.POST.get("farm", "").strip()
        disease_name = request.POST.get("disease_name", "").strip()
        description = request.POST.get("description", "").strip()
        severity = request.POST.get("severity", "warning")

        with set_tenant_context(org):
            farms = list(Farm.objects.filter(org=org, is_active=True))

        if not disease_name:
            return render(
                request,
                "health/_outbreak_report_form.html",
                {"farms": farms, "error": "Disease name is required."},
            )
        if not farm_id:
            return render(
                request,
                "health/_outbreak_report_form.html",
                {"farms": farms, "error": "Please select an affected farm."},
            )

        with set_tenant_context(org):
            farm = Farm.objects.filter(org=org, pk=farm_id).first()
            if not farm:
                return render(
                    request,
                    "health/_outbreak_report_form.html",
                    {"farms": farms, "error": "Selected farm not found."},
                )
            OutbreakAlert.objects.create(
                org=org,
                farm=farm,
                disease_name=disease_name,
                description=description,
                severity=severity,
                source="admin",
                is_active=True,
            )
            # Fire disease_outbreak notification through the standard pipeline.
            # NotificationService respects AlertRule channels (sms + in_app for
            # disease_outbreak) and routes delivery via the outbox worker.
            try:
                from apps.infrastructure.notifications.services import (
                    NotificationService,
                )
                NotificationService(org).send(
                    event_type="disease_outbreak",
                    context={"farm_name": farm.name},
                    severity=severity,
                )
            except Exception:
                logger.warning(
                    "outbreak.notification_failed",
                    org=str(org.id),
                    disease=disease_name,
                )

        response = HttpResponse(status=204)
        response["HX-Trigger"] = _json.dumps({
            "showToast": {
                "message": f"Outbreak reported: {disease_name}",
                "type": "success",
            },
            "close-modal": True,
        })
        return response


class OutbreakResolveView(TenantRequiredMixin, View):
    """POST /health/outbreaks/<uuid:pk>/resolve/ — Mark outbreak resolved."""

    def post(self, request, pk):
        import json as _json

        from django.utils import timezone

        from .models import OutbreakAlert

        org = _get_org(request)
        with set_tenant_context(org):
            alert = get_object_or_404(OutbreakAlert, pk=pk, org=org)
            alert.is_active = False
            alert.resolved_at = timezone.now()
            alert.save(update_fields=["is_active", "resolved_at"])

        response = HttpResponse(status=204)
        response["HX-Trigger"] = _json.dumps({
            "showToast": {
                "message": f"{alert.disease_name} marked resolved.",
                "type": "success",
            }
        })
        return response


class AddVaccinationView(TenantRequiredMixin, View):
    """GET+POST /health/vaccinations/add/ — Manual vaccination schedule creation."""

    def get(self, request):
        from apps.farm.flocks.models import Batch

        org = _get_org(request)
        with set_tenant_context(org):
            batches = list(Batch.objects.filter(status="active").select_related("farm"))
        return render(request, "health/_add_vaccination_form.html", {"batches": batches})

    def post(self, request):
        from datetime import datetime

        from apps.farm.flocks.models import Batch

        from .models import VaccinationSchedule

        org = _get_org(request)
        batch_id = request.POST.get("batch_id")
        vaccine_name = request.POST.get("vaccine_name", "").strip()
        due_date_str = request.POST.get("due_date")
        route = request.POST.get("route", "oral")
        notes = request.POST.get("notes", "").strip()

        if not all([batch_id, vaccine_name, due_date_str]):
            with set_tenant_context(org):
                batches = list(Batch.objects.filter(status="active").select_related("farm"))
            return render(
                request,
                "health/_add_vaccination_form.html",
                {"batches": batches, "error": "Batch, vaccine name, and due date are required."},
            )

        try:
            with set_tenant_context(org):
                batch = get_object_or_404(Batch, pk=batch_id, org=org)
                due_date = datetime.strptime(due_date_str, "%Y-%m-%d").date()
                VaccinationSchedule.objects.create(
                    org=org,
                    batch=batch,
                    farm=batch.farm,
                    vaccine_name=vaccine_name,
                    due_date=due_date,
                    route=route,
                    notes=notes,
                    status="scheduled",
                )
        except Exception as exc:
            logger.warning("add_vaccination_failed", error=str(exc))
            with set_tenant_context(org):
                batches = list(Batch.objects.filter(status="active").select_related("farm"))
            return render(
                request,
                "health/_add_vaccination_form.html",
                {"batches": batches, "error": str(exc)},
            )

        response = HttpResponse()
        response["HX-Trigger"] = json.dumps(
            {
                "showToast": {
                    "message": f"{vaccine_name} scheduled for {due_date_str}",
                    "type": "success",
                },
                "close-modal": True,
            }
        )
        response["HX-Refresh"] = "true"
        return response


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


# ── Health Dashboard ─────────────────────────────────────────────────────────

NIGERIAN_STATES = [
    'Abia', 'Adamawa', 'Akwa Ibom', 'Anambra', 'Bauchi',
    'Bayelsa', 'Benue', 'Borno', 'Cross River', 'Delta',
    'Ebonyi', 'Edo', 'Ekiti', 'Enugu', 'FCT', 'Abuja',
    'Gombe', 'Imo', 'Jigawa', 'Kaduna', 'Kano', 'Katsina',
    'Kebbi', 'Kogi', 'Kwara', 'Lagos', 'Nasarawa', 'Niger',
    'Ogun', 'Ondo', 'Osun', 'Oyo', 'Plateau', 'Rivers',
    'Sokoto', 'Taraba', 'Yobe', 'Zamfara',
]


def extract_state(location_str: str) -> str:
    """Extract Nigerian state name from free-text location."""
    if not location_str:
        return 'Unknown'
    loc_upper = location_str.upper()
    for state in NIGERIAN_STATES:
        if state.upper() in loc_upper:
            return state
    parts = location_str.replace(',', ' ').split()
    if parts:
        last = parts[-1].strip()
        if last.lower() in ['state', 'nigeria']:
            last = parts[-2].strip() if len(parts) > 1 else ''
        for state in NIGERIAN_STATES:
            if state.lower() == last.lower():
                return state
    return location_str.split(',')[0].strip() if location_str else 'Unknown'


def generate_health_advice(org, biosecurity_score, compliance_pct,
                           active_alerts, overdue_vaccs, today):
    """Generate rule-based health advisory cards from farm metrics."""
    advice = []

    if biosecurity_score < 70:
        advice.append({
            'severity': 'critical',
            'title': 'Low Biosecurity Score',
            'text': (f'Your biosecurity score is {biosecurity_score}%. '
                     f'Immediately review vaccination schedules and '
                     f'ensure all batches are up to date.'),
            'action': 'View Vaccinations',
            'action_url': '/health/vaccinations/',
        })
    elif biosecurity_score < 85:
        advice.append({
            'severity': 'warning',
            'title': 'Biosecurity Needs Attention',
            'text': (f'Score is {biosecurity_score}%. '
                     f'Schedule overdue vaccinations within 48 hours '
                     f'to prevent disease exposure.'),
            'action': 'View Overdue',
            'action_url': '/health/vaccinations/?status=overdue',
        })

    if active_alerts > 0:
        label = f'{active_alerts} Unread Health Alert{"s" if active_alerts > 1 else ""}'
        advice.append({
            'severity': 'critical',
            'title': label,
            'text': ('You have unread critical or warning alerts. '
                     'Review immediately to prevent flock losses.'),
            'action': 'View Alerts',
            'action_url': '/notifications/',
        })

    overdue_count = len(list(overdue_vaccs))
    if overdue_count > 0:
        label = f'{overdue_count} Overdue Vaccination{"s" if overdue_count > 1 else ""}'
        advice.append({
            'severity': 'warning',
            'title': label,
            'text': (f'Delayed vaccinations increase disease risk by 10-20%. '
                     f'Administer immediately and log in the system.'),
            'action': 'Schedule Now',
            'action_url': '/health/vaccinations/?status=overdue',
        })

    if not advice:
        advice.append({
            'severity': 'good',
            'title': 'Farm Health is Optimal',
            'text': (f'All vaccinations are on schedule and no critical '
                     f'alerts are active. Biosecurity score: '
                     f'{biosecurity_score}%. Keep it up!'),
            'action': None,
            'action_url': None,
        })

    return advice


class HealthDashboardView(TenantRequiredMixin, View):
    """GET /health/ — Health Command Center."""

    def get(self, request):
        from django.db.models import Sum

        from apps.farm.farms.models import Farm
        from apps.farm.flocks.models import Batch, MortalityLog
        from apps.infrastructure.notifications.models import NotificationLog

        from .models import (
            MedicationRecord,
            OutbreakAlert,
            SymptomLog,
            VaccinationSchedule,
        )

        org = _get_org(request)
        today = date.today()
        last_30 = today - timedelta(days=30)

        with set_tenant_context(org):
            # ── METRIC CARDS ──────────────────────────────────────
            active_alerts = NotificationLog.objects.filter(
                org=org,
                severity__in=['critical', 'warning'],
                is_read=False,
            ).count()

            total_vacc = VaccinationSchedule.objects.filter(
                batch__status='active').count()
            completed_vacc = VaccinationSchedule.objects.filter(
                batch__status='active',
                status='completed').count()
            biosecurity_score = round(
                completed_vacc / max(total_vacc, 1) * 100)

            active_batches = Batch.objects.filter(status='active')
            total_batches = active_batches.count()
            batches_with_overdue = VaccinationSchedule.objects.filter(
                batch__status='active',
                status='scheduled',
                due_date__lt=today,
            ).values('batch').distinct().count()
            compliance_pct = round(
                (total_batches - batches_with_overdue) /
                max(total_batches, 1) * 100)

            # ── DISEASE ALERT FEED ────────────────────────────────
            disease_alerts = list(
                NotificationLog.objects.filter(
                    org=org,
                    event_type__in=[
                        'disease_outbreak', 'mortality_spike',
                        'vaccination_overdue', 'ai_anomaly',
                    ],
                ).order_by('-created_at')[:10]
            )

            # ── SYMPTOM OBSERVATION LOG ───────────────────────────
            symptom_logs = list(
                SymptomLog.objects.filter(
                    org=org,
                ).select_related(
                    'batch__farm', 'recorded_by'
                ).order_by('-record_date')[:8]
            )

            # ── OUTBREAK ALERTS ───────────────────────────────────
            outbreak_alerts = list(
                OutbreakAlert.objects.filter(
                    org=org,
                    is_active=True,
                ).select_related('farm').order_by('-created_at')[:5]
            )

            # ── CLINICAL ACTION ITEMS ─────────────────────────────
            overdue_vaccs = list(
                VaccinationSchedule.objects.filter(
                    batch__status='active',
                    status='scheduled',
                    due_date__lt=today,
                ).select_related('batch__farm')[:3]
            )

            active_meds = list(
                MedicationRecord.objects.filter(
                    org=org,
                    batch__status='active',
                    withdrawal_cleared_date__gte=today,
                ).select_related('batch__farm')[:3]
            )

            # ── REGIONAL RISK MAP ─────────────────────────────────
            farms = list(Farm.objects.filter(
                org=org, is_active=True,
            ).values('name', 'location', 'pk'))

            state_risk = {}
            for farm in farms:
                loc = farm['location'] or ''
                state = extract_state(loc)
                if state not in state_risk:
                    state_risk[state] = {
                        'state': state,
                        'farm_count': 0,
                        'total_mortality': 0,
                        'live_birds': 0,
                    }
                state_risk[state]['farm_count'] += 1

            for batch in active_batches.select_related('farm'):
                state = extract_state(batch.farm.location or '')
                if state in state_risk:
                    state_risk[state]['live_birds'] += (
                        batch.current_count or 0)

            mort_data = MortalityLog.objects.filter(
                org=org,
                date__gte=last_30,
            ).values('farm__location').annotate(total=Sum('count'))

            for row in mort_data:
                state = extract_state(row['farm__location'] or '')
                if state in state_risk:
                    state_risk[state]['total_mortality'] += (
                        row['total'] or 0)

            outbreak_states = {
                extract_state(a.farm.location or '')
                for a in outbreak_alerts
            }

            state_risk_list = []
            for state, data in state_risk.items():
                if data['live_birds'] > 0:
                    mort_rate = (
                        data['total_mortality'] /
                        data['live_birds'] * 100)
                else:
                    mort_rate = 0

                if mort_rate > 5 or state in outbreak_states:
                    risk = 'high'
                elif mort_rate > 2:
                    risk = 'moderate'
                else:
                    risk = 'low'

                state_risk_list.append({
                    'state': state or 'Unknown',
                    'risk': risk,
                    'farm_count': data['farm_count'],
                    'mort_rate': round(mort_rate, 1),
                })

            state_risk_list.sort(
                key=lambda x: {'high': 0, 'moderate': 1, 'low': 2}[x['risk']])

            # ── AI HEALTH ADVICE ──────────────────────────────────
            ai_advice = generate_health_advice(
                org, biosecurity_score, compliance_pct,
                active_alerts, overdue_vaccs, today)

        context = {
            'active_alerts': active_alerts,
            'biosecurity_score': biosecurity_score,
            'compliance_pct': compliance_pct,
            'disease_alerts': disease_alerts,
            'symptom_logs': symptom_logs,
            'outbreak_alerts': outbreak_alerts,
            'overdue_vaccs': overdue_vaccs,
            'active_meds': active_meds,
            'state_risk_list': state_risk_list,
            'ai_advice': ai_advice,
            'today': today,
        }
        return render(request, 'health/health_dashboard.html', context)


# ── DRF API ───────────────────────────────────────────────────────────────────


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
