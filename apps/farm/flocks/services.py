import datetime
from decimal import Decimal

import structlog
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from apps.infrastructure.core.rls import assert_tenant_context
from apps.infrastructure.core.services import BaseService

logger = structlog.get_logger(__name__)


class BatchService(BaseService):
    """
    All Batch lifecycle business logic.
    Every write method uses transaction.atomic() so signals and count updates
    are rolled back together on failure.
    """

    # ── Batch placement ────────────────────────────────────────────────────

    def create_batch(
        self,
        farm_id: str,
        house_id: str,
        batch_name: str,
        bird_type: str,
        placement_date: datetime.date,
        initial_count: int,
        breed_name: str = "",
        notes: str = "",
        hatchery=None,
        doc_price_per_chick=None,
        doc_supplier_name: str = "",
    ):
        assert_tenant_context()
        from apps.farm.farms.models import Farm, House
        from apps.farm.flocks.exceptions import (
            HouseCapacityExceededError,
            HouseOccupiedError,
        )
        from apps.farm.flocks.models import Batch

        try:
            farm = Farm.objects.get(id=farm_id, org=self.org)
        except Farm.DoesNotExist:
            raise ValueError(f"Farm {farm_id} not found for this organisation.")

        try:
            house = House.objects.get(id=house_id, farm=farm, org=self.org)
        except House.DoesNotExist:
            raise ValueError(f"House {house_id} not found under farm {farm_id}.")

        if initial_count > house.capacity:
            raise HouseCapacityExceededError(
                f"initial_count {initial_count} exceeds house capacity {house.capacity}."
            )

        occupied = Batch.objects.filter(org_id=self.org.id, house_id=house.id, status="active").exists()
        if occupied:
            existing = Batch.objects.filter(org_id=self.org.id, house_id=house.id, status="active").first()
            raise HouseOccupiedError(
                f"House already has active batch: {existing.batch_name}."
            )

        try:
            with transaction.atomic():
                batch = Batch.objects.create(
                    org=self.org,
                    farm=farm,
                    house=house,
                    batch_name=batch_name,
                    breed_name=breed_name,
                    bird_type=bird_type,
                    placement_date=placement_date,
                    initial_count=initial_count,
                    current_count=initial_count,
                    notes=notes,
                    hatchery=hatchery,
                    doc_price_per_chick=doc_price_per_chick,
                    doc_supplier_name=doc_supplier_name,
                )
        except IntegrityError:
            # The .exists() check above is advisory only — two concurrent
            # placements can both pass it. The unique_active_batch_per_house
            # partial index is the real guard; convert the race loser into the
            # same user-facing error the occupancy check raises.
            raise HouseOccupiedError(
                "This house already has an active batch. Close the current "
                "batch before starting a new one."
            )

        self.logger.info(
            "flocks.batch_created",
            batch_id=str(batch.pk),
            batch_name=batch_name,
            initial_count=initial_count,
        )
        return batch

    # ── Batch edit ─────────────────────────────────────────────────────────

    def update_batch(self, batch_id: str, **kwargs):
        """
        Updates descriptive batch fields only.

        Editable: batch_name, breed_name, bird_type, doc_supplier_name, notes.

        Structural / financial fields are never touched here regardless of what
        is passed in:
          - initial_count  → anchors every financial record (use mortality logs)
          - placement_date → determines cycle day and benchmark calculations
          - current_count  → derived from mortality logs, not edited directly
          - farm / house / org → moving a batch breaks history and RLS scoping
        """
        assert_tenant_context()
        from apps.farm.flocks.models import Batch

        try:
            batch = Batch.objects.get(id=batch_id, org=self.org)
        except Batch.DoesNotExist:
            raise ValueError(f"Batch {batch_id} not found.")

        allowed = {"batch_name", "breed_name", "bird_type", "doc_supplier_name", "notes"}
        update_fields = []
        for field, value in kwargs.items():
            if field in allowed:
                setattr(batch, field, value)
                update_fields.append(field)

        if not update_fields:
            return batch

        with transaction.atomic():
            batch.save(update_fields=update_fields + ["updated_at"])

        self.logger.info(
            "flocks.batch_updated",
            batch_id=str(batch.pk),
            fields=update_fields,
        )
        return batch

    # ── Batch close ────────────────────────────────────────────────────────

    def close_batch(self, batch_id: str, notes: str = ""):
        assert_tenant_context()
        from apps.farm.flocks.exceptions import BatchAlreadyClosedError
        from apps.farm.flocks.models import Batch

        try:
            batch = Batch.objects.get(id=batch_id, org=self.org)
        except Batch.DoesNotExist:
            raise ValueError(f"Batch {batch_id} not found.")

        if batch.status == "closed":
            raise BatchAlreadyClosedError(f"Batch {batch.batch_name} is already closed.")

        with transaction.atomic():
            batch.status = "closed"
            batch.closed_at = timezone.now()
            if notes:
                batch.notes = notes
            batch.save(update_fields=["status", "closed_at", "notes", "updated_at"])

            reconciliation = self._run_reconciliation(batch)

        # Learning loop: fold this just-closed batch into the farm's baseline.
        # Best-effort — never let baseline maths break a batch close.
        try:
            from apps.health.analytics.farm_baseline_service import FarmBaselineService

            FarmBaselineService(self.org).compute_and_save(
                bird_type=batch.bird_type,
                breed_name=batch.breed_name,
            )
        except Exception:
            logger.exception(
                "flocks.baseline_recompute_failed",
                batch_id=str(batch.pk),
            )

        # Recompute credit score for this org after every batch close.
        try:
            from apps.infrastructure.core.credit_scoring import CreditScoringService

            CreditScoringService(self.org).compute()
        except Exception:
            logger.exception(
                "flocks.credit_score_recompute_failed",
                batch_id=str(batch.pk),
            )

        self.logger.info(
            "flocks.batch_closed",
            batch_id=str(batch.pk),
            reconciliation_flagged=reconciliation.is_flagged,
        )
        return batch

    # ── Mortality logging ──────────────────────────────────────────────────

    def log_mortality(
        self,
        batch_id: str,
        count: int,
        cause: str = "unknown",
        date: datetime.date = None,
        notes: str = "",
    ):
        assert_tenant_context()
        from apps.farm.flocks.exceptions import (
            BatchClosedError,
            MortalityExceedsLiveBirdsError,
        )
        from apps.farm.flocks.models import Batch, MortalityLog

        try:
            batch = Batch.objects.get(id=batch_id, org=self.org)
        except Batch.DoesNotExist:
            raise ValueError(f"Batch {batch_id} not found.")

        if batch.status != "active":
            raise BatchClosedError(
                f"Cannot log mortality on {batch.status} batch '{batch.batch_name}'."
            )

        if count > batch.current_count:
            raise MortalityExceedsLiveBirdsError(
                f"Mortality count {count} exceeds current live birds {batch.current_count}."
            )

        log_date = date or datetime.date.today()

        with transaction.atomic():
            log = MortalityLog.objects.create(
                org=self.org,
                batch=batch,
                farm=batch.farm,
                date=log_date,
                count=count,
                cause=cause,
                notes=notes,
            )

        return log

    # ── Weight recording ───────────────────────────────────────────────────

    def log_weight(
        self,
        batch_id: str,
        sample_size: int,
        avg_weight_kg,
        min_weight_kg=None,
        max_weight_kg=None,
        sample_date: datetime.date = None,
        notes: str = "",
    ):
        from apps.farm.flocks.exceptions import BatchClosedError
        from apps.farm.flocks.models import Batch, WeightRecord

        try:
            batch = Batch.objects.get(id=batch_id, org=self.org)
        except Batch.DoesNotExist:
            raise ValueError(f"Batch {batch_id} not found.")

        if batch.status != "active":
            raise BatchClosedError(
                f"Cannot log weight on {batch.status} batch."
            )

        if batch.bird_type != "broiler":
            raise ValueError(
                f"Weight records are only applicable to broiler batches, not '{batch.bird_type}'."
            )

        record = WeightRecord.objects.create(
            org=self.org,
            batch=batch,
            sample_date=sample_date or datetime.date.today(),
            sample_size=sample_size,
            avg_weight_kg=Decimal(str(avg_weight_kg)),
            min_weight_kg=Decimal(str(min_weight_kg)) if min_weight_kg is not None else None,
            max_weight_kg=Decimal(str(max_weight_kg)) if max_weight_kg is not None else None,
            notes=notes,
        )
        return record

    # ── Dashboard data ─────────────────────────────────────────────────────

    def get_batch_dashboard_data(self, batch_id: str) -> dict:
        from apps.infrastructure.core.calculator import BreedCalculator
        from apps.farm.flocks.models import Batch, MortalityLog

        try:
            batch = Batch.objects.get(id=batch_id, org=self.org)
        except Batch.DoesNotExist:
            raise ValueError(f"Batch {batch_id} not found.")

        feed_requirement_today = BreedCalculator.daily_feed_requirement_kg(
            bird_count=batch.current_count,
            age_days=batch.cycle_day,
            breed=batch.bird_type,
        )
        water_requirement_today = BreedCalculator.daily_water_requirement_litres(
            bird_count=batch.current_count,
        )

        seven_days_ago = datetime.date.today() - datetime.timedelta(days=7)
        recent_mortality = list(
            MortalityLog.objects.filter(
                batch=batch,
                date__gte=seven_days_ago,
            ).order_by("-date")
        )

        weight_trend = []
        if batch.bird_type == "broiler":
            weight_trend = list(
                batch.weight_records.order_by("-sample_date")[:5]
            )

        return {
            "batch": batch,
            "cycle_day": batch.cycle_day,
            "mortality_rate_pct": batch.mortality_rate_pct,
            "feed_requirement_today": feed_requirement_today,
            "water_requirement_today": water_requirement_today,
            "recent_mortality": recent_mortality,
            "weight_trend": weight_trend,
        }

    def get_active_batches(self, farm_id: str = None):
        from apps.farm.flocks.models import Batch

        qs = Batch.objects.filter(org_id=self.org.id, status="active")
        if farm_id:
            qs = qs.filter(farm_id=farm_id)
        return qs.select_related("farm", "house").order_by("-placement_date")

    # ── Internal reconciliation ────────────────────────────────────────────

    def _run_reconciliation(self, batch):
        from apps.farm.flocks.models import MortalityLog, StockReconciliation
        from apps.infrastructure.notifications.services import NotificationService

        logged_mortality = (
            MortalityLog.objects.filter(batch=batch)
            .aggregate(total=Sum("count"))["total"]
            or 0
        )
        # Expected = what the count should be based on logged events
        expected_count = batch.initial_count - logged_mortality
        # Actual = what the physical count is right now
        actual_count = batch.current_count
        variance = expected_count - actual_count
        variance_pct = round(
            Decimal(str(variance)) / Decimal(str(batch.initial_count)) * 100, 2
        ) if batch.initial_count else Decimal("0.00")
        is_flagged = float(abs(variance_pct)) > 1.5

        reconciliation = StockReconciliation.objects.create(
            org=self.org,
            batch=batch,
            date=datetime.date.today(),
            expected_count=expected_count,
            actual_count=actual_count,
            variance=variance,
            variance_pct=variance_pct,
            is_flagged=is_flagged,
        )

        if is_flagged:
            try:
                NotificationService(self.org).send(
                    event_type="theft_suspected",
                    context={
                        "farm_name": batch.farm.name if batch.farm_id else "",
                        "batch_name": batch.batch_name,
                        "count": abs(variance),
                    },
                    batch=batch,
                )
            except Exception:
                logger.exception(
                    "flocks.theft_notification_failed",
                    batch_id=str(batch.pk),
                )

        return reconciliation
