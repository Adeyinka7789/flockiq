import json

import structlog
from axes.decorators import axes_dispatch
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
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


class ProfilePageView(LoginRequiredMixin, View):
    """Profile page — displays user details."""

    def get(self, request):
        return render(request, "accounts/profile.html")


class EditProfileView(LoginRequiredMixin, View):
    """GET/POST /profile/edit/ — HTMX modal for editing profile fields."""

    def get(self, request):
        return render(request, "accounts/_edit_profile_form.html")

    def post(self, request):
        user = request.user
        user.first_name = request.POST.get("first_name", "").strip()
        user.last_name = request.POST.get("last_name", "").strip()
        user.phone = request.POST.get("phone", "").strip()
        user.save(update_fields=["first_name", "last_name", "phone"])
        logger.info("profile_updated", user_id=str(user.id))
        response = render(request, "accounts/_edit_profile_form.html")
        response["HX-Trigger"] = json.dumps({
            "showToast": {"message": "Profile updated.", "type": "success"},
        })
        response["HX-Refresh"] = "true"
        return response


class WebChangePasswordView(LoginRequiredMixin, View):
    """POST /profile/change-password/ — HTMX fragment for #pw-result."""

    def post(self, request):
        old_password = request.POST.get("old_password", "")
        new_password = request.POST.get("new_password", "")
        confirm_password = request.POST.get("confirm_password", "")

        if not request.user.check_password(old_password):
            return render(request, "accounts/_pw_result.html",
                          {"error": "Current password is incorrect."})
        if len(new_password) < 8:
            return render(request, "accounts/_pw_result.html",
                          {"error": "New password must be at least 8 characters."})
        if new_password != confirm_password:
            return render(request, "accounts/_pw_result.html",
                          {"error": "Passwords do not match."})

        request.user.set_password(new_password)
        request.user.save(update_fields=["password"])
        update_session_auth_hash(request, request.user)
        logger.info("password_changed", user_id=str(request.user.id))
        return render(request, "accounts/_pw_result.html", {"success": True})
