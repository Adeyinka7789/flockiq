import structlog
from django.db import transaction

from apps.infrastructure.core.services import BaseService

from .models import Farm, House

logger = structlog.get_logger(__name__)


class FarmService(BaseService):

    # ── Farm CRUD ──────────────────────────────────────────────────────────────

    def create_farm(self, name: str, location: str, lat, lng, farm_type: str = "mixed") -> Farm:
        """
        Creates a Farm for this org. Validates GPS bounds via model.clean().
        Queues a weather cache refresh for the new farm's coordinates.
        """
        farm = Farm(
            org=self.org,
            name=name,
            location=location,
            latitude=lat,
            longitude=lng,
            farm_type=farm_type,
        )
        farm.clean()  # Raises ValidationError if GPS out of Nigeria bounds

        with self.atomic():
            farm.save()
            self.logger.info("farm.created", farm_id=str(farm.id), name=name)
            # Queue weather cache refresh after the transaction commits
            farm_id_str = str(farm.id)
            org_id_str = str(farm.org_id)
            transaction.on_commit(
                lambda: _queue_weather_refresh(farm_id_str, org_id_str)
            )

        return farm

    def update_farm(self, farm_id: str, **kwargs) -> Farm:
        """Updates allowed fields only. Validates GPS if coordinates are changed."""
        farm = Farm.objects.get(id=farm_id, org_id=self.org.id)
        allowed = {"name", "location", "latitude", "longitude", "farm_type", "is_active", "notes"}
        for field, value in kwargs.items():
            if field in allowed:
                setattr(farm, field, value)
        farm.clean()
        farm.save(update_fields=list(set(kwargs.keys()) & allowed) + ["updated_at"])
        self.logger.info("farm.updated", farm_id=str(farm.id))
        return farm

    def list_farms(self, active_only: bool = True):
        """Returns farms for the current org, ordered by name."""
        qs = Farm.objects.filter(org_id=self.org.id)
        if active_only:
            qs = qs.filter(is_active=True)
        return qs.order_by("name")

    def get_farm_detail(self, farm_id: str) -> dict:
        """Returns farm + all houses + active batch summaries."""
        farm = Farm.objects.get(id=farm_id, org_id=self.org.id)
        houses = list(
            House.objects.filter(org_id=self.org.id, farm_id=farm.id, is_active=True).order_by("name")
        )
        return {
            "farm": farm,
            "houses": houses,
        }

    # ── House CRUD ─────────────────────────────────────────────────────────────

    def create_house(self, farm_id: str, name: str, capacity: int, house_type: str = "mixed") -> House:
        """Creates a House within a farm. Validates ownership and capacity."""
        if capacity <= 0:
            raise ValueError("House capacity must be greater than 0.")

        farm = Farm.objects.get(id=farm_id, org_id=self.org.id)

        house = House(
            org=self.org,
            farm=farm,
            name=name,
            capacity=capacity,
            house_type=house_type,
        )
        with self.atomic():
            house.save()
            self.logger.info("house.created", house_id=str(house.id), farm_id=str(farm.id))

        return house

    def update_house(self, house_id: str, **kwargs) -> House:
        """
        Updates descriptive house fields only (name, capacity, house_type, notes).

        The owning farm and org are structural — moving a house between farms
        would break batch history — so they are never reassigned here regardless
        of what is passed in.
        """
        house = House.objects.get(id=house_id, org_id=self.org.id)
        allowed = {"name", "capacity", "house_type", "notes"}
        for field, value in kwargs.items():
            if field in allowed:
                setattr(house, field, value)
        if house.capacity is not None and int(house.capacity) <= 0:
            raise ValueError("House capacity must be greater than 0.")
        house.save(update_fields=list(set(kwargs.keys()) & allowed) + ["updated_at"])
        self.logger.info("house.updated", house_id=str(house.id))
        return house

    # ── Summary / dashboard ────────────────────────────────────────────────────

    def get_farm_summary(self, farm_id: str) -> dict:
        """
        Returns aggregated summary for one farm.
        In Phase 2A (no Batch model yet): live_birds=0, active_batches=0.
        """
        farm = Farm.objects.get(id=farm_id, org_id=self.org.id)
        houses = list(
            House.objects.filter(org_id=self.org.id, farm_id=farm.id, is_active=True).order_by("name")
        )
        total_capacity = sum(h.capacity for h in houses)
        total_live = sum(h.current_occupancy for h in houses)
        active_batches = sum(1 for h in houses if h.current_occupancy > 0)
        occupancy_pct = round(total_live / total_capacity * 100, 1) if total_capacity else 0.0

        return {
            "farm": farm,
            "total_live_birds": total_live,
            "active_batches": active_batches,
            "total_capacity": total_capacity,
            "occupancy_pct": occupancy_pct,
            "houses": [
                {
                    "house": h,
                    "current_occupancy": h.current_occupancy,
                    "occupancy_pct": h.occupancy_pct,
                }
                for h in houses
            ],
        }

    def get_dashboard_data(self) -> dict:
        """
        Aggregates across ALL farms for the org.
        In Phase 2A (no Batch model yet): live_birds=0, active_batches=0.
        """
        farms = list(Farm.objects.filter(org_id=self.org.id, is_active=True).order_by("name"))
        total_farms = len(farms)
        total_live_birds = 0
        total_active_batches = 0

        farms_list = []
        for farm in farms:
            live = farm.total_live_birds
            batches = farm.active_batch_count
            total_live_birds += live
            total_active_batches += batches
            farms_list.append(
                {
                    "farm": farm,
                    "total_live_birds": live,
                    "active_batch_count": batches,
                }
            )

        return {
            "total_live_birds": total_live_birds,
            "total_active_batches": total_active_batches,
            "total_farms": total_farms,
            "farms_list": farms_list,
        }


def _queue_weather_refresh(farm_id: str, org_id: str) -> None:
    """Safely enqueue weather cache refresh — no-op if task isn't registered yet."""
    try:
        from apps.farm.weather.tasks import refresh_weather_for_farm
        farm = Farm.objects.get(id=farm_id, org_id=org_id)
        refresh_weather_for_farm.delay(
            str(farm.id),
            float(farm.latitude) if farm.latitude else None,
            float(farm.longitude) if farm.longitude else None,
            str(farm.org_id),
        )
    except Exception:
        logger.debug("weather.refresh_skipped", farm_id=farm_id)
