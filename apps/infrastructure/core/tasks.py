import structlog
from celery import shared_task
from django.core.management import call_command

logger = structlog.get_logger(__name__)


@shared_task(name="core.clear_expired_sessions")
def clear_expired_sessions():
    call_command("clearsessions")
    logger.info("sessions.cleared")
