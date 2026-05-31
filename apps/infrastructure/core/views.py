import json

from django.http import HttpResponse
from django.shortcuts import redirect, render


class HtmxMixin:
    """
    Mixin for views that serve both full pages and HTMX partials.
    Provides HTMX detection, template switching, OOB swap helpers.
    """

    htmx_template = None
    full_template = None

    @property
    def is_htmx(self):
        return self.request.headers.get("HX-Request") == "true"

    def get_template_names(self):
        if self.is_htmx and self.htmx_template:
            return [self.htmx_template]
        return [self.full_template or super().get_template_names()[0]]

    def render_htmx_fragment(self, template_name, context, status=200):
        return render(self.request, template_name, context, status=status)

    def htmx_redirect(self, url):
        if self.is_htmx:
            response = HttpResponse()
            response["HX-Redirect"] = url
            return response
        return redirect(url)

    def htmx_refresh(self):
        response = HttpResponse()
        response["HX-Refresh"] = "true"
        return response

    def trigger_event(self, response, event_name, detail=None):
        payload = {event_name: detail or {}}
        response["HX-Trigger"] = json.dumps(payload)
        return response
