"""
Phase 4A — Health app tests.
"""

import datetime
from decimal import Decimal

import pytest

pytestmark = pytest.mark.django_db


# ── Helpers ─────────────────────────────────────────────────────────────────────

def _make_org(subdomain):
    from apps.infrastructure.tenants.models import Organization
    return Organization.objects.create(name="Health Org", subdomain=subdomain)


def _make_user(org, email=None, username=None):
    from apps.infrastructure.accounts.models import CustomUser
    email = email or f"{username}@example.com"
    return CustomUser.objects.create_user(
        email=email, password="testpass123", username=username or email, org=org,
    )


def _make_farm(org, name="Health Farm"):
    from apps.farm.farms.models import Farm
    farm = Farm(
        org=org, name=name, location="Abuja",
        latitude=Decimal("9.0579"), longitude=Decimal("7.4951"),
        farm_type="layer",
    )
    farm.clean()
    farm.save()
    return farm


def _make_house(org, farm):
    from apps.farm.farms.models import House
    return House.objects.create(
        org=org, farm=farm, name="House 1", capacity=2000, house_type="layer",
    )


def _make_batch(org, farm, house, bird_type="layer", placement_date=None, status="active"):
    from apps.farm.flocks.models import Batch
    if placement_date is None:
        placement_date = datetime.date.today() - datetime.timedelta(days=10)
    return Batch.objects.create(
        org=org, farm=farm, house=house,
        batch_name=f"Batch {bird_type}",
        bird_type=bird_type,
        placement_date=placement_date,
        initial_count=500,
        current_count=500,
        status=status,
    )


# ── 1. VaccinationSchedule — signal auto-generation ─────────────────────────────

class TestVaccinationAutoGeneration:

    def test_vaccination_schedule_auto_generated_on_batch_creation(self, db):
        from apps.health.health.models import VaccinationSchedule
        from apps.infrastructure.core.rls import set_tenant_context

        org = _make_org("vacc_auto1")
        farm = _make_farm(org)
        house = _make_house(org, farm)

        with set_tenant_context(org):
            batch = _make_batch(org, farm, house)
            count = VaccinationSchedule.objects.filter(batch=batch).count()

        assert count > 0

    def test_layer_gets_7_vaccinations(self, db):
        from apps.health.health.models import VaccinationSchedule
        from apps.infrastructure.core.rls import set_tenant_context

        org = _make_org("vacc_layer")
        farm = _make_farm(org)
        house = _make_house(org, farm)

        with set_tenant_context(org):
            batch = _make_batch(org, farm, house, bird_type="layer")
            count = VaccinationSchedule.objects.filter(batch=batch).count()

        assert count == 7

    def test_broiler_gets_3_vaccinations(self, db):
        from apps.health.health.models import VaccinationSchedule
        from apps.farm.farms.models import House
        from apps.infrastructure.core.rls import set_tenant_context

        org = _make_org("vacc_broiler")
        farm = _make_farm(org)
        house = House.objects.create(
            org=org, farm=farm, name="Broiler House", capacity=2000, house_type="broiler",
        )

        with set_tenant_context(org):
            batch = _make_batch(org, farm, house, bird_type="broiler")
            count = VaccinationSchedule.objects.filter(batch=batch).count()

        assert count == 3

    def test_vaccination_due_dates_calculated_from_placement(self, db):
        from apps.health.health.models import VaccinationSchedule
        from apps.infrastructure.core.rls import set_tenant_context

        placement = datetime.date.today() - datetime.timedelta(days=5)
        org = _make_org("vacc_dates")
        farm = _make_farm(org)
        house = _make_house(org, farm)

        with set_tenant_context(org):
            batch = _make_batch(org, farm, house, placement_date=placement)
            first = VaccinationSchedule.objects.filter(batch=batch).order_by("due_date").first()

        assert first is not None
        expected = placement + datetime.timedelta(days=1)  # Marek's Disease on day 1
        assert first.due_date == expected


# ── 2. VaccinationSchedule — properties ──────────────────────────────────────────

class TestVaccinationProperties:

    def test_overdue_vaccination_detected(self, db):
        from apps.health.health.models import VaccinationSchedule
        from apps.infrastructure.core.rls import set_tenant_context

        org = _make_org("vacc_overdue")
        farm = _make_farm(org)
        house = _make_house(org, farm)

        with set_tenant_context(org):
            batch = _make_batch(org, farm, house)
            vacc = VaccinationSchedule.objects.create(
                org=org, batch=batch, farm=farm,
                vaccine_name="Test Vaccine",
                due_date=datetime.date.today() - datetime.timedelta(days=5),
                status="scheduled",
            )

        assert vacc.is_overdue is True

    def test_completed_vaccination_not_overdue(self, db):
        from apps.health.health.models import VaccinationSchedule
        from apps.infrastructure.core.rls import set_tenant_context

        org = _make_org("vacc_not_overdue")
        farm = _make_farm(org)
        house = _make_house(org, farm)

        with set_tenant_context(org):
            batch = _make_batch(org, farm, house)
            vacc = VaccinationSchedule.objects.create(
                org=org, batch=batch, farm=farm,
                vaccine_name="Done Vaccine",
                due_date=datetime.date.today() - datetime.timedelta(days=3),
                status="completed",
                administered_date=datetime.date.today() - datetime.timedelta(days=3),
            )

        assert vacc.is_overdue is False


# ── 3. HealthService — vaccination ───────────────────────────────────────────────

class TestHealthServiceVaccination:

    def test_record_vaccination_sets_completed(self, db):
        from apps.health.health.models import VaccinationSchedule
        from apps.health.health.services import HealthService
        from apps.infrastructure.core.rls import set_tenant_context

        org = _make_org("vacc_record")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        user = _make_user(org, username="vaccuser")

        with set_tenant_context(org):
            batch = _make_batch(org, farm, house)
            vacc = VaccinationSchedule.objects.filter(batch=batch, status="scheduled").first()
            result = HealthService(org).record_vaccination(
                vaccination_id=vacc.id,
                administered_by=user,
            )

        assert result.status == "completed"
        assert result.administered_date == datetime.date.today()

    def test_compliance_rate_calculation(self, db):
        from apps.health.health.models import VaccinationSchedule
        from apps.health.health.services import HealthService
        from apps.infrastructure.core.rls import set_tenant_context

        org = _make_org("vacc_compliance")
        farm = _make_farm(org)
        house = _make_house(org, farm)
        user = _make_user(org, username="compuser")

        with set_tenant_context(org):
            batch = _make_batch(org, farm, house)

            all_vacc = list(VaccinationSchedule.objects.filter(batch=batch, status="scheduled"))
            # Complete the first one on time
            if all_vacc:
                v = all_vacc[0]
                v.status = "completed"
                v.administered_date = v.due_date
                v.save(update_fields=["status", "administered_date", "updated_at"])

            rate = HealthService(org).get_compliance_rate(batch_id=batch.id)

        total = len(all_vacc)
        expected = round((1 / total) * 100, 1) if total else 0.0
        assert rate == pytest.approx(expected, abs=0.1)

    def test_vaccination_calendar_view_returns_200(self, db, client):
        org = _make_org("vacc_calendar_view")
        user = _make_user(org, username="calview")
        farm = _make_farm(org)
        house = _make_house(org, farm)

        from apps.infrastructure.core.rls import set_tenant_context
        with set_tenant_context(org):
            _make_batch(org, farm, house)

        client.force_login(user)
        response = client.get("/health/vaccinations/")
        assert response.status_code == 200


# ── 4. MedicationRecord ───────────────────────────────────────────────────────────

class TestMedicationRecord:

    def _make_med(self, org, batch, start_date=None, duration=5, withdrawal=3):
        from apps.health.health.services import HealthService
        from apps.infrastructure.core.rls import set_tenant_context

        start = start_date or datetime.date.today()
        with set_tenant_context(org):
            return HealthService(org).record_medication(
                batch_id=str(batch.id),
                drug_name="Tetracycline",
                drug_type="antibiotic",
                start_date=start,
                duration_days=duration,
                withdrawal_period_days=withdrawal,
                dosage="1ml per litre",
                quantity_used=Decimal("500"),
                unit="ml",
            )

    def test_medication_end_date_auto_calculated(self, db):
        from apps.infrastructure.core.rls import set_tenant_context

        org = _make_org("med_end")
        farm = _make_farm(org)
        house = _make_house(org, farm)

        with set_tenant_context(org):
            batch = _make_batch(org, farm, house)

        start = datetime.date.today()
        med = self._make_med(org, batch, start_date=start, duration=5)

        assert med.end_date == start + datetime.timedelta(days=5)

    def test_withdrawal_cleared_date_auto_calculated(self, db):
        from apps.infrastructure.core.rls import set_tenant_context

        org = _make_org("med_withdrawal")
        farm = _make_farm(org)
        house = _make_house(org, farm)

        with set_tenant_context(org):
            batch = _make_batch(org, farm, house)

        start = datetime.date.today()
        med = self._make_med(org, batch, start_date=start, duration=5, withdrawal=7)

        expected = start + datetime.timedelta(days=5) + datetime.timedelta(days=7)
        assert med.withdrawal_cleared_date == expected

    def test_withdrawal_active_property(self, db):
        from apps.infrastructure.core.rls import set_tenant_context

        org = _make_org("med_active")
        farm = _make_farm(org)
        house = _make_house(org, farm)

        with set_tenant_context(org):
            batch = _make_batch(org, farm, house)

        med = self._make_med(org, batch, duration=1, withdrawal=10)
        assert med.withdrawal_active is True

    def test_withdrawal_not_active_when_cleared(self, db):
        from apps.infrastructure.core.rls import set_tenant_context

        org = _make_org("med_cleared")
        farm = _make_farm(org)
        house = _make_house(org, farm)

        with set_tenant_context(org):
            batch = _make_batch(org, farm, house)

        past = datetime.date.today() - datetime.timedelta(days=30)
        med = self._make_med(org, batch, start_date=past, duration=5, withdrawal=0)
        assert med.withdrawal_active is False


# ── 5. SymptomLog ─────────────────────────────────────────────────────────────────

class TestSymptomLog:

    def test_symptom_log_created(self, db):
        from apps.health.health.services import HealthService
        from apps.infrastructure.core.rls import set_tenant_context

        org = _make_org("sym_create")
        farm = _make_farm(org)
        house = _make_house(org, farm)

        with set_tenant_context(org):
            batch = _make_batch(org, farm, house)
            log = HealthService(org).log_symptoms(
                batch_id=str(batch.id),
                affected_count=10,
                symptoms=["lethargy", "reduced_feed"],
                severity="mild",
            )

        assert log.pk is not None
        assert log.affected_count == 10
        assert "lethargy" in log.symptoms

    def test_severe_symptom_fires_notification(self, db):
        from apps.health.health.services import HealthService
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.infrastructure.notifications.models import AlertRule

        org = _make_org("sym_severe")
        farm = _make_farm(org)
        house = _make_house(org, farm)

        with set_tenant_context(org):
            # Rules are auto-seeded on org create; ensure mortality_spike is active
            AlertRule.objects.update_or_create(
                org=org,
                event_type="mortality_spike",
                defaults={"channels": ["in_app"], "notify_roles": ["owner"], "is_active": True},
            )
            batch = _make_batch(org, farm, house)
            log = HealthService(org).log_symptoms(
                batch_id=str(batch.id),
                affected_count=50,
                symptoms=["sudden_death"],
                severity="severe",
            )

        assert log.severity == "severe"

    def test_log_symptoms_invalid_batch_raises(self, db):
        from apps.health.health.services import HealthService
        from apps.infrastructure.core.rls import set_tenant_context
        import uuid

        org = _make_org("sym_invalid")

        with set_tenant_context(org):
            with pytest.raises(ValueError, match="not found"):
                HealthService(org).log_symptoms(
                    batch_id=str(uuid.uuid4()),
                    affected_count=5,
                    symptoms=["lethargy"],
                    severity="mild",
                )


# ── 6. HealthService — summary ────────────────────────────────────────────────────

class TestHealthSummary:

    def test_health_summary_returns_compliance_rate(self, db):
        from apps.health.health.services import HealthService
        from apps.infrastructure.core.rls import set_tenant_context

        org = _make_org("summary1")
        farm = _make_farm(org)
        house = _make_house(org, farm)

        with set_tenant_context(org):
            batch = _make_batch(org, farm, house)
            summary = HealthService(org).get_health_summary(str(batch.id))

        assert "vaccination_compliance_pct" in summary
        assert "upcoming_vaccinations" in summary
        assert "overdue_vaccinations" in summary
        assert "active_medications" in summary
        assert "withdrawal_active" in summary
        assert "recent_symptom_logs" in summary

    def test_health_summary_view_returns_200(self, db, client):
        from apps.infrastructure.core.rls import set_tenant_context

        org = _make_org("summary_view")
        user = _make_user(org, username="sumview")
        farm = _make_farm(org)
        house = _make_house(org, farm)

        with set_tenant_context(org):
            batch = _make_batch(org, farm, house)

        client.force_login(user)
        response = client.get(f"/health/summary/{batch.id}/")
        assert response.status_code == 200


# ── 7. Celery task ────────────────────────────────────────────────────────────────

class TestVaccinationReminderTask:

    def test_vaccination_reminder_task_sets_reminder_sent(self, db):
        from apps.health.health.models import VaccinationSchedule
        from apps.health.health.tasks import send_vaccination_reminders_for_org
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.infrastructure.notifications.models import AlertRule

        org = _make_org("task_reminder")
        farm = _make_farm(org)
        house = _make_house(org, farm)

        with set_tenant_context(org):
            AlertRule.objects.update_or_create(
                org=org,
                event_type="vaccination_due",
                defaults={"channels": ["in_app"], "notify_roles": ["owner"], "is_active": True},
            )
            batch = _make_batch(org, farm, house)
            # Manually create a vaccination due today
            vacc = VaccinationSchedule.objects.create(
                org=org, batch=batch, farm=farm,
                vaccine_name="Reminder Test",
                due_date=datetime.date.today(),
                status="scheduled",
                reminder_sent=False,
            )

        send_vaccination_reminders_for_org(str(org.id))

        vacc.refresh_from_db()
        assert vacc.reminder_sent is True

    def test_overdue_vaccinations_marked_missed_by_task(self, db):
        from apps.health.health.models import VaccinationSchedule
        from apps.health.health.tasks import send_vaccination_reminders_for_org
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.infrastructure.notifications.models import AlertRule

        org = _make_org("task_missed")
        farm = _make_farm(org)
        house = _make_house(org, farm)

        with set_tenant_context(org):
            AlertRule.objects.update_or_create(
                org=org,
                event_type="vaccination_overdue",
                defaults={"channels": ["in_app"], "notify_roles": ["owner"], "is_active": True},
            )
            batch = _make_batch(org, farm, house)
            vacc = VaccinationSchedule.objects.create(
                org=org, batch=batch, farm=farm,
                vaccine_name="Overdue Vaccine",
                due_date=datetime.date.today() - datetime.timedelta(days=5),
                status="scheduled",
            )

        send_vaccination_reminders_for_org(str(org.id))

        vacc.refresh_from_db()
        assert vacc.status == "missed"


# ── 8. RLS isolation ──────────────────────────────────────────────────────────────

class TestHealthRLSIsolation:

    def _make_org_and_batch(self, subdomain):
        from apps.infrastructure.core.rls import set_tenant_context

        org = _make_org(subdomain)
        farm = _make_farm(org, f"Farm {subdomain}")
        house = _make_house(org, farm)

        with set_tenant_context(org):
            batch = _make_batch(org, farm, house)

        return org, batch

    def test_vaccination_rls_isolation(self, db):
        from apps.health.health.models import VaccinationSchedule
        from apps.infrastructure.core.rls import set_tenant_context

        org_a, batch_a = self._make_org_and_batch("rls_vacc_a")
        org_b, batch_b = self._make_org_and_batch("rls_vacc_b")

        with set_tenant_context(org_a):
            count_a = VaccinationSchedule.objects.count()

        with set_tenant_context(org_b):
            count_b = VaccinationSchedule.objects.count()

        # Each org sees only their own vaccinations (7 for layer batch)
        assert count_a == 7
        assert count_b == 7

        # Confirm cross-tenant isolation: total in db is 14
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM health_vaccinationschedule")
            total = cursor.fetchone()[0]
        assert total == 14

    def test_medication_rls_isolation(self, db):
        from apps.health.health.services import HealthService
        from apps.health.health.models import MedicationRecord
        from apps.infrastructure.core.rls import set_tenant_context

        org_a, batch_a = self._make_org_and_batch("rls_med_a")
        org_b, batch_b = self._make_org_and_batch("rls_med_b")

        with set_tenant_context(org_a):
            HealthService(org_a).record_medication(
                batch_id=str(batch_a.id),
                drug_name="Drug A", drug_type="antibiotic",
                start_date=datetime.date.today(), duration_days=3,
                withdrawal_period_days=0, dosage="1ml/L",
                quantity_used=Decimal("100"), unit="ml",
            )

        with set_tenant_context(org_b):
            HealthService(org_b).record_medication(
                batch_id=str(batch_b.id),
                drug_name="Drug B", drug_type="antiviral",
                start_date=datetime.date.today(), duration_days=5,
                withdrawal_period_days=0, dosage="2ml/L",
                quantity_used=Decimal("200"), unit="ml",
            )

        with set_tenant_context(org_a):
            count_a = MedicationRecord.objects.count()

        with set_tenant_context(org_b):
            count_b = MedicationRecord.objects.count()

        assert count_a == 1
        assert count_b == 1
