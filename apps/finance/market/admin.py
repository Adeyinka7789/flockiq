from django.contrib import admin

from .models import MarketPrice, SeasonalDemandIndex


@admin.register(MarketPrice)
class MarketPriceAdmin(admin.ModelAdmin):
    list_display = ["date", "product_type", "price_per_unit_kobo", "unit", "market_name", "region"]
    list_filter = ["product_type", "region"]
    date_hierarchy = "date"


@admin.register(SeasonalDemandIndex)
class SeasonalDemandIndexAdmin(admin.ModelAdmin):
    list_display = ["month", "product_type", "demand_index", "notes"]
    list_filter = ["product_type"]
    ordering = ["product_type", "month"]
