from django.contrib.auth.mixins import AccessMixin
from django.shortcuts import redirect


class SuperAdminMixin(AccessMixin):
    """Restricts view to super_admin role or is_superuser."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        if not (request.user.is_superuser or
                getattr(request.user, 'role', '') == 'super_admin'):
            return redirect('dashboard')
        return super().dispatch(request, *args, **kwargs)
