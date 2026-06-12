import datetime

from rest_framework import serializers

from .models import EggProductionLog


class EggProductionLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = EggProductionLog
        fields = [
            "id",
            "batch",
            "farm",
            "house",
            "record_date",
            "total_eggs",
            "grade_a",
            "grade_b",
            "grade_c",
            "broken",
            "hen_day_pct",
            "crates",
            "recorded_by",
            "notes",
            "created_at",
        ]
        read_only_fields = ["id", "hen_day_pct", "crates", "created_at"]


class EggProductionLogCreateSerializer(serializers.Serializer):
    record_date = serializers.DateField(default=datetime.date.today)
    total_eggs = serializers.IntegerField(min_value=0)
    grade_a = serializers.IntegerField(min_value=0, default=0, required=False)
    grade_b = serializers.IntegerField(min_value=0, default=0, required=False)
    grade_c = serializers.IntegerField(min_value=0, default=0, required=False)
    broken = serializers.IntegerField(min_value=0, default=0, required=False)
    notes = serializers.CharField(default="", required=False)

    def validate_record_date(self, value):
        if value > datetime.date.today():
            raise serializers.ValidationError("Record date cannot be in the future.")
        return value

    def validate(self, data):
        total_grades = (
            data.get("grade_a", 0)
            + data.get("grade_b", 0)
            + data.get("grade_c", 0)
            + data.get("broken", 0)
        )
        if total_grades > 0 and total_grades != data["total_eggs"]:
            raise serializers.ValidationError(
                f"Grade counts ({total_grades}) must equal total_eggs ({data['total_eggs']})."
            )
        return data
