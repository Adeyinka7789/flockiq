from django.urls import path

from . import views

app_name = 'superadmin'

urlpatterns = [
    path('superadmin/', views.SuperAdminDashboardView.as_view(), name='dashboard'),
    path('superadmin/tenants/', views.SuperAdminTenantsView.as_view(), name='tenants'),
    path('superadmin/tenants/<uuid:pk>/action/', views.SuperAdminTenantActionView.as_view(), name='tenant_action'),
    path('superadmin/analytics/', views.SuperAdminAnalyticsView.as_view(), name='analytics'),
    path('superadmin/broadcast/', views.BroadcastCreateView.as_view(), name='broadcast'),
    path('superadmin/broadcasts/', views.BroadcastHistoryView.as_view(), name='broadcast_history'),
    path('superadmin/billing/', views.BillingControlView.as_view(), name='billing'),
    path('superadmin/billing/<uuid:pk>/manage/', views.BillingManageOrgView.as_view(), name='billing_manage'),
    path('superadmin/audit/', views.AuditTrailView.as_view(), name='audit_trail'),
    path('superadmin/quotas/', views.TenantQuotasView.as_view(), name='tenant_quotas'),
    path('superadmin/quotas/<uuid:pk>/edit/', views.TenantQuotaEditView.as_view(), name='quota_edit'),
    path('superadmin/impersonation/', views.ImpersonationView.as_view(), name='impersonation'),
    path('superadmin/impersonate/<uuid:user_pk>/start/', views.ImpersonateStartView.as_view(), name='impersonate_start'),
    path('superadmin/impersonate/stop/', views.ImpersonateStopView.as_view(), name='impersonate_stop'),
    path('superadmin/system-health/', views.SystemHealthView.as_view(), name='system_health'),
]
