from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import OrganizationOnboardingSerializer, OrganizationSerializer
from .services import TenantService


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

        org, owner, temp_password = TenantService.create_organization(
            org_name=data["name"],
            subdomain=data["subdomain"],
            owner_email=data["owner_email"],
            owner_name=data.get("owner_name", ""),
            owner_phone=data.get("owner_phone", ""),
            country=data.get("country") or "Nigeria",
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
