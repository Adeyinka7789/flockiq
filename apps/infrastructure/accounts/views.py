import json
import secrets

import structlog
from axes.decorators import axes_dispatch
from django.conf import settings as django_settings
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.cache import cache
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.infrastructure.core.helpers import get_org_or_404
from django.utils.decorators import method_decorator
from django.views import View
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.views import TokenRefreshView as BaseTokenRefreshView

from apps.infrastructure.core.email_service import EmailService

from .constants import COMMON_TIMEZONES, COUNTRY_CHOICES, timezone_for_country
from .models import CustomUser
from .permissions import IsManagerOrAbove
from .throttles import LoginRateThrottle, SignupRateThrottle
from .serializers import (
    ChangePasswordSerializer,
    CustomTokenObtainPairSerializer,
    LoginSerializer,
    UserCreateSerializer,
    UserProfileSerializer,
)

logger = structlog.get_logger(__name__)


class ThrottledTokenObtainPairView(TokenObtainPairView):
    """
    Stock JWT login with the 'login' throttle scope (10/h, see
    DEFAULT_THROTTLE_RATES). The stock view has no throttle_scope, so without
    this subclass the /api/auth/token/ endpoint was only covered by the
    blanket 30/h anon rate — and django-axes does not see this surface at
    all (it protects the web login form).
    """
    throttle_classes = [LoginRateThrottle]


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
    throttle_classes = [LoginRateThrottle]

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
        users = CustomUser.tenant_objects.order_by("email")
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
            # Block login for users whose organisation has been suspended.
            # Superadmins (no org / super_admin role) are never affected.
            org = getattr(user, 'org', None)
            is_privileged = user.is_superuser or getattr(user, 'role', '') == 'super_admin'
            if org is not None and not is_privileged and not org.is_active:
                return render(request, 'accounts/login.html', {
                    'suspension_error': True,
                    'support_email': django_settings.SUPPORT_EMAIL,
                    'email': email,
                }, status=403)

            if not getattr(user, 'email_verified', True):
                return render(request, 'accounts/login.html', {
                    'error': 'Please verify your email before logging in.',
                    'show_resend_verification': True,
                    'unverified_email': email,
                })
            login(request, user)
            next_url = request.GET.get('next', '/')
            return redirect(next_url)

        return render(request, 'accounts/login.html', {
            'error': 'Invalid email or password. Please try again.',
            'email': email,
        })


# Subdomains that would shadow platform infrastructure, mail routing or app
# routes if a tenant claimed them. Checked at signup; expand before adding any
# new platform-level hostname or top-level URL path.
RESERVED_SUBDOMAINS = {
    "www", "api", "admin", "superadmin", "app",
    "mail", "email", "smtp", "pop", "imap",
    "ftp", "ssh", "vpn", "cdn", "static",
    "media", "assets", "blog", "docs", "help",
    "support", "billing", "pay", "payment",
    "ns", "ns1", "ns2", "dns",
    "dev", "staging", "test", "demo", "sandbox",
    "flockiq", "accounts", "auth", "login",
    "signup", "register", "dashboard",
}


class SignupView(View):
    """Session-based signup — creates Organisation + owner user atomically."""

    def get(self, request):
        if request.user.is_authenticated:
            return redirect("/")
        return render(request, "accounts/signup.html", {
            "country_choices": COUNTRY_CHOICES,
        })

    def post(self, request):
        import re
        from datetime import timedelta

        from django.db import IntegrityError, transaction
        from django.http import JsonResponse
        from django.utils import timezone

        from apps.infrastructure.tenants.models import Organization

        # Rate limit signups per IP (scope "signup" in DEFAULT_THROTTLE_RATES).
        # This is a plain Django view, so the throttle is invoked manually —
        # DRF's throttle_classes machinery only runs on APIView.
        throttle = SignupRateThrottle()
        if not throttle.allow_request(request, self):
            logger.warning("signup.throttled", ip=request.META.get("REMOTE_ADDR", ""))
            return JsonResponse(
                {"error": "Too many signup attempts. Try again later."},
                status=429,
            )

        errors = {}

        org_name = request.POST.get("org_name", "").strip()
        owner_name = request.POST.get("owner_name", "").strip()
        email = request.POST.get("email", "").strip().lower()
        phone = request.POST.get("phone", "").strip()
        subdomain = request.POST.get("subdomain", "").strip().lower()
        country = request.POST.get("country", "").strip()
        state_region = request.POST.get("state_region", "").strip()
        password = request.POST.get("password", "")
        confirm = request.POST.get("confirm_password", "")

        if not org_name:
            errors["org_name"] = "Farm name is required"
        if not email:
            errors["email"] = "Email is required"
        if not country:
            errors["country"] = "Country is required"
        if not subdomain:
            errors["subdomain"] = "Subdomain is required"
        elif not re.match(r"^[a-z0-9][a-z0-9-]{1,30}[a-z0-9]$", subdomain):
            errors["subdomain"] = "Use only lowercase letters, numbers, hyphens"
        elif subdomain in RESERVED_SUBDOMAINS:
            errors["subdomain"] = "This subdomain is reserved"
        elif Organization.objects.filter(subdomain=subdomain).exists():
            errors["subdomain"] = "This subdomain is already taken"
        if email and CustomUser.objects.filter(email__iexact=email).exists():
            errors["email"] = "An account with this email already exists"
        if len(password) < 8:
            errors["password"] = "Password must be at least 8 characters"
        if password != confirm:
            errors["confirm_password"] = "Passwords do not match"

        if errors:
            return render(request, "accounts/signup.html", {
                "errors": errors,
                "values": request.POST,
                "country_choices": COUNTRY_CHOICES,
            })

        # The exists() checks above are advisory only — two concurrent signups
        # can both pass them. The unique constraints on subdomain and username
        # are the real guard; IntegrityError converts the race loser into a
        # form error instead of a 500.
        try:
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
                    country=country,
                    state_region=state_region,
                    timezone=timezone_for_country(country),
                    org=org,
                    role="owner",
                )
        except IntegrityError:
            errors["subdomain"] = "This subdomain is already taken. Please choose another."
            return render(request, "accounts/signup.html", {
                "errors": errors,
                "values": request.POST,
                "country_choices": COUNTRY_CHOICES,
            })

        verification_url = request.build_absolute_uri(
            f"/accounts/verify/{user.email_verification_token}/"
        )
        EmailService.send_verification(user, verification_url)
        if django_settings.DEBUG:
            logger.info("signup.verification_url", url=verification_url)
        logger.info("org_signup", org_id=str(org.id), user_id=str(user.id))
        return redirect(f"/accounts/verify-sent/?email={email}")


class VerifyEmailSentView(View):
    """GET /accounts/verify-sent/ — 'check your inbox' page shown after signup."""

    def get(self, request):
        email = request.GET.get('email', '')
        return render(request, 'accounts/verify_email_sent.html', {'email': email})


class VerifyEmailView(View):
    """GET /accounts/verify/<uuid:token>/ — confirms email and logs the user in."""

    def get(self, request, token):
        try:
            user = CustomUser.objects.get(email_verification_token=token)
        except CustomUser.DoesNotExist:
            return render(request, 'accounts/login.html', {
                'error': 'This verification link is invalid or has already been used.',
            })

        if user.email_verified:
            return redirect('/login/')

        user.email_verified = True
        user.save(update_fields=['email_verified'])
        user.backend = 'django.contrib.auth.backends.ModelBackend'
        login(request, user)
        logger.info("email_verified", user_id=str(user.id))
        return redirect('/')


class ResendVerificationView(View):
    """POST /accounts/resend-verification/ — re-sends the verification email."""

    def post(self, request):
        from django.conf import settings as django_settings

        email = request.POST.get('email', '').strip()
        try:
            user = CustomUser.objects.get(email=email, email_verified=False)
            verification_url = request.build_absolute_uri(
                f"/accounts/verify/{user.email_verification_token}/"
            )
            EmailService.send_verification(user, verification_url)
            if django_settings.DEBUG:
                logger.info("resend_verification.url", url=verification_url)
            logger.info("verification_resent", email=email)
        except CustomUser.DoesNotExist:
            pass  # Silently ignore — prevents email enumeration

        return render(request, 'accounts/verify_email_sent.html', {
            'email': email,
            'resent': True,
        })


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
            reset_url = request.build_absolute_uri(f"/reset-password/?token={token}")
            EmailService.send_password_reset(user, reset_url)
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
        return render(request, "accounts/_edit_profile_form.html", {
            "country_choices": COUNTRY_CHOICES,
            "timezones": COMMON_TIMEZONES,
        })

    def post(self, request):
        user = request.user
        user.first_name = request.POST.get("first_name", "").strip()
        user.last_name = request.POST.get("last_name", "").strip()
        user.phone = request.POST.get("phone", "").strip()
        user.bio = request.POST.get("bio", "").strip()
        user.country = request.POST.get("country", "").strip()
        user.state_region = request.POST.get("state_region", "").strip()
        # Honour an explicit timezone choice; otherwise derive it from the country.
        selected_tz = request.POST.get("timezone", "").strip()
        user.timezone = (
            selected_tz if selected_tz in COMMON_TIMEZONES
            else timezone_for_country(user.country)
        )
        user.save(update_fields=[
            "first_name", "last_name", "phone", "bio",
            "country", "state_region", "timezone",
        ])
        logger.info("profile_updated", user_id=str(user.id))
        response = render(request, "accounts/_edit_profile_form.html", {
            "country_choices": COUNTRY_CHOICES,
            "timezones": COMMON_TIMEZONES,
        })
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


# ── Team management views ──────────────────────────────────────────────────────

_INVITABLE_ROLES = ("manager", "supervisor", "data_entry", "vet_advisor")


def _role_choices():
    """Role options offered by the team role picker (excludes owner)."""
    return [c for c in CustomUser.ROLE_CHOICES if c[0] in _INVITABLE_ROLES]


class TeamListView(LoginRequiredMixin, View):
    """GET /team/ — lists all org members."""

    def get(self, request):
        if request.user.role not in ("owner", "manager"):
            return redirect("dashboard")
        all_users = CustomUser.tenant_objects.all()
        active_count = all_users.filter(is_active=True).count()
        unique_roles = all_users.values_list("role", flat=True).distinct().count()
        q = request.GET.get("q", "").strip()
        users = all_users.order_by("role", "email")
        if q:
            users = users.filter(
                Q(first_name__icontains=q)
                | Q(last_name__icontains=q)
                | Q(email__icontains=q)
            )
        if "q" in request.GET and request.headers.get("HX-Request"):
            return render(request, "accounts/_member_rows.html", {
                "users": users,
                "role_choices": _role_choices(),
            })
        return render(request, "accounts/team.html", {
            "users": users,
            "active_count": active_count,
            "unique_roles": unique_roles,
            "role_choices": _role_choices(),
            "search_query": q,
        })


class InviteUserView(LoginRequiredMixin, View):
    """GET /team/invite/ — modal form; POST creates user + sends welcome email."""

    def get(self, request):
        if request.user.role != "owner":
            return HttpResponse(status=403)
        return render(request, "accounts/_invite_form.html")

    def post(self, request):
        if request.user.role != "owner":
            return HttpResponse(status=403)

        from apps.infrastructure.billing.features import get_plan_features
        features = get_plan_features(request.user.org.plan_tier)
        current_members = CustomUser.tenant_objects.count()
        if current_members >= features['team_members']:
            return render(request, "accounts/_invite_form.html", {
                "error": (
                    f'Your {request.user.org.plan_tier} plan allows {features["team_members"]} team member(s). '
                    f'Upgrade to add more.'
                ),
            })

        email = request.POST.get("email", "").strip()
        first_name = request.POST.get("first_name", "").strip()
        last_name = request.POST.get("last_name", "").strip()
        role = request.POST.get("role", "data_entry")

        def _error(msg):
            return render(request, "accounts/_invite_form.html", {
                "error": msg,
                "post": request.POST,
            })

        if not email:
            return _error("Email is required.")
        if not first_name:
            return _error("First name is required.")
        if role not in _INVITABLE_ROLES:
            return _error("Invalid role selected.")
        if CustomUser.objects.filter(email=email).exists():
            return _error("A user with this email already exists.")

        temp_password = secrets.token_urlsafe(10)
        user = CustomUser.objects.create_user(
            email=email,
            username=email,
            password=temp_password,
            first_name=first_name,
            last_name=last_name,
            role=role,
            org=request.user.org,
            is_active=True,
        )

        login_url = request.build_absolute_uri("/login/")
        EmailService.send_team_invite(
            recipient_email=email,
            first_name=first_name,
            org_name=request.user.org.name,
            temp_password=temp_password,
            login_url=login_url,
        )

        logger.info("team_member_invited", invited_by=str(request.user.id), new_user=str(user.id))

        response = HttpResponse("")
        response["HX-Trigger"] = json.dumps({
            "close-modal": {},
            "showToast": {"message": f"Invitation sent to {email}", "type": "success"},
        })
        response["HX-Refresh"] = "true"
        return response


class EditUserRoleView(LoginRequiredMixin, View):
    """POST /team/<uuid>/role/ — updates member role, returns updated row."""

    def post(self, request, pk):
        if request.user.role != "owner":
            return HttpResponse(status=403)

        member = get_object_or_404(CustomUser, pk=pk, org=request.user.org)

        if member == request.user:
            return _member_row_response(request, member, toast="You cannot change your own role.")
        if member.role == "owner":
            return _member_row_response(request, member, toast="Cannot change another owner's role.", toast_type="error")

        role = request.POST.get("role", "")
        if role not in _INVITABLE_ROLES:
            return _member_row_response(request, member, toast="Invalid role.", toast_type="error")

        member.role = role
        member.save(update_fields=["role"])
        logger.info("team_role_changed", changed_by=str(request.user.id), member=str(member.id), new_role=role)
        return _member_row_response(request, member, toast=f"Role updated to {member.get_role_display()}.")


class DeactivateUserView(LoginRequiredMixin, View):
    """POST /team/<uuid>/deactivate/ — sets is_active=False."""

    def post(self, request, pk):
        if request.user.role != "owner":
            return HttpResponse(status=403)

        member = get_object_or_404(CustomUser, pk=pk, org=request.user.org)

        if member == request.user:
            return _member_row_response(request, member, toast="You cannot deactivate yourself.", toast_type="error")

        member.is_active = False
        member.save(update_fields=["is_active"])
        logger.info("team_member_deactivated", by=str(request.user.id), member=str(member.id))
        return _member_row_response(request, member, toast="User deactivated.")


class ReactivateUserView(LoginRequiredMixin, View):
    """POST /team/<uuid>/reactivate/ — sets is_active=True."""

    def post(self, request, pk):
        if request.user.role != "owner":
            return HttpResponse(status=403)

        member = get_object_or_404(CustomUser, pk=pk, org=request.user.org)
        member.is_active = True
        member.save(update_fields=["is_active"])
        logger.info("team_member_reactivated", by=str(request.user.id), member=str(member.id))
        return _member_row_response(request, member, toast="User reactivated.")


def _member_row_response(request, member, toast=None, toast_type="success"):
    """Render the member row partial with an optional toast trigger."""
    response = render(request, "accounts/_member_row.html", {
        "member": member,
        "role_choices": _role_choices(),
    })
    if toast:
        response["HX-Trigger"] = json.dumps({
            "showToast": {"message": toast, "type": toast_type},
        })
    return response


# ── NDPR compliance — data export & account deletion ───────────────────────────

@login_required
def export_data(request):
    """GET — download a JSON copy of all data belonging to the user + their org.

    Owner only — the export contains the entire organisation's data (NDPR data
    portability is the owner's right). Limited to one export per 24 hours.
    """
    from .services import build_data_export

    # Function-based view, so the role gate is inline (mirrors RoleRequiredMixin).
    if not request.user.is_superuser and request.user.role != "owner":
        return render(
            request,
            "errors/403.html",
            {"role": request.user.role, "required_roles": ["owner"]},
            status=403,
        )

    org = get_org_or_404(request)

    cache_key = f"data_export_{request.user.id}"
    if cache.get(cache_key):
        return HttpResponse(
            "You can only export your data once per 24 hours.",
            status=429,
        )

    data = build_data_export(request.user, org)
    cache.set(cache_key, True, timeout=86400)

    response = HttpResponse(
        json.dumps(data, indent=2, default=str, ensure_ascii=False),
        content_type="application/json",
    )
    filename = (
        f"flockiq_data_export_{org.subdomain}_"
        f"{timezone.now().strftime('%Y%m%d')}.json"
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    logger.info("data_exported", user_id=str(request.user.id), org_id=str(org.id))
    return response


def _notify_superadmins_org_deleted(user, org):
    """Create an in-app AdminNotification for every superadmin on org deletion."""
    from apps.infrastructure.notifications.models import AdminNotification

    for admin in CustomUser.objects.filter(is_superuser=True):
        AdminNotification.objects.create(
            recipient=admin,
            title=f"Organisation deleted — {org.name}",
            body=(
                f"{user.email} has deleted their account "
                f"and organisation {org.name}."
            ),
        )


@login_required
def delete_account(request):
    """GET shows a confirmation page; POST validates and erases the account.

    Owners delete the entire organisation (all farms, batches, production data
    and team members). Non-owners delete only their own user account.
    """
    from .services import delete_organisation

    is_owner = request.user.role == "owner"

    if request.method == "GET":
        return render(request, "accounts/delete_account.html", {"is_owner": is_owner})

    # POST — validate confirmation text + password before doing anything.
    password = request.POST.get("password", "")
    confirmation = request.POST.get("confirmation", "").strip()

    def _error(message):
        return render(request, "accounts/delete_account.html", {
            "is_owner": is_owner,
            "error": message,
        })

    if confirmation != "DELETE":
        return _error('Please type DELETE (in capitals) to confirm.')
    if not request.user.check_password(password):
        return _error("Incorrect password. Please try again.")

    user = request.user

    if is_owner:
        org = get_org_or_404(request)
        # Notify staff and farewell the owner while records still exist.
        _notify_superadmins_org_deleted(user, org)
        EmailService.send_account_deleted(user, org)
        logger.info("account_deleted", user_id=str(user.id), org_id=str(org.id), owner=True)
        logout(request)
        delete_organisation(org)  # clears all org data + team members + org
    else:
        from apps.infrastructure.core.rls import set_tenant_context
        EmailService.send_account_deleted(user, None)
        logger.info("account_deleted", user_id=str(user.id), owner=False)
        user_org = user.org
        logout(request)
        # Delete inside the RLS scope so the delete collector's SELECTs against
        # tenant tables (rows referencing this user) run with the GUC set.
        if user_org is not None:
            with set_tenant_context(user_org):
                user.delete()
        else:
            user.delete()

    return redirect("/?deleted=1")
