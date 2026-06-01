import structlog
from axes.decorators import axes_dispatch
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect, render
from django.utils.decorators import method_decorator
from django.views import View
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView as BaseTokenRefreshView

from .models import CustomUser
from .permissions import IsManagerOrAbove
from .serializers import (
    ChangePasswordSerializer,
    CustomTokenObtainPairSerializer,
    LoginSerializer,
    UserCreateSerializer,
    UserProfileSerializer,
)

logger = structlog.get_logger(__name__)


def _token_response(user):
    refresh = CustomTokenObtainPairSerializer.get_token(user)
    access = refresh.access_token
    return {
        "access": str(access),
        "refresh": str(refresh),
        "user": UserProfileSerializer(user).data,
    }


@method_decorator(axes_dispatch, name="dispatch")
class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data, context={"request": request})
        if not serializer.is_valid():
            return Response(
                {"error": {"code": "VALIDATION_ERROR", "fields": serializer.errors}},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        user = serializer.validated_data["user"]
        logger.info("user_login", user_id=str(user.id), email=user.email)
        return Response({"data": _token_response(user)}, status=status.HTTP_200_OK)


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            refresh_token = request.data.get("refresh")
            if refresh_token:
                token = RefreshToken(refresh_token)
                token.blacklist()
        except Exception:
            pass
        return Response(status=status.HTTP_200_OK)


class TokenRefreshView(BaseTokenRefreshView):
    pass


class UserProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = UserProfileSerializer(request.user)
        return Response({"data": serializer.data})


class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data, context={"request": request})
        if not serializer.is_valid():
            return Response(
                {"error": {"code": "VALIDATION_ERROR", "fields": serializer.errors}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        request.user.set_password(serializer.validated_data["new_password"])
        request.user.save(update_fields=["password"])
        return Response({"data": _token_response(request.user)}, status=status.HTTP_200_OK)


class UserCreateView(APIView):
    permission_classes = [IsManagerOrAbove]

    def post(self, request):
        serializer = UserCreateSerializer(data=request.data, context={"request": request})
        if not serializer.is_valid():
            return Response(
                {"error": {"code": "VALIDATION_ERROR", "fields": serializer.errors}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        user = serializer.save()
        logger.info("user_created", created_by=str(request.user.id), new_user=str(user.id))
        return Response(
            {"data": UserProfileSerializer(user).data},
            status=status.HTTP_201_CREATED,
        )


class UserListView(APIView):
    permission_classes = [IsManagerOrAbove]

    def get(self, request):
        users = CustomUser.objects.filter(org=request.user.org).order_by("email")
        serializer = UserProfileSerializer(users, many=True)
        return Response({"data": serializer.data})


# ── Web / session-based auth views ────────────────────────────────────────────

class WebLoginView(View):
    """Session-based login for the HTMX web app (separate from JWT API)."""

    def get(self, request):
        if request.user.is_authenticated:
            return redirect("dashboard")
        next_url = request.GET.get("next", "")
        return render(request, "accounts/login.html", {"next": next_url})

    def post(self, request):
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')

        user = authenticate(request, username=email, password=password)

        if user is not None:
            login(request, user)
            next_url = request.GET.get('next', '/')
            return redirect(next_url)

        return render(request, 'accounts/login.html', {
            'error': 'Invalid email or password. Please try again.',
            'email': email,
        })


class WebLogoutView(LoginRequiredMixin, View):
    """Session logout — clears Django session."""

    def get(self, request):
        logout(request)
        return redirect("login")

    def post(self, request):
        logout(request)
        return redirect("login")
