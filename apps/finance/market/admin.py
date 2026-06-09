from django.contrib import admin

from .models import FeedPriceReport, Hatchery, HatcheryReview, MarketPrice, SeasonalDemandIndex


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


@admin.register(FeedPriceReport)
class FeedPriceReportAdmin(admin.ModelAdmin):
    list_display = ["reported_date", "feed_type", "brand", "price_per_25kg_bag", "state", "lga"]
    list_filter = ["feed_type", "brand", "state"]
    search_fields = ["state", "lga"]
    date_hierarchy = "reported_date"
    readonly_fields = ["submitted_by", "org", "reported_date", "created_at"]


@admin.register(Hatchery)
class HatcheryAdmin(admin.ModelAdmin):
    list_display = ["name", "state", "lga", "is_verified", "created_at"]
    list_filter = ["state", "is_verified"]
    search_fields = ["name", "state", "lga"]
    list_editable = ["is_verified"]
    readonly_fields = ["added_by", "created_at"]


@admin.register(HatcheryReview)
class HatcheryReviewAdmin(admin.ModelAdmin):
    list_display = ["hatchery", "overall_rating", "doc_quality_rating", "survival_rate_pct", "created_at"]
    list_filter = ["overall_rating", "hatchery__state"]
    search_fields = ["hatchery__name", "comment"]
    readonly_fields = ["submitted_by", "org", "batch", "created_at"]
