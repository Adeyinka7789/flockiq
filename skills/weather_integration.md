# Skill: Weather Integration — OpenWeatherMap

## Overview
FlockIQ fetches daily weather per farm GPS every 6 hours via Celery Beat.
Threshold breaches create WeatherAlert records and push outbox events for SMS delivery.

## Thresholds
- Heat stress: temperature > 32°C (critical for birds)
- High humidity: humidity > 85% (feed mould risk)
- Heavy rain: precipitation > 10mm forecast (biosecurity risk)

## API Call Pattern
```python
# One call per farm per 6 hours
# 200 farms × 4 refreshes/day = 800 calls/day (within free tier limit of 1000/day)

GET https://api.openweathermap.org/data/2.5/forecast
  ?lat={farm.latitude}
  &lon={farm.longitude}
  &appid={OPENWEATHERMAP_API_KEY}
  &units=metric
  &cnt=8  # 8 × 3hr intervals = 24 hours
```

## Caching Pattern
```python
# Check Redis before making API call
import redis
from django.core.cache import cache

cache_key = f"weather:{farm_id}"
cached = cache.get(cache_key)
if cached:
    return cached

# Fetch from API
data = fetch_from_openweathermap(lat, lng)

# Cache for 6 hours
cache.set(cache_key, data, timeout=6 * 3600)

# Also write to WeatherCache DB table for historical analysis
WeatherCache.objects.update_or_create(farm_id=farm_id, defaults={...})
```

## Alert Message Templates
```python
WEATHER_MESSAGES = {
    'heat_stress': "HEAT ALERT: {temp:.0f}°C at {farm_name}. Increase ventilation NOW. Add extra water points. Reduce bird density if possible.",
    'high_humidity': "HUMIDITY ALERT: {humidity:.0f}% at {farm_name}. Check feed storage for mould. Ensure litter is dry.",
    'heavy_rain': "RAIN ALERT at {farm_name}. Check roof drainage. Prevent water seepage into houses. Biosecurity: disinfect entry points.",
}
```

## Django Settings
```python
# config/settings/base.py
OPENWEATHERMAP_API_KEY = env('OPENWEATHERMAP_API_KEY')
OPENWEATHERMAP_BASE_URL = 'https://api.openweathermap.org/data/2.5'

WEATHER_THRESHOLDS = {
    'heat_stress_celsius': 32,
    'high_humidity_pct': 85,
    'heavy_rain_mm': 10,
}
```

## GPS Required at Farm Creation
```python
# Farm model — both fields required, not nullable
latitude = models.DecimalField(max_digits=10, decimal_places=7)
longitude = models.DecimalField(max_digits=10, decimal_places=7)

# Form validation
class FarmForm(forms.ModelForm):
    class Meta:
        model = Farm
        fields = ['name', 'location', 'latitude', 'longitude']

    def clean(self):
        lat = self.cleaned_data.get('latitude')
        lng = self.cleaned_data.get('longitude')
        # Nigeria bounding box validation
        if lat and (lat < 4.0 or lat > 14.0):
            raise forms.ValidationError("Latitude must be within Nigeria (4°N to 14°N)")
        if lng and (lng < 2.7 or lng > 15.0):
            raise forms.ValidationError("Longitude must be within Nigeria (2.7°E to 15°E)")
        return self.cleaned_data
```
