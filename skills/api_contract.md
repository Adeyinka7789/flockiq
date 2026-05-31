# FlockIQ — REST API Contract
## `skills/api_contract.md`

**Version:** 1.0  
**Date:** April 2026  
**Author:** ADM Tech Hub — Lead Systems Architecture  
**Base URL:** `https://{subdomain}.flockiq.com/api/v1/`  
**Companion to:** `skills/system_architectures.md`, `skills/deployment_runbook.md`

---

## Table of Contents

1. [Global Conventions](#1-global-conventions)
2. [Authentication & Authorization](#2-authentication--authorization)
3. [Tenant Resolution](#3-tenant-resolution)
4. [Error Schema](#4-error-schema)
5. [Pagination](#5-pagination)
6. [Versioning Strategy](#6-versioning-strategy)
7. [Authentication Endpoints](#7-authentication-endpoints)
8. [Tenants & Onboarding](#8-tenants--onboarding)
9. [Farms & Houses](#9-farms--houses)
10. [Flocks & Batches](#10-flocks--batches)
11. [Feed Management](#11-feed-management)
12. [Water Management](#12-water-management)
13. [Egg Production](#13-egg-production)
14. [Health & Biosecurity](#14-health--biosecurity)
15. [AI Diagnostics](#15-ai-diagnostics)
16. [Waste Management](#16-waste-management)
17. [Task Scheduling](#17-task-scheduling)
18. [Weather](#18-weather)
19. [Expenses](#19-expenses)
20. [Finance & Sales](#20-finance--sales)
21. [Market Intelligence](#21-market-intelligence)
22. [Analytics & Forecasting](#22-analytics--forecasting)
23. [Notifications](#23-notifications)
24. [Billing & Subscriptions](#24-billing--subscriptions)
25. [Offline Sync](#25-offline-sync)
26. [DRF Serializer Contracts](#26-drf-serializer-contracts)
27. [Permission Matrix](#27-permission-matrix)
28. [Rate Limits Reference](#28-rate-limits-reference)

---

## 1. Global Conventions

### 1.1 Request & Response Format

All endpoints accept and return `application/json` unless noted otherwise.

```
Content-Type: application/json
Accept: application/json
Authorization: Bearer <access_token>
X-Request-ID: <uuid>          # Optional — returned in response for tracing
```

### 1.2 UUID Fields

All primary keys are UUID v4 strings. Never use integer IDs in API responses — they leak row counts and allow enumeration attacks.

```json
{ "id": "a3f8c2d1-4b5e-7890-abcd-ef1234567890" }
```

### 1.3 Date & Time

- All datetimes returned as ISO 8601 UTC: `"2026-04-08T14:30:00Z"`
- All dates (no time component) as: `"2026-04-08"`
- Clients send datetimes in UTC; the server stores in UTC
- Display localisation (WAT = UTC+1) is the client's responsibility

### 1.4 Decimal Fields

All monetary and ratio values are returned as strings to prevent floating-point precision loss:

```json
{
  "amount": "125000.00",
  "fcr": "1.820",
  "hen_day_pct": "87.40"
}
```

### 1.5 Null vs Omitted

Fields that have no value are returned as `null`, never omitted. This allows clients to distinguish "server sent this field with no value" from "server doesn't know about this field".

### 1.6 HTTP Methods

| Method | Semantics |
|---|---|
| `GET` | Read-only. Safe and idempotent. Never modifies state. |
| `POST` | Create a new resource. Returns `201 Created` with the created object. |
| `PATCH` | Partial update. Only the fields sent are changed. Returns `200 OK`. |
| `PUT` | Full replacement. Rarely used in FlockIQ — prefer PATCH. |
| `DELETE` | Soft-delete. Returns `204 No Content`. Never hard-deletes tenant data. |

### 1.7 Response Envelope

All responses follow a consistent envelope:

```json
// Success — single object
{
  "data": { ... },
  "meta": { "request_id": "uuid" }
}

// Success — list
{
  "data": [ ... ],
  "meta": {
    "count": 120,
    "next": "https://farmname.flockiq.com/api/v1/batches/?cursor=abc123",
    "previous": null,
    "request_id": "uuid"
  }
}

// Error
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Request validation failed.",
    "fields": {
      "bird_count": ["This field is required."],
      "placement_date": ["Date cannot be in the future."]
    },
    "request_id": "uuid"
  }
}
```

---

## 2. Authentication & Authorization

FlockIQ uses JWT (JSON Web Tokens) via `djangorestframework-simplejwt`.

### 2.1 Token Structure

```
Access token:   Short-lived (60 minutes). Sent in Authorization header.
Refresh token:  Long-lived (7 days). Sent only to /auth/token/refresh/.
                Stored in httpOnly cookie on web; secure storage on mobile.
```

### 2.2 Token Payload

```json
{
  "token_type": "access",
  "exp": 1712580600,
  "iat": 1712577000,
  "jti": "unique-token-id",
  "user_id": "uuid",
  "org_id": "uuid",
  "org_subdomain": "greenfield",
  "role": "farm_manager",
  "permissions": ["batch:write", "finance:read", "health:write"]
}
```

### 2.3 Roles

| Role | Code | Description |
|---|---|---|
| Owner | `owner` | Full access. Manages billing and users. |
| Farm Manager | `farm_manager` | Full farm operations access. No billing. |
| Worker | `worker` | Data entry only: mortality, feed, eggs, water, tasks. |
| Veterinarian | `vet` | Read-only on health records + write on health observations. |
| Accountant | `accountant` | Read/write on expenses and finance. No farm ops. |

### 2.4 Authentication Middleware Behaviour

The `TenantMiddleware` (see `system_architectures.md §7.5`) resolves the org from the JWT `org_id` claim when the subdomain is `app`, and from the subdomain itself for direct subdomain access. The resolved org is attached to `request.org` before any view executes.

---

## 3. Tenant Resolution

### 3.1 Subdomain Routing

```
app.flockiq.com         → Main SPA login. Org resolved from JWT after login.
greenfield.flockiq.com  → Direct tenant access. Org resolved from subdomain.
admin.flockiq.com       → Platform admin (Anthropic/ADM Tech Hub staff only).
```

### 3.2 Tenant Context Header (API Clients)

Mobile apps and third-party API clients that cannot control the subdomain must send:

```
X-Org-Subdomain: greenfield
```

The middleware checks this header when the Host resolves to `app.flockiq.com`.

---

## 4. Error Schema

### 4.1 Error Codes

| Code | HTTP Status | Meaning |
|---|---|---|
| `VALIDATION_ERROR` | 400 | Request body failed serializer validation |
| `AUTHENTICATION_REQUIRED` | 401 | Missing or expired token |
| `TOKEN_EXPIRED` | 401 | Access token expired — refresh it |
| `PERMISSION_DENIED` | 403 | Authenticated but lacks required permission |
| `TENANT_REQUIRED` | 403 | Request reached API without a resolved org |
| `NOT_FOUND` | 404 | Resource does not exist in this tenant's scope |
| `CONFLICT` | 409 | Resource already exists (e.g. duplicate batch for same house+date) |
| `RATE_LIMITED` | 429 | Too many requests — see `Retry-After` header |
| `UNPROCESSABLE` | 422 | Semantically invalid (e.g. closing a batch that is already closed) |
| `SERVER_ERROR` | 500 | Unexpected error — Sentry captures this automatically |

### 4.2 Field-Level Validation Errors

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Request validation failed.",
    "fields": {
      "bird_count": ["Ensure this value is greater than or equal to 1."],
      "bird_type": ["\"cockatoo\" is not a valid choice."],
      "placement_date": ["Date cannot be more than 30 days in the past."]
    },
    "request_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6"
  }
}
```

### 4.3 DRF Exception Handler

```python
# apps/infrastructure/core/exceptions.py

from rest_framework.views import exception_handler
from rest_framework.response import Response
import uuid


def flockiq_exception_handler(exc, context):
    response = exception_handler(exc, context)

    if response is None:
        return None

    request_id = str(uuid.uuid4())

    # Log Sentry on 5xx
    if response.status_code >= 500:
        import sentry_sdk
        sentry_sdk.capture_exception(exc)

    error_payload = {
        "code": _get_error_code(response.status_code, exc),
        "message": _get_message(exc),
        "request_id": request_id,
    }

    # Attach field errors for 400
    if hasattr(exc, "detail") and isinstance(exc.detail, dict):
        error_payload["fields"] = {
            field: [str(e) for e in errors]
            for field, errors in exc.detail.items()
        }

    response.data = {"error": error_payload}
    response["X-Request-ID"] = request_id
    return response


def _get_error_code(status_code, exc):
    from rest_framework import exceptions as drf_exc
    mapping = {
        400: "VALIDATION_ERROR",
        401: "TOKEN_EXPIRED" if "expired" in str(exc).lower() else "AUTHENTICATION_REQUIRED",
        403: "PERMISSION_DENIED",
        404: "NOT_FOUND",
        409: "CONFLICT",
        422: "UNPROCESSABLE",
        429: "RATE_LIMITED",
    }
    return mapping.get(status_code, "SERVER_ERROR")


def _get_message(exc):
    if hasattr(exc, "detail"):
        if isinstance(exc.detail, str):
            return exc.detail
        if isinstance(exc.detail, list) and exc.detail:
            return str(exc.detail[0])
    return "An unexpected error occurred."
```

---

## 5. Pagination

All list endpoints use **cursor-based pagination**. Offset pagination is disabled — it degrades at depth on large tables like `FeedMovement` and `EggProductionLog`.

### 5.1 Request Parameters

```
GET /api/v1/batches/?page_size=20&cursor=cD0yMDI2LTA0LTA4
```

| Parameter | Default | Max | Description |
|---|---|---|---|
| `page_size` | 20 | 100 | Records per page |
| `cursor` | — | — | Opaque cursor string from previous response |
| `ordering` | `-created_at` | — | Field to order by (prefix `-` for descending) |

### 5.2 Response

```json
{
  "data": [ ... ],
  "meta": {
    "count": 847,
    "page_size": 20,
    "next": "https://greenfield.flockiq.com/api/v1/batches/?cursor=cD0yMDI2LTA0LTA5",
    "previous": "https://greenfield.flockiq.com/api/v1/batches/?cursor=cD0yMDI2LTA0LTA3",
    "request_id": "uuid"
  }
}
```

### 5.3 DRF Pagination Class

```python
# apps/infrastructure/core/pagination.py

from rest_framework.pagination import CursorPagination
from rest_framework.response import Response


class FlockIQCursorPagination(CursorPagination):
    page_size            = 20
    page_size_query_param = "page_size"
    max_page_size        = 100
    ordering             = "-created_at"

    def get_paginated_response(self, data):
        return Response({
            "data": data,
            "meta": {
                "count": self.page.paginator.count if hasattr(self.page, 'paginator') else None,
                "page_size": self.get_page_size(self.request),
                "next": self.get_next_link(),
                "previous": self.get_previous_link(),
            }
        })
```

---

## 6. Versioning Strategy

### 6.1 URL Versioning

Version is embedded in the URL path: `/api/v1/`, `/api/v2/`.

The current and only version is **v1**. v2 will be introduced when a breaking change is required. v1 and v2 will run in parallel for a minimum of **6 months** before v1 is deprecated.

### 6.2 Breaking vs Non-Breaking Changes

| Change | Breaking? | Strategy |
|---|---|---|
| Adding a new optional field to a response | No | Ship immediately |
| Adding a new optional request parameter | No | Ship immediately |
| Adding a new endpoint | No | Ship immediately |
| Removing a field from a response | **Yes** | New API version |
| Renaming a field | **Yes** | New API version |
| Changing a field's type | **Yes** | New API version |
| Removing an endpoint | **Yes** | Deprecation header first, then new version |
| Changing error codes | **Yes** | New API version |

### 6.3 Deprecation Header

When a field or endpoint is scheduled for removal, the response includes:

```
Deprecation: true
Sunset: Sat, 01 Nov 2026 00:00:00 GMT
Link: <https://docs.flockiq.com/api/migration/v1-to-v2>; rel="deprecation"
```

---

## 7. Authentication Endpoints

### `POST /api/v1/auth/token/`
Obtain a JWT access/refresh token pair.

**Request**
```json
{
  "email": "michael@greenfieldfarm.com",
  "password": "secure_password"
}
```

**Response `200 OK`**
```json
{
  "data": {
    "access": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "user": {
      "id": "uuid",
      "email": "michael@greenfieldfarm.com",
      "full_name": "Michael Adeniran",
      "role": "farm_manager",
      "org": {
        "id": "uuid",
        "name": "Greenfield Farm",
        "subdomain": "greenfield",
        "subscription_status": "active",
        "plan": "growth"
      }
    }
  }
}
```

**Errors**
- `401` — Invalid credentials
- `403` — Account suspended (subscription lapsed)
- `429` — Rate limited (5 attempts per 15 minutes per IP)

---

### `POST /api/v1/auth/token/refresh/`
Exchange a valid refresh token for a new access token.

**Request**
```json
{ "refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..." }
```

**Response `200 OK`**
```json
{
  "data": {
    "access": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
  }
}
```

---

### `POST /api/v1/auth/token/blacklist/`
Invalidate a refresh token (logout).

**Request**
```json
{ "refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..." }
```

**Response `204 No Content`**

---

### `POST /api/v1/auth/password/change/`
Change the authenticated user's password.

**Request**
```json
{
  "current_password": "old_password",
  "new_password": "new_secure_password",
  "new_password_confirm": "new_secure_password"
}
```

**Response `200 OK`**
```json
{ "data": { "message": "Password updated successfully." } }
```

---

## 8. Tenants & Onboarding

### `POST /api/v1/onboarding/register/`
Register a new organisation. Creates the org, first admin user, and triggers welcome email.
**Auth required:** No (public endpoint)

**Request**
```json
{
  "org_name": "Greenfield Poultry Farm",
  "subdomain": "greenfield",
  "full_name": "Michael Adeniran",
  "email": "michael@greenfieldfarm.com",
  "phone_number": "+2348012345678",
  "password": "secure_password",
  "country": "NG",
  "plan": "starter"
}
```

**Response `201 Created`**
```json
{
  "data": {
    "org": {
      "id": "uuid",
      "name": "Greenfield Poultry Farm",
      "subdomain": "greenfield",
      "plan": "starter",
      "subscription_status": "trial",
      "trial_ends_at": "2026-05-08T00:00:00Z"
    },
    "user": {
      "id": "uuid",
      "email": "michael@greenfieldfarm.com",
      "role": "owner"
    },
    "access": "eyJ...",
    "refresh": "eyJ..."
  }
}
```

**Validation**
- `subdomain`: 3–30 chars, alphanumeric and hyphens only, must be unique
- `phone_number`: E.164 format
- `plan`: `starter` | `growth` | `enterprise`

---

### `GET /api/v1/org/`
Returns the authenticated user's organisation profile.

**Response `200 OK`**
```json
{
  "data": {
    "id": "uuid",
    "name": "Greenfield Poultry Farm",
    "subdomain": "greenfield",
    "country": "NG",
    "currency": "NGN",
    "plan": "growth",
    "subscription_status": "active",
    "subscription_renews_at": "2026-05-08T00:00:00Z",
    "total_farms": 2,
    "total_active_batches": 5,
    "created_at": "2026-01-15T09:00:00Z"
  }
}
```

---

### `GET /api/v1/org/users/`
List all users in the organisation.
**Permission:** `owner`, `farm_manager`

**Response `200 OK`**
```json
{
  "data": [
    {
      "id": "uuid",
      "full_name": "Emeka Okafor",
      "email": "emeka@greenfieldfarm.com",
      "phone_number": "+2348098765432",
      "role": "worker",
      "is_active": true,
      "last_login": "2026-04-07T08:30:00Z",
      "created_at": "2026-02-01T00:00:00Z"
    }
  ]
}
```

---

### `POST /api/v1/org/users/`
Invite a new user to the organisation.
**Permission:** `owner`

**Request**
```json
{
  "full_name": "Emeka Okafor",
  "email": "emeka@greenfieldfarm.com",
  "phone_number": "+2348098765432",
  "role": "worker"
}
```

**Response `201 Created`** — user object + invite email triggered.

---

### `PATCH /api/v1/org/users/{user_id}/`
Update a user's role or active status.
**Permission:** `owner`

**Request**
```json
{
  "role": "farm_manager",
  "is_active": true
}
```

---

## 9. Farms & Houses

### `GET /api/v1/farms/`
List all farms for the authenticated org.

**Response `200 OK`**
```json
{
  "data": [
    {
      "id": "uuid",
      "name": "Main Farm — Ikorodu",
      "address": "Km 15, Ikorodu Road, Lagos",
      "gps_latitude": "6.6194",
      "gps_longitude": "3.3634",
      "total_houses": 4,
      "total_active_batches": 3,
      "created_at": "2026-01-15T09:00:00Z"
    }
  ]
}
```

---

### `POST /api/v1/farms/`
Create a new farm.
**Permission:** `owner`, `farm_manager`

**Request**
```json
{
  "name": "Main Farm — Ikorodu",
  "address": "Km 15, Ikorodu Road, Lagos",
  "gps_latitude": "6.6194",
  "gps_longitude": "3.3634"
}
```

**Response `201 Created`** — farm object.

---

### `GET /api/v1/farms/{farm_id}/houses/`
List houses (poultry houses) within a farm.

**Response `200 OK`**
```json
{
  "data": [
    {
      "id": "uuid",
      "farm": "uuid",
      "name": "House A",
      "capacity": 5000,
      "house_type": "deep_litter",
      "current_batch": {
        "id": "uuid",
        "batch_code": "GF-BRO-2026-003",
        "bird_type": "broiler_cobb500",
        "current_count": 4812,
        "age_days": 28,
        "status": "active"
      },
      "created_at": "2026-01-15T09:00:00Z"
    }
  ]
}
```

---

### `POST /api/v1/farms/{farm_id}/houses/`

**Request**
```json
{
  "name": "House B",
  "capacity": 5000,
  "house_type": "deep_litter"
}
```

`house_type`: `deep_litter` | `battery_cage` | `free_range` | `semi_intensive`

---

## 10. Flocks & Batches

### `GET /api/v1/batches/`
List all batches for the org. Supports filtering.

**Query Parameters**
```
status        = active | closed | all       (default: active)
farm_id       = uuid
bird_type     = broiler_cobb500 | layer_isa_brown | ...
date_from     = 2026-01-01
date_to       = 2026-04-08
```

**Response `200 OK`**
```json
{
  "data": [
    {
      "id": "uuid",
      "batch_code": "GF-BRO-2026-003",
      "house": {
        "id": "uuid",
        "name": "House A",
        "farm_name": "Main Farm — Ikorodu"
      },
      "bird_type": "broiler_cobb500",
      "breed_name": "Cobb 500",
      "initial_count": 5000,
      "current_count": 4812,
      "age_days": 28,
      "placement_date": "2026-03-11",
      "expected_close_date": "2026-04-22",
      "status": "active",
      "current_fcr": "1.720",
      "cumulative_mortality_pct": "3.76",
      "created_at": "2026-03-11T07:30:00Z"
    }
  ]
}
```

---

### `POST /api/v1/batches/`
Place a new batch (calls `BatchService.place_batch()`).
**Permission:** `farm_manager`, `owner`

**Request**
```json
{
  "house_id": "uuid",
  "bird_type": "broiler_cobb500",
  "initial_count": 5000,
  "placement_date": "2026-03-11",
  "supplier": "Amo Byng Hatchery",
  "cost_per_bird": "420.00",
  "expected_close_date": "2026-04-22",
  "notes": "Day-old chicks. Vaccinated for Marek's at hatchery."
}
```

**Response `201 Created`** — full batch object including auto-generated `batch_code`.

**Side effects:**
- If `bird_type` is broiler: `CycleSubscriptionService.activate_for_batch()` fires
- `TaskGenerationService` creates initial task templates for the batch

---

### `GET /api/v1/batches/{batch_id}/`
Retrieve full batch detail with all calculated metrics.

**Response `200 OK`**
```json
{
  "data": {
    "id": "uuid",
    "batch_code": "GF-BRO-2026-003",
    "house": { "id": "uuid", "name": "House A", "farm_name": "Main Farm — Ikorodu" },
    "bird_type": "broiler_cobb500",
    "breed_name": "Cobb 500",
    "initial_count": 5000,
    "current_count": 4812,
    "age_days": 28,
    "placement_date": "2026-03-11",
    "expected_close_date": "2026-04-22",
    "status": "active",
    "supplier": "Amo Byng Hatchery",
    "cost_per_bird": "420.00",
    "metrics": {
      "fcr": {
        "value": "1.720",
        "target": "1.800",
        "variance": "-0.080",
        "rating": "excellent"
      },
      "mortality": {
        "cumulative_pct": "3.76",
        "weekly_pct": "0.42",
        "threshold_pct": "0.50",
        "alert_required": false
      },
      "daily_feed_requirement_kg": "520.000",
      "daily_water_requirement_litres": "962.40",
      "cumulative_feed_consumed_kg": "18420.000",
      "cumulative_weight_gain_kg": "10709.302"
    },
    "created_at": "2026-03-11T07:30:00Z",
    "closed_at": null,
    "close_reason": null
  }
}
```

---

### `POST /api/v1/batches/{batch_id}/close/`
Close a batch (calls `BatchService.close_batch()`).
**Permission:** `farm_manager`, `owner`

**Request**
```json
{
  "close_reason": "sold",
  "close_date": "2026-04-20",
  "final_weight_kg": "2.85",
  "notes": "Sold to Chicken Republic. Good FCR cycle."
}
```

`close_reason`: `sold` | `depopulated` | `disease_loss` | `end_of_lay` | `other`

**Response `200 OK`** — updated batch object with `status: "closed"`.

**Side effects:**
- If broiler: `CycleSubscriptionService.deactivate_for_batch()` fires
- Ledger posts final batch closure summary

---

### `GET /api/v1/batches/{batch_id}/mortality/`
List mortality logs for a batch.

**Response `200 OK`**
```json
{
  "data": [
    {
      "id": "uuid",
      "date": "2026-04-07",
      "count": 8,
      "cause": "respiratory",
      "notes": "Found 8 birds dead in House A north section",
      "logged_by": "Emeka Okafor",
      "external_id": null,
      "created_at": "2026-04-07T17:30:00Z"
    }
  ]
}
```

---

### `POST /api/v1/batches/{batch_id}/mortality/`
Log a mortality event.
**Permission:** Any authenticated user

**Request**
```json
{
  "date": "2026-04-07",
  "count": 8,
  "cause": "respiratory",
  "notes": "Found 8 birds dead in House A north section"
}
```

`cause`: `respiratory` | `Newcastle` | `coccidiosis` | `heat_stress` | `injury` | `unknown` | `other`

**Response `201 Created`** — mortality log object.

**Side effects:**
- `BatchService` decrements `batch.current_count`
- `check_mortality_anomaly.delay()` fired asynchronously
- If anomaly detected: SMS notification to farm manager

---

### `GET /api/v1/batches/{batch_id}/weight/`
List weight records for a batch.

**Response `200 OK`**
```json
{
  "data": [
    {
      "id": "uuid",
      "date": "2026-04-07",
      "sample_size": 50,
      "average_weight_kg": "1.820",
      "total_estimated_weight_kg": "8763.840",
      "target_weight_kg": "1.900",
      "variance_pct": "-4.21",
      "created_at": "2026-04-07T14:00:00Z"
    }
  ]
}
```

---

### `POST /api/v1/batches/{batch_id}/weight/`

**Request**
```json
{
  "date": "2026-04-07",
  "sample_size": 50,
  "average_weight_kg": "1.820"
}
```

**Side effects:** FCR recalculated via Django signal and cached in Redis.

---

## 11. Feed Management

### `GET /api/v1/feed/stock/`
List current feed stock records across all stores.

**Response `200 OK`**
```json
{
  "data": [
    {
      "id": "uuid",
      "feed_type": "starter",
      "feed_brand": "Vital Feed",
      "current_quantity_kg": "2850.000",
      "unit_cost": "520.00",
      "total_value": "1482000.00",
      "reorder_threshold_kg": "500.000",
      "below_threshold": false,
      "last_restocked": "2026-04-05",
      "created_at": "2026-01-20T00:00:00Z"
    }
  ]
}
```

---

### `POST /api/v1/feed/stock/restock/`
Record a feed purchase (stock-in movement).
**Permission:** `farm_manager`, `owner`

**Request**
```json
{
  "feed_stock_id": "uuid",
  "quantity_kg": "2000.000",
  "unit_cost": "520.00",
  "supplier": "Vital Feed Nigeria",
  "purchase_date": "2026-04-05",
  "invoice_number": "VFN-2026-1042"
}
```

**Side effects:** `LedgerService.post_feed_purchase()` creates double-entry records.

---

### `GET /api/v1/batches/{batch_id}/feed/`
List feed consumption records for a batch.

**Response `200 OK`**
```json
{
  "data": [
    {
      "id": "uuid",
      "date": "2026-04-07",
      "quantity_kg": "520.000",
      "feed_type": "grower",
      "feed_brand": "Vital Feed",
      "recommended_kg": "520.000",
      "variance_pct": "0.00",
      "cost": "270400.00",
      "recorded_by": "Emeka Okafor",
      "created_at": "2026-04-07T08:00:00Z"
    }
  ]
}
```

---

### `POST /api/v1/batches/{batch_id}/feed/`
Log daily feed consumption.

**Request**
```json
{
  "date": "2026-04-07",
  "quantity_kg": "520.000",
  "feed_type": "grower",
  "feed_stock_id": "uuid"
}
```

`feed_type`: `prestarter` | `starter` | `grower` | `finisher` | `layer_mash` | `layer_crumble`

**Side effects:**
- `FeedStock.current_quantity_kg` decremented
- FCR updated via Django signal
- `LedgerService.post_feed_consumption()` records cost of goods
- If below `reorder_threshold_kg`: in-app notification to farm manager

---

### `GET /api/v1/batches/{batch_id}/feed/schedule/`
Returns the recommended feed schedule for the batch based on breed standard and age.

**Response `200 OK`**
```json
{
  "data": {
    "batch_id": "uuid",
    "age_days": 28,
    "week_of_age": 4,
    "breed_standard": "Cobb 500",
    "recommended_daily_kg": "520.000",
    "grams_per_bird": "104.0",
    "feed_type_recommended": "grower",
    "is_beyond_standard_table": false
  }
}
```

---

## 12. Water Management

### `GET /api/v1/batches/{batch_id}/water/`
List daily water consumption records.

**Response `200 OK`**
```json
{
  "data": [
    {
      "id": "uuid",
      "date": "2026-04-07",
      "quantity_litres": "985.000",
      "recommended_litres": "962.400",
      "ambient_temp_c": "31.5",
      "heat_adjusted_recommendation": "1010.520",
      "variance_pct": "2.36",
      "is_anomaly": false,
      "cost": "2955.00",
      "created_at": "2026-04-07T09:00:00Z"
    }
  ]
}
```

---

### `POST /api/v1/batches/{batch_id}/water/`

**Request**
```json
{
  "date": "2026-04-07",
  "quantity_litres": "985.000",
  "ambient_temp_c": "31.5",
  "cost": "2955.00"
}
```

**Side effects:** `PoultryCalculator.daily_water_requirement()` runs on save; anomaly check queued.

---

## 13. Egg Production

### `GET /api/v1/batches/{batch_id}/production/`
List egg production logs.

**Response `200 OK`**
```json
{
  "data": [
    {
      "id": "uuid",
      "date": "2026-04-07",
      "total_eggs": 4250,
      "cracked_eggs": 48,
      "sellable_eggs": 4202,
      "crates_collected": "70.83",
      "live_hen_count": 4890,
      "hen_day_pct": "86.91",
      "target_hen_day_pct": "88.00",
      "variance_pct": "-1.25",
      "rating": "good",
      "created_at": "2026-04-07T16:00:00Z"
    }
  ]
}
```

---

### `POST /api/v1/batches/{batch_id}/production/`
Log daily egg production.

**Request**
```json
{
  "date": "2026-04-07",
  "total_eggs": 4250,
  "cracked_eggs": 48,
  "live_hen_count": 4890
}
```

**Side effects:**
- `PoultryCalculator.hen_day_pct()` computed on save (Django signal)
- Crate inventory updated
- Prophet forecast data point added (forecast re-runs at 1:00 AM)

---

### `GET /api/v1/batches/{batch_id}/production/crates/`
Crate inventory summary.

**Response `200 OK`**
```json
{
  "data": {
    "batch_id": "uuid",
    "total_crates_accumulated": "1842.50",
    "crates_sold": "1610.00",
    "crates_in_store": "232.50",
    "estimated_store_value": "580500.00",
    "last_sale_date": "2026-04-05"
  }
}
```

---

## 14. Health & Biosecurity

### `GET /api/v1/batches/{batch_id}/vaccinations/`
List vaccination schedule for a batch.

**Response `200 OK`**
```json
{
  "data": [
    {
      "id": "uuid",
      "vaccine_name": "Newcastle Disease (Lasota)",
      "route": "drinking_water",
      "due_date": "2026-04-14",
      "administered_date": null,
      "status": "upcoming",
      "age_days_at_due": 34,
      "dosage": "1 vial per 1000 birds",
      "administered_by": null,
      "notes": null,
      "reminder_sent": false
    }
  ]
}
```

---

### `POST /api/v1/batches/{batch_id}/vaccinations/`
Add a vaccination entry to the schedule.
**Permission:** `farm_manager`, `vet`, `owner`

**Request**
```json
{
  "vaccine_name": "Newcastle Disease (Lasota)",
  "route": "drinking_water",
  "due_date": "2026-04-14",
  "dosage": "1 vial per 1000 birds",
  "notes": "Booster dose"
}
```

`route`: `drinking_water` | `eye_drop` | `injection` | `spray` | `wing_web`

---

### `PATCH /api/v1/batches/{batch_id}/vaccinations/{vaccination_id}/administer/`
Record that a vaccination was administered.
**Permission:** `farm_manager`, `vet`

**Request**
```json
{
  "administered_date": "2026-04-14",
  "administered_by": "Dr. Funke Adeyemi",
  "notes": "All 4812 birds dosed. No adverse reactions."
}
```

---

### `GET /api/v1/batches/{batch_id}/medications/`
List medication logs.

**Response `200 OK`**
```json
{
  "data": [
    {
      "id": "uuid",
      "drug_name": "Oxytetracycline",
      "indication": "Suspected CRD",
      "start_date": "2026-04-02",
      "end_date": "2026-04-06",
      "dosage": "1g per litre drinking water",
      "withdrawal_period_days": 5,
      "withdrawal_clear_date": "2026-04-11",
      "cost": "12500.00",
      "prescribed_by": "Dr. Funke Adeyemi",
      "created_at": "2026-04-02T08:00:00Z"
    }
  ]
}
```

---

### `POST /api/v1/batches/{batch_id}/medications/`

**Request**
```json
{
  "drug_name": "Oxytetracycline",
  "indication": "Suspected CRD",
  "start_date": "2026-04-02",
  "end_date": "2026-04-06",
  "dosage": "1g per litre drinking water",
  "withdrawal_period_days": 5,
  "cost": "12500.00",
  "prescribed_by": "Dr. Funke Adeyemi"
}
```

**Side effects:** `LedgerService.post_feed_purchase()` equivalent for medication cost.

---

### `GET /api/v1/batches/{batch_id}/biosecurity/`
List biosecurity check logs.

**Response `200 OK`**
```json
{
  "data": [
    {
      "id": "uuid",
      "check_date": "2026-04-07",
      "checked_by": "Emeka Okafor",
      "disinfection_done": true,
      "footbath_changed": true,
      "visitor_log_updated": true,
      "ventilation_adequate": true,
      "rodent_bait_checked": false,
      "notes": "Rodent bait stations need restocking in northeast corner.",
      "created_at": "2026-04-07T07:00:00Z"
    }
  ]
}
```

---

## 15. AI Diagnostics

### `POST /api/v1/batches/{batch_id}/symptoms/`
Log observed symptoms for AI diagnosis (fires asynchronously).

**Request**
```json
{
  "observation_date": "2026-04-07",
  "symptoms": [
    "lethargy",
    "ruffled_feathers",
    "reduced_feed_intake",
    "nasal_discharge"
  ],
  "affected_count": 35,
  "notes": "Concentrated in the north section of House A"
}
```

**Available symptom codes:**
`lethargy` | `ruffled_feathers` | `reduced_feed_intake` | `reduced_water_intake` |
`watery_droppings` | `bloody_droppings` | `green_droppings` | `nasal_discharge` |
`laboured_breathing` | `swollen_face` | `twisted_neck` | `reduced_egg_production` |
`soft_shell_eggs` | `sudden_death` | `lameness` | `feather_pecking` | `pale_comb`

**Response `202 Accepted`**
```json
{
  "data": {
    "symptom_log_id": "uuid",
    "status": "diagnosis_pending",
    "message": "Symptoms logged. AI diagnosis will be ready within 60 seconds.",
    "poll_url": "/api/v1/batches/{batch_id}/symptoms/{symptom_log_id}/diagnosis/"
  }
}
```

---

### `GET /api/v1/batches/{batch_id}/symptoms/{symptom_log_id}/diagnosis/`
Poll for diagnosis result.

**Response `200 OK` (ready)**
```json
{
  "data": {
    "symptom_log_id": "uuid",
    "diagnosis_id": "uuid",
    "status": "complete",
    "observation_date": "2026-04-07",
    "symptoms_observed": ["lethargy", "ruffled_feathers", "reduced_feed_intake", "nasal_discharge"],
    "diagnosis": {
      "suggested_disease": "Newcastle Disease",
      "confidence_score": "0.82",
      "confidence_label": "High",
      "treatment_protocol": "Isolate affected birds immediately. No curative treatment available. Notify state veterinary authority. Implement strict biosecurity to prevent spread.",
      "differential_diagnoses": [
        { "disease": "Infectious Bronchitis", "confidence": "0.61" },
        { "disease": "Avian Influenza", "confidence": "0.38" }
      ],
      "engine": "rule_based_v1",
      "vet_review_required": true
    },
    "diagnosed_at": "2026-04-07T17:31:42Z"
  }
}
```

**Response `202 Accepted` (still processing)**
```json
{
  "data": {
    "symptom_log_id": "uuid",
    "status": "pending",
    "message": "Diagnosis in progress. Try again in 10 seconds."
  }
}
```

---

### `GET /api/v1/batches/{batch_id}/symptoms/`
List all symptom logs and their diagnosis results for a batch.

---

## 16. Waste Management

### `GET /api/v1/batches/{batch_id}/waste/`

**Response `200 OK`**
```json
{
  "data": [
    {
      "id": "uuid",
      "date": "2026-04-07",
      "litter_volume_kg": "320.000",
      "disposal_method": "sold_as_manure",
      "disposal_cost": "0.00",
      "revenue_from_disposal": "16000.00",
      "notes": "Sold to Ade Farms. Dry litter.",
      "created_at": "2026-04-07T16:00:00Z"
    }
  ]
}
```

---

### `POST /api/v1/batches/{batch_id}/waste/`

**Request**
```json
{
  "date": "2026-04-07",
  "litter_volume_kg": "320.000",
  "disposal_method": "sold_as_manure",
  "disposal_cost": "0.00",
  "revenue_from_disposal": "16000.00",
  "notes": "Sold to Ade Farms. Dry litter."
}
```

`disposal_method`: `sold_as_manure` | `composted` | `incinerated` | `buried` | `other`

---

## 17. Task Scheduling

### `GET /api/v1/tasks/`
List tasks for today (or a specified date).

**Query Parameters**
```
date       = 2026-04-08       (default: today)
status     = pending | complete | incomplete | all
assigned_to = uuid
farm_id    = uuid
```

**Response `200 OK`**
```json
{
  "data": [
    {
      "id": "uuid",
      "task_type": "egg_collection",
      "batch": {
        "id": "uuid",
        "batch_code": "GF-LAY-2026-001",
        "house_name": "House B"
      },
      "scheduled_date": "2026-04-08",
      "scheduled_time": "07:00",
      "assigned_to": {
        "id": "uuid",
        "full_name": "Emeka Okafor"
      },
      "status": "pending",
      "completed_at": null,
      "completion_notes": null,
      "created_at": "2026-04-07T23:59:00Z"
    }
  ]
}
```

---

### `PATCH /api/v1/tasks/{task_id}/complete/`
Mark a task as complete.
**Permission:** `worker`, `farm_manager`, `owner`

**Request**
```json
{
  "completion_notes": "Collected 4,250 eggs. All feeders checked and full."
}
```

**Response `200 OK`** — updated task object with `completed_at`.

---

### `GET /api/v1/tasks/report/incomplete/`
Returns today's incomplete task summary (mirrors the 6PM Celery Beat report).
**Permission:** `farm_manager`, `owner`

**Response `200 OK`**
```json
{
  "data": {
    "report_date": "2026-04-08",
    "total_tasks": 24,
    "completed": 19,
    "incomplete": 5,
    "incomplete_tasks": [
      {
        "task_type": "mortality_check",
        "house_name": "House C",
        "assigned_to": "Chinedu Nwosu",
        "scheduled_time": "17:00"
      }
    ]
  }
}
```

---

## 18. Weather

### `GET /api/v1/farms/{farm_id}/weather/`
Current weather and alerts for a farm (served from Redis cache).

**Response `200 OK`**
```json
{
  "data": {
    "farm_id": "uuid",
    "fetched_at": "2026-04-08T12:00:00Z",
    "current": {
      "temperature_c": "32.1",
      "humidity_pct": "78",
      "description": "Partly cloudy",
      "wind_speed_ms": "3.2"
    },
    "forecast_24h": [
      {
        "time": "2026-04-08T15:00:00Z",
        "temperature_c": "34.5",
        "humidity_pct": "82",
        "rain_probability_pct": "15"
      }
    ],
    "active_alerts": [
      {
        "id": "uuid",
        "alert_type": "high_temperature",
        "threshold": "32°C",
        "current_value": "34.5°C",
        "message": "Forecast temperature exceeds 32°C. Increase ventilation and water supply.",
        "created_at": "2026-04-08T12:00:00Z"
      }
    ],
    "cache_ttl_seconds": 18430
  }
}
```

---

## 19. Expenses

### `GET /api/v1/expenses/`
List all expenses. Filterable by batch, category, and date range.

**Query Parameters**
```
batch_id    = uuid
category    = feed | medication | labour | utilities | equipment | chicks | transport | other
date_from   = 2026-01-01
date_to     = 2026-04-08
```

**Response `200 OK`**
```json
{
  "data": [
    {
      "id": "uuid",
      "batch": { "id": "uuid", "batch_code": "GF-BRO-2026-003" },
      "category": "feed",
      "description": "Vital Feed Grower — 100 bags",
      "amount": "1040000.00",
      "currency": "NGN",
      "expense_date": "2026-04-05",
      "vendor": "Vital Feed Nigeria",
      "invoice_number": "VFN-2026-1042",
      "created_at": "2026-04-05T11:00:00Z"
    }
  ]
}
```

---

### `POST /api/v1/expenses/`
**Permission:** `farm_manager`, `accountant`, `owner`

**Request**
```json
{
  "batch_id": "uuid",
  "category": "labour",
  "description": "April farm worker salaries",
  "amount": "120000.00",
  "expense_date": "2026-04-01",
  "vendor": "Internal"
}
```

**Side effects:** `LedgerService` creates debit entry for the appropriate expense account.

---

### `GET /api/v1/expenses/summary/`
Expense summary grouped by category for a date range.

**Response `200 OK`**
```json
{
  "data": {
    "period": { "from": "2026-04-01", "to": "2026-04-08" },
    "total": "1342500.00",
    "by_category": {
      "feed":       "1040000.00",
      "medication":  "12500.00",
      "labour":     "120000.00",
      "utilities":   "45000.00",
      "equipment":  "125000.00",
      "other":           "0.00"
    }
  }
}
```

---

## 20. Finance & Sales

### `POST /api/v1/finance/sales/`
Record a sale.
**Permission:** `farm_manager`, `accountant`, `owner`

**Request**
```json
{
  "batch_id": "uuid",
  "sale_type": "broiler",
  "sale_date": "2026-04-20",
  "quantity": 4750,
  "unit": "birds",
  "unit_price": "3200.00",
  "total_amount": "15200000.00",
  "buyer_name": "Chicken Republic Nigeria",
  "payment_method": "bank_transfer",
  "invoice_number": "FLQ-2026-0042"
}
```

`sale_type`: `broiler` | `eggs` | `spent_hen` | `manure`
`unit`: `birds` | `kg` | `crates` | `bags`
`payment_method`: `cash` | `bank_transfer` | `pos` | `credit`

**Side effects:** `LedgerService.post_broiler_sale()` or `post_egg_sale()` creates revenue entry.

---

### `GET /api/v1/finance/sales/`
List sales records. Filterable by batch, type, date range.

---

### `GET /api/v1/batches/{batch_id}/finance/pnl/`
Profit and loss summary for a batch (from ledger).

**Response `200 OK`**
```json
{
  "data": {
    "batch_id": "uuid",
    "batch_code": "GF-BRO-2026-003",
    "status": "closed",
    "period": {
      "placement_date": "2026-03-11",
      "close_date": "2026-04-20"
    },
    "revenue": {
      "total": "15200000.00",
      "egg_revenue": "0.00",
      "broiler_revenue": "15200000.00"
    },
    "costs": {
      "feed_cost": "9578400.00",
      "medication_cost": "62500.00",
      "chick_cost": "2100000.00",
      "labour_cost": "360000.00",
      "utilities_cost": "180000.00",
      "mortality_loss": "394240.00",
      "overhead": "125000.00",
      "total_cost": "12800140.00"
    },
    "profit": {
      "gross_profit": "2399860.00",
      "margin_pct": "15.79",
      "cost_per_bird_sold": "2695.82",
      "revenue_per_bird_sold": "3200.00"
    },
    "break_even": {
      "break_even_price_per_bird": "2695.82",
      "current_sale_price": "3200.00",
      "buffer_above_breakeven": "504.18"
    },
    "performance": {
      "fcr": "1.720",
      "mortality_pct": "5.00",
      "avg_bird_weight_kg": "2.85"
    }
  }
}
```

---

### `GET /api/v1/finance/summary/`
Cross-batch financial overview for a date range.

**Query Parameters**
```
date_from = 2026-01-01
date_to   = 2026-04-08
farm_id   = uuid   (optional)
```

**Response `200 OK`**
```json
{
  "data": {
    "period": { "from": "2026-01-01", "to": "2026-04-08" },
    "revenue":    "38400000.00",
    "total_cost": "29850000.00",
    "gross_profit": "8550000.00",
    "margin_pct": "22.27",
    "total_batches_closed": 4,
    "best_performing_batch": {
      "batch_code": "GF-LAY-2026-001",
      "margin_pct": "31.40"
    },
    "revenue_by_type": {
      "broiler": "15200000.00",
      "eggs": "21800000.00",
      "manure": "1400000.00"
    }
  }
}
```

---

## 21. Market Intelligence

### `GET /api/v1/market/alerts/`
Seasonal demand and pricing alerts.

**Response `200 OK`**
```json
{
  "data": [
    {
      "id": "uuid",
      "alert_type": "seasonal_demand",
      "title": "Eid al-Adha Demand Surge",
      "message": "Broiler demand typically increases 35–50% in the 3 weeks before Eid al-Adha. Consider placing an additional batch 6 weeks ahead to capture this demand. Expected this year: approximately June 6–8, 2026.",
      "advance_notice_days": 59,
      "expected_price_change_pct": "18.00",
      "is_read": false,
      "created_at": "2026-04-01T00:00:00Z"
    }
  ]
}
```

---

### `GET /api/v1/market/pricing/`
Current and historical market pricing data.

**Query Parameters**
```
product  = broiler | eggs | spent_hen
state    = Lagos | Abuja | Kano | ...
```

**Response `200 OK`**
```json
{
  "data": {
    "product": "broiler",
    "state": "Lagos",
    "current_farm_gate_price": "3100.00",
    "current_market_price": "3500.00",
    "price_30d_ago": "2950.00",
    "price_change_pct": "5.08",
    "trend": "rising",
    "last_updated": "2026-04-07T00:00:00Z"
  }
}
```

---

### `GET /api/v1/market/roi-calculator/`
ROI projection for a hypothetical new batch.

**Query Parameters**
```
bird_type     = broiler_cobb500
bird_count    = 5000
expected_days = 42
cost_per_chick = 450.00
target_sale_price = 3200.00
```

**Response `200 OK`**
```json
{
  "data": {
    "inputs": {
      "bird_type": "broiler_cobb500",
      "bird_count": 5000,
      "expected_days": 42
    },
    "projected_costs": {
      "chick_cost": "2250000.00",
      "feed_cost": "8736000.00",
      "medication_est": "150000.00",
      "labour_est": "360000.00",
      "overhead_est": "250000.00",
      "total_cost": "11746000.00"
    },
    "projected_revenue": {
      "assuming_5pct_mortality": {
        "birds_sold": 4750,
        "revenue": "15200000.00",
        "gross_profit": "3454000.00",
        "margin_pct": "22.72",
        "roi_pct": "29.41"
      }
    },
    "break_even_price_per_bird": "2473.89"
  }
}
```

---

## 22. Analytics & Forecasting

### `GET /api/v1/batches/{batch_id}/forecast/`
Returns the Prophet egg production forecast (from Redis cache → DB fallback).
**Applicable to layer batches only.**

**Response `200 OK`**
```json
{
  "data": {
    "batch_id": "uuid",
    "generated_at": "2026-04-08T01:02:30Z",
    "horizon_days": 14,
    "training_rows": 78,
    "model_version": "prophet-1.1",
    "forecast": [
      {
        "date": "2026-04-09",
        "predicted_hen_day_pct": "87.20",
        "lower_bound": "83.10",
        "upper_bound": "91.30"
      },
      {
        "date": "2026-04-10",
        "predicted_hen_day_pct": "86.90",
        "lower_bound": "82.80",
        "upper_bound": "91.00"
      }
    ],
    "cache_hit": true
  }
}
```

**Response `404 Not Found`** — if no forecast exists yet (batch is too new, fewer than 21 days of data).

---

### `GET /api/v1/batches/{batch_id}/anomalies/`
List anomaly detection results for a batch.

**Response `200 OK`**
```json
{
  "data": [
    {
      "id": "uuid",
      "alert_type": "mortality_spike",
      "alert_date": "2026-04-06",
      "severity": "medium",
      "detail": {
        "latest_mortality": 32,
        "rolling_mean": 8.2,
        "z_score": "2.91",
        "iqr_upper_bound": "18.50"
      },
      "resolved": true,
      "resolved_at": "2026-04-07T09:00:00Z",
      "created_at": "2026-04-06T18:00:00Z"
    }
  ]
}
```

---

### `PATCH /api/v1/batches/{batch_id}/anomalies/{anomaly_id}/resolve/`
Mark an anomaly as resolved.
**Permission:** `farm_manager`, `vet`, `owner`

**Request**
```json
{
  "resolution_notes": "Heat stress confirmed. Installed additional fans. Mortality returned to normal."
}
```

---

### `GET /api/v1/analytics/dashboard/`
Aggregated dashboard metrics for the authenticated org.
**Results cached in Redis per org (5-minute TTL).**

**Response `200 OK`**
```json
{
  "data": {
    "generated_at": "2026-04-08T14:00:00Z",
    "cache_hit": true,
    "active_batches": {
      "total": 5,
      "broiler": 3,
      "layer": 2
    },
    "total_live_birds": 23840,
    "today_egg_production": 8420,
    "today_feed_consumed_kg": "2480.000",
    "this_month": {
      "revenue": "12400000.00",
      "expenses": "9100000.00",
      "gross_profit": "3300000.00",
      "margin_pct": "26.61"
    },
    "active_alerts": {
      "anomalies": 1,
      "weather": 2,
      "vaccination_due_today": 0,
      "low_feed_stock": 1
    },
    "farm_breakdown": [
      {
        "farm_id": "uuid",
        "farm_name": "Main Farm — Ikorodu",
        "active_batches": 3,
        "live_birds": 14250
      }
    ]
  }
}
```

---

## 23. Notifications

### `GET /api/v1/notifications/`
List in-app notifications for the authenticated user.

**Query Parameters**
```
is_read = true | false | all    (default: false)
```

**Response `200 OK`**
```json
{
  "data": [
    {
      "id": "uuid",
      "subject": "Mortality Anomaly Detected",
      "body": "Unusual mortality detected on batch GF-BRO-2026-003. Today: 32 deaths (avg: 8.2). Investigate immediately.",
      "is_read": false,
      "created_at": "2026-04-06T18:00:05Z"
    }
  ],
  "meta": {
    "unread_count": 3
  }
}
```

---

### `PATCH /api/v1/notifications/{notification_id}/read/`
Mark a notification as read.

**Response `200 OK`**
```json
{ "data": { "id": "uuid", "is_read": true } }
```

---

### `POST /api/v1/notifications/read-all/`
Mark all notifications as read.

**Response `200 OK`**
```json
{ "data": { "marked_read": 3 } }
```

---

## 24. Billing & Subscriptions

### `GET /api/v1/billing/plan/`
Returns the org's current billing plan and subscription status.
**Permission:** `owner`

**Response `200 OK`**
```json
{
  "data": {
    "plan": "growth",
    "status": "active",
    "billing_cycle": "monthly",
    "next_billing_date": "2026-05-08",
    "amount_due": "15000.00",
    "currency": "NGN",
    "active_cycle_subscriptions": [
      {
        "id": "uuid",
        "batch_code": "GF-BRO-2026-003",
        "status": "active",
        "activated_at": "2026-03-11T07:30:00Z",
        "per_cycle_charge": "5000.00"
      }
    ],
    "paystack_customer_code": "CUS_xxxxxxxxxxxx"
  }
}
```

---

### `GET /api/v1/billing/invoices/`
List billing invoices.
**Permission:** `owner`

**Response `200 OK`**
```json
{
  "data": [
    {
      "id": "uuid",
      "invoice_number": "FLQ-INV-2026-0041",
      "amount": "30000.00",
      "status": "paid",
      "period_from": "2026-03-08",
      "period_to": "2026-04-07",
      "paid_at": "2026-03-08T09:12:00Z",
      "paystack_reference": "PS_xxxxxxxxxxxx",
      "created_at": "2026-03-08T00:00:00Z"
    }
  ]
}
```

---

### `POST /api/v1/billing/webhook/`
Paystack webhook receiver. Called by Paystack only — not by clients.
**Auth:** Paystack signature verification (not JWT).

```python
# Verified via X-Paystack-Signature header
# HMAC-SHA512 of request body using PAYSTACK_WEBHOOK_SECRET
# Any request failing signature check → 400 immediately
```

Handles events: `charge.success` | `subscription.create` | `subscription.disable` | `invoice.create` | `invoice.payment_failed`

**Response `200 OK`** — always (Paystack retries on non-200)

---

## 25. Offline Sync

### `POST /api/v1/sync/`
Batch submission of records collected offline.
Full protocol described in `system_architectures.md §6`.

**Request**
```json
{
  "device_id": "device-uuid-or-fingerprint",
  "records": [
    {
      "type": "mortality_log",
      "client_id": "550e8400-e29b-41d4-a716-446655440000",
      "client_timestamp": "2026-04-07T17:30:00Z",
      "payload": {
        "batch_id": "uuid",
        "date": "2026-04-07",
        "count": 8,
        "cause": "respiratory"
      }
    },
    {
      "type": "egg_log",
      "client_id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
      "client_timestamp": "2026-04-07T16:00:00Z",
      "payload": {
        "batch_id": "uuid",
        "date": "2026-04-07",
        "total_eggs": 4250,
        "cracked_eggs": 48,
        "live_hen_count": 4890
      }
    }
  ]
}
```

**Response `200 OK`** — always 200; check `status` per record.

```json
{
  "data": {
    "synced_at": "2026-04-08T08:15:32Z",
    "device_id": "device-uuid-or-fingerprint",
    "results": [
      {
        "client_id": "550e8400-e29b-41d4-a716-446655440000",
        "server_id": "uuid",
        "type": "mortality_log",
        "status": "created"
      },
      {
        "client_id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
        "server_id": "uuid",
        "type": "egg_log",
        "status": "already_synced"
      }
    ],
    "summary": {
      "total": 2,
      "created": 1,
      "already_synced": 1,
      "conflicts": 0,
      "errors": 0
    }
  }
}
```

**Record status values:**
- `created` — successfully written to server
- `already_synced` — duplicate `client_id`; no action taken (safe to retry)
- `conflict` — another record exists for same batch+date; human review needed
- `error` — server error; `error_code` and `error_detail` fields present

---

### `GET /api/v1/sync/conflicts/`
List unresolved sync conflicts for the authenticated user's org.

**Response `200 OK`**
```json
{
  "data": [
    {
      "client_id": "uuid",
      "record_type": "mortality_log",
      "client_timestamp": "2026-04-07T17:30:00Z",
      "client_data": { "count": 8, "cause": "respiratory" },
      "server_id": "uuid",
      "server_data": { "count": 12, "cause": "unknown" },
      "server_created_at": "2026-04-07T17:15:00Z",
      "status": "unresolved"
    }
  ]
}
```

---

### `POST /api/v1/sync/conflicts/{client_id}/resolve/`
Resolve a sync conflict by choosing client or server record.

**Request**
```json
{
  "resolution": "use_client",
  "notes": "Field data is correct — worker logged 8, not 12."
}
```

`resolution`: `use_client` | `use_server` | `merge`

---

## 26. DRF Serializer Contracts

Key serializers with their field-level validation rules. These are the canonical definitions — views must use these serializers and not redefine validation inline.

### 26.1 BatchPlacementSerializer

```python
# apps/farm/flocks/serializers.py

from rest_framework import serializers
from django.utils import timezone
import datetime


class BatchPlacementSerializer(serializers.Serializer):
    house_id             = serializers.UUIDField()
    bird_type            = serializers.ChoiceField(choices=[
                               "broiler_cobb500", "broiler_ross308",
                               "layer_hyline_brown", "layer_isa_brown",
                               "generic_broiler", "generic_layer",
                           ])
    initial_count        = serializers.IntegerField(min_value=1, max_value=100_000)
    placement_date       = serializers.DateField()
    supplier             = serializers.CharField(max_length=200, required=False, allow_blank=True)
    cost_per_bird        = serializers.DecimalField(max_digits=10, decimal_places=2, required=False)
    expected_close_date  = serializers.DateField(required=False)
    notes                = serializers.CharField(max_length=1000, required=False, allow_blank=True)

    def validate_placement_date(self, value):
        if value > timezone.now().date():
            raise serializers.ValidationError("Placement date cannot be in the future.")
        if value < timezone.now().date() - datetime.timedelta(days=30):
            raise serializers.ValidationError("Placement date cannot be more than 30 days in the past.")
        return value

    def validate_house_id(self, value):
        from apps.farm.farms.models import House
        from apps.infrastructure.core.middleware import get_current_org
        try:
            house = House.objects.get(id=value, org=get_current_org())
        except House.DoesNotExist:
            raise serializers.ValidationError("House not found.")
        if house.current_batch and house.current_batch.status == "active":
            raise serializers.ValidationError(
                f"House already has an active batch: {house.current_batch.batch_code}."
            )
        return value

    def validate(self, data):
        if data.get("expected_close_date") and data.get("placement_date"):
            delta = (data["expected_close_date"] - data["placement_date"]).days
            if delta < 14:
                raise serializers.ValidationError(
                    {"expected_close_date": "Expected close date must be at least 14 days after placement."}
                )
        return data
```

### 26.2 MortalityLogSerializer

```python
class MortalityLogSerializer(serializers.Serializer):
    date   = serializers.DateField()
    count  = serializers.IntegerField(min_value=1)
    cause  = serializers.ChoiceField(
                 choices=["respiratory", "Newcastle", "coccidiosis",
                          "heat_stress", "injury", "unknown", "other"],
                 required=False, default="unknown"
             )
    notes  = serializers.CharField(max_length=500, required=False, allow_blank=True)

    def validate(self, data):
        # Validated against the batch in the view context
        batch = self.context.get("batch")
        if batch and data["count"] > batch.current_count:
            raise serializers.ValidationError(
                {"count": f"Cannot log {data['count']} deaths — only {batch.current_count} birds alive."}
            )
        return data
```

### 26.3 SymptomLogSerializer

```python
VALID_SYMPTOMS = [
    "lethargy", "ruffled_feathers", "reduced_feed_intake", "reduced_water_intake",
    "watery_droppings", "bloody_droppings", "green_droppings", "nasal_discharge",
    "laboured_breathing", "swollen_face", "twisted_neck", "reduced_egg_production",
    "soft_shell_eggs", "sudden_death", "lameness", "feather_pecking", "pale_comb",
]

class SymptomLogSerializer(serializers.Serializer):
    observation_date = serializers.DateField()
    symptoms         = serializers.ListField(
                           child=serializers.ChoiceField(choices=VALID_SYMPTOMS),
                           min_length=1,
                           max_length=len(VALID_SYMPTOMS),
                       )
    affected_count   = serializers.IntegerField(min_value=1, required=False)
    notes            = serializers.CharField(max_length=500, required=False, allow_blank=True)

    def validate_symptoms(self, value):
        if len(value) != len(set(value)):
            raise serializers.ValidationError("Duplicate symptoms in list.")
        return value
```

### 26.4 SyncRecordSerializer

```python
class SyncPayloadSerializer(serializers.Serializer):
    """Dynamic — validates based on record type."""
    pass   # Type-specific validation handled in SyncProcessor

class SyncRecordSerializer(serializers.Serializer):
    type             = serializers.ChoiceField(
                           choices=["mortality_log", "egg_log", "feed_entry", "water_log"]
                       )
    client_id        = serializers.UUIDField()
    client_timestamp = serializers.DateTimeField()
    payload          = serializers.DictField(child=serializers.JSONField())

class SyncBatchSerializer(serializers.Serializer):
    device_id = serializers.CharField(max_length=128)
    records   = SyncRecordSerializer(many=True)

    def validate_records(self, value):
        if len(value) > 500:
            raise serializers.ValidationError("Maximum 500 records per sync batch.")
        # Check for duplicate client_ids within the batch
        client_ids = [str(r["client_id"]) for r in value]
        if len(client_ids) != len(set(client_ids)):
            raise serializers.ValidationError("Duplicate client_id values within the sync batch.")
        return value
```

---

## 27. Permission Matrix

| Endpoint Group | owner | farm_manager | worker | vet | accountant |
|---|:---:|:---:|:---:|:---:|:---:|
| Auth (all) | ✓ | ✓ | ✓ | ✓ | ✓ |
| Org profile (read) | ✓ | ✓ | — | — | — |
| User management | ✓ | — | — | — | — |
| Farms / Houses (write) | ✓ | ✓ | — | — | — |
| Farms / Houses (read) | ✓ | ✓ | ✓ | ✓ | — |
| Batch placement / close | ✓ | ✓ | — | — | — |
| Mortality / weight logs | ✓ | ✓ | ✓ | — | — |
| Feed / water / waste logs | ✓ | ✓ | ✓ | — | — |
| Egg production logs | ✓ | ✓ | ✓ | — | — |
| Vaccinations (write) | ✓ | ✓ | — | ✓ | — |
| Medications (write) | ✓ | ✓ | — | ✓ | — |
| Biosecurity checks | ✓ | ✓ | ✓ | — | — |
| Symptom logging | ✓ | ✓ | ✓ | ✓ | — |
| Diagnoses (read) | ✓ | ✓ | — | ✓ | — |
| Tasks (complete) | ✓ | ✓ | ✓ | — | — |
| Task reports | ✓ | ✓ | — | — | — |
| Expenses (write) | ✓ | ✓ | — | — | ✓ |
| Finance / Sales (write) | ✓ | ✓ | — | — | ✓ |
| Finance (read) | ✓ | ✓ | — | — | ✓ |
| Analytics / Dashboard | ✓ | ✓ | — | — | ✓ |
| Forecasts / Anomalies | ✓ | ✓ | — | ✓ | — |
| Notifications (own) | ✓ | ✓ | ✓ | ✓ | ✓ |
| Billing | ✓ | — | — | — | — |
| Offline Sync | ✓ | ✓ | ✓ | ✓ | ✓ |

---

## 28. Rate Limits Reference

Configured in Nginx (`limit_req_zone`) and enforced additionally via `django-ratelimit` at the view layer for finer control.

| Endpoint Group | Limit | Burst | Scope |
|---|---|---|---|
| `POST /auth/token/` | 5/15min | 10 | Per IP |
| `POST /auth/token/refresh/` | 30/min | 50 | Per user |
| `GET /api/v1/*` (general) | 100/min | 150 | Per user |
| `POST /api/v1/*` (general) | 60/min | 80 | Per user |
| `POST /api/v1/sync/` | 20/min | 40 | Per device |
| `POST /onboarding/register/` | 3/hour | 5 | Per IP |
| `POST /billing/webhook/` | Unlimited | — | Paystack IPs only |
| `GET /api/v1/analytics/dashboard/` | 30/min | 50 | Per user |
| `POST /batches/{id}/symptoms/` | 10/min | 20 | Per user |

```python
# apps/infrastructure/core/throttling.py
from rest_framework.throttling import UserRateThrottle

class BurstRateThrottle(UserRateThrottle):
    scope = "burst"     # 60/min

class SustainedRateThrottle(UserRateThrottle):
    scope = "sustained" # 1000/day

class SyncRateThrottle(UserRateThrottle):
    scope = "sync"      # 20/min per user

# settings.py
REST_FRAMEWORK = {
    "DEFAULT_THROTTLE_CLASSES": [
        "apps.infrastructure.core.throttling.BurstRateThrottle",
        "apps.infrastructure.core.throttling.SustainedRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "burst":     "60/min",
        "sustained": "1000/day",
        "sync":      "20/min",
        "anon":      "20/day",
    },
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_PAGINATION_CLASS": "apps.infrastructure.core.pagination.FlockIQCursorPagination",
    "PAGE_SIZE": 20,
    "EXCEPTION_HANDLER": "apps.infrastructure.core.exceptions.flockiq_exception_handler",
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
    ],
    "COERCE_DECIMAL_TO_STRING": True,    # Ensures decimal fields serialise as strings
}
```

---

*End of FlockIQ REST API Contract v1.0*  
*Companion documents:*  
*— `skills/system_architectures.md` (Core Engine Technical Specification)*  
*— `skills/deployment_runbook.md` (Deployment & Operations)*  
*— Next: `skills/frontend_component_guide.md` (HTMX + Tailwind component patterns)*
