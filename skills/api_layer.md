# Skill: API Layer — Django REST Framework (Mobile-Ready)

## Why This Matters
The api/v1/ layer is consumed by future mobile apps (React Native / Flutter).
Built correctly now = zero backend changes when mobile app is developed.

## Standard Response Format
```json
{ "success": true, "data": {...}, "message": "...", "pagination": {...} }
{ "success": false, "error": "FARM_NOT_FOUND", "message": "...", "details": {} }
```

## Base View
```python
# api/v1/base.py
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

class FlockIQAPIView(APIView):
    def success(self, data, message="OK", code=status.HTTP_200_OK, pagination=None):
        body = {"success": True, "data": data, "message": message}
        if pagination:
            body["pagination"] = pagination
        return Response(body, status=code)

    def error(self, error_code, message, code=status.HTTP_400_BAD_REQUEST, details=None):
        return Response({
            "success": False, "error": error_code,
            "message": message, "details": details or {}
        }, status=code)
```

## All API Endpoints
```
POST   /api/v1/auth/login/
POST   /api/v1/auth/refresh/
POST   /api/v1/auth/logout/
GET    /api/v1/auth/me/
POST   /api/v1/auth/forgot-password/
POST   /api/v1/auth/reset-password/

GET    /api/v1/farms/
POST   /api/v1/farms/
GET    /api/v1/farms/{id}/
PUT    /api/v1/farms/{id}/
GET    /api/v1/farms/{id}/dashboard/
GET    /api/v1/farms/{id}/weather/

GET    /api/v1/flocks/batches/
POST   /api/v1/flocks/batches/
GET    /api/v1/flocks/batches/{id}/
POST   /api/v1/flocks/batches/{id}/mortality/
GET    /api/v1/flocks/batches/{id}/mortality/
POST   /api/v1/flocks/batches/{id}/weight/
POST   /api/v1/flocks/batches/{id}/close/

GET    /api/v1/production/eggs/
POST   /api/v1/production/eggs/
GET    /api/v1/production/eggs/{batch_id}/

POST   /api/v1/water/log/
GET    /api/v1/water/{batch_id}/

POST   /api/v1/waste/log/

POST   /api/v1/health/vaccinations/
GET    /api/v1/health/vaccinations/
PUT    /api/v1/health/vaccinations/{id}/complete/
POST   /api/v1/health/medications/
POST   /api/v1/health/symptoms/
GET    /api/v1/health/symptoms/{batch_id}/diagnoses/

POST   /api/v1/expenses/
GET    /api/v1/expenses/

GET    /api/v1/finance/summary/
POST   /api/v1/finance/sales/
GET    /api/v1/finance/sales/
GET    /api/v1/finance/breakeven/{batch_id}/

GET    /api/v1/analytics/alerts/
POST   /api/v1/analytics/alerts/{id}/acknowledge/
GET    /api/v1/analytics/forecast/{batch_id}/
GET    /api/v1/analytics/theft/{batch_id}/
GET    /api/v1/analytics/sale-timing/{batch_id}/

GET    /api/v1/tasks/today/
POST   /api/v1/tasks/{id}/complete/

GET    /api/v1/weather/farm/{farm_id}/
```

## Permissions
```python
# api/v1/permissions.py
class IsOwner(BasePermission):
    def has_permission(self, request, view):
        return request.user.role == 'owner'

class IsManagerOrAbove(BasePermission):
    def has_permission(self, request, view):
        return request.user.role in ['owner', 'manager']

class CanRecord(BasePermission):
    """All roles except vet can record data."""
    def has_permission(self, request, view):
        return request.user.role in ['owner', 'manager', 'supervisor', 'data_entry']

class IsVetOrAbove(BasePermission):
    """Vet can read health data; managers can write."""
    def has_permission(self, request, view):
        return request.user.is_authenticated
```
