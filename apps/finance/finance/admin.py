from auditlog.registry import auditlog
from django.contrib import admin

from .models import BatchFinancialSummary, SalesRecord

auditlog.register(SalesRecord)


@admin.register(SalesRecord)
class SalesRecordAdmin(admin.ModelAdmin):
    list_display = ["sale_date", "product_type", "quantity", "unit", "unit_price_kobo", "total_revenue_kobo", "buyer_name"]
    list_filter = ["product_type", "sale_date"]
    search_fields = ["buyer_name", "notes"]
    date_hierarchy = "sale_date"


@admin.register(BatchFinancialSummary)
class BatchFinancialSummaryAdmin(admin.ModelAdmin):
    list_display = ["batch", "total_revenue_kobo", "total_expenses_kobo", "gross_profit_kobo", "profit_margin_pct", "roi_pct"]
    readonly_fields = ["last_updated"]
