"""
Base soft-delete view.

Subclass ``SoftDeleteView`` per model, setting ``model``, ``allowed_roles`` and
(optionally) a typed-confirmation requirement. The view:

    GET  → renders the confirmation modal fragment into #modal-body
    POST → validates confirmation, soft-deletes the object, refreshes the page

Role enforcement is inherited from RoleRequiredMixin (guards GET and POST).
All DB access is wrapped in set_tenant_context so RLS (Layer 2) applies, and the
object is fetched through the tenant-scoped default manager (Layer 1).
"""

import json

import structlog
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from apps.infrastructure.core.helpers import get_org_or_404
from apps.infrastructure.core.mixins import RoleRequiredMixin
from apps.infrastructure.core.rls import set_tenant_context

logger = structlog.get_logger(__name__)


class SoftDeleteView(RoleRequiredMixin, View):
    """
    Base view for soft-deleting a tenant-scoped object.

    Subclass and set:
        model              — the model class (must use SoftDeleteMixin)
        allowed_roles      — list of roles permitted to delete
        success_url        — where non-HTMX requests redirect after delete
        pk_url_kwarg       — URL kwarg holding the object PK (default 'pk')
        confirmation_field — model attr whose value must be typed (optional)
        require_phrase     — extra fixed phrase that must be typed (optional)
    """

    model = None
    allowed_roles: list = []
    success_url = "/"
    pk_url_kwarg = "pk"
    confirmation_field = None
    require_phrase = None
    template_name = "components/_delete_modal.html"

    # ── Helpers ──────────────────────────────────────────────────────────────

    def get_object(self, org, pk):
        # Default manager already excludes soft-deleted rows; is_deleted=False
        # is explicit so a double-delete returns 404 rather than re-deleting.
        with set_tenant_context(org):
            return get_object_or_404(self.model, pk=pk, is_deleted=False)

    def get_success_url(self, obj):
        return self.success_url

    def _modal_context(self, request, obj, **extra):
        ctx = {
            "object": obj,
            "object_name": str(obj),
            "confirmation_field": self.confirmation_field,
            "confirmation_value": (
                getattr(obj, self.confirmation_field)
                if self.confirmation_field
                else None
            ),
            "require_phrase": self.require_phrase,
            "delete_url": request.path,
            "cancel_url": request.META.get("HTTP_REFERER", self.success_url),
        }
        ctx.update(extra)
        return ctx

    # ── HTTP methods ──────────────────────────────────────────────────────────

    def get(self, request, *args, **kwargs):
        org = get_org_or_404(request)
        obj = self.get_object(org, kwargs[self.pk_url_kwarg])
        return render(request, self.template_name, self._modal_context(request, obj))

    def post(self, request, *args, **kwargs):
        org = get_org_or_404(request)
        obj = self.get_object(org, kwargs[self.pk_url_kwarg])

        # Typed confirmation (e.g. type the farm / batch name).
        if self.confirmation_field:
            typed = request.POST.get("confirmation", "").strip()
            expected = str(getattr(obj, self.confirmation_field, "") or "")
            if typed != expected:
                label = self.confirmation_field.replace("_", " ")
                return render(
                    request,
                    self.template_name,
                    self._modal_context(
                        request,
                        obj,
                        error=f"Please type the exact {label} to confirm deletion.",
                    ),
                    status=422,
                )

        # Extra destructive phrase (e.g. "DELETE FARM").
        if self.require_phrase:
            typed_phrase = request.POST.get("confirmation_phrase", "").strip()
            if typed_phrase != self.require_phrase:
                return render(
                    request,
                    self.template_name,
                    self._modal_context(
                        request,
                        obj,
                        error=f'Please type the phrase "{self.require_phrase}" to confirm.',
                    ),
                    status=422,
                )

        with set_tenant_context(org):
            obj.soft_delete(user=request.user)

        logger.info(
            "core.soft_delete",
            model=self.model.__name__,
            object_id=str(obj.pk),
            org_id=str(org.id),
            user_id=str(request.user.id),
        )

        if request.headers.get("HX-Request"):
            response = HttpResponse(status=204)
            response["HX-Trigger"] = json.dumps(
                {
                    "showToast": {"message": f"{str(obj)} deleted.", "type": "success"},
                    "close-modal": True,
                }
            )
            response["HX-Refresh"] = "true"
            return response

        return redirect(self.get_success_url(obj))
