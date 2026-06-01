import structlog

logger = structlog.get_logger(__name__)


def _recalculate_for_batch(instance):
    if not instance.batch_id:
        return
    from apps.infrastructure.core.rls import set_tenant_context
    from .services import FinanceService
    from apps.farm.flocks.models import Batch

    try:
        with set_tenant_context(instance.org_id):
            batch = Batch.objects.get(id=instance.batch_id)
            FinanceService(instance.org).recalculate_summary(batch)
    except Exception as exc:
        logger.error("signal.finance_summary_update_failed", error=str(exc))


def on_sales_record_saved(sender, instance, created, **kwargs):
    if created:
        _recalculate_for_batch(instance)


def on_expense_record_saved(sender, instance, created, **kwargs):
    if created:
        _recalculate_for_batch(instance)


def connect_signals():
    from django.db.models.signals import post_save
    # Inline imports: avoids circular import at module level
    from apps.finance.finance.models import SalesRecord
    from apps.finance.expenses.models import ExpenseRecord

    post_save.connect(on_sales_record_saved, sender=SalesRecord, dispatch_uid="finance.sales_summary")
    post_save.connect(on_expense_record_saved, sender=ExpenseRecord, dispatch_uid="finance.expense_summary")
