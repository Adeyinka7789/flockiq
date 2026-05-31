import secrets
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import OrganizationOnboardingSerializer, OrganizationSerializer


class TenantOnboardingView(APIView):
    """POST /api/v1/onboarding/ — create new tenant + owner user (atomic)."""

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = OrganizationOnboardingSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"error": {"code": "VALIDATION_ERROR", "fields": serializer.errors}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = serializer.validated_data

        with transaction.atomic():
            from .models import Organization

            org = Organization.objects.create(
                name=data["name"],
                subdomain=data["subdomain"],
                owner_name=data.get("owner_name", ""),
                owner_phone=data.get("owner_phone", ""),
                owner_email=data.get("owner_email", ""),
                plan_tier="trial",
                subscription_status="trial",
                trial_ends_at=timezone.now() + timedelta(days=14),
            )

            from apps.infrastructure.accounts.models import CustomUser

            temp_password = secrets.token_urlsafe(12)
            owner = CustomUser.objects.create_user(
                email=data["owner_email"],
                username=data["owner_email"],
                password=temp_password,
                role="owner",
                org=org,
                is_active=True,
            )

        from apps.infrastructure.accounts.serializers import CustomTokenObtainPairSerializer

        refresh = CustomTokenObtainPairSerializer.get_token(owner)

        return Response(
            {
                "data": {
                    "org": OrganizationSerializer(org).data,
                    "user": {
                        "id": str(owner.id),
                        "email": owner.email,
                        "role": owner.role,
                    },
                    "temp_password": temp_password,
                    "access": str(refresh.access_token),
                    "refresh": str(refresh),
                }
            },
            status=status.HTTP_201_CREATED,
        )
