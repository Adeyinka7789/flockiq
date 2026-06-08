"""
Farm-operation journeys: vaccination auto-scheduling on batch placement,
mortality logging decrementing the live count, batch-level RLS isolation, and
the baseline learning loop on batch close.
"""
import datetime

import pytest

from apps.infrastructure.core.rls import set_tenant_context


@pytest.mark.django_db(transaction=True)
class TestFarmOperationJourney:

    def test_batch_creation_generates_vaccinations(self, make_org, make_farm):
        org, user = make_org(subdomain='vacctest')
        farm, house, batch = make_farm(org)

        # health.signals.on_batch_created_generate_vaccinations seeds the schedule.
        from apps.health.health.models import VaccinationSchedule
        with set_tenant_context(org):
            count = VaccinationSchedule.objects.filter(batch=batch).count()
        assert count > 0

    def test_mortality_log_updates_batch_count(self, tenant_client, make_farm):
        client, org, user = tenant_client
        farm, house, batch = make_farm(org)
        initial_count = batch.current_count

        # Mortality is logged via the batch-scoped HTMX endpoint; the batch id
        # is part of the URL, not a POST field.
        response = client.post(
            f'/batches/{batch.id}/mortality/',
            {
                'count': 5,
                'cause': 'disease',
                'date': datetime.date.today().isoformat(),
            },
        )
        assert response.status_code == 200

        with set_tenant_context(org):
            batch.refresh_from_db()
        assert batch.current_count == initial_count - 5

    def test_rls_batch_isolation(self, make_org, make_farm):
        org_a, _ = make_org(subdomain='rlsa')
        org_b, _ = make_org(subdomain='rlsb')
        farm_a, house_a, batch_a = make_farm(org_a)
        farm_b, house_b, batch_b = make_farm(org_b)

        from apps.farm.flocks.models import Batch
        with set_tenant_context(org_a):
            batches = list(Batch.objects.values_list('id', flat=True))
        assert batch_a.id in batches
        assert batch_b.id not in batches

    def test_batch_close_triggers_baseline_recompute(self, make_org, make_farm):
        org, user = make_org(subdomain='baselinetest')
        farm, house, batch = make_farm(org)

        # The baseline learning loop lives in BatchService.close_batch (not in a
        # signal), so close the batch through the service.
        from apps.farm.flocks.services import BatchService
        with set_tenant_context(org):
            BatchService(org).close_batch(str(batch.id))

        from apps.health.analytics.models import FarmBaseline
        with set_tenant_context(org):
            baseline = FarmBaseline.objects.filter(
                org=org,
                bird_type='broiler',
            ).first()
        assert baseline is not None
        assert baseline.batch_count >= 1
