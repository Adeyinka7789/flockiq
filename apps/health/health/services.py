import datetime

import structlog

from apps.infrastructure.core.services import BaseService

logger = structlog.get_logger(__name__)


class HealthService(BaseService):

    def get_vaccination_calendar(self, days_ahead: int = 30) -> list:
        from .models import VaccinationSchedule

        today = datetime.date.today()
        cutoff = today + datetime.timedelta(days=days_ahead)

        upcoming = VaccinationSchedule.objects.filter(
            status="scheduled",
            due_date__lte=cutoff,
        ).select_related("batch", "farm").order_by("due_date")

        return list(upcoming)

    def record_vaccination(
        self,
        vaccination_id,
        administered_by,
        administered_date=None,
        notes="",
    ):
        from .models import VaccinationSchedule
        from apps.farm.flocks.models import Batch

        try:
            vacc = VaccinationSchedule.objects.get(id=vaccination_id, org=self.org)
        except VaccinationSchedule.DoesNotExist:
            raise ValueError(f"VaccinationSchedule {vaccination_id} not found.")

        batch = Batch.objects.unscoped().filter(id=vacc.batch_id).first()
        if batch and batch.status != "active":
            raise ValueError("Cannot record vaccination for an inactive batch.")

        with self.atomic():
            vacc.status = "completed"
            vacc.administered_date = administered_date or datetime.date.today()
            vacc.administered_by = administered_by
            if notes:
                vacc.notes = notes
            vacc.save(update_fields=["status", "administered_date", "administered_by", "notes", "updated_at"])

        self.logger.info("health.vaccination_recorded", vaccination_id=str(vaccination_id))
        return vacc

    def get_compliance_rate(self, batch_id=None) -> float:
        from .models import VaccinationSchedule

        qs = VaccinationSchedule.objects.filter(org=self.org)
        if batch_id:
            qs = qs.filter(batch_id=batch_id)

        scheduled = qs.exclude(status="skipped")
        total = scheduled.count()
        if total == 0:
            return 0.0

        # Completed on time = within 3 days of due_date
        on_time = 0
        for v in scheduled.filter(status="completed").only("due_date", "administered_date"):
            if v.administered_date and abs((v.administered_date - v.due_date).days) <= 3:
                on_time += 1

        return round((on_time / total) * 100, 1)

    def record_medication(
        self,
        batch_id,
        drug_name,
        drug_type,
        start_date,
        duration_days,
        withdrawal_period_days,
        dosage,
        quantity_used,
        unit,
        cost=0,
        vet_name="",
        reason="reactive",
        notes="",
    ):
        from .models import MedicationRecord
        from apps.farm.flocks.models import Batch

        try:
            batch = Batch.objects.get(id=batch_id, org=self.org)
        except Batch.DoesNotExist:
            raise ValueError(f"Batch {batch_id} not found.")

        with self.atomic():
            record = MedicationRecord.objects.create(
                org=self.org,
                batch=batch,
                farm=batch.farm,
                drug_name=drug_name,
                drug_type=drug_type,
                start_date=start_date,
                duration_days=duration_days,
                withdrawal_period_days=withdrawal_period_days,
                dosage=dosage,
                quantity_used=quantity_used,
                unit=unit,
                cost=cost,
                vet_name=vet_name,
                reason=reason,
                notes=notes,
            )

        self.logger.info(
            "health.medication_recorded",
            record_id=str(record.id),
            batch_id=str(batch_id),
        )
        return record

    def log_symptoms(
        self,
        batch_id,
        affected_count,
        symptoms,
        severity,
        treatment_notes="",
        recorded_by=None,
    ):
        from .models import SymptomLog
        from apps.farm.flocks.models import Batch

        try:
            batch = Batch.objects.get(id=batch_id, org=self.org)
        except Batch.DoesNotExist:
            raise ValueError(f"Batch {batch_id} not found.")

        with self.atomic():
            log = SymptomLog.objects.create(
                org=self.org,
                batch=batch,
                farm=batch.farm,
                affected_count=affected_count,
                symptoms=symptoms,
                severity=severity,
                treatment_notes=treatment_notes,
                recorded_by=recorded_by,
            )

            if severity == "severe":
                try:
                    from apps.infrastructure.notifications.services import NotificationService
                    NotificationService(self.org).send(
                        "mortality_spike",
                        context={
                            "farm_name": str(batch.farm),
                            "batch_name": str(batch),
                            "count": affected_count,
                            "normal": "",
                        },
                        farm=batch.farm,
                        batch=batch,
                    )
                except Exception:
                    logger.exception(
                        "health.severe_symptom_notification_failed",
                        log_id=str(log.id),
                    )

        self.logger.info(
            "health.symptom_logged",
            log_id=str(log.id),
            batch_id=str(batch_id),
            severity=severity,
        )
        return log

    def get_health_summary(self, batch_id) -> dict:
        from .models import VaccinationSchedule, MedicationRecord, SymptomLog

        today = datetime.date.today()
        cutoff_30 = today - datetime.timedelta(days=30)

        upcoming = list(
            VaccinationSchedule.objects.filter(
                batch_id=batch_id,
                status="scheduled",
                due_date__gte=today,
            ).order_by("due_date")[:5]
        )

        overdue = list(
            VaccinationSchedule.objects.filter(
                batch_id=batch_id,
                status="scheduled",
                due_date__lt=today,
            ).order_by("due_date")
        )

        active_medications = list(
            MedicationRecord.objects.filter(
                batch_id=batch_id,
                start_date__lte=today,
                end_date__gte=today,
            )
        )

        withdrawal_active = any(m.withdrawal_active for m in active_medications)

        recent_logs = list(
            SymptomLog.objects.filter(
                batch_id=batch_id,
                record_date__gte=cutoff_30,
            ).order_by("-record_date")[:5]
        )

        compliance = self.get_compliance_rate(batch_id=batch_id)

        return {
            "vaccination_compliance_pct": compliance,
            "upcoming_vaccinations": upcoming,
            "overdue_vaccinations": overdue,
            "active_medications": active_medications,
            "withdrawal_active": withdrawal_active,
            "recent_symptom_logs": recent_logs,
        }
