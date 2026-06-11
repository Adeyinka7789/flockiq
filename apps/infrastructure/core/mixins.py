from django.contrib.auth.mixins import AccessMixin, LoginRequiredMixin
from django.http import HttpResponse
from django.shortcuts import redirect, render


class RoleRequiredMixin(LoginRequiredMixin):
    """
    Enforces role-based access on class-based views.

    Set ``allowed_roles = ['owner', 'manager']`` on the view. The check runs in
    ``dispatch`` and therefore guards every HTTP method (GET, POST, …) on the
    view. Superadmins (``is_superuser``) bypass all role checks.

    For HTMX requests a small inline 403 fragment is returned so the modal /
    target swaps a friendly message; full-page requests render errors/403.html.
    """

    allowed_roles: list = []

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if request.user.is_superuser:
            return super().dispatch(request, *args, **kwargs)
        if self.allowed_roles and request.user.role not in self.allowed_roles:
            if request.headers.get('HX-Request'):
                return HttpResponse(
                    '<div class="bg-red-50 border border-red-200 '
                    'rounded-xl p-4 text-sm text-red-700">'
                    '🔒 You do not have permission to '
                    'perform this action.</div>',
                    status=403,
                )
            return render(
                request,
                'errors/403.html',
                {
                    'role': request.user.role,
                    'required_roles': self.allowed_roles,
                },
                status=403,
            )
        return super().dispatch(request, *args, **kwargs)


class SuperAdminMixin(AccessMixin):
    """Restricts view to super_admin role or is_superuser."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        if not (request.user.is_superuser or
                getattr(request.user, 'role', '') == 'super_admin'):
            return redirect('dashboard')
        return super().dispatch(request, *args, **kwargs)
