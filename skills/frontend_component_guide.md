# FlockIQ — Frontend Component Guide
## `skills/frontend_component_guide.md`

**Version:** 1.0  
**Date:** April 2026  
**Author:** ADM Tech Hub — Lead Systems Architecture  
**Stack:** Django 5.x Templates · HTMX 2.x · Tailwind CSS 3.x · Alpine.js 3.x · Chart.js 4.x  
**Companion to:** `skills/system_architectures.md` · `skills/api_contract.md`

---

## Table of Contents

1. [Design System](#1-design-system)
2. [Project Structure](#2-project-structure)
3. [Base Templates & Layout](#3-base-templates--layout)
4. [HTMX Interaction Patterns](#4-htmx-interaction-patterns)
5. [Alpine.js Client-State Patterns](#5-alpinejs-client-state-patterns)
6. [Core UI Components](#6-core-ui-components)
7. [Form Components & Validation](#7-form-components--validation)
8. [Data Display Components](#8-data-display-components)
9. [Chart Components](#9-chart-components)
10. [Notification & Alert Components](#10-notification--alert-components)
11. [Dashboard Layout Patterns](#11-dashboard-layout-patterns)
12. [PWA & Offline UI Patterns](#12-pwa--offline-ui-patterns)
13. [Django Template Tags & Filters](#13-django-template-tags--filters)
14. [Tailwind Configuration](#14-tailwind-configuration)
15. [Performance Patterns](#15-performance-patterns)
16. [Accessibility Checklist](#16-accessibility-checklist)

---

## 1. Design System

### 1.1 Design Principles

FlockIQ serves **farm managers and workers in rural Nigeria**, often on low-end Android phones, intermittent 3G/4G, and bright sunlight conditions. Every component decision must serve this user before desktop aesthetics.

| Principle | What it means in practice |
|---|---|
| **Data-dense but scannable** | Pack information; use colour and size hierarchy aggressively to guide eyes |
| **Touch-first** | Minimum 44px touch targets. No hover-only interactions. |
| **Offline-tolerant** | Visual feedback when offline. No silent failures. |
| **Low-data friendly** | HTMX partial loads. No full-page JS bundles per route. |
| **Sunlight-readable** | High contrast ratios (≥ 4.5:1). Avoid light-on-light. |

### 1.2 Colour Palette

```css
/* tailwind.config.js — custom colours */

colors: {
  /* Brand */
  'flock-green':  { 50: '#f0fdf4', 500: '#22c55e', 600: '#16a34a', 700: '#15803d', 900: '#14532d' },
  'flock-amber':  { 50: '#fffbeb', 500: '#f59e0b', 600: '#d97706', 700: '#b45309' },
  'flock-red':    { 50: '#fef2f2', 500: '#ef4444', 600: '#dc2626', 700: '#b91c1c' },
  'flock-blue':   { 50: '#eff6ff', 500: '#3b82f6', 600: '#2563eb', 700: '#1d4ed8' },

  /* Neutral — warm grey to suit earthy farm context */
  'earth': {
    50:  '#fafaf9',
    100: '#f5f5f4',
    200: '#e7e5e4',
    300: '#d6d3d1',
    400: '#a8a29e',
    500: '#78716c',
    600: '#57534e',
    700: '#44403c',
    800: '#292524',
    900: '#1c1917',
  },
}
```

### 1.3 Typography Scale

```html
<!-- Heading sizes — always use semantic heading tags -->
<h1 class="text-2xl font-bold text-earth-900">Farm Overview</h1>      <!-- Page title -->
<h2 class="text-xl font-semibold text-earth-800">Active Batches</h2>  <!-- Section title -->
<h3 class="text-base font-semibold text-earth-700">House A</h3>       <!-- Card title -->

<!-- Body text -->
<p class="text-sm text-earth-600 leading-relaxed">...</p>              <!-- Secondary body -->
<p class="text-base text-earth-800">...</p>                            <!-- Primary body -->

<!-- Data values — numbers should be larger and bolder than labels -->
<span class="text-2xl font-bold text-earth-900 tabular-nums">4,812</span>
<span class="text-xs text-earth-500 uppercase tracking-wide">Live Birds</span>
```

### 1.4 Spacing & Sizing

```html
<!-- Touch targets: minimum 44px height on all interactive elements -->
<button class="min-h-[44px] px-4 py-2.5 ...">Submit</button>

<!-- Card padding: 16px mobile, 24px desktop -->
<div class="p-4 md:p-6 rounded-xl bg-white shadow-sm border border-earth-200">

<!-- Stack spacing within cards -->
<div class="space-y-3">   <!-- Tight: related items -->
<div class="space-y-5">   <!-- Normal: section items -->
<div class="space-y-8">   <!-- Loose: major sections -->
```

### 1.5 Elevation (Shadow System)

```html
<!-- Level 0: flat — inline elements, table rows -->
<!-- Level 1: card — default content container -->
<div class="shadow-sm border border-earth-200 rounded-xl">

<!-- Level 2: raised — highlighted or hovered cards -->
<div class="shadow-md border border-earth-200 rounded-xl">

<!-- Level 3: modal — overlays and drawers -->
<div class="shadow-xl border border-earth-300 rounded-2xl">
```

---

## 2. Project Structure

```
templates/
├── base/
│   ├── _base.html              # Root shell: meta, CSS, HTMX, Alpine CDN
│   ├── _sidebar.html           # Navigation sidebar
│   ├── _topbar.html            # Top bar: farm selector, user menu, notifications bell
│   ├── _messages.html          # Django messages → HTMX toast bridge
│   └── _pwa_meta.html          # PWA manifest link, theme-color, viewport
│
├── components/
│   ├── ui/
│   │   ├── _button.html        # Button variants
│   │   ├── _badge.html         # Status badges
│   │   ├── _card.html          # Card shell
│   │   ├── _modal.html         # Modal shell + HTMX swap target
│   │   ├── _empty_state.html   # Empty list / zero-data states
│   │   ├── _spinner.html       # HTMX loading indicator
│   │   └── _stat_card.html     # KPI number card
│   │
│   ├── forms/
│   │   ├── _field.html         # Single form field (label + input + error)
│   │   ├── _select.html        # Select with Alpine search
│   │   ├── _date_input.html    # Native date picker
│   │   └── _form_errors.html   # Non-field errors
│   │
│   ├── data/
│   │   ├── _table.html         # Data table shell
│   │   ├── _pagination.html    # Cursor pagination controls
│   │   └── _chart_card.html    # Chart.js wrapper card
│   │
│   └── domain/
│       ├── _batch_card.html    # Batch summary card
│       ├── _mortality_row.html # Table row for mortality logs
│       ├── _metric_pill.html   # FCR / Hen-Day % pill with rating colour
│       └── _alert_banner.html  # Weather / anomaly alert banner
│
├── partials/                   # HTMX swap targets — fragments, not full pages
│   ├── batch_list.html
│   ├── mortality_list.html
│   ├── feed_log_list.html
│   ├── notification_dropdown.html
│   └── dashboard_stats.html
│
└── pages/                      # Full page views (extend _base.html)
    ├── dashboard.html
    ├── batches/
    │   ├── list.html
    │   ├── detail.html
    │   └── create.html
    ├── health/
    ├── finance/
    └── settings/
```

---

## 3. Base Templates & Layout

### 3.1 `templates/base/_base.html`

```html
<!DOCTYPE html>
<html lang="en" class="h-full" x-data="flockApp()" x-init="initApp()">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
  <meta name="theme-color" content="#15803d">

  {% include "base/_pwa_meta.html" %}

  <title>{% block title %}FlockIQ{% endblock %} — FlockIQ</title>

  {# Tailwind production build — from collectstatic #}
  <link rel="stylesheet" href="{% static 'dist/output.css' %}">

  {# HTMX 2.x — loaded from staticfiles, not CDN, for offline PWA support #}
  <script src="{% static 'js/htmx.min.js' %}" defer></script>

  {# Alpine.js — lightweight reactivity for client state only #}
  <script src="{% static 'js/alpine.min.js' %}" defer></script>

  {# Chart.js — lazy loaded only on pages that need it #}
  {% block extra_head %}{% endblock %}
</head>

<body class="h-full bg-earth-50 text-earth-900 antialiased"
      hx-headers='{"X-CSRFToken": "{{ csrf_token }}"}'
      hx-boost="true">

  {# Offline indicator — shown by Alpine when navigator.onLine = false #}
  <div x-show="!online"
       x-transition
       class="fixed top-0 inset-x-0 z-50 bg-flock-amber-500 text-white
              text-sm text-center py-2 font-medium">
    You're offline. Data entry will sync when you reconnect.
  </div>

  <div class="flex h-full">
    {% include "base/_sidebar.html" %}

    <div class="flex-1 flex flex-col min-w-0 overflow-hidden">
      {% include "base/_topbar.html" %}

      {# HTMX toast notification target — always present in DOM #}
      <div id="toast-container"
           class="fixed bottom-4 right-4 z-40 space-y-2 pointer-events-none"
           aria-live="polite">
      </div>

      {# Main content area #}
      <main id="main-content"
            class="flex-1 overflow-y-auto focus:outline-none"
            tabindex="-1">
        <div class="px-4 py-6 sm:px-6 lg:px-8 max-w-7xl mx-auto">
          {% block content %}{% endblock %}
        </div>
      </main>
    </div>
  </div>

  {# Global modal target — HTMX swaps modal content here #}
  <div id="modal-container"></div>

  {# Django messages → Alpine toast bridge #}
  {% include "base/_messages.html" %}

  <script src="{% static 'js/app.js' %}" defer></script>
  {% block extra_scripts %}{% endblock %}
</body>
</html>
```

### 3.2 `templates/base/_sidebar.html`

```html
{# Sidebar — hidden on mobile (toggled by Alpine), always visible on lg+ and can be closed#}
<div class="hidden lg:flex lg:flex-shrink-0">
  <div class="flex flex-col w-64 bg-earth-900">

    {# Logo #}
    <div class="flex items-center h-16 px-6 border-b border-earth-800">
      <span class="text-xl font-bold text-white tracking-tight">🐔 FlockIQ</span>
    </div>

    {# Farm selector #}
    <div class="px-4 py-3 border-b border-earth-800" x-data="farmSelector()">
      <button @click="open = !open"
              class="w-full flex items-center justify-between px-3 py-2
                     rounded-lg bg-earth-800 text-earth-100 text-sm
                     hover:bg-earth-700 transition-colors min-h-[44px]">
        <span class="font-medium truncate" x-text="currentFarm.name"></span>
        <svg class="w-4 h-4 flex-shrink-0 transition-transform" :class="{'rotate-180': open}"
             fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
        </svg>
      </button>
      <div x-show="open" x-transition @click.outside="open = false"
           class="mt-1 rounded-lg bg-earth-800 shadow-lg overflow-hidden">
        <template x-for="farm in farms" :key="farm.id">
          <button @click="selectFarm(farm)"
                  class="w-full px-4 py-2.5 text-left text-sm text-earth-200
                         hover:bg-earth-700 transition-colors"
                  :class="{'bg-earth-700 text-white font-medium': farm.id === currentFarm.id}"
                  x-text="farm.name">
          </button>
        </template>
      </div>
    </div>

    {# Navigation #}
    <nav class="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
      {% with request.resolver_match.url_name as url_name %}

      {% for item in nav_items %}
      <a href="{% url item.url_name %}"
         class="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm
                transition-colors min-h-[44px]
                {% if url_name == item.url_name %}
                  bg-flock-green-600 text-white font-medium
                {% else %}
                  text-earth-400 hover:bg-earth-800 hover:text-earth-100
                {% endif %}">
        <span class="flex-shrink-0">{{ item.icon|safe }}</span>
        {{ item.label }}
        {% if item.badge %}
        <span class="ml-auto bg-flock-amber-500 text-white text-xs
                     font-medium px-1.5 py-0.5 rounded-full">
          {{ item.badge }}
        </span>
        {% endif %}
      </a>
      {% endfor %}

      {% endwith %}
    </nav>

    {# User menu — bottom of sidebar #}
    <div class="px-4 py-4 border-t border-earth-800">
      <div class="flex items-center gap-3">
        <div class="w-9 h-9 rounded-full bg-flock-green-600 flex items-center
                    justify-center text-white font-semibold text-sm flex-shrink-0">
          {{ request.user.initials }}
        </div>
        <div class="min-w-0">
          <p class="text-sm font-medium text-earth-100 truncate">{{ request.user.get_full_name }}</p>
          <p class="text-xs text-earth-500 truncate capitalize">{{ request.user.role }}</p>
        </div>
        <a href="{% url 'auth:logout' %}"
           class="ml-auto p-2 text-earth-500 hover:text-earth-300 transition-colors rounded-lg
                  hover:bg-earth-800 min-h-[44px] flex items-center"
           title="Log out">
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                  d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1"/>
          </svg>
        </a>
      </div>
    </div>

  </div>
</div>
```

---

## 4. HTMX Interaction Patterns

### 4.1 The Three HTMX Rules for FlockIQ

```
RULE 1 — Views return fragments for HTMX, full pages for non-HTMX.
         Use the HtmxMixin (below) on every view. Never write two views for one action.

RULE 2 — POST always returns the updated fragment, never a redirect.
         Django's Post-Redirect-Get is for non-JS browsers only.
         HTMX clients get the new HTML directly in the response.

RULE 3 — Error responses (400, 422) return the form fragment with errors.
         HTMX re-swaps the form with inline validation messages.
         Never redirect on error.
```

### 4.2 HtmxMixin — View Base Class

```python
# apps/infrastructure/core/views.py

from django.http import HttpResponse
from django.shortcuts import render


class HtmxMixin:
    """
    Mixin for all views that serve both full pages and HTMX partials.

    Provides:
    - htmx_template: fragment template used for HTMX requests
    - full_template:  full page template for direct navigation
    - Automatic HTMX request detection
    - OOB (Out-of-Band) swap helpers for updating multiple page regions

    Usage:
        class BatchListView(HtmxMixin, ListView):
            full_template   = "pages/batches/list.html"
            htmx_template   = "partials/batch_list.html"
    """

    htmx_template = None   # Fragment returned to HTMX
    full_template = None   # Full page for direct navigation

    @property
    def is_htmx(self):
        return self.request.headers.get("HX-Request") == "true"

    def get_template_names(self):
        if self.is_htmx and self.htmx_template:
            return [self.htmx_template]
        return [self.full_template or super().get_template_names()[0]]

    def render_htmx_fragment(self, template_name, context, status=200):
        """Render a named fragment with optional OOB swaps."""
        return render(self.request, template_name, context, status=status)

    def htmx_redirect(self, url):
        """HTMX-aware redirect — uses HX-Redirect header instead of 302."""
        if self.is_htmx:
            response = HttpResponse()
            response["HX-Redirect"] = url
            return response
        from django.shortcuts import redirect
        return redirect(url)

    def htmx_refresh(self):
        """Tell HTMX to do a full page refresh."""
        response = HttpResponse()
        response["HX-Refresh"] = "true"
        return response

    def trigger_event(self, response, event_name, detail=None):
        """
        Attach an HX-Trigger header to fire a client-side event.
        Used to update other page regions without OOB swaps.

        Example: after saving a mortality log, trigger a dashboard stats refresh.
        """
        import json
        payload = {event_name: detail or {}}
        response["HX-Trigger"] = json.dumps(payload)
        return response
```

### 4.3 List with Live Search & Pagination

```html
{# templates/pages/batches/list.html #}
{% extends "base/_base.html" %}

{% block content %}
<div class="space-y-5">

  {# Page header #}
  <div class="flex items-center justify-between">
    <h1 class="text-2xl font-bold text-earth-900">Batches</h1>
    <a href="{% url 'batches:create' %}"
       class="inline-flex items-center gap-2 px-4 py-2.5 bg-flock-green-600
              text-white text-sm font-medium rounded-lg hover:bg-flock-green-700
              transition-colors min-h-[44px]">
      <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/>
      </svg>
      New Batch
    </a>
  </div>

  {# Live search — triggers HTMX request on input with 400ms debounce #}
  <div class="relative">
    <svg class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-earth-400 pointer-events-none"
         fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
            d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0"/>
    </svg>
    <input type="search"
           name="q"
           placeholder="Search batches..."
           class="w-full pl-10 pr-4 py-2.5 rounded-lg border border-earth-300
                  bg-white text-earth-900 placeholder-earth-400 text-sm
                  focus:outline-none focus:ring-2 focus:ring-flock-green-500
                  focus:border-transparent min-h-[44px]"
           hx-get="{% url 'batches:list' %}"
           hx-target="#batch-list"
           hx-swap="innerHTML"
           hx-trigger="input changed delay:400ms, search"
           hx-push-url="true"
           value="{{ request.GET.q }}">
  </div>

  {# Filter pills #}
  <div class="flex gap-2 flex-wrap">
    {% for status, label in status_choices %}
    <a href="?status={{ status }}"
       hx-get="{% url 'batches:list' %}?status={{ status }}"
       hx-target="#batch-list"
       hx-swap="innerHTML"
       hx-push-url="true"
       class="px-3 py-1.5 rounded-full text-sm font-medium transition-colors
              {% if current_status == status %}
                bg-flock-green-600 text-white
              {% else %}
                bg-earth-100 text-earth-600 hover:bg-earth-200
              {% endif %}">
      {{ label }}
    </a>
    {% endfor %}
  </div>

  {# Batch list — HTMX swap target #}
  <div id="batch-list">
    {% include "partials/batch_list.html" %}
  </div>

</div>
{% endblock %}
```

```html
{# templates/partials/batch_list.html — the HTMX fragment #}

{% if batches %}
  <div class="space-y-3">
    {% for batch in batches %}
      {% include "components/domain/_batch_card.html" with batch=batch %}
    {% endfor %}
  </div>

  {# Pagination — also HTMX-aware #}
  {% include "components/data/_pagination.html" %}

{% else %}
  {% include "components/ui/_empty_state.html" with
    icon="🐔"
    title="No batches found"
    message="Place your first batch to get started."
    action_url=batches_create_url
    action_label="Place a Batch"
  %}
{% endif %}
```

### 4.4 Form Submit Pattern (Create / Edit)

```html
{# templates/pages/batches/create.html #}
{% extends "base/_base.html" %}
{% block content %}

<div class="max-w-2xl mx-auto space-y-6">
  <h1 class="text-2xl font-bold text-earth-900">Place New Batch</h1>

  {# Form — HTMX posts to same URL. On success: HX-Redirect. On error: re-render form. #}
  <form hx-post="{% url 'batches:create' %}"
        hx-target="#create-form"
        hx-swap="outerHTML"
        hx-indicator="#form-spinner"
        id="create-form"
        class="bg-white rounded-xl shadow-sm border border-earth-200 p-6 space-y-5">

    {% csrf_token %}

    {% include "components/forms/_form_errors.html" with form=form %}

    {# House selector #}
    {% include "components/forms/_field.html" with
      field=form.house_id
      label="Poultry House"
      help="Select the house where birds will be placed."
    %}

    <div class="grid grid-cols-2 gap-4">
      {# Bird type #}
      {% include "components/forms/_select.html" with
        field=form.bird_type
        label="Bird Type / Breed"
      %}

      {# Initial count #}
      {% include "components/forms/_field.html" with
        field=form.initial_count
        label="Number of Birds"
        type="number"
        min="1"
        max="100000"
      %}
    </div>

    {# Placement date #}
    {% include "components/forms/_date_input.html" with
      field=form.placement_date
      label="Placement Date"
      max=today
    %}

    {# Cost per bird #}
    {% include "components/forms/_field.html" with
      field=form.cost_per_bird
      label="Cost per Bird (₦)"
      type="number"
      step="0.01"
      help="Purchase price per chick or pullet."
    %}

    {# Notes #}
    <div>
      <label class="block text-sm font-medium text-earth-700 mb-1.5">Notes (optional)</label>
      <textarea name="notes" rows="3"
                class="w-full rounded-lg border border-earth-300 px-3 py-2.5
                       text-sm text-earth-900 placeholder-earth-400
                       focus:outline-none focus:ring-2 focus:ring-flock-green-500
                       focus:border-transparent resize-none">{{ form.notes.value|default:'' }}</textarea>
    </div>

    {# Submit row #}
    <div class="flex items-center justify-between pt-2">
      <a href="{% url 'batches:list' %}"
         class="text-sm text-earth-500 hover:text-earth-700 transition-colors">
        Cancel
      </a>
      <button type="submit"
              class="inline-flex items-center gap-2 px-6 py-2.5 bg-flock-green-600
                     text-white text-sm font-medium rounded-lg hover:bg-flock-green-700
                     transition-colors min-h-[44px] disabled:opacity-50"
              hx-disabled-elt="this">
        <span id="form-spinner" class="htmx-indicator">
          {% include "components/ui/_spinner.html" with size="sm" %}
        </span>
        Place Batch
      </button>
    </div>

  </form>
</div>

{% endblock %}
```

```python
# apps/farm/flocks/views.py

from django.views.generic import CreateView
from apps.infrastructure.core.views import HtmxMixin


class BatchCreateView(HtmxMixin, CreateView):
    form_class = BatchPlacementForm
    full_template = "pages/batches/create.html"

    def form_valid(self, form):
        batch = BatchService(self.request.org).place_batch(**form.cleaned_data)
        if self.is_htmx:
            return self.htmx_redirect(reverse("batches:detail", args=[batch.id]))
        return redirect("batches:detail", pk=batch.id)

    def form_invalid(self, form):
        # Return the form fragment with errors — HTMX swaps outerHTML of #create-form
        status = 422  # Signals error to HTMX (prevents history push on re-render)
        return self.render_htmx_fragment(
            "pages/batches/create.html",
            {"form": form},
            status=status,
        )
```

### 4.5 Inline Edit Pattern (Partial Update)

```html
{# Mortality log row — inline edit triggered by HTMX #}
<tr id="mortality-{{ log.id }}"
    class="border-b border-earth-100 hover:bg-earth-50 transition-colors">
  <td class="px-4 py-3 text-sm text-earth-900">{{ log.date|date:"M j" }}</td>
  <td class="px-4 py-3">
    <span class="text-xl font-bold text-flock-red-600 tabular-nums">{{ log.count }}</span>
  </td>
  <td class="px-4 py-3 text-sm text-earth-600 capitalize">{{ log.cause }}</td>
  <td class="px-4 py-3 text-sm text-earth-500">{{ log.notes|truncatewords:8 }}</td>
  <td class="px-4 py-3 text-right">
    <button hx-get="{% url 'batches:mortality-edit' batch.id log.id %}"
            hx-target="#mortality-{{ log.id }}"
            hx-swap="outerHTML"
            class="text-xs text-earth-400 hover:text-flock-green-600
                   transition-colors px-2 py-1 rounded min-h-[44px]">
      Edit
    </button>
  </td>
</tr>
```

### 4.6 Out-of-Band (OOB) Swaps

OOB swaps update multiple page regions from a single HTMX response — no JavaScript needed.

```html
{# After logging mortality, update the batch stats AND the mortality list #}
{# views.py returns this combined fragment #}

{# Primary swap target: the mortality list #}
{% include "partials/mortality_list.html" %}

{# OOB swap: update the batch metrics bar at the top of the page #}
<div id="batch-metrics" hx-swap-oob="true">
  {% include "components/domain/_batch_metrics_bar.html" with batch=batch %}
</div>

{# OOB swap: update the live bird count in the sidebar stat #}
<span id="live-bird-count" hx-swap-oob="true"
      class="tabular-nums font-bold text-flock-green-600">
  {{ batch.current_count|intcomma }}
</span>
```

### 4.7 Modal Pattern

```html
{# Open modal via HTMX — loads content from server into #modal-container #}
<button hx-get="{% url 'batches:close-modal' batch.id %}"
        hx-target="#modal-container"
        hx-swap="innerHTML"
        class="...">
  Close Batch
</button>
```

```html
{# templates/components/ui/_modal.html — included in the HTMX response #}
<div x-data="{ open: true }"
     x-init="$nextTick(() => open = true)"
     @keydown.escape.window="open = false; $el.remove()"
     class="fixed inset-0 z-50 overflow-y-auto">

  {# Backdrop #}
  <div x-show="open"
       x-transition:enter="ease-out duration-200"
       x-transition:enter-start="opacity-0"
       x-transition:enter-end="opacity-100"
       x-transition:leave="ease-in duration-150"
       x-transition:leave-start="opacity-100"
       x-transition:leave-end="opacity-0"
       @click="open = false; $el.closest('[x-data]').remove()"
       class="fixed inset-0 bg-earth-900/50 backdrop-blur-sm">
  </div>

  {# Panel #}
  <div class="relative flex min-h-full items-end sm:items-center justify-center p-4">
    <div x-show="open"
         x-transition:enter="ease-out duration-200"
         x-transition:enter-start="opacity-0 translate-y-4 sm:translate-y-0 sm:scale-95"
         x-transition:enter-end="opacity-100 translate-y-0 sm:scale-100"
         class="relative w-full max-w-lg bg-white rounded-2xl shadow-xl p-6">

      <div class="flex items-center justify-between mb-5">
        <h3 class="text-lg font-semibold text-earth-900">{% block modal_title %}{% endblock %}</h3>
        <button @click="open = false; $el.closest('[x-data]').remove()"
                class="p-2 text-earth-400 hover:text-earth-600 transition-colors
                       rounded-lg hover:bg-earth-100 min-h-[44px]">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
          </svg>
        </button>
      </div>

      {% block modal_body %}{% endblock %}

    </div>
  </div>
</div>
```

---

## 5. Alpine.js Client-State Patterns

Alpine handles **client-only state** — things that don't require a server round-trip. HTMX handles server communication. The two never overlap.

```
Alpine:  toggle menus, tabs, show/hide, client validation, character counts
HTMX:    loading data, submitting forms, live search, partial page updates
```

### 5.1 Global App State (`app.js`)

```javascript
// static/js/app.js

function flockApp() {
  return {
    // Online/offline state — drives the banner in _base.html
    online: navigator.onLine,

    // Mobile sidebar toggle
    sidebarOpen: false,

    // Toast queue
    toasts: [],

    initApp() {
      window.addEventListener('online',  () => this.online = true);
      window.addEventListener('offline', () => this.online = false);

      // Listen for HTMX-triggered toast events
      document.body.addEventListener('showToast', (e) => {
        this.addToast(e.detail.message, e.detail.type || 'success');
      });

      // Register service worker
      if ('serviceWorker' in navigator) {
        navigator.serviceWorker.register('/sw.js').catch(console.error);
      }
    },

    addToast(message, type = 'success') {
      const id = Date.now();
      this.toasts.push({ id, message, type });
      setTimeout(() => this.removeToast(id), 4000);
    },

    removeToast(id) {
      this.toasts = this.toasts.filter(t => t.id !== id);
    },
  };
}


function farmSelector() {
  return {
    open: false,
    farms: JSON.parse(document.getElementById('farm-data')?.textContent || '[]'),
    currentFarm: JSON.parse(localStorage.getItem('currentFarm') || 'null') || {},

    selectFarm(farm) {
      this.currentFarm = farm;
      this.open = false;
      localStorage.setItem('currentFarm', JSON.stringify(farm));
      // Reload dashboard data for new farm context
      htmx.trigger('#main-content', 'farmChanged');
    },
  };
}
```

### 5.2 Confirmation Dialog Pattern

```html
{# Reusable confirmation for destructive actions #}
<div x-data="{ confirming: false }">
  <button @click="confirming = true"
          class="text-sm text-flock-red-600 hover:text-flock-red-700 font-medium
                 px-3 py-2 rounded-lg hover:bg-flock-red-50 transition-colors min-h-[44px]"
          :disabled="confirming">
    <template x-if="!confirming">
      <span>Close Batch</span>
    </template>
    <template x-if="confirming">
      <span class="flex items-center gap-2">
        Are you sure?
        <button @click.stop="confirming = false"
                class="text-earth-500 underline text-xs">Cancel</button>
      </span>
    </template>
  </button>

  {# Only rendered and triggered when confirmed #}
  <form x-show="confirming"
        hx-post="{% url 'batches:close' batch.id %}"
        hx-target="#batch-detail"
        hx-swap="outerHTML"
        id="close-batch-form">
    {% csrf_token %}
  </form>
  <script>
    document.addEventListener('alpine:init', () => {
      // Auto-submit when confirming flips to true
    });
  </script>
</div>
```

### 5.3 Character Count on Textareas

```html
<div x-data="{ count: {{ form.notes.value|length|default:0 }}, max: 500 }">
  <textarea name="notes"
            @input="count = $el.value.length"
            :class="{ 'border-flock-red-500': count > max }"
            class="w-full rounded-lg border border-earth-300 px-3 py-2.5
                   text-sm resize-none focus:outline-none focus:ring-2
                   focus:ring-flock-green-500"
            rows="3"
            maxlength="500">{{ form.notes.value|default:'' }}</textarea>
  <p class="mt-1 text-xs text-right"
     :class="count > max * 0.9 ? 'text-flock-amber-600' : 'text-earth-400'">
    <span x-text="count"></span>/{{ 500 }}
  </p>
</div>
```

---

## 6. Core UI Components

### 6.1 `components/ui/_stat_card.html`

```html
{# Usage: {% include "components/ui/_stat_card.html" with label="Live Birds" value=batch.current_count colour="green" trend="+120 today" %} #}

{% load humanize %}

<div class="bg-white rounded-xl border border-earth-200 p-5 space-y-2">
  <p class="text-xs font-medium text-earth-500 uppercase tracking-wide">{{ label }}</p>
  <div class="flex items-baseline gap-2">
    <span class="text-3xl font-bold tabular-nums
                 {% if colour == 'green' %}text-flock-green-600
                 {% elif colour == 'red' %}text-flock-red-600
                 {% elif colour == 'amber' %}text-flock-amber-600
                 {% else %}text-earth-900{% endif %}">
      {{ value|intcomma }}{% if unit %}<span class="text-base font-medium ml-1">{{ unit }}</span>{% endif %}
    </span>
  </div>
  {% if trend %}
  <p class="text-xs text-earth-500">{{ trend }}</p>
  {% endif %}
</div>
```

### 6.2 `components/ui/_badge.html`

```html
{# Usage: {% include "components/ui/_badge.html" with text=batch.status %} #}

{% with text|lower as s %}
<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium
             {% if s == 'active' %}bg-flock-green-100 text-flock-green-800
             {% elif s == 'closed' %}bg-earth-100 text-earth-600
             {% elif s == 'pending' %}bg-flock-amber-100 text-flock-amber-800
             {% elif s == 'high' %}bg-flock-red-100 text-flock-red-800
             {% elif s == 'medium' %}bg-flock-amber-100 text-flock-amber-700
             {% elif s == 'low' %}bg-flock-blue-100 text-flock-blue-800
             {% elif s == 'excellent' %}bg-flock-green-100 text-flock-green-800
             {% elif s == 'good' %}bg-flock-green-50 text-flock-green-700
             {% elif s == 'acceptable' %}bg-flock-amber-50 text-flock-amber-700
             {% elif s == 'poor' %}bg-flock-red-100 text-flock-red-700
             {% else %}bg-earth-100 text-earth-700{% endif %}">
  {{ text|capfirst }}
</span>
{% endwith %}
```

### 6.3 `components/ui/_empty_state.html`

```html
<div class="text-center py-16 px-4">
  <div class="text-5xl mb-4">{{ icon|default:"📋" }}</div>
  <h3 class="text-base font-semibold text-earth-900 mb-1">{{ title }}</h3>
  <p class="text-sm text-earth-500 mb-6 max-w-xs mx-auto">{{ message }}</p>
  {% if action_url %}
  <a href="{{ action_url }}"
     class="inline-flex items-center gap-2 px-4 py-2.5 bg-flock-green-600
            text-white text-sm font-medium rounded-lg hover:bg-flock-green-700
            transition-colors min-h-[44px]">
    {{ action_label|default:"Get Started" }}
  </a>
  {% endif %}
</div>
```

### 6.4 `components/ui/_spinner.html`

```html
{# size: sm (16px) | md (20px) | lg (32px) #}
<svg class="animate-spin
            {% if size == 'sm' %}w-4 h-4
            {% elif size == 'lg' %}w-8 h-8
            {% else %}w-5 h-5{% endif %}
            {% if colour == 'white' %}text-white{% else %}text-flock-green-600{% endif %}"
     fill="none" viewBox="0 0 24 24">
  <circle class="opacity-25" cx="12" cy="12" r="10"
          stroke="currentColor" stroke-width="4"/>
  <path class="opacity-75" fill="currentColor"
        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
</svg>
```

### 6.5 `components/domain/_batch_card.html`

```html
{% load humanize flockiq_tags %}

<div class="bg-white rounded-xl border border-earth-200 p-5 hover:shadow-md
            transition-shadow cursor-pointer"
     hx-get="{% url 'batches:detail' batch.id %}"
     hx-target="#main-content"
     hx-push-url="{% url 'batches:detail' batch.id %}"
     hx-swap="innerHTML">

  <div class="flex items-start justify-between gap-3 mb-4">
    <div class="min-w-0">
      <p class="text-xs text-earth-400 mb-0.5">{{ batch.house.farm_name }}</p>
      <h3 class="font-semibold text-earth-900 truncate">{{ batch.house.name }}</h3>
      <p class="text-xs text-earth-500 font-mono">{{ batch.batch_code }}</p>
    </div>
    <div class="flex-shrink-0 space-y-1 text-right">
      {% include "components/ui/_badge.html" with text=batch.status %}
      <p class="text-xs text-earth-400">Day {{ batch.age_days }}</p>
    </div>
  </div>

  <div class="grid grid-cols-3 gap-3 mb-4">
    <div>
      <p class="text-xs text-earth-500 mb-0.5">Live Birds</p>
      <p class="text-xl font-bold tabular-nums text-earth-900">
        {{ batch.current_count|intcomma }}
      </p>
    </div>
    <div>
      {% if batch.bird_type|contains:"layer" %}
      <p class="text-xs text-earth-500 mb-0.5">Hen-Day %</p>
      <p class="text-xl font-bold tabular-nums
                {{ batch.metrics.hen_day_pct.rating|rating_colour }}">
        {{ batch.metrics.hen_day_pct.value }}%
      </p>
      {% else %}
      <p class="text-xs text-earth-500 mb-0.5">FCR</p>
      <p class="text-xl font-bold tabular-nums
                {{ batch.metrics.fcr.rating|rating_colour }}">
        {{ batch.metrics.fcr.value }}
      </p>
      {% endif %}
    </div>
    <div>
      <p class="text-xs text-earth-500 mb-0.5">Mortality</p>
      <p class="text-xl font-bold tabular-nums
                {% if batch.metrics.mortality.alert_required %}text-flock-red-600
                {% else %}text-earth-900{% endif %}">
        {{ batch.metrics.mortality.cumulative_pct }}%
      </p>
    </div>
  </div>

  {# Progress bar: age vs expected duration #}
  {% with batch.age_days|divide:batch.expected_duration_days|multiply:100 as progress %}
  <div class="space-y-1">
    <div class="flex justify-between text-xs text-earth-400">
      <span>Day {{ batch.age_days }}</span>
      <span>Day {{ batch.expected_duration_days }}</span>
    </div>
    <div class="w-full bg-earth-100 rounded-full h-1.5">
      <div class="bg-flock-green-500 h-1.5 rounded-full transition-all"
           style="width: min({{ progress|floatformat:0 }}%, 100%)"></div>
    </div>
  </div>
  {% endwith %}

</div>
```

---

## 7. Form Components & Validation

### 7.1 `components/forms/_field.html`

```html
{# Universal field wrapper — handles all text-like inputs #}

{% with field_id=field.auto_id|default:field.html_name %}
<div class="space-y-1.5">
  <label for="{{ field_id }}"
         class="block text-sm font-medium text-earth-700">
    {{ label }}
    {% if field.field.required %}
    <span class="text-flock-red-500 ml-0.5" aria-hidden="true">*</span>
    {% endif %}
  </label>

  <input type="{{ type|default:'text' }}"
         name="{{ field.html_name }}"
         id="{{ field_id }}"
         value="{{ field.value|default:'' }}"
         placeholder="{{ placeholder|default:'' }}"
         {% if min %}min="{{ min }}"{% endif %}
         {% if max %}max="{{ max }}"{% endif %}
         {% if step %}step="{{ step }}"{% endif %}
         {% if field.field.required %}required{% endif %}
         class="w-full rounded-lg px-3 py-2.5 text-sm text-earth-900
                placeholder-earth-400 border transition-colors min-h-[44px]
                focus:outline-none focus:ring-2 focus:ring-flock-green-500
                focus:border-transparent
                {% if field.errors %}
                  border-flock-red-500 bg-flock-red-50
                {% else %}
                  border-earth-300 bg-white hover:border-earth-400
                {% endif %}">

  {% if help and not field.errors %}
  <p class="text-xs text-earth-400">{{ help }}</p>
  {% endif %}

  {% if field.errors %}
  <p class="text-xs text-flock-red-600 flex items-center gap-1">
    <svg class="w-3.5 h-3.5 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
      <path fill-rule="evenodd"
            d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z"
            clip-rule="evenodd"/>
    </svg>
    {{ field.errors|join:", " }}
  </p>
  {% endif %}
</div>
{% endwith %}
```

### 7.2 `components/forms/_select.html`

```html
{# Select with optional Alpine.js search filter for long lists #}
{% with field_id=field.auto_id|default:field.html_name %}
<div class="space-y-1.5" x-data="{ search: '', open: false }">
  <label for="{{ field_id }}"
         class="block text-sm font-medium text-earth-700">
    {{ label }}
    {% if field.field.required %}<span class="text-flock-red-500 ml-0.5">*</span>{% endif %}
  </label>

  <div class="relative">
    <select name="{{ field.html_name }}"
            id="{{ field_id }}"
            class="w-full rounded-lg px-3 py-2.5 pr-10 text-sm text-earth-900
                   border appearance-none cursor-pointer min-h-[44px]
                   focus:outline-none focus:ring-2 focus:ring-flock-green-500
                   focus:border-transparent
                   {% if field.errors %}border-flock-red-500 bg-flock-red-50
                   {% else %}border-earth-300 bg-white{% endif %}">
      {% if not field.field.required %}
      <option value="">— Select —</option>
      {% endif %}
      {% for value, text in field.field.choices %}
      <option value="{{ value }}"
              {% if value|stringformat:"s" == field.value|stringformat:"s" %}selected{% endif %}>
        {{ text }}
      </option>
      {% endfor %}
    </select>
    <div class="pointer-events-none absolute inset-y-0 right-3 flex items-center">
      <svg class="w-4 h-4 text-earth-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
      </svg>
    </div>
  </div>

  {% if field.errors %}
  <p class="text-xs text-flock-red-600">{{ field.errors|join:", " }}</p>
  {% endif %}
</div>
{% endwith %}
```

### 7.3 `components/forms/_form_errors.html`

```html
{# Non-field errors — displayed at top of form #}
{% if form.non_field_errors %}
<div class="rounded-lg bg-flock-red-50 border border-flock-red-200 p-4">
  <div class="flex gap-3">
    <svg class="w-5 h-5 text-flock-red-500 flex-shrink-0 mt-0.5"
         fill="currentColor" viewBox="0 0 20 20">
      <path fill-rule="evenodd"
            d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z"
            clip-rule="evenodd"/>
    </svg>
    <div class="space-y-1">
      {% for error in form.non_field_errors %}
      <p class="text-sm text-flock-red-700">{{ error }}</p>
      {% endfor %}
    </div>
  </div>
</div>
{% endif %}
```

---

## 8. Data Display Components

### 8.1 `components/data/_table.html`

```html
{# Responsive table — scrolls horizontally on mobile #}
<div class="bg-white rounded-xl border border-earth-200 overflow-hidden">

  {# Table header row with optional actions #}
  {% if table_title %}
  <div class="px-5 py-4 border-b border-earth-100 flex items-center justify-between">
    <h3 class="font-semibold text-earth-900 text-sm">{{ table_title }}</h3>
    {% if table_action_url %}
    <a href="{{ table_action_url }}"
       class="text-xs text-flock-green-600 hover:text-flock-green-700 font-medium">
      {{ table_action_label|default:"View all" }}
    </a>
    {% endif %}
  </div>
  {% endif %}

  <div class="overflow-x-auto">
    <table class="w-full text-sm">
      <thead>
        <tr class="border-b border-earth-100 bg-earth-50">
          {% block table_headers %}{% endblock %}
        </tr>
      </thead>
      <tbody class="divide-y divide-earth-50">
        {% block table_rows %}{% endblock %}
      </tbody>
    </table>
  </div>

  {# Empty state inside table #}
  {% block table_empty %}{% endblock %}

</div>
```

```html
{# Table header cell — with optional sort #}
{% comment %}
Usage: {% include "components/data/_th.html" with label="Date" field="date" %}
{% endcomment %}

<th class="px-4 py-3 text-left text-xs font-medium text-earth-500 uppercase tracking-wide whitespace-nowrap">
  {% if field %}
  <a href="?ordering={% if current_ordering == field %}-{% endif %}{{ field }}&{{ request.GET.urlencode }}"
     class="hover:text-earth-700 transition-colors flex items-center gap-1">
    {{ label }}
    {% if current_ordering == field %}
    <svg class="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
      <path d="M5 10l5-5 5 5H5z"/>
    </svg>
    {% elif current_ordering == '-'|add:field %}
    <svg class="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
      <path d="M15 10l-5 5-5-5h10z"/>
    </svg>
    {% endif %}
  </a>
  {% else %}
    {{ label }}
  {% endif %}
</th>
```

### 8.2 `components/data/_pagination.html`

```html
{% if page_obj.has_other_pages or meta.next or meta.previous %}
<div class="flex items-center justify-between px-1 py-4">
  <p class="text-sm text-earth-500">
    {% if meta.count %}
      {{ meta.count|intcomma }} total
    {% endif %}
  </p>

  <div class="flex items-center gap-2">
    {% if meta.previous %}
    <a href="{{ meta.previous }}"
       hx-get="{{ meta.previous }}"
       hx-target="#{{ target_id|default:'list-container' }}"
       hx-swap="innerHTML"
       hx-push-url="true"
       class="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border
              border-earth-300 bg-white text-sm text-earth-700
              hover:bg-earth-50 transition-colors min-h-[44px]">
      <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7"/>
      </svg>
      Previous
    </a>
    {% endif %}

    {% if meta.next %}
    <a href="{{ meta.next }}"
       hx-get="{{ meta.next }}"
       hx-target="#{{ target_id|default:'list-container' }}"
       hx-swap="innerHTML"
       hx-push-url="true"
       class="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border
              border-earth-300 bg-white text-sm text-earth-700
              hover:bg-earth-50 transition-colors min-h-[44px]">
      Next
      <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/>
      </svg>
    </a>
    {% endif %}
  </div>
</div>
{% endif %}
```

### 8.3 `components/domain/_metric_pill.html`

```html
{# Compact metric pill — for batch cards and inline summaries #}
{# Usage: {% include "..._metric_pill.html" with label="FCR" value=batch.metrics.fcr.value rating=batch.metrics.fcr.rating %} #}

<div class="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-sm font-medium
            {% if rating == 'excellent' %}bg-flock-green-100 text-flock-green-800
            {% elif rating == 'good' %}bg-flock-green-50 text-flock-green-700
            {% elif rating == 'acceptable' %}bg-flock-amber-100 text-flock-amber-800
            {% elif rating == 'poor' %}bg-flock-red-100 text-flock-red-800
            {% else %}bg-earth-100 text-earth-700{% endif %}">
  <span class="font-normal opacity-70">{{ label }}</span>
  <span class="tabular-nums font-bold">{{ value }}</span>
</div>
```

---

## 9. Chart Components

### 9.1 Base Chart Card

```html
{# templates/components/data/_chart_card.html #}
<div class="bg-white rounded-xl border border-earth-200 p-5">
  <div class="flex items-center justify-between mb-5">
    <h3 class="font-semibold text-earth-900 text-sm">{{ title }}</h3>
    {% if subtitle %}
    <p class="text-xs text-earth-400">{{ subtitle }}</p>
    {% endif %}
  </div>
  <div class="relative" style="height: {{ height|default:'220px' }}">
    <canvas id="{{ chart_id }}"></canvas>
    {# Loading placeholder — hidden once Chart.js renders #}
    <div id="{{ chart_id }}-placeholder"
         class="absolute inset-0 flex items-center justify-center bg-earth-50 rounded-lg">
      {% include "components/ui/_spinner.html" %}
    </div>
  </div>
</div>
```

### 9.2 Egg Production Trend Chart

```html
{# templates/pages/batches/partials/_production_chart.html #}
{% include "components/data/_chart_card.html" with
  chart_id="egg-production-chart"
  title="Egg Production — Hen-Day %"
  subtitle="Last 30 days + 14-day forecast"
  height="260px"
%}

{% block extra_scripts %}
<script>
document.addEventListener('DOMContentLoaded', () => {
  const ctx = document.getElementById('egg-production-chart');
  if (!ctx) return;

  // Data injected from Django template (JSON-serialised in view context)
  const actual   = {{ production_data|safe }};    // [{x: "2026-04-01", y: 87.4}, ...]
  const forecast = {{ forecast_data|safe }};       // [{x: "2026-04-09", y: 86.8, yMin: 82.1, yMax: 91.2}, ...]

  // Hide placeholder once Chart.js is ready
  document.getElementById('egg-production-chart-placeholder').remove();

  new Chart(ctx, {
    type: 'line',
    data: {
      datasets: [
        {
          label: 'Actual Hen-Day %',
          data: actual,
          borderColor: '#16a34a',       // flock-green-600
          backgroundColor: 'transparent',
          borderWidth: 2,
          pointRadius: 3,
          pointBackgroundColor: '#16a34a',
          tension: 0.3,
        },
        {
          label: 'Forecast',
          data: forecast.map(d => ({ x: d.x, y: d.y })),
          borderColor: '#f59e0b',       // flock-amber-500
          backgroundColor: 'transparent',
          borderWidth: 2,
          borderDash: [4, 4],
          pointRadius: 0,
          tension: 0.3,
        },
        {
          label: 'Forecast range',
          data: forecast.map(d => ({ x: d.x, y: d.yMax })),
          fill: '+1',                   // Fill down to next dataset
          backgroundColor: 'rgba(245, 158, 11, 0.1)',
          borderWidth: 0,
          pointRadius: 0,
        },
        {
          label: '',
          data: forecast.map(d => ({ x: d.x, y: d.yMin })),
          backgroundColor: 'transparent',
          borderWidth: 0,
          pointRadius: 0,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: {
          display: true,
          labels: {
            filter: (item) => item.text !== '',  // Hide the range boundary line
            usePointStyle: true,
            pointStyle: 'line',
            color: '#57534e',   // earth-600
            font: { size: 11 },
          },
        },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              if (ctx.dataset.label === 'Forecast range') return null;
              return `${ctx.dataset.label}: ${ctx.parsed.y.toFixed(1)}%`;
            },
          },
        },
      },
      scales: {
        x: {
          type: 'time',
          time: { unit: 'day', displayFormats: { day: 'Apr d' } },
          grid: { display: false },
          ticks: { color: '#a8a29e', font: { size: 11 } },
        },
        y: {
          min: 60,
          max: 100,
          grid: { color: '#f5f5f4' },
          ticks: {
            color: '#a8a29e',
            font: { size: 11 },
            callback: (v) => v + '%',
          },
        },
      },
    },
  });
});
</script>
{% endblock %}
```

### 9.3 Expense Breakdown Donut

```html
<script>
const expenseCtx = document.getElementById('expense-chart');
const expenseData = {{ expense_summary|safe }};

new Chart(expenseCtx, {
  type: 'doughnut',
  data: {
    labels: Object.keys(expenseData.by_category).map(k => k.replace('_', ' ')),
    datasets: [{
      data: Object.values(expenseData.by_category),
      backgroundColor: [
        '#16a34a',  // feed — green (biggest)
        '#f59e0b',  // medication — amber
        '#3b82f6',  // labour — blue
        '#78716c',  // utilities — earth
        '#ef4444',  // equipment — red
        '#a8a29e',  // other — muted
      ],
      borderWidth: 0,
      hoverOffset: 4,
    }],
  },
  options: {
    responsive: true,
    maintainAspectRatio: false,
    cutout: '72%',
    plugins: {
      legend: {
        position: 'right',
        labels: {
          color: '#57534e',
          font: { size: 11 },
          padding: 12,
          usePointStyle: true,
        },
      },
      tooltip: {
        callbacks: {
          label: (ctx) => {
            const total = ctx.dataset.data.reduce((a, b) => a + b, 0);
            const pct = ((ctx.parsed / total) * 100).toFixed(1);
            return `${ctx.label}: ₦${ctx.parsed.toLocaleString()} (${pct}%)`;
          },
        },
      },
    },
  },
});
</script>
```

---

## 10. Notification & Alert Components

### 10.1 Toast Notification

```html
{# templates/base/_messages.html — converts Django messages to Alpine toasts #}

{# JSON-encode messages for Alpine to consume #}
<script id="django-messages" type="application/json">
  [
    {% for message in messages %}
    {
      "message": "{{ message|escapejs }}",
      "type": "{% if message.level >= 40 %}error{% elif message.level >= 30 %}warning{% else %}success{% endif %}"
    }{% if not forloop.last %},{% endif %}
    {% endfor %}
  ]
</script>

<script>
  document.addEventListener('alpine:initialized', () => {
    const msgs = JSON.parse(document.getElementById('django-messages')?.textContent || '[]');
    msgs.forEach(m => window.dispatchEvent(new CustomEvent('showToast', { detail: m })));
  });
</script>
```

```html
{# Toast container — in _base.html, rendered by Alpine #}
<div id="toast-container"
     class="fixed bottom-4 right-4 z-40 space-y-2 pointer-events-none max-w-sm w-full"
     aria-live="polite">

  <template x-for="toast in $store.toasts" :key="toast.id">
    <div x-show="true"
         x-transition:enter="transition ease-out duration-200"
         x-transition:enter-start="opacity-0 translate-y-2"
         x-transition:enter-end="opacity-100 translate-y-0"
         x-transition:leave="transition ease-in duration-150"
         x-transition:leave-start="opacity-100"
         x-transition:leave-end="opacity-0"
         class="pointer-events-auto flex items-start gap-3 rounded-xl shadow-lg
                border px-4 py-3.5 text-sm"
         :class="{
           'bg-flock-green-50 border-flock-green-200 text-flock-green-800': toast.type === 'success',
           'bg-flock-red-50 border-flock-red-200 text-flock-red-800': toast.type === 'error',
           'bg-flock-amber-50 border-flock-amber-200 text-flock-amber-800': toast.type === 'warning',
         }">
      <span x-text="toast.message" class="flex-1 font-medium"></span>
      <button @click="$store.app.removeToast(toast.id)"
              class="flex-shrink-0 opacity-60 hover:opacity-100 transition-opacity -mr-1 p-1">
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
        </svg>
      </button>
    </div>
  </template>
</div>
```

### 10.2 Alert Banner (Weather / Anomaly)

```html
{# templates/components/domain/_alert_banner.html #}

{% if alerts %}
<div class="space-y-2 mb-5" id="alert-banners">
  {% for alert in alerts %}
  <div class="flex items-start gap-3 rounded-xl p-4 border
              {% if alert.severity == 'high' or alert.alert_type == 'high_temperature' %}
                bg-flock-red-50 border-flock-red-200
              {% elif alert.severity == 'medium' %}
                bg-flock-amber-50 border-flock-amber-200
              {% else %}
                bg-flock-blue-50 border-flock-blue-200
              {% endif %}">

    <span class="text-xl flex-shrink-0" aria-hidden="true">
      {% if alert.alert_type == 'mortality_spike' %}⚠️
      {% elif alert.alert_type == 'high_temperature' %}🌡️
      {% elif alert.alert_type == 'low_feed_stock' %}📦
      {% elif alert.alert_type == 'vaccination_due' %}💉
      {% else %}📋{% endif %}
    </span>

    <div class="flex-1 min-w-0">
      <p class="text-sm font-semibold
                {% if alert.severity == 'high' %}text-flock-red-800
                {% elif alert.severity == 'medium' %}text-flock-amber-800
                {% else %}text-flock-blue-800{% endif %}">
        {{ alert.message }}
      </p>
      <p class="text-xs mt-0.5 opacity-70">{{ alert.created_at|timesince }} ago</p>
    </div>

    {# Dismiss via HTMX #}
    <button hx-post="{% url 'alerts:dismiss' alert.id %}"
            hx-target="#alert-{{ alert.id }}"
            hx-swap="outerHTML swap:0.15s"
            class="flex-shrink-0 p-1.5 rounded-lg opacity-60 hover:opacity-100
                   hover:bg-black/5 transition-all min-h-[44px] flex items-center"
            aria-label="Dismiss alert">
      <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
      </svg>
    </button>

  </div>
  {% endfor %}
</div>
{% endif %}
```

---

## 11. Dashboard Layout Patterns

### 11.1 `templates/pages/dashboard.html`

```html
{% extends "base/_base.html" %}
{% load humanize %}

{% block title %}Dashboard{% endblock %}

{% block content %}
<div class="space-y-6">

  {# Active alerts — always first #}
  {% include "components/domain/_alert_banner.html" with alerts=active_alerts %}

  {# Top-level KPI row — 4 stats #}
  <div class="grid grid-cols-2 lg:grid-cols-4 gap-4"
       id="dashboard-stats"
       hx-get="{% url 'dashboard:stats' %}"
       hx-trigger="load, farmChanged from:body, every 5m"
       hx-swap="innerHTML">
    {% include "partials/dashboard_stats.html" %}
  </div>

  {# Two-column: active batches + quick log form #}
  <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">

    {# Active batches — 2/3 width #}
    <div class="lg:col-span-2 space-y-4">
      <h2 class="text-lg font-semibold text-earth-900">Active Batches</h2>
      <div id="active-batches" class="space-y-3">
        {% for batch in active_batches %}
          {% include "components/domain/_batch_card.html" with batch=batch %}
        {% empty %}
          {% include "components/ui/_empty_state.html" with
            icon="🐔" title="No active batches"
            message="Place a batch to start tracking."
            action_url=batches_create_url action_label="Place a Batch"
          %}
        {% endfor %}
      </div>
    </div>

    {# Quick log sidebar — 1/3 width #}
    <div class="space-y-4">
      <h2 class="text-lg font-semibold text-earth-900">Quick Log</h2>

      {# Quick mortality entry #}
      <div class="bg-white rounded-xl border border-earth-200 p-5">
        <h3 class="text-sm font-semibold text-earth-700 mb-4">Log Mortality</h3>
        <form hx-post="{% url 'batches:mortality-quick' %}"
              hx-target="#quick-log-feedback"
              hx-swap="innerHTML"
              class="space-y-3">
          {% csrf_token %}
          {% include "components/forms/_select.html" with
            field=quick_mortality_form.batch_id label="Batch" %}
          <div class="flex gap-2">
            <input type="number" name="count" min="1" placeholder="Count"
                   class="flex-1 rounded-lg border border-earth-300 px-3 py-2.5
                          text-sm min-h-[44px] focus:outline-none focus:ring-2
                          focus:ring-flock-green-500">
            <button type="submit"
                    class="px-4 py-2.5 bg-flock-red-600 text-white text-sm
                           font-medium rounded-lg hover:bg-flock-red-700
                           transition-colors min-h-[44px]">
              Log
            </button>
          </div>
        </form>
        <div id="quick-log-feedback" class="mt-3"></div>
      </div>

      {# Today's task completion #}
      <div class="bg-white rounded-xl border border-earth-200 p-5"
           hx-get="{% url 'tasks:today-summary' %}"
           hx-trigger="load, every 2m"
           hx-swap="innerHTML">
        {% include "partials/task_today_summary.html" %}
      </div>

    </div>
  </div>

  {# Bottom row: egg production chart + expense breakdown #}
  <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
    {% include "components/data/_chart_card.html" with
      chart_id="dashboard-egg-chart"
      title="Egg Production Trend"
      subtitle="All active layer batches — 14 days"
      height="220px"
    %}

    {% include "components/data/_chart_card.html" with
      chart_id="dashboard-expense-chart"
      title="Expense Breakdown"
      subtitle="This month"
      height="220px"
    %}
  </div>

</div>
{% endblock %}
```

---

## 12. PWA & Offline UI Patterns

### 12.1 Offline Data Entry Form

```html
{# Wraps any form to enable offline queuing #}
{# When offline: intercepts submit → stores in IndexedDB → shows pending state #}

<div x-data="offlineForm('mortality_log')" @submit.prevent="handleSubmit($event)">
  <form :class="{ 'opacity-75': pending }" id="offline-mortality-form">
    {% csrf_token %}
    {# ... form fields ... #}

    {# Sync status indicator #}
    <div class="mt-3 flex items-center gap-2 text-xs"
         x-show="pending || synced">
      <template x-if="pending">
        <span class="flex items-center gap-1.5 text-flock-amber-700">
          {% include "components/ui/_spinner.html" with size="sm" colour="amber" %}
          Saved offline. Will sync when connected.
        </span>
      </template>
      <template x-if="synced">
        <span class="text-flock-green-700 flex items-center gap-1.5">
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>
          </svg>
          Synced to server.
        </span>
      </template>
    </div>

  </form>
</div>
```

```javascript
// static/js/offline-form.js

function offlineForm(recordType) {
  return {
    pending: false,
    synced:  false,

    async handleSubmit(event) {
      const form    = event.target;
      const payload = Object.fromEntries(new FormData(form).entries());

      if (!navigator.onLine) {
        // Queue for background sync
        await window.idbQueue.add({
          type: recordType,
          client_id: crypto.randomUUID(),
          client_timestamp: new Date().toISOString(),
          payload,
        });

        // Register background sync
        const reg = await navigator.serviceWorker.ready;
        await reg.sync.register('flockiq-data-sync');

        this.pending = true;
        form.reset();
        return;
      }

      // Online: submit normally via HTMX
      htmx.trigger(form, 'submit');
    },
  };
}
```

### 12.2 Sync Status Indicator

```html
{# Global sync pending count — shown in topbar when records are queued #}
<div x-data="syncStatus()"
     x-init="init()"
     x-show="pendingCount > 0"
     class="flex items-center gap-1.5 px-3 py-1 rounded-full
            bg-flock-amber-100 text-flock-amber-800 text-xs font-medium">
  <svg class="w-3.5 h-3.5 animate-pulse" fill="currentColor" viewBox="0 0 20 20">
    <path d="M4 2a1 1 0 011 1v2.101a7.002 7.002 0 0111.601 2.566 1 1 0 11-1.885.666A5.002 5.002 0 005.999 7H9a1 1 0 010 2H4a1 1 0 01-1-1V3a1 1 0 011-1z"/>
  </svg>
  <span x-text="pendingCount + ' pending sync'"></span>
</div>
```

---

## 13. Django Template Tags & Filters

```python
# apps/infrastructure/core/templatetags/flockiq_tags.py

from django import template
from django.utils.html import mark_safe

register = template.Library()


@register.filter
def rating_colour(rating: str) -> str:
    """Returns Tailwind text colour class for a performance rating."""
    mapping = {
        "excellent": "text-flock-green-600",
        "good":      "text-flock-green-500",
        "acceptable": "text-flock-amber-600",
        "poor":      "text-flock-red-600",
    }
    return mapping.get(rating, "text-earth-900")


@register.filter
def naira(value) -> str:
    """Formats a decimal value as Nigerian Naira."""
    try:
        return f"₦{float(value):,.2f}"
    except (ValueError, TypeError):
        return "₦0.00"


@register.filter
def contains(value: str, substring: str) -> bool:
    """Checks if string contains substring — for bird_type checks in templates."""
    return substring in str(value)


@register.filter
def divide(value, divisor):
    """Safe division — returns 0 if divisor is 0."""
    try:
        return float(value) / float(divisor)
    except (ValueError, TypeError, ZeroDivisionError):
        return 0


@register.filter
def multiply(value, factor):
    """Multiplies a value — used for progress bar widths."""
    try:
        return float(value) * float(factor)
    except (ValueError, TypeError):
        return 0


@register.simple_tag(takes_context=True)
def active_nav(context, url_name: str) -> str:
    """Returns Tailwind classes for active navigation link."""
    request = context.get("request")
    if request and request.resolver_match.url_name == url_name:
        return "bg-flock-green-600 text-white font-medium"
    return "text-earth-400 hover:bg-earth-800 hover:text-earth-100"


@register.inclusion_tag("components/ui/_stat_card.html")
def stat_card(label, value, colour="default", trend=None, unit=None):
    return {"label": label, "value": value, "colour": colour,
            "trend": trend, "unit": unit}
```

---

## 14. Tailwind Configuration

```javascript
// tailwind.config.js

const defaultTheme = require('tailwindcss/defaultTheme');

module.exports = {
  content: [
    './templates/**/*.html',
    './static/js/**/*.js',
    // Scan Python files for dynamically-constructed class strings
    './apps/**/*.py',
  ],

  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter var', 'Inter', ...defaultTheme.fontFamily.sans],
        mono: ['JetBrains Mono', ...defaultTheme.fontFamily.mono],
      },

      colors: {
        'flock-green': {
          50: '#f0fdf4', 100: '#dcfce7', 200: '#bbf7d0', 300: '#86efac',
          400: '#4ade80', 500: '#22c55e', 600: '#16a34a', 700: '#15803d',
          800: '#166534', 900: '#14532d',
        },
        'flock-amber': {
          50: '#fffbeb', 100: '#fef3c7', 200: '#fde68a', 300: '#fcd34d',
          400: '#fbbf24', 500: '#f59e0b', 600: '#d97706', 700: '#b45309',
          800: '#92400e', 900: '#78350f',
        },
        'flock-red': {
          50: '#fef2f2', 100: '#fee2e2', 200: '#fecaca', 300: '#fca5a5',
          400: '#f87171', 500: '#ef4444', 600: '#dc2626', 700: '#b91c1c',
          800: '#991b1b', 900: '#7f1d1d',
        },
        'flock-blue': {
          50: '#eff6ff', 500: '#3b82f6', 600: '#2563eb', 700: '#1d4ed8',
        },
        'earth': {
          50: '#fafaf9', 100: '#f5f5f4', 200: '#e7e5e4', 300: '#d6d3d1',
          400: '#a8a29e', 500: '#78716c', 600: '#57534e', 700: '#44403c',
          800: '#292524', 900: '#1c1917',
        },
      },

      // Ensure min-h-[44px] touch targets are always in the safelist
      minHeight: {
        'touch': '44px',
      },

      // Tabular nums utility
      fontVariantNumeric: {
        'tabular': 'tabular-nums',
      },

      borderRadius: {
        'xl': '12px',
        '2xl': '16px',
        '3xl': '24px',
      },
    },
  },

  plugins: [
    require('@tailwindcss/forms')({
      strategy: 'class',  // Only apply to elements with the `form-input` class
    }),
    require('@tailwindcss/typography'),
  ],

  // Safelist dynamically-generated classes (from Python views)
  safelist: [
    // Rating colours — generated by rating_colour template filter
    'text-flock-green-600', 'text-flock-green-500',
    'text-flock-amber-600', 'text-flock-red-600',
    // Badge backgrounds — generated from status values
    { pattern: /bg-flock-(green|amber|red|blue)-(50|100)/ },
    { pattern: /text-flock-(green|amber|red|blue)-(700|800)/ },
  ],
};
```

---

## 15. Performance Patterns

### 15.1 HTMX Lazy Loading

```html
{# Defer expensive sections until they scroll into view #}
<div hx-get="{% url 'batches:performance-chart' batch.id %}"
     hx-trigger="intersect once"
     hx-swap="outerHTML"
     hx-indicator="#chart-spinner">

  {# Placeholder shown until HTMX loads the real chart #}
  <div class="bg-white rounded-xl border border-earth-200 p-5">
    <div class="flex items-center justify-center h-56">
      <span id="chart-spinner" class="htmx-indicator">
        {% include "components/ui/_spinner.html" %}
      </span>
    </div>
  </div>
</div>
```

### 15.2 Dashboard Stats Caching in View

```python
# apps/core/views/dashboard.py

from django.core.cache import cache
from django.views.generic import TemplateView
from apps.infrastructure.core.views import HtmxMixin


class DashboardStatsView(HtmxMixin, TemplateView):
    htmx_template  = "partials/dashboard_stats.html"
    full_template  = "partials/dashboard_stats.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        org = self.request.org
        cache_key = f"dashboard:stats:{org.id}"

        stats = cache.get(cache_key)
        if stats is None:
            stats = self._compute_stats(org)
            cache.set(cache_key, stats, timeout=300)  # 5-minute TTL

        ctx.update(stats)
        return ctx

    def _compute_stats(self, org):
        from apps.farm.flocks.models import Batch
        from django.db.models import Sum, Count

        batches = Batch.objects.filter(status="active").select_related("house__farm")
        return {
            "total_active_batches": batches.count(),
            "total_live_birds": batches.aggregate(t=Sum("current_count"))["t"] or 0,
            "broiler_batches": batches.filter(bird_type__contains="broiler").count(),
            "layer_batches": batches.filter(bird_type__contains="layer").count(),
        }
```

### 15.3 Data Serialisation for Chart.js

```python
# Serialise queryset to JSON-safe list — never use DjangoJSONEncoder for Chart.js #
# It produces strings; Chart.js needs native JS numbers.

def get_production_chart_data(batch_id, org_id):
    from apps.production.production.models import EggProductionLog
    from django.utils.formats import date_format

    logs = (
        EggProductionLog.objects
        .filter(batch_id=batch_id)
        .order_by("date")
        .values("date", "hen_day_pct")
    )

    return [
        {
            "x": log["date"].isoformat(),
            "y": float(log["hen_day_pct"]),
        }
        for log in logs
    ]

# In template context: pass as json.dumps(data) and use |safe in template
# context["production_data"] = json.dumps(get_production_chart_data(...))
# Template: const actual = {{ production_data|safe }};
```

---

## 16. Accessibility Checklist

Every FlockIQ template must pass these checks before merging. Run `axe-core` in Chrome DevTools or use `pytest-axe` in CI.

```
MANDATORY BEFORE EVERY PR:

Keyboard navigation
  [ ] All interactive elements reachable by Tab key in logical order
  [ ] No keyboard traps inside modals (Escape closes; focus returns to trigger)
  [ ] Focus ring visible on all focusable elements (Tailwind focus:ring-2)

Touch targets
  [ ] All buttons, links, and inputs are minimum 44×44px (min-h-[44px])
  [ ] Sufficient spacing between touch targets (≥ 8px gap)

Colour & contrast
  [ ] Text contrast ratio ≥ 4.5:1 against background (WCAG AA)
  [ ] Interactive elements contrast ≥ 3:1
  [ ] Never use colour as the only way to convey information
      (badges must have text label, not just colour)

Screen reader
  [ ] All images have alt text (alt="" for decorative icons)
  [ ] Form inputs have associated <label> elements
  [ ] Aria-live regions set for dynamic content (toast container, alerts)
  [ ] HTMX swap targets with live data use aria-live="polite"
  [ ] Modal: aria-modal="true", role="dialog", aria-labelledby pointing to title

Offline indicator
  [ ] Banner announces offline status to screen readers via aria-live="assertive"
  [ ] Pending sync count announced on change
```

```html
{# Accessible HTMX loading region — screen readers announce when content updates #}
<div id="batch-list"
     aria-live="polite"
     aria-label="Batch list — updates automatically"
     aria-busy="false"
     hx-on:htmx:before-request="this.setAttribute('aria-busy', 'true')"
     hx-on:htmx:after-swap="this.setAttribute('aria-busy', 'false')">
  {% include "partials/batch_list.html" %}
</div>
```

---

*End of FlockIQ Frontend Component Guide v1.0*  
*Companion documents:*  
*— `skills/system_architectures.md` (Core Engine Technical Specification)*  
*— `skills/deployment_runbook.md` (Deployment & Operations)*  
*— `skills/api_contract.md` (REST API Contract)*  
*— Next: `skills/testing_guide.md` (pytest strategy, fixtures, factory patterns)*
