import json
import secrets

import structlog
from axes.decorators import axes_dispatch
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.cache import cache
from django.core.mail import send_mail
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
        success_msg = (
            "Password reset successfully. Please sign in."
            if request.GET.get("reset") == "success"
            else None
        )
        return render(request, "accounts/login.html", {
            "next": next_url,
            "success_msg": success_msg,
        })

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


class SignupView(View):
    """Session-based signup — creates Organisation + owner user atomically."""

    def get(self, request):
        if request.user.is_authenticated:
            return redirect("/")
        return render(request, "accounts/signup.html")

    def post(self, request):
        import re
        from datetime import timedelta

        from django.db import transaction
        from django.utils import timezone

        from apps.infrastructure.tenants.models import Organization

        errors = {}

        org_name = request.POST.get("org_name", "").strip()
        owner_name = request.POST.get("owner_name", "").strip()
        email = request.POST.get("email", "").strip()
        phone = request.POST.get("phone", "").strip()
        subdomain = request.POST.get("subdomain", "").strip().lower()
        password = request.POST.get("password", "")
        confirm = request.POST.get("confirm_password", "")

        if not org_name:
            errors["org_name"] = "Farm name is required"
        if not email:
            errors["email"] = "Email is required"
        if not subdomain:
            errors["subdomain"] = "Subdomain is required"
        elif not re.match(r"^[a-z0-9][a-z0-9-]{1,30}[a-z0-9]$", subdomain):
            errors["subdomain"] = "Use only lowercase letters, numbers, hyphens"
        elif subdomain in {"www", "api", "admin", "app", "mail", "static", "media"}:
            errors["subdomain"] = "This subdomain is reserved"
        elif Organization.objects.filter(subdomain=subdomain).exists():
            errors["subdomain"] = "This subdomain is already taken"
        if email and CustomUser.objects.filter(email=email).exists():
            errors["email"] = "An account with this email already exists"
        if len(password) < 8:
            errors["password"] = "Password must be at least 8 characters"
        if password != confirm:
            errors["confirm_password"] = "Passwords do not match"

        if errors:
            return render(request, "accounts/signup.html", {
                "errors": errors,
                "values": request.POST,
            })

        with transaction.atomic():
            org = Organization.objects.create(
                name=org_name,
                subdomain=subdomain,
                owner_name=owner_name,
                owner_email=email,
                owner_phone=phone,
                plan_tier="trial",
                subscription_status="trial",
                trial_ends_at=timezone.now() + timedelta(days=14),
                is_active=True,
            )
            name_parts = owner_name.split()
            user = CustomUser.objects.create_user(
                email=email,
                password=password,
                username=email,
                first_name=name_parts[0] if name_parts else "",
                last_name=" ".join(name_parts[1:]) if len(name_parts) > 1 else "",
                phone=phone,
                org=org,
                role="owner",
            )

        user.backend = "django.contrib.auth.backends.ModelBackend"
        login(request, user)
        logger.info("org_signup", org_id=str(org.id), user_id=str(user.id))
        return redirect("/")


class ForgotPasswordView(View):
    """GET/POST /forgot-password/ — sends a one-time reset link via email."""

    def get(self, request):
        return render(request, "accounts/forgot_password.html")

    def post(self, request):
        from django.conf import settings as django_settings

        email = request.POST.get("email", "").strip()
        try:
            user = CustomUser.objects.get(email=email)
        except CustomUser.DoesNotExist:
            user = None

        if user is not None:
            token = secrets.token_urlsafe(32)
            cache.set(f"pwd_reset:{token}", email, timeout=3600)
            reset_url = f"/reset-password/?token={token}"
            send_mail(
                subject="Reset your FlockIQ password",
                message=(
                    f"Hi {user.first_name or user.email},\n\n"
                    f"Click the link below to reset your password.\n"
                    f"This link expires in 1 hour.\n\n"
                    f"http://localhost:8000{reset_url}\n\n"
                    f"If you did not request this, ignore this email.\n\n"
                    f"— The FlockIQ Team"
                ),
                from_email=getattr(django_settings, "DEFAULT_FROM_EMAIL", "noreply@flockiq.com"),
                recipient_list=[email],
                fail_silently=True,
            )
            logger.info("password_reset_requested", email=email)

        return render(request, "accounts/forgot_password.html", {"success": True})


class ResetPasswordView(View):
    """GET/POST /reset-password/ — validates token and sets new password."""

    _template = "accounts/reset_password.html"

    def get(self, request):
        token = request.GET.get("token", "").strip()
        if not token:
            return redirect("/forgot-password/")
        email = cache.get(f"pwd_reset:{token}")
        if not email:
            return render(request, self._template, {
                "error": "This reset link has expired or is invalid.",
            })
        return render(request, self._template, {"token": token})

    def post(self, request):
        token = request.POST.get("token", "").strip()
        new_password = request.POST.get("new_password", "")
        confirm = request.POST.get("confirm_password", "")
        email = cache.get(f"pwd_reset:{token}")

        if not email:
            return render(request, self._template, {
                "error": "Reset link expired. Request a new one.",
            })
        if len(new_password) < 8:
            return render(request, self._template, {
                "token": token,
                "error": "Password must be at least 8 characters.",
            })
        if new_password != confirm:
            return render(request, self._template, {
                "token": token,
                "error": "Passwords do not match.",
            })

        try:
            user = CustomUser.objects.get(email=email)
        except CustomUser.DoesNotExist:
            return render(request, self._template, {
                "error": "Account not found. Please sign up.",
            })

        user.set_password(new_password)
        user.save(update_fields=["password"])
        cache.delete(f"pwd_reset:{token}")
        logger.info("password_reset_complete", email=email)
        return redirect("/login/?reset=success")


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
