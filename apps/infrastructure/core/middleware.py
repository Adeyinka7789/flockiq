import time

import structlog
from django.conf import settings
from django.http import Http404, HttpResponse

from .rls import set_tenant_context

logger = structlog.get_logger(__name__)
IMPERSONATION_MAX_SECONDS = getattr(settings, 'IMPERSONATION_MAX_SECONDS', 30 * 60)


class ImpersonationMiddleware:
    """
    If _impersonated_user_id is in session, swap request.user to the
    impersonated user for this request. Original admin identity preserved.

    Hardened: re-verifies the real user is still an admin on every request,
    enforces a TTL on the impersonation session, and refuses to impersonate
    privileged (super_admin / superuser) targets.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.is_impersonating = False
        request.impersonator = None

        impersonated_id = request.session.get('_impersonated_user_id')
        started_at = request.session.get('_impersonation_started_at')

        if impersonated_id and request.user.is_authenticated:
            real_user = request.user
            is_admin = real_user.is_superuser or \
                       getattr(real_user, 'role', '') == 'super_admin'
            expired = not started_at or \
                      (time.time() - started_at) > IMPERSONATION_MAX_SECONDS

            if not is_admin or expired:
                for k in ('_impersonated_user_id', '_impersonator_id',
                          '_impersonation_started_at'):
                    request.session.pop(k, None)
                request.session.modified = True
                logger.warning(
                    "impersonation.revoked",
                    extra={
                        "reason": "not_admin" if not is_admin else "expired",
                        "real_user": str(real_user.pk)
                    }
                )
            else:
                try:
                    from apps.infrastructure.accounts.models import CustomUser
                    impersonated = CustomUser.objects.get(
                        pk=impersonated_id, is_active=True
                    )
                    if impersonated.is_superuser or \
                       getattr(impersonated, 'role', '') == 'super_admin':
                        raise CustomUser.DoesNotExist
                    request.impersonator = real_user
                    request.user = impersonated
                    request.is_impersonating = True
                except CustomUser.DoesNotExist:
                    request.session.pop('_impersonated_user_id', None)
                    request.session.modified = True

        return self.get_response(request)


class HtmxSessionExpiredMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if (
            response.status_code == 302
            and request.headers.get("HX-Request")
            and "/login/" in response.get("Location", "")
        ):
            new_response = HttpResponse(status=401)
            from urllib.parse import urlencode, urlparse
            from django.utils.http import url_has_allowed_host_and_scheme
            # Use the Referer header so the user lands back on the full page
            # they were viewing, not on the HTMX fragment endpoint URL.
            referer = request.META.get("HTTP_REFERER", "")
            if referer:
                parsed = urlparse(referer)
                dest = parsed.path or "/"
            else:
                dest = "/"
            if not url_has_allowed_host_and_scheme(
                dest,
                allowed_hosts={request.get_host()},
                require_https=request.is_secure()
            ):
                dest = "/"
            new_response["HX-Redirect"] = "/login/?" + urlencode({"next": dest})
            return new_response
        return response


class TenantMiddleware:
    """
    Resolves the active tenant from the request subdomain on every HTTP request.
    Sets the RLS context for the entire request via set_tenant_context(), which:
      - Sets thread-local current_org (used by TenantAwareManager)
      - Executes SET LOCAL app.current_org_id inside transaction.atomic()
        so PostgreSQL RLS policies are satisfied for the request's lifetime.

    Subdomain resolution:
        apetech.flockiq.com  → subdomain='apetech' → Organization(subdomain='apetech')
        localhost/127.0.0.1  → dev bypass, request.org = None
        www/app/admin/api    → auth-resolved subdomains (JWT carries org claim)

    Middleware position:
        Must come AFTER AuthenticationMiddleware in settings.MIDDLEWARE.
        Add to MIDDLEWARE in config/settings/base.py once Phase 1C is complete.
    """

    # Subdomains that don't map to a specific tenant — org resolved from JWT instead
    AUTH_SUBDOMAINS = {"www", "app", "admin", "api"}

    # Hosts that bypass tenant resolution in development
    DEV_HOSTS = {"localhost", "127.0.0.1", "testserver"}

    def __init__(self, get_response):
        self.get_response = get_response

    @staticmethod
    def _is_privileged(user):
        """Superadmins are never affected by org suspension."""
        return bool(getattr(user, "is_superuser", False)) or \
            getattr(user, "role", "") == "super_admin"

    @staticmethod
    def _org_active_cached(org_id):
        """Return whether the org is active, using a short-lived cache to avoid
        a DB hit on every request. Suspensions are cached only briefly so a
        re-activation propagates quickly; superadmin actions invalidate the key
        immediately (see superadmin views)."""
        from django.core.cache import cache

        from apps.infrastructure.tenants.models import Organization

        cache_key = f"org_active:{org_id}"
        is_active = cache.get(cache_key)
        if is_active is None:
            is_active = Organization.objects.filter(id=org_id, is_active=True).exists()
            cache.set(cache_key, is_active, timeout=300 if is_active else 60)
        return is_active

    def _suspended_response(self, request, **log_kwargs):
        """Log an authenticated user out and bounce them to the login page."""
        from django.contrib.auth import logout
        from django.shortcuts import redirect

        logout(request)
        logger.warning("tenant.suspended_user_kicked", **log_kwargs)
        return redirect("/login/?suspended=1")

    def _kick_if_suspended(self, request, org):
        """Return a redirect response if the authenticated user's org has been
        suspended, otherwise None. Superadmins and active impersonation
        sessions are never kicked. Anonymous users are left alone so the login
        page can render (and to avoid a redirect loop after logout)."""
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return None
        if self._is_privileged(user) or getattr(request, "is_impersonating", False):
            return None
        if not self._org_active_cached(org.id):
            return self._suspended_response(request, org_id=str(org.id))
        return None

    def __call__(self, request):
        host = request.get_host().split(":")[0]  # Strip port

        # Dev / health-check bypass.
        # In production the tenant is resolved from the subdomain; on localhost /
        # testserver there is no tenant subdomain, so fall back to the authenticated
        # user's org (mirroring the AUTH_SUBDOMAINS branch below). Without this, every
        # tenant-scoped query (TenantAwareManager, CustomUser.tenant_objects,
        # assert_tenant_context()) runs with no context and returns empty / raises.
        # The Django test client always uses the 'testserver' host, so this is also
        # what gives request-driven tests a tenant context.
        if host in self.DEV_HOSTS or host.startswith("192.168."):
            org = None
            if getattr(request, "user", None) and request.user.is_authenticated:
                org = getattr(request.user, "org", None)
            request.org = org
            if org:
                kicked = self._kick_if_suspended(request, org)
                if kicked is not None:
                    return kicked
                with set_tenant_context(org):
                    return self.get_response(request)
            return self.get_response(request)

        # Custom domain resolution.
        # A tenant may point their own domain (e.g. app.obasanjofarm.com) at
        # FlockIQ. Such hosts never end in ".flockiq.com", so we resolve the org
        # from the verified custom_domain mapping BEFORE subdomain parsing.
        # Unknown / unverified hosts fall through to the existing subdomain
        # logic, so the root marketing domain (flockiq.com) is unaffected.
        if not host.endswith(".flockiq.com"):
            from apps.infrastructure.tenants.models import Organization  # noqa: PLC0415

            try:
                # Organization has RLS disabled — safe to query without a context.
                # Only verified + active custom domains resolve here.
                org = Organization.objects.get(
                    custom_domain=host,
                    custom_domain_verified=True,
                    is_active=True,
                )
            except Organization.DoesNotExist:
                org = None

            if org is not None:
                request.org = org
                # Custom-domain requests are treated exactly like subdomain
                # requests: re-verify the org is still active (handles a
                # suspension that happened after this short-lived query) and set
                # the RLS context for the request lifetime.
                kicked = self._kick_if_suspended(request, org)
                if kicked is not None:
                    return kicked
                with set_tenant_context(org):
                    return self.get_response(request)

        parts = host.split(".")
        if len(parts) < 3:
            # Root domain (e.g. flockiq.com) — no tenant
            request.org = None
            return self.get_response(request)

        subdomain = parts[0]

        if subdomain in self.AUTH_SUBDOMAINS:
            # JWT-authenticated routes — org comes from the token claim
            org = None
            if hasattr(request, "user") and request.user.is_authenticated:
                org = getattr(request.user, "org", None)
            request.org = org
            if org:
                # Re-verify org is still active — the session-cached user.org
                # may be stale if the org was deactivated after the session
                # started. Suspended users are logged out and bounced to login.
                kicked = self._kick_if_suspended(request, org)
                if kicked is not None:
                    return kicked
                with set_tenant_context(org):
                    return self.get_response(request)
            return self.get_response(request)

        # Tenant subdomain
        from apps.infrastructure.tenants.models import Organization  # noqa: PLC0415

        try:
            # Organization has RLS disabled — safe without a context.
            # Resolve regardless of is_active so suspended-org users get a clear
            # "suspended" bounce to login rather than a bare 404.
            org = Organization.objects.get(subdomain=subdomain)
        except Organization.DoesNotExist:
            logger.warning("tenant.not_found", subdomain=subdomain, host=host)
            raise Http404(f"No active tenant for subdomain: {subdomain}")

        if not org.is_active:
            user = getattr(request, "user", None)
            # Authenticated, non-superadmin users are logged out and redirected.
            # Anonymous users fall through so the login page can render with the
            # suspension banner (and to avoid a post-logout redirect loop).
            if user and user.is_authenticated and not self._is_privileged(user):
                return self._suspended_response(
                    request, subdomain=subdomain, org_id=str(org.id)
                )

        request.org = org

        with set_tenant_context(org):
            response = self.get_response(request)

        return response
