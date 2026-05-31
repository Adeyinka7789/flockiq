# Skill: Frontend — Django Templates + HTMX + Tailwind + Chart.js + PWA

## Philosophy
Server-rendered HTML with HTMX for dynamic interactions.
No React, no Vue. Fast to build, fast to load on Nigerian mobile connections.
PWA for offline field access — critical for farm workers with intermittent internet.

---

## Base Template
```html
<!-- templates/base/base.html -->
<!DOCTYPE html>
<html lang="en" class="h-full bg-gray-50">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{% block title %}FlockIQ{% endblock %}</title>
  <link rel="manifest" href="/static/pwa/manifest.json">
  <meta name="theme-color" content="#16a34a">
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://unpkg.com/htmx.org@1.9.10"></script>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <link rel="stylesheet" href="/static/css/flockiq.css">
</head>
<body class="h-full" hx-headers='{"X-CSRFToken": "{{ csrf_token }}"}'>
  <div class="flex h-full">
    {% include "base/partials/sidebar.html" %}
    <div class="flex-1 flex flex-col min-h-0 overflow-hidden">
      {% include "base/partials/topbar.html" %}
      <main class="flex-1 overflow-y-auto p-4 lg:p-6">
        {% if messages %}
          {% for message in messages %}
            <div class="mb-4 p-3 rounded-lg text-sm
              {% if message.tags == 'error' %}bg-red-50 text-red-800 border border-red-200
              {% elif message.tags == 'warning' %}bg-amber-50 text-amber-800 border border-amber-200
              {% else %}bg-green-50 text-green-800 border border-green-200{% endif %}">
              {{ message }}
            </div>
          {% endfor %}
        {% endif %}
        {% block content %}{% endblock %}
      </main>
    </div>
  </div>
  <script src="/static/js/app.js"></script>
  <script>
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('/static/pwa/service-worker.js');
    }
  </script>
  {% block extra_js %}{% endblock %}
</body>
</html>
```

---

## Key HTMX Patterns

### Live search
```html
<input type="text" name="q"
       hx-get="{% url 'farms:search' %}"
       hx-target="#search-results"
       hx-trigger="keyup changed delay:300ms"
       hx-indicator="#search-spinner"
       placeholder="Search farms..."
       class="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm">
<div id="search-spinner" class="htmx-indicator">Searching...</div>
<div id="search-results"></div>
```

### Form submission without page reload
```html
<form hx-post="{% url 'flocks:log_mortality' batch.id %}"
      hx-target="#mortality-list"
      hx-swap="afterbegin"
      hx-on::after-request="this.reset()">
  {% csrf_token %}
  ...
</form>
```

### Auto-refresh alerts panel every 60 seconds
```html
<div id="alerts-panel"
     hx-get="{% url 'analytics:alerts_panel' %}"
     hx-trigger="every 60s"
     hx-swap="innerHTML">
  {% include "analytics/partials/alerts_panel.html" %}
</div>
```

### Inline delete with confirmation
```html
<button hx-delete="{% url 'farms:delete' farm.id %}"
        hx-target="#farm-{{ farm.id }}"
        hx-swap="outerHTML"
        hx-confirm="Delete {{ farm.name }}? This cannot be undone."
        class="text-red-600 hover:text-red-800 text-sm">
  Delete
</button>
```

### Infinite scroll for data tables
```html
<tr id="sentinel"
    hx-get="{% url 'production:egg_logs' %}?page={{ next_page }}"
    hx-trigger="revealed"
    hx-target="#egg-table-body"
    hx-swap="beforeend">
  <td colspan="6" class="text-center py-4 text-gray-400 text-sm">Loading more...</td>
</tr>
```

---

## Chart.js Patterns

### Line chart with forecast overlay
```html
<div class="bg-white rounded-xl border border-gray-100 p-5">
  <h3 class="text-sm font-medium text-gray-500 mb-4">Egg production — actual vs forecast</h3>
  <div style="position: relative; height: 240px;">
    <canvas id="productionChart"></canvas>
  </div>
</div>
<script>
new Chart(document.getElementById('productionChart'), {
  type: 'line',
  data: {
    labels: {{ chart_labels|safe }},
    datasets: [
      {
        label: 'Actual',
        data: {{ actual_data|safe }},
        borderColor: '#16a34a',
        backgroundColor: 'rgba(22,163,74,0.08)',
        fill: true, tension: 0.3, pointRadius: 2,
      },
      {
        label: 'AI Forecast',
        data: {{ forecast_data|safe }},
        borderColor: '#60a5fa',
        borderDash: [5, 4],
        tension: 0.3, pointRadius: 0,
      }
    ]
  },
  options: {
    responsive: true, maintainAspectRatio: false,
    plugins: { legend: { position: 'top', labels: { font: { size: 11 } } } },
    scales: {
      x: { grid: { display: false }, ticks: { font: { size: 10 }, color: '#9ca3af' } },
      y: { grid: { color: '#f3f4f6' }, ticks: { font: { size: 10 }, color: '#9ca3af' } }
    }
  }
});
</script>
```

---

## Tailwind Color System for FlockIQ
```
Primary green:   bg-green-600 / text-green-600 / border-green-600
Success:         bg-green-50 / text-green-800
Warning:         bg-amber-50 / text-amber-800
Critical/Danger: bg-red-50 / text-red-800
Info:            bg-blue-50 / text-blue-800
Neutral:         bg-gray-50 / text-gray-600
```

---

## PWA Setup

```json
// static/pwa/manifest.json
{
  "name": "FlockIQ",
  "short_name": "FlockIQ",
  "description": "Poultry Farm Management Platform",
  "start_url": "/dashboard/",
  "display": "standalone",
  "background_color": "#ffffff",
  "theme_color": "#16a34a",
  "icons": [
    { "src": "/static/icons/icon-192.png", "sizes": "192x192", "type": "image/png" },
    { "src": "/static/icons/icon-512.png", "sizes": "512x512", "type": "image/png" }
  ]
}
```

```javascript
// static/pwa/service-worker.js
const CACHE = 'flockiq-v2';
const OFFLINE_PAGES = [
  '/dashboard/', '/flocks/batches/', '/production/eggs/log/',
  '/flocks/mortality/log/', '/water/log/', '/static/css/flockiq.css',
];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(OFFLINE_PAGES)));
});

self.addEventListener('fetch', e => {
  if (e.request.url.includes('/api/')) {
    // Network-first for API calls
    e.respondWith(fetch(e.request).catch(() => caches.match(e.request)));
  } else {
    // Cache-first for pages and static assets
    e.respondWith(caches.match(e.request).then(r => r || fetch(e.request)));
  }
});

// Background sync for offline form submissions
self.addEventListener('sync', e => {
  if (e.tag === 'sync-mortality') e.waitUntil(syncOfflineData('mortality'));
  if (e.tag === 'sync-eggs') e.waitUntil(syncOfflineData('eggs'));
  if (e.tag === 'sync-water') e.waitUntil(syncOfflineData('water'));
});
```

---

## RBAC Template Tags

```python
# apps/accounts/templatetags/rbac.py
from django import template
register = template.Library()

@register.simple_tag(takes_context=True)
def can_manage(context):
    user = context.get('request').user
    return hasattr(user, 'role') and user.role in ['owner', 'manager']

@register.simple_tag(takes_context=True)
def is_owner(context):
    user = context.get('request').user
    return hasattr(user, 'role') and user.role == 'owner'
```

```html
<!-- Usage in templates -->
{% load rbac %}
{% if can_manage %}
  <button class="btn-green">+ Add Farm</button>
{% endif %}
{% if is_owner %}
  <a href="{% url 'finance:reports' %}">View Financial Reports</a>
{% endif %}
```

---

## Mobile-First Form Pattern (for field workers)
```html
<!-- Log mortality — optimised for phone use -->
<div class="max-w-md mx-auto">
  <div class="bg-white rounded-xl border border-gray-100 p-5">
    <div class="mb-4">
      <label class="block text-sm font-medium text-gray-700 mb-1">
        Number of deaths today
      </label>
      <!-- Large touch target -->
      <input type="number" name="count" inputmode="numeric"
             class="w-full text-3xl text-center font-bold p-4 border-2 border-gray-200
                    rounded-xl focus:border-green-500 focus:outline-none"
             placeholder="0" min="0">
    </div>
    <!-- Large radio buttons for cause -->
    <div class="mb-4">
      <label class="block text-sm font-medium text-gray-700 mb-2">Cause</label>
      <div class="grid grid-cols-2 gap-2">
        {% for value, label in cause_choices %}
        <label class="flex items-center justify-center p-3 border-2 border-gray-200
                       rounded-xl cursor-pointer has-[:checked]:border-green-500
                       has-[:checked]:bg-green-50 text-sm font-medium">
          <input type="radio" name="cause" value="{{ value }}" class="sr-only">
          {{ label }}
        </label>
        {% endfor %}
      </div>
    </div>
    <button type="submit"
            class="w-full bg-green-600 text-white py-4 rounded-xl font-medium text-lg
                   active:scale-95 transition-transform">
      Save Record
    </button>
  </div>
</div>
```
