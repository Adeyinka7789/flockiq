"""
Phase 2B — Flocks app tests.

Coverage:
- Batch model: creation, validation, properties
- MortalityLog: decrement signal, validation, closed-batch guard
- StockReconciliation: flag logic
- WeightRecord: broiler-only guard
- BatchService: create_batch, close_batch, log_mortality, log_weight
- RLS isolation
- HTMX views
"""

import datetime
from decimal import Decimal

import pytest

pytestmark = pytest.mark.django_db


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_org(subdomain="testflock"):
    from apps.infrastructure.tenants.models import Organization
    return Organization.objects.create(name="Test Flock Org", subdomain=subdomain)


def _make_farm(org, name="Flock Farm"):
    from apps.farm.farms.models import Farm
    farm = Farm(
        org=org, name=name, location="Lagos",
        latitude=Decimal("6.5244"), longitude=Decimal("3.3792"),
        farm_type="broiler",
    )
    farm.clean()
    farm.save()
    return farm


def _make_house(org, farm, capacity=5000, name="House A"):
    from apps.farm.farms.models import House
    return House.objects.create(
        org=org, farm=farm, name=name, capacity=capacity, house_type="broiler"
    )


def _make_batch(org, farm, house, bird_type="broiler", initial_count=1000, status="active"):
    from apps.farm.flocks.models import Batch
    return Batch.objects.create(
        org=org,
        farm=farm,
        house=house,
        batch_name=f"Test Batch {bird_type}",
        bird_type=bird_type,
        placement_date=datetime.date.today() - datetime.timedelta(days=21),
        initial_count=initial_count,
        current_count=initial_count,
        status=status,
    )


# ── 1. test_batch_created_with_correct_initial_count ──────────────────────────

class TestBatchCreation:

    def test_batch_created_with_correct_initial_count(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        org = _make_org("batchcreate")
        farm = _make_farm(org)
        house = _make_house(org, farm)

        with set_tenant_context(org):
            from apps.farm.flocks.services import BatchService
            batch = BatchService(org).create_batch(
                farm_id=str(farm.id),
                house_id=str(house.id),
                batch_name="Cycle A",
                bird_type="broiler",
                placement_date=datetime.date.today(),
                initial_count=4000,
            )

        assert batch.initial_count == 4000
        assert batch.current_count == 4000
        assert batch.status == "active"
        assert batch.org == org

    def test_batch_rejects_count_exceeding_house_capacity(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.farm.flocks.exceptions import HouseCapacityExceededError
        org = _make_org("batchcapacity")
        farm = _make_farm(org)
        house = _make_house(org, farm, capacity=2000)

        with set_tenant_context(org):
            with pytest.raises(HouseCapacityExceededError):
                from apps.farm.flocks.services import BatchService
                BatchService(org).create_batch(
                    farm_id=str(farm.id),
                    house_id=str(house.id),
                    batch_name="Too Many",
                    bird_type="broiler",
                    placement_date=datetime.date.today(),
                    initial_count=3000,
                )

    def test_batch_rejects_duplicate_active_batch_in_house(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.farm.flocks.exceptions import HouseOccupiedError
        org = _make_org("batchduplicate")
        farm = _make_farm(org)
        house = _make_house(org, farm)

        with set_tenant_context(org):
            from apps.farm.flocks.services import BatchService
            svc = BatchService(org)
            svc.create_batch(
                farm_id=str(farm.id),
                house_id=str(house.id),
                batch_name="First Batch",
                bird_type="broiler",
                placement_date=datetime.date.today(),
                initial_count=500,
            )
            with pytest.raises(HouseOccupiedError):
                svc.create_batch(
                    farm_id=str(farm.id),
                    house_id=str(house.id),
                    batch_name="Second Batch",
                    bird_type="broiler",
                    placement_date=datetime.date.today(),
                    initial_count=500,
                )


# ── 2. MortalityLog tests ─────────────────────────────────────────────────────

class TestMortalityLog:

    def test_mortality_log_decrements_current_count(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        org = _make_org("mortdecrement")
        farm = _make_farm(org)
        house = _make_house(org, farm)

        with set_tenant_context(org):
            batch = _make_batch(org, farm, house, initial_count=1000)
            from apps.farm.flocks.services import BatchService
            BatchService(org).log_mortality(
                batch_id=str(batch.id), count=50, cause="disease"
            )
            batch.refresh_from_db()

        assert batch.current_count == 950

    def test_mortality_cannot_exceed_current_count(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.farm.flocks.exceptions import MortalityExceedsLiveBirdsError
        org = _make_org("mortexceed")
        farm = _make_farm(org)
        house = _make_house(org, farm)

        with set_tenant_context(org):
            batch = _make_batch(org, farm, house, initial_count=100)
            with pytest.raises(MortalityExceedsLiveBirdsError):
                from apps.farm.flocks.services import BatchService
                BatchService(org).log_mortality(
                    batch_id=str(batch.id), count=200
                )

    def test_mortality_on_closed_batch_raises_error(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.farm.flocks.exceptions import BatchClosedError
        org = _make_org("mortclosed")
        farm = _make_farm(org)
        house = _make_house(org, farm)

        with set_tenant_context(org):
            batch = _make_batch(org, farm, house, status="closed")
            with pytest.raises(BatchClosedError):
                from apps.farm.flocks.services import BatchService
                BatchService(org).log_mortality(
                    batch_id=str(batch.id), count=10
                )


# ── 3. Batch property tests ───────────────────────────────────────────────────

class TestBatchProperties:

    def test_cycle_day_property(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        org = _make_org("cycleday")
        farm = _make_farm(org)
        house = _make_house(org, farm)

        with set_tenant_context(org):
            batch = _make_batch(org, farm, house)

        expected_days = (datetime.date.today() - batch.placement_date).days
        assert batch.cycle_day == expected_days
        assert batch.cycle_day == 21

    def test_mortality_rate_pct_property(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        org = _make_org("mortrate")
        farm = _make_farm(org)
        house = _make_house(org, farm)

        with set_tenant_context(org):
            from apps.farm.flocks.models import Batch
            batch = Batch.objects.create(
                org=org,
                farm=farm,
                house=house,
                batch_name="Rate Test",
                bird_type="broiler",
                placement_date=datetime.date.today(),
                initial_count=200,
                current_count=180,
                status="active",
            )

        # (200 - 180) / 200 * 100 = 10.0%
        assert batch.mortality_rate_pct == pytest.approx(10.0, abs=0.01)
        assert batch.mortality_to_date == 20


# ── 4. StockReconciliation tests ──────────────────────────────────────────────

class TestStockReconciliation:

    def test_reconciliation_flags_variance_above_1_5_pct(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        org = _make_org("reconcflag")
        farm = _make_farm(org)
        house = _make_house(org, farm)

        with set_tenant_context(org):
            from apps.farm.flocks.models import Batch
            # Simulate 20 unexplained missing birds on a 1000-bird batch (2%)
            batch = Batch.objects.create(
                org=org, farm=farm, house=house,
                batch_name="Flag Test",
                bird_type="broiler",
                placement_date=datetime.date.today() - datetime.timedelta(days=30),
                initial_count=1000,
                current_count=980,  # 20 missing — variance 2% > 1.5% threshold
                status="active",
            )
            from apps.farm.flocks.services import BatchService
            recon = BatchService(org)._run_reconciliation(batch)

        assert recon.is_flagged is True
        assert float(recon.variance_pct) > 1.5

    def test_reconciliation_clean_when_within_threshold(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        org = _make_org("reconcclean")
        farm = _make_farm(org)
        house = _make_house(org, farm)

        with set_tenant_context(org):
            from apps.farm.flocks.models import Batch
            # initial=1000, current=1000 → no mortality logged → variance=0
            batch = Batch.objects.create(
                org=org, farm=farm, house=house,
                batch_name="Clean Test",
                bird_type="broiler",
                placement_date=datetime.date.today() - datetime.timedelta(days=30),
                initial_count=1000,
                current_count=1000,
                status="active",
            )
            from apps.farm.flocks.services import BatchService
            recon = BatchService(org)._run_reconciliation(batch)

        assert recon.is_flagged is False
        assert recon.variance == 0

    def test_batch_close_triggers_reconciliation(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.farm.flocks.models import StockReconciliation
        org = _make_org("closerecon")
        farm = _make_farm(org)
        house = _make_house(org, farm)

        with set_tenant_context(org):
            batch = _make_batch(org, farm, house, initial_count=500)
            from apps.farm.flocks.services import BatchService
            BatchService(org).close_batch(batch_id=str(batch.id))
            recon_count = StockReconciliation.objects.filter(batch=batch).count()

        assert recon_count == 1
        batch.refresh_from_db()
        assert batch.status == "closed"
        assert batch.closed_at is not None


# ── 5. WeightRecord tests ─────────────────────────────────────────────────────

class TestWeightRecord:

    def test_weight_record_only_for_broiler(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        org = _make_org("weightbroiler")
        farm = _make_farm(org)
        house = _make_house(org, farm)

        with set_tenant_context(org):
            layer_batch = _make_batch(org, farm, house, bird_type="layer")
            with pytest.raises(ValueError, match="broiler"):
                from apps.farm.flocks.services import BatchService
                BatchService(org).log_weight(
                    batch_id=str(layer_batch.id),
                    sample_size=50,
                    avg_weight_kg=Decimal("1.820"),
                )

    def test_weight_record_created_for_broiler(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.farm.flocks.models import WeightRecord
        org = _make_org("weightbroiler2")
        farm = _make_farm(org)
        house = _make_house(org, farm)

        with set_tenant_context(org):
            broiler_batch = _make_batch(org, farm, house, bird_type="broiler")
            from apps.farm.flocks.services import BatchService
            record = BatchService(org).log_weight(
                batch_id=str(broiler_batch.id),
                sample_size=50,
                avg_weight_kg=Decimal("1.820"),
            )

        assert record.avg_weight_kg == Decimal("1.820")
        assert record.sample_size == 50


# ── 6. RLS isolation tests ────────────────────────────────────────────────────

class TestBatchRLSIsolation:

    def test_batch_rls_isolation(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.farm.flocks.models import Batch

        org1 = _make_org("rls1flock")
        org2 = _make_org("rls2flock")
        farm1 = _make_farm(org1, "Farm 1")
        farm2 = _make_farm(org2, "Farm 2")
        house1 = _make_house(org1, farm1)
        house2 = _make_house(org2, farm2)

        with set_tenant_context(org1):
            batch1 = _make_batch(org1, farm1, house1)

        with set_tenant_context(org2):
            batch2 = _make_batch(org2, farm2, house2)

        with set_tenant_context(org1):
            ids = set(str(i) for i in Batch.objects.values_list("id", flat=True))

        assert str(batch1.id) in ids
        assert str(batch2.id) not in ids, "CRITICAL: Tenant A can see Tenant B's batch"

    def test_mortality_log_rls_isolation(self, db):
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.farm.flocks.models import MortalityLog

        org1 = _make_org("rlsmort1")
        org2 = _make_org("rlsmort2")
        farm1 = _make_farm(org1, "Farm RLS 1")
        farm2 = _make_farm(org2, "Farm RLS 2")
        house1 = _make_house(org1, farm1)
        house2 = _make_house(org2, farm2)

        with set_tenant_context(org1):
            batch1 = _make_batch(org1, farm1, house1)
            from apps.farm.flocks.services import BatchService
            log1 = BatchService(org1).log_mortality(batch_id=str(batch1.id), count=5)

        with set_tenant_context(org2):
            batch2 = _make_batch(org2, farm2, house2)
            log2 = BatchService(org2).log_mortality(batch_id=str(batch2.id), count=3)

        with set_tenant_context(org1):
            log_ids = set(str(i) for i in MortalityLog.objects.values_list("id", flat=True))

        assert str(log1.id) in log_ids
        assert str(log2.id) not in log_ids, "CRITICAL: Tenant A can see Tenant B's mortality log"


# ── 7. View tests ─────────────────────────────────────────────────────────────

class TestBatchViews:

    def _setup(self, db):
        from apps.infrastructure.tenants.models import Organization
        from apps.infrastructure.accounts.models import CustomUser
        org = Organization.objects.create(name="View Org Flock", subdomain="vieworgflock")
        user = CustomUser.objects.create_user(
            email="flockview@example.com",
            password="testpass123",
            username="flockviewuser",
            org=org,
        )
        return org, user

    def test_batch_list_view_returns_200(self, db, client):
        org, user = self._setup(db)
        client.force_login(user)
        from apps.infrastructure.core.rls import set_tenant_context
        with set_tenant_context(org):
            pass
        response = client.get("/batches/")
        assert response.status_code == 200

    def test_mortality_htmx_post_returns_fragment(self, db, client):
        from apps.infrastructure.core.rls import set_tenant_context
        org, user = self._setup(db)
        client.force_login(user)

        farm = _make_farm(org, "HTMX Farm")
        house = _make_house(org, farm, capacity=500)

        with set_tenant_context(org):
            batch = _make_batch(org, farm, house, initial_count=200)

        response = client.post(
            f"/batches/{batch.pk}/mortality/",
            {
                "date": datetime.date.today().isoformat(),
                "count": "5",
                "cause": "unknown",
                "notes": "",
            },
            HTTP_HX_REQUEST="true",
        )
        # HTMX mortality post returns fragment (not redirect)
        assert response.status_code == 200
        assert b"mortality" in response.content.lower() or b"table" in response.content.lower() or b"log" in response.content.lower()

    def test_batch_metrics_card_returns_feed_requirement(self, db, client):
        from apps.infrastructure.core.rls import set_tenant_context
        org, user = self._setup(db)
        client.force_login(user)

        farm = _make_farm(org, "Metrics Farm")
        house = _make_house(org, farm, capacity=1000)

        with set_tenant_context(org):
            batch = _make_batch(org, farm, house, initial_count=500)

        response = client.get(f"/batches/{batch.pk}/metrics/")
        assert response.status_code == 200
        # Metrics card contains feed requirement data
        content = response.content.decode()
        assert "feed" in content.lower() or "kg" in content.lower()
