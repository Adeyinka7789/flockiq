"""
Tests for True Flock Memory — FarmBaseline + FarmBaselineService.

Covers baseline computation from closed batches, confidence levels, the
farm-history-vs-breed-benchmark fallback, the batch-close trigger, and that the
proactive alert engine consumes the baseline without regressing.
"""
import datetime

import pytest
from django.utils import timezone

from apps.infrastructure.core.rls import set_tenant_context

pytestmark = pytest.mark.django_db


# ── Helpers ────────────────────────────────────────────────────────────────


def _make_closed_batch(
    org,
    farm,
    house,
    *,
    idx=0,
    initial=100,
    current=95,
    deaths=5,
    feed_kg=304,
    weight_kg=2.0,
    water_l=2500,
    breed="Cobb 500",
    bird_type="broiler",
    close=True,
):
    """Create a broiler batch with feed/weight/mortality/water logs, then close it."""
    from apps.farm.flocks.models import Batch, MortalityLog, WeightRecord
    from apps.production.feed.models import FeedLog
    from apps.production.water.models import WaterLog

    today = datetime.date.today()
    with set_tenant_context(org):
        batch = Batch.objects.create(
            org=org,
            farm=farm,
            house=house,
            batch_name=f"Closed Batch {idx}",
            bird_type=bird_type,
            breed_name=breed,
            placement_date=today - datetime.timedelta(days=42),
            initial_count=initial,
            current_count=current,
            status="active",
        )
        # Logs must be written while the batch is active.
        MortalityLog.objects.create(
            org=org,
            batch=batch,
            farm=farm,
            date=today - datetime.timedelta(days=10),
            count=deaths,
        )
        FeedLog.objects.create(
            org=org,
            batch=batch,
            farm=farm,
            quantity_kg=feed_kg,
            record_date=today - datetime.timedelta(days=5),
        )
        WeightRecord.objects.create(
            org=org,
            batch=batch,
            sample_date=today - datetime.timedelta(days=2),
            sample_size=10,
            avg_weight_kg=str(weight_kg),
        )
        if water_l:
            WaterLog.objects.create(
                org=org,
                batch=batch,
                farm=farm,
                litres_consumed=water_l,
                record_date=today - datetime.timedelta(days=5),
            )
        if close:
            batch.status = "closed"
            batch.closed_at = timezone.now()
            batch.save(update_fields=["status", "closed_at", "updated_at"])
    return batch


# ── Model: confidence_level / confidence_label ─────────────────────────────


class TestFarmBaselineConfidence:
    @pytest.mark.parametrize(
        "count,expected",
        [(0, "none"), (1, "low"), (2, "low"), (3, "medium"), (5, "medium"),
         (6, "high"), (12, "high")],
    )
    def test_confidence_level(self, count, expected):
        from apps.health.analytics.models import FarmBaseline

        fb = FarmBaseline(batch_count=count)
        assert fb.confidence_level == expected

    def test_confidence_label_mentions_count(self):
        from apps.health.analytics.models import FarmBaseline

        assert "6" in FarmBaseline(batch_count=6).confidence_label
        assert "breed benchmarks" in FarmBaseline(batch_count=0).confidence_label


# ── compute_and_save ───────────────────────────────────────────────────────


class TestComputeAndSave:
    def test_no_history_returns_none(self, test_org):
        from apps.health.analytics.farm_baseline_service import FarmBaselineService

        svc = FarmBaselineService(test_org)
        assert svc.compute_and_save("broiler", "Cobb 500") is None

    def test_single_batch_low_confidence(self, test_org, test_farm, test_house):
        from apps.health.analytics.farm_baseline_service import FarmBaselineService

        _make_closed_batch(test_org, test_farm, test_house, idx=0)
        baseline = FarmBaselineService(test_org).compute_and_save("broiler", "Cobb 500")

        assert baseline is not None
        assert baseline.batch_count == 1
        assert baseline.confidence_level == "low"
        assert baseline.avg_fcr is not None
        assert baseline.avg_mortality_rate is not None
        # 5 deaths / 100 placed == 0.05
        assert abs(float(baseline.avg_mortality_rate) - 0.05) < 0.001

    def test_three_batches_medium_confidence(self, test_org, test_farm, test_house):
        from apps.health.analytics.farm_baseline_service import FarmBaselineService

        for i in range(3):
            _make_closed_batch(test_org, test_farm, test_house, idx=i)
        baseline = FarmBaselineService(test_org).compute_and_save("broiler", "Cobb 500")

        assert baseline.batch_count == 3
        assert baseline.confidence_level == "medium"

    def test_six_batches_high_confidence(self, test_org, test_farm, test_house):
        from apps.health.analytics.farm_baseline_service import FarmBaselineService

        for i in range(6):
            _make_closed_batch(test_org, test_farm, test_house, idx=i)
        baseline = FarmBaselineService(test_org).compute_and_save("broiler", "Cobb 500")

        assert baseline.batch_count == 6
        assert baseline.confidence_level == "high"

    def test_best_worst_range_tracked(self, test_org, test_farm, test_house):
        from apps.health.analytics.farm_baseline_service import FarmBaselineService

        _make_closed_batch(test_org, test_farm, test_house, idx=0, feed_kg=200)
        _make_closed_batch(test_org, test_farm, test_house, idx=1, feed_kg=400)
        baseline = FarmBaselineService(test_org).compute_and_save("broiler", "Cobb 500")

        assert baseline.best_fcr <= baseline.avg_fcr <= baseline.worst_fcr


# ── get_baseline_or_benchmark ──────────────────────────────────────────────


class TestGetBaselineOrBenchmark:
    def test_falls_back_to_breed_benchmark_for_new_farm(self, test_org):
        from apps.health.analytics.farm_baseline_service import FarmBaselineService

        result = FarmBaselineService(test_org).get_baseline_or_benchmark(
            "broiler", "Cobb 500"
        )
        assert result["source"] == "breed_benchmark"
        assert result["confidence"] == "none"
        assert result["batch_count"] == 0
        assert "breed benchmarks" in result["confidence_label"]
        # Cobb 500 target FCR from the static table.
        assert abs(result["avg_fcr"] - 1.65) < 0.001
        assert "avg_mortality_rate_pct" in result

    def test_returns_farm_history_when_available(self, test_org, test_farm, test_house):
        from apps.health.analytics.farm_baseline_service import FarmBaselineService

        _make_closed_batch(test_org, test_farm, test_house, idx=0)
        svc = FarmBaselineService(test_org)
        svc.compute_and_save("broiler", "Cobb 500")

        result = svc.get_baseline_or_benchmark("broiler", "Cobb 500")
        assert result["source"] == "farm_history"
        assert result["confidence"] == "low"
        assert result["batch_count"] == 1
        assert result["avg_fcr"] > 0
        assert abs(result["avg_mortality_rate_pct"] - 5.0) < 0.2

    def test_consistent_dict_shape_across_sources(self, test_org, test_farm, test_house):
        from apps.health.analytics.farm_baseline_service import FarmBaselineService

        svc = FarmBaselineService(test_org)
        benchmark = svc.get_baseline_or_benchmark("broiler", "Cobb 500")

        _make_closed_batch(test_org, test_farm, test_house, idx=0)
        svc.compute_and_save("broiler", "Cobb 500")
        history = svc.get_baseline_or_benchmark("broiler", "Cobb 500")

        assert set(benchmark.keys()) == set(history.keys())


# ── Batch-close trigger ────────────────────────────────────────────────────


class TestBatchCloseTrigger:
    def test_closing_a_batch_creates_baseline(self, test_org, test_farm, test_house):
        from apps.farm.flocks.services import BatchService
        from apps.health.analytics.models import FarmBaseline

        # Build an active broiler batch with the logs needed for a baseline.
        batch = _make_closed_batch(
            test_org, test_farm, test_house, idx=0, close=False
        )

        with set_tenant_context(test_org):
            BatchService(test_org).close_batch(str(batch.pk))

            assert FarmBaseline.objects.filter(
                org=test_org, bird_type="broiler", breed_name="Cobb 500"
            ).exists()


# ── Proactive alert consumes baseline ──────────────────────────────────────


class TestProactiveAlertBaselineAware:
    def test_threshold_path_runs_with_history(self, test_org, test_farm, test_house):
        """With farm history + a real spike, the engine still returns an alert."""
        from apps.farm.flocks.models import Batch, MortalityLog
        from apps.health.analytics.farm_baseline_service import FarmBaselineService
        from apps.health.analytics.proactive_alerts import ProactiveAlertEngine

        # Seed closed history so the baseline path is exercised.
        for i in range(2):
            _make_closed_batch(test_org, test_farm, test_house, idx=i)
        FarmBaselineService(test_org).compute_and_save("broiler", "Cobb 500")

        today = datetime.date.today()
        with set_tenant_context(test_org):
            active = Batch.objects.create(
                org=test_org,
                farm=test_farm,
                house=test_house,
                batch_name="Active Spike",
                bird_type="broiler",
                breed_name="Cobb 500",
                placement_date=today - datetime.timedelta(days=20),
                initial_count=100,
                current_count=80,
                status="active",
            )
            # Low baseline over days 4-7, sharp spike in last 3 days.
            for d in range(4, 7):
                MortalityLog.objects.create(
                    org=test_org, batch=active, farm=test_farm,
                    date=today - datetime.timedelta(days=d), count=1,
                )
            for d in range(0, 3):
                MortalityLog.objects.create(
                    org=test_org, batch=active, farm=test_farm,
                    date=today - datetime.timedelta(days=d), count=8,
                )

        engine = ProactiveAlertEngine(test_org)
        result = engine.check_mortality_trajectory(active)
        assert result is not None
        assert result["severity"] in ("warning", "critical")

    def test_no_data_still_returns_none(self, test_org, test_batch):
        from apps.health.analytics.proactive_alerts import ProactiveAlertEngine

        engine = ProactiveAlertEngine(test_org)
        assert engine.check_mortality_trajectory(test_batch) is None
