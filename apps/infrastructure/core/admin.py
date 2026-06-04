from django.contrib import admin

from apps.infrastructure.core.config import PlatformConfig


@admin.register(PlatformConfig)
class PlatformConfigAdmin(admin.ModelAdmin):
    fieldsets = (
        ('Contact Details', {
            'fields': ('admin_whatsapp', 'admin_email', 'admin_phone')
        }),
        ('Bank Transfer', {
            'fields': ('bank_name', 'bank_account_number', 'bank_account_name')
        }),
        ('Company Info', {
            'fields': ('company_name', 'support_hours')
        }),
    )

    def has_add_permission(self, request):
        return not PlatformConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
