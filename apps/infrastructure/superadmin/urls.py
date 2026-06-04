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
]
