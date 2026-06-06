import structlog
from django.http import Http404
from django.shortcuts import redirect

logger = structlog.get_logger(__name__)


def get_org_or_404(request, org_slug=None):
    from apps.infrastructure.tenants.models import Organization

    org = getattr(request.user, "org", None)
    if org is None:
        logger.warning("request_missing_org", user_id=str(request.user.id))
        raise Http404("No organisation found for this user.")

    if org_slug is not None and org.slug != org_slug:
        raise Http404("Organisation not found.")

    try:
        org.refresh_from_db()
        if not org.is_active:
            logger.warning("request_inactive_org", org_id=str(org.id), user_id=str(request.user.id))
            raise Http404("Your organisation is no longer active.")
        return org
    except Organization.DoesNotExist:
        logger.warning("request_org_deleted", org_id=str(org.id), user_id=str(request.user.id))
        raise Http404("Your organisation no longer exists.")


def get_org_or_redirect(request, org_slug=None, redirect_url="dashboard"):
    try:
        org = get_org_or_404(request, org_slug=org_slug)
        return org, None
    except Http404:
        return None, redirect(redirect_url)
