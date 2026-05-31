import re

from rest_framework import serializers

from .models import Organization

RESERVED_SUBDOMAINS = {"www", "api", "admin", "app", "mail", "static", "media"}


class OrganizationSerializer(serializers.ModelSerializer):
    is_on_trial = serializers.BooleanField(read_only=True)

    class Meta:
        model = Organization
        fields = [
            "id", "name", "subdomain", "plan_tier",
            "subscription_status", "is_on_trial", "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class OrganizationOnboardingSerializer(serializers.ModelSerializer):
    """Used during tenant registration — Phase 1D wires the full creation logic."""

    class Meta:
        model = Organization
        fields = ["name", "subdomain", "owner_name", "owner_phone", "owner_email"]

    def validate_subdomain(self, value):
        if not re.match(r"^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$", value):
            raise serializers.ValidationError(
                "Subdomain must be 3–63 characters, lowercase letters, numbers, and hyphens only."
            )
        if value in RESERVED_SUBDOMAINS:
            raise serializers.ValidationError(f"'{value}' is a reserved subdomain.")
        return value
