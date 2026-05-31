from django.contrib import admin

from .models import WeatherAlert, WeatherCache


@admin.register(WeatherCache)
class WeatherCacheAdmin(admin.ModelAdmin):
    list_display = ["farm_id", "fetched_at"]
    readonly_fields = ["fetched_at"]


@admin.register(WeatherAlert)
class WeatherAlertAdmin(admin.ModelAdmin):
    list_display = ["farm", "alert_type", "severity", "created_at", "acknowledged_at"]
    list_filter = ["alert_type", "severity"]
    readonly_fields = ["created_at", "acknowledged_at"]
