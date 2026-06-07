import time

import structlog
from django.conf import settings
from django.http import Http404, HttpResponse, HttpResponseForbidden

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
                with set_tenant_context(org):
                    return self.get_response(request)
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
                # may be stale if the org was deactivated after the session started.
                from django.core.cache import cache
                from apps.infrastructure.tenants.models import Organization

                cache_key = f"org_active:{org.id}"
                is_active = cache.get(cache_key)
                if is_active is None:
                    try:
                        org = Organization.objects.get(id=org.id, is_active=True)
                        cache.set(cache_key, True, timeout=300)  # 5 min TTL
                    except Organization.DoesNotExist:
                        cache.set(cache_key, False, timeout=60)
                        logger.warning(
                            "tenant.inactive_org_blocked",
                            org_id=str(org.id),
                            subdomain=subdomain,
                        )
                        return HttpResponseForbidden("Organisation is inactive")
                elif not is_active:
                    return HttpResponseForbidden("Organisation is inactive")

                with set_tenant_context(org):
                    return self.get_response(request)
            return self.get_response(request)

        # Tenant subdomain
        from apps.infrastructure.tenants.models import Organization  # noqa: PLC0415

        try:
            # Organization has RLS disabled — safe without a context
            org = Organization.objects.get(subdomain=subdomain, is_active=True)
        except Organization.DoesNotExist:
            logger.warning("tenant.not_found", subdomain=subdomain, host=host)
            raise Http404(f"No active tenant for subdomain: {subdomain}")

        request.org = org

        with set_tenant_context(org):
            response = self.get_response(request)

        return response
