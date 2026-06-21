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
    from apps.infrastructure.core.rls import set_tenant_context
    farm = Farm(
        org=org, name=name, location="Lagos",
        latitude=Decimal("6.5244"), longitude=Decimal("3.3792"),
        farm_type="broiler",
    )
    farm.clean()
    with set_tenant_context(org):
        farm.save()
    return farm


def _make_house(org, farm, capacity=5000, name="House A"):
    from apps.farm.farms.models import House
    from apps.infrastructure.core.rls import set_tenant_context
    with set_tenant_context(org):
        return House.objects.create(
            org=org, farm=farm, name=name, capacity=capacity, house_type="broiler"
        )


def _make_batch(org, farm, house, bird_type="broiler", initial_count=1000, status="active"):
    from apps.farm.flocks.models import Batch
    from apps.infrastructure.core.rls import set_tenant_context
    with set_tenant_context(org):
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


# ── 1b. Active-batch-per-house DB constraint (race guard) ──────────────────────

class TestActiveBatchPerHouseConstraint:
    """The unique_active_batch_per_house partial index is the real guard against
    the create_batch TOCTOU race — the service .exists() check is advisory."""

    def test_db_constraint_blocks_second_active_batch_same_house(self, db):
        """Bypass the service entirely: two direct active inserts in one house
        must be rejected by the partial unique index at the DB level."""
        from django.db import IntegrityError, transaction
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.farm.flocks.models import Batch
        org = _make_org("dbconstraint")
        farm = _make_farm(org)
        house = _make_house(org, farm)

        with set_tenant_context(org):
            Batch.objects.create(
                org=org, farm=farm, house=house,
                batch_name="First", bird_type="broiler",
                placement_date=datetime.date.today(),
                initial_count=100, current_count=100, status="active",
            )

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                with set_tenant_context(org):
                    Batch.objects.create(
                        org=org, farm=farm, house=house,
                        batch_name="Second", bird_type="broiler",
                        placement_date=datetime.date.today(),
                        initial_count=100, current_count=100, status="active",
                    )

    def test_db_constraint_allows_active_batch_in_different_house(self, db):
        """A second active batch in a DIFFERENT house is fine."""
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.farm.flocks.models import Batch
        org = _make_org("diffhouse")
        farm = _make_farm(org)
        house_a = _make_house(org, farm, name="House A")
        house_b = _make_house(org, farm, name="House B")

        with set_tenant_context(org):
            Batch.objects.create(
                org=org, farm=farm, house=house_a,
                batch_name="A", bird_type="broiler",
                placement_date=datetime.date.today(),
                initial_count=100, current_count=100, status="active",
            )
            second = Batch.objects.create(
                org=org, farm=farm, house=house_b,
                batch_name="B", bird_type="broiler",
                placement_date=datetime.date.today(),
                initial_count=100, current_count=100, status="active",
            )

        assert second.pk is not None
        assert second.house == house_b

    def test_db_constraint_allows_reuse_after_batch_closed(self, db):
        """Closing the first batch frees the house — the condition only covers
        status='active', so a new active batch can be placed."""
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.farm.flocks.models import Batch
        org = _make_org("reuseclosed")
        farm = _make_farm(org)
        house = _make_house(org, farm)

        with set_tenant_context(org):
            first = Batch.objects.create(
                org=org, farm=farm, house=house,
                batch_name="First", bird_type="broiler",
                placement_date=datetime.date.today(),
                initial_count=100, current_count=100, status="active",
            )
            first.status = "closed"
            first.save(update_fields=["status"])

            second = Batch.objects.create(
                org=org, farm=farm, house=house,
                batch_name="Second", bird_type="broiler",
                placement_date=datetime.date.today(),
                initial_count=100, current_count=100, status="active",
            )

        assert second.pk is not None

    def test_create_batch_view_returns_422_when_house_occupied(self, db, client):
        """BatchCreateView surfaces a 422 with a user-facing error when the
        chosen house already holds an active batch."""
        from apps.infrastructure.accounts.models import CustomUser
        from apps.infrastructure.core.rls import set_tenant_context

        # plan_tier=monthly → max_active_batches=10, so the occupancy check
        # (not the plan-limit gate) is what blocks the second placement.
        org = _make_org("occupied422")
        org.plan_tier = "monthly"
        org.subscription_status = "active"
        org.save(update_fields=["plan_tier", "subscription_status"])
        farm = _make_farm(org)
        house = _make_house(org, farm)

        user = CustomUser.objects.create_user(
            email="occ@example.com", username="occuser",
            password="testpass123", org=org, role="owner",
        )
        client.force_login(user)

        with set_tenant_context(org):
            _make_batch(org, farm, house, initial_count=100)

        response = client.post(
            f"/farms/{farm.pk}/batches/create/",
            {
                "house_id": str(house.id),
                "batch_name": "Second Batch",
                "bird_type": "broiler",
                "placement_date": datetime.date.today().isoformat(),
                "initial_count": "100",
            },
            HTTP_HX_REQUEST="true",
        )

        assert response.status_code == 422
        assert b"active batch" in response.content.lower()


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
            role='manager',
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


# ── flocks/tasks.py — Celery task functions ───────────────────────────────────

class TestFlocksCeleryTasks:

    def test_mortality_log_save_dispatches_anomaly_check(self, db):
        """Saving a MortalityLog should dispatch the real analytics anomaly
        check, not a stub."""
        from unittest.mock import patch
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.farm.flocks.services import BatchService

        org = _make_org("anomalydispatch1")
        farm = _make_farm(org)
        house = _make_house(org, farm)

        with set_tenant_context(org):
            batch = _make_batch(org, farm, house, initial_count=500)

        with set_tenant_context(org), patch(
            "apps.health.analytics.tasks.check_mortality_anomaly.delay"
        ) as mock_check:
            BatchService(org).log_mortality(batch_id=str(batch.id), count=5)

        mock_check.assert_called_once()
        _, kwargs = mock_check.call_args
        assert kwargs["org_id"] == str(org.id)
        assert kwargs["batch_id"] == str(batch.id)

    def test_create_batch_async_creates_batch(self, db):
        from apps.farm.flocks.tasks import create_batch_async
        from apps.farm.flocks.models import Batch
        from apps.infrastructure.core.rls import set_tenant_context

        org = _make_org("batchtask1")
        farm = _make_farm(org)
        house = _make_house(org, farm)

        create_batch_async(
            org_id=str(org.id),
            farm_id=str(farm.id),
            house_id=str(house.id),
            batch_name="Async Batch",
            bird_type="broiler",
            placement_date=datetime.date.today(),
            initial_count=500,
            breed_name="Cobb 500",
        )
        with set_tenant_context(org):
            assert Batch.objects.filter(batch_name="Async Batch").exists()

    def test_create_batch_async_reraises_on_invalid_org(self, db):
        import uuid as _uuid
        from apps.farm.flocks.tasks import create_batch_async

        with pytest.raises(Exception):
            create_batch_async(
                org_id=str(_uuid.uuid4()),
                farm_id=str(_uuid.uuid4()),
                house_id=str(_uuid.uuid4()),
                batch_name="Ghost Batch",
                bird_type="broiler",
                placement_date=datetime.date.today(),
                initial_count=100,
                breed_name="",
            )


# ── flocks/signals.py — edge case branches ────────────────────────────────────

class TestFlocksSignalEdgeCases:

    def test_mortality_signal_skips_on_update(self, db):
        """Line 12: created=False path returns immediately."""
        from apps.infrastructure.core.rls import set_tenant_context

        org = _make_org("sigedge1")
        farm = _make_farm(org)
        house = _make_house(org, farm)

        with set_tenant_context(org):
            batch = _make_batch(org, farm, house, initial_count=200)
            from apps.farm.flocks.services import BatchService
            log = BatchService(org).log_mortality(batch_id=str(batch.id), count=5)
            batch.refresh_from_db()
            count_after = batch.current_count

            # Update the log (created=False) — signal returns immediately
            log.notes = "edited"
            log.save()
            batch.refresh_from_db()

        assert batch.current_count == count_after  # unchanged

    def test_mortality_signal_cross_tenant_block(self, db):
        """Lines 21-28: Batch.update() returning 0 logs error, does not raise."""
        from apps.farm.flocks.signals import on_mortality_log_saved
        from apps.infrastructure.core.rls import set_tenant_context
        from unittest.mock import patch, MagicMock

        org = _make_org("sigedge2")
        farm = _make_farm(org)
        house = _make_house(org, farm)

        with set_tenant_context(org):
            batch = _make_batch(org, farm, house, initial_count=200)
            from apps.farm.flocks.services import BatchService
            log = BatchService(org).log_mortality(batch_id=str(batch.id), count=5)

        # Simulate cross-tenant block: make unscoped().filter().update() return 0
        mock_qs = MagicMock()
        mock_qs.filter.return_value.update.return_value = 0
        with patch("apps.farm.flocks.models.Batch") as MockBatch:
            MockBatch.objects.unscoped.return_value = mock_qs
            on_mortality_log_saved(sender=None, instance=log, created=True)  # must not raise

    def test_mortality_spike_notification_exception_swallowed(self, db):
        """Lines 48-50: notification failure never aborts the domain write."""
        from unittest.mock import patch
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.infrastructure.notifications.services import NotificationService
        from apps.farm.flocks.models import Batch

        org = _make_org("sigedge3")
        farm = _make_farm(org)
        house = _make_house(org, farm)

        with set_tenant_context(org):
            # Small batch so a single death triggers the spike threshold (< 10%)
            batch = Batch.objects.create(
                org=org, farm=farm, house=house,
                batch_name="Spike Batch",
                bird_type="broiler",
                placement_date=datetime.date.today() - datetime.timedelta(days=10),
                initial_count=10,
                current_count=10,
                status="active",
            )

        with set_tenant_context(org), patch.object(
            NotificationService, "send", side_effect=Exception("notif down")
        ):
            from apps.farm.flocks.services import BatchService
            BatchService(org).log_mortality(batch_id=str(batch.id), count=2)

    def test_mortality_anomaly_task_exception_swallowed(self, db):
        """check_mortality_anomaly.delay() failure on the real analytics task
        is swallowed and never aborts the domain write."""
        from unittest.mock import patch
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.health.analytics.tasks import check_mortality_anomaly

        org = _make_org("sigedge4")
        farm = _make_farm(org)
        house = _make_house(org, farm)

        with set_tenant_context(org):
            batch = _make_batch(org, farm, house, initial_count=200)

        with set_tenant_context(org), patch.object(
            check_mortality_anomaly, "delay", side_effect=Exception("Redis down")
        ):
            from apps.farm.flocks.services import BatchService
            BatchService(org).log_mortality(batch_id=str(batch.id), count=5)


# ── flocks/views.py — easy GET branches ──────────────────────────────────────

class TestFlocksViewGets:

    def _setup(self, db, subdomain):
        from apps.infrastructure.tenants.models import Organization
        from apps.infrastructure.accounts.models import CustomUser
        from apps.infrastructure.core.rls import set_tenant_context

        org = Organization.objects.create(name="View Org", subdomain=subdomain)
        user = CustomUser.objects.create_user(
            email=f"{subdomain}@example.com",
            password="testpass123",
            username=subdomain,
            org=org,
            role='manager',
        )
        farm = _make_farm(org)
        house = _make_house(org, farm, capacity=500)
        with set_tenant_context(org):
            batch = _make_batch(org, farm, house, initial_count=200)
        return org, user, batch

    def test_mortality_log_get_renders_form(self, db, client):
        """MortalityLogView.get renders the modal form."""
        org, user, batch = self._setup(db, "flocksviewget1")
        client.force_login(user)
        response = client.get(f"/batches/{batch.pk}/mortality/")
        assert response.status_code == 200

    def test_mortality_recent_get_renders_table(self, db, client):
        """MortalityRecentView.get renders the mortality table partial."""
        org, user, batch = self._setup(db, "flocksviewget2")
        client.force_login(user)
        response = client.get(f"/batches/{batch.pk}/mortality/recent/")
        assert response.status_code == 200

    def test_batch_close_get_renders_modal(self, db, client):
        """BatchCloseView.get renders the close confirmation modal."""
        org, user, batch = self._setup(db, "flocksviewget3")
        client.force_login(user)
        response = client.get(f"/batches/{batch.pk}/close/")
        assert response.status_code == 200
