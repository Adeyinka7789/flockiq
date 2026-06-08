from django.http import JsonResponse
from django.db import connection
from django.core.cache import cache


def health_check(request):
    """
    Health check endpoint for uptime monitors and load balancers.
    Returns 200 if all systems operational, 503 if degraded.
    """
    checks = {}
    status = 200

    # Database check
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {str(e)}"
        status = 503

    # Cache/Redis check
    try:
        cache.set("health_check", "ok", timeout=10)
        val = cache.get("health_check")
        checks["cache"] = "ok" if val == "ok" else "error"
        if val != "ok":
            status = 503
    except Exception as e:
        checks["cache"] = f"error: {str(e)}"
        status = 503

    # Celery check (optional — check if broker reachable)
    try:
        from django_celery_beat.models import PeriodicTask

        checks["celery_beat"] = (
            "ok" if PeriodicTask.objects.exists() else "no_tasks"
        )
    except Exception as e:
        checks["celery_beat"] = f"error: {str(e)}"

    return JsonResponse(
        {
            "status": "ok" if status == 200 else "degraded",
            "checks": checks,
            "version": "1.0.0",
        },
        status=status,
    )


def ping(request):
    """Simple ping for basic uptime monitoring."""
    return JsonResponse({"status": "ok", "service": "flockiq"})
