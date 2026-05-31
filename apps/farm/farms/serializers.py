from rest_framework import serializers

from .models import Farm, House

_LAT_MIN, _LAT_MAX = 4.0, 14.0
_LNG_MIN, _LNG_MAX = 2.7, 15.0


class HouseSerializer(serializers.ModelSerializer):
    current_occupancy = serializers.IntegerField(read_only=True)
    occupancy_pct = serializers.FloatField(read_only=True)

    class Meta:
        model = House
        fields = [
            "id", "name", "capacity", "house_type", "is_active", "notes",
            "current_occupancy", "occupancy_pct", "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class FarmSerializer(serializers.ModelSerializer):
    houses = HouseSerializer(many=True, read_only=True)

    class Meta:
        model = Farm
        fields = [
            "id", "name", "location", "latitude", "longitude",
            "farm_type", "is_active", "notes", "houses", "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class FarmSummarySerializer(serializers.ModelSerializer):
    active_batch_count = serializers.IntegerField(read_only=True)
    total_live_birds = serializers.IntegerField(read_only=True)

    class Meta:
        model = Farm
        fields = ["id", "name", "farm_type", "total_live_birds", "active_batch_count", "is_active"]


class FarmCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200)
    location = serializers.CharField(max_length=300)
    latitude = serializers.DecimalField(max_digits=10, decimal_places=7)
    longitude = serializers.DecimalField(max_digits=10, decimal_places=7)
    farm_type = serializers.ChoiceField(
        choices=Farm.FarmType.choices,
        default=Farm.FarmType.MIXED,
    )

    def validate(self, data):
        lat = float(data.get("latitude", 0))
        lng = float(data.get("longitude", 0))
        if not (_LAT_MIN <= lat <= _LAT_MAX):
            raise serializers.ValidationError(
                {"latitude": f"Latitude must be between {_LAT_MIN} and {_LAT_MAX} (Nigeria bounding box)."}
            )
        if not (_LNG_MIN <= lng <= _LNG_MAX):
            raise serializers.ValidationError(
                {"longitude": f"Longitude must be between {_LNG_MIN} and {_LNG_MAX} (Nigeria bounding box)."}
            )
        return data


class HouseCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100)
    capacity = serializers.IntegerField(min_value=1)
    house_type = serializers.ChoiceField(
        choices=House.HouseType.choices,
        default=House.HouseType.MIXED,
    )
