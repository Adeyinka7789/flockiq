import datetime

from rest_framework import serializers

from apps.farm.flocks.models import Batch, MortalityLog, StockReconciliation, WeightRecord


class BatchSerializer(serializers.ModelSerializer):
    cycle_day = serializers.IntegerField(read_only=True)
    mortality_rate_pct = serializers.FloatField(read_only=True)
    is_active = serializers.BooleanField(read_only=True)

    class Meta:
        model = Batch
        fields = [
            "id",
            "farm",
            "house",
            "batch_name",
            "breed_name",
            "bird_type",
            "placement_date",
            "initial_count",
            "current_count",
            "status",
            "closed_at",
            "notes",
            "cycle_day",
            "mortality_rate_pct",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "current_count", "created_at", "updated_at"]


class BatchCreateSerializer(serializers.Serializer):
    farm_id = serializers.UUIDField()
    house_id = serializers.UUIDField()
    batch_name = serializers.CharField(max_length=100)
    bird_type = serializers.ChoiceField(choices=["layer", "broiler"])
    placement_date = serializers.DateField()
    initial_count = serializers.IntegerField(min_value=1)
    breed_name = serializers.CharField(max_length=100, required=False, default="")
    notes = serializers.CharField(required=False, default="", allow_blank=True)

    def validate_placement_date(self, value):
        if value > datetime.date.today():
            raise serializers.ValidationError("Placement date cannot be in the future.")
        return value


class MortalityLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = MortalityLog
        fields = [
            "id",
            "batch",
            "farm",
            "date",
            "count",
            "cause",
            "notes",
            "created_at",
        ]
        read_only_fields = ["id", "batch", "farm", "created_at"]


class MortalityLogCreateSerializer(serializers.Serializer):
    date = serializers.DateField(required=False, default=datetime.date.today)
    count = serializers.IntegerField(min_value=1)
    cause = serializers.ChoiceField(
        choices=["disease", "accident", "culling", "unknown", "theft"],
        default="unknown",
    )
    notes = serializers.CharField(required=False, default="", allow_blank=True)


class WeightRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = WeightRecord
        fields = [
            "id",
            "batch",
            "sample_date",
            "sample_size",
            "avg_weight_kg",
            "min_weight_kg",
            "max_weight_kg",
            "notes",
            "created_at",
        ]
        read_only_fields = ["id", "batch", "created_at"]


class StockReconciliationSerializer(serializers.ModelSerializer):
    class Meta:
        model = StockReconciliation
        fields = [
            "id",
            "batch",
            "date",
            "expected_count",
            "actual_count",
            "variance",
            "variance_pct",
            "is_flagged",
            "notes",
            "created_at",
        ]
        read_only_fields = ["id", "batch", "created_at"]
