"""Custom domain management for tenant owners.

Flow:
  1. Owner adds a custom domain      → CustomDomainSettingsView.post
  2. FlockIQ shows a DNS TXT record   → settings/_domain_pending.html
  3. Owner adds the TXT record at their DNS provider
  4. FlockIQ verifies it (dnspython)  → VerifyCustomDomainView.post
  5. TenantMiddleware then serves app.obasanjofarm.com as that org's dashboard.
"""

import re
import secrets

import structlog
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.views import View

from apps.infrastructure.core.helpers import get_org_or_404

logger = structlog.get_logger(__name__)

# A conservative hostname check: dot-separated labels of letters/digits/hyphens,
# each label 1–63 chars and not starting/ending with a hyphen, at least two
# labels (a domain must have a TLD).
_DOMAIN_RE = re.compile(
    r"^(?!-)[a-z0-9-]{1,63}(?<!-)(\.(?!-)[a-z0-9-]{1,63}(?<!-))+$"
)


def _is_owner(request):
    return getattr(request.user, "role", "") == "owner"


def _render_status(request, org):
    """Render whichever of the three domain-status partials matches org state."""
    if org.custom_domain and org.custom_domain_verified:
        template = "settings/_domain_verified.html"
    elif org.custom_domain:
        template = "settings/_domain_pending.html"
    else:
        template = "settings/_domain_empty.html"
    return render(request, template, {"org": org})


class CustomDomainSettingsView(LoginRequiredMixin, View):
    """GET /settings/custom-domain/  — full settings page (owner only).
    POST /settings/custom-domain/  — add a custom domain, returns the pending
                                     verification fragment for #domain-status.
    """

    def get(self, request):
        if not _is_owner(request):
            return render(request, "settings/custom_domain.html", {
                "org": request.user.org,
                "forbidden": True,
            })
        org = get_org_or_404(request)
        return render(request, "settings/custom_domain.html", {"org": org})

    def post(self, request):
        if not _is_owner(request):
            return HttpResponse(status=403)

        from .models import Organization

        org = get_org_or_404(request)
        domain = request.POST.get("custom_domain", "").strip().lower()
        # Strip a scheme or path if the owner pasted a full URL.
        domain = re.sub(r"^https?://", "", domain).split("/")[0].strip()

        def _error(message):
            return render(request, "settings/_domain_empty.html", {
                "org": org,
                "error": message,
                "value": domain,
            })

        if not domain:
            return _error("Please enter a domain.")
        if not _DOMAIN_RE.match(domain):
            return _error("Enter a valid domain, e.g. app.yourfarm.com")
        if domain.endswith(".flockiq.com") or domain == "flockiq.com":
            return _error("You cannot use a flockiq.com domain here.")
        # Uniqueness across orgs (excluding this org, in case of re-entry).
        if (
            Organization.objects.filter(custom_domain=domain)
            .exclude(pk=org.pk)
            .exists()
        ):
            return _error("That domain is already in use by another account.")

        org.custom_domain = domain
        org.custom_domain_verified = False
        org.custom_domain_verified_at = None
        org.custom_domain_verification_token = secrets.token_urlsafe(32)
        org.save(update_fields=[
            "custom_domain",
            "custom_domain_verified",
            "custom_domain_verified_at",
            "custom_domain_verification_token",
        ])
        logger.info("custom_domain.added", org_id=str(org.id), domain=domain)
        return _render_status(request, org)


class VerifyCustomDomainView(LoginRequiredMixin, View):
    """POST /settings/custom-domain/verify/ — check the DNS TXT record."""

    def post(self, request):
        if not _is_owner(request):
            return HttpResponse(status=403)

        org = get_org_or_404(request)
        if not org.custom_domain:
            return _render_status(request, org)

        if org.custom_domain_verified:
            return _render_status(request, org)

        verified = self._dns_txt_matches(
            org.custom_domain, org.custom_domain_verification_token
        )

        if verified:
            org.custom_domain_verified = True
            org.custom_domain_verified_at = timezone.now()
            org.save(update_fields=[
                "custom_domain_verified", "custom_domain_verified_at",
            ])
            logger.info(
                "custom_domain.verified",
                org_id=str(org.id), domain=org.custom_domain,
            )
            return _render_status(request, org)

        logger.info(
            "custom_domain.verify_failed",
            org_id=str(org.id), domain=org.custom_domain,
        )
        return render(request, "settings/_domain_pending.html", {
            "org": org,
            "error": (
                "We couldn't find the TXT record yet. DNS changes can take a "
                "few minutes to propagate — please try again shortly."
            ),
        })

    @staticmethod
    def _dns_txt_matches(domain, token):
        """Return True if _flockiq-verify.<domain> has the expected TXT value."""
        try:
            import dns.resolver
        except ImportError:  # pragma: no cover - dependency must be installed
            logger.error("custom_domain.dnspython_missing")
            return False

        expected = f"flockiq-verify={token}"
        try:
            answers = dns.resolver.resolve(f"_flockiq-verify.{domain}", "TXT")
            for rdata in answers:
                for txt in rdata.strings:
                    if txt.decode() == expected:
                        return True
        except Exception:
            return False
        return False


class RemoveCustomDomainView(LoginRequiredMixin, View):
    """POST /settings/custom-domain/remove/ — clear all custom-domain fields."""

    def post(self, request):
        if not _is_owner(request):
            return HttpResponse(status=403)

        org = get_org_or_404(request)
        domain = org.custom_domain
        org.custom_domain = None
        org.custom_domain_verified = False
        org.custom_domain_verified_at = None
        org.custom_domain_verification_token = ""
        org.save(update_fields=[
            "custom_domain",
            "custom_domain_verified",
            "custom_domain_verified_at",
            "custom_domain_verification_token",
        ])
        logger.info("custom_domain.removed", org_id=str(org.id), domain=domain)
        return _render_status(request, org)
