from rest_framework import serializers

from .models import NotificationLog


class NotificationLogSerializer(serializers.ModelSerializer):
    """Read-only representation of an in-app notification for the mobile feed/bell."""

    class Meta:
        model = NotificationLog
        fields = [
            "id",
            "event_type",
            "title",
            "body",
            "severity",
            "channel",
            "action_url",
            "is_read",
            "read_at",
            "acknowledged",
            "created_at",
        ]
        read_only_fields = fields
