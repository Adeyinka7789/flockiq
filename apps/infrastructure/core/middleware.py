import structlog
from django.http import Http404, HttpResponse

from .rls import set_tenant_context

logger = structlog.get_logger(__name__)


class ImpersonationMiddleware:
    """
    If _impersonated_user_id is in session, swap request.user to the
    impersonated user for this request. Original admin identity preserved.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        impersonated_user_id = request.session.get('_impersonated_user_id')

        if impersonated_user_id and request.user.is_authenticated:
            try:
                from apps.infrastructure.accounts.models import CustomUser
                impersonated = CustomUser.objects.get(
                    pk=impersonated_user_id, is_active=True)
                request.impersonator = request.user
                request.user = impersonated
                request.is_impersonating = True
            except CustomUser.DoesNotExist:
                del request.session['_impersonated_user_id']
                request.is_impersonating = False
        else:
            request.is_impersonating = False
            request.impersonator = None

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
            new_response = HttpResponse(status=204)
            new_response["HX-Redirect"] = response["Location"]
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

        # Dev / health-check bypass
        if host in self.DEV_HOSTS or host.startswith("192.168."):
            request.org = None
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
