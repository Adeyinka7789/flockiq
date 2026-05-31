"""
Base service and cross-app coordination layer.

IMPORT DIRECTION RULE (Section 3.4 — enforced at code review):
    infrastructure/* ← farm/* ← production/* ← health/* ← finance/*
    Lower layers NEVER import from higher layers.
    Cross-domain financial coordination goes through LedgerService here.
    Domain services never import each other directly.
"""

import structlog
from django.db import transaction

logger = structlog.get_logger(__name__)


class BaseService:
    """
    All FlockIQ services inherit from this.

    Binds the service to a specific org for its lifetime.
    Never instantiate a service without an org — it raises immediately so the
    programming error surfaces at the call site, not silently later.

    Usage:
        class BatchService(BaseService):
            def log_mortality(self, ...):
                with self.atomic():
                    ...
    """

    def __init__(self, org):
        if org is None:
            raise ValueError(
                f"{self.__class__.__name__} requires an org. "
                "Never instantiate a service without a tenant context."
            )
        self.org = org
        self.logger = structlog.get_logger(self.__class__.__module__).bind(
            org_id=str(org.id),
            org_name=getattr(org, "name", "unknown"),
            service=self.__class__.__name__,
        )

    def atomic(self):
        """Convenience shortcut for transaction.atomic() in service methods."""
        return transaction.atomic()


class LedgerService(BaseService):
    """
    Cross-app financial coordinator.

    Called by ExpenseService and FinanceService to keep BatchFinancialSummary
    in sync after every financial write. This is the ONLY file allowed to
    coordinate across domain boundaries for financial operations.

    Full double-entry implementation: Phase 5.
    Current stub: logs the transaction for debugging; no DB writes.

    Section 3.1 double-entry model reference:
        Feed purchase  → DEBIT feed_stock,      CREDIT accounts_payable
        Feed consumed  → DEBIT feed_cost,        CREDIT feed_stock
        Egg sale       → DEBIT cash,             CREDIT egg_revenue
        Broiler sale   → DEBIT cash,             CREDIT broiler_revenue
        Mortality      → DEBIT mortality_loss,   CREDIT livestock_asset
    """

    def record_transaction(
        self,
        batch,
        amount_kobo: int,
        category: str,
        direction: str,
    ) -> None:
        """
        direction: 'debit' (expense) or 'credit' (revenue).
        amount_kobo: all monetary values stored as integers in kobo (1 NGN = 100 kobo).
        Stub — logs only until the finance app is built in Phase 5.
        """
        self.logger.info(
            "ledger.transaction",
            batch_id=str(batch.id) if batch else None,
            amount_kobo=amount_kobo,
            category=category,
            direction=direction,
        )

    def record_feed_purchase(self, batch, movement_id, amount_kobo: int, date) -> None:
        """Stub for Phase 5 double-entry: DEBIT feed_stock / CREDIT accounts_payable."""
        self.record_transaction(batch, amount_kobo, "feed_purchase", "debit")

    def record_feed_consumption(self, batch, movement_id, amount_kobo: int, date) -> None:
        """Stub for Phase 5 double-entry: DEBIT feed_cost / CREDIT feed_stock."""
        self.record_transaction(batch, amount_kobo, "feed_consumption", "debit")

    def record_egg_sale(self, batch, sale_id, amount_kobo: int, date) -> None:
        """Stub for Phase 5 double-entry: DEBIT cash / CREDIT egg_revenue."""
        self.record_transaction(batch, amount_kobo, "egg_sale", "credit")

    def record_broiler_sale(self, batch, sale_id, amount_kobo: int, date) -> None:
        """Stub for Phase 5 double-entry: DEBIT cash / CREDIT broiler_revenue."""
        self.record_transaction(batch, amount_kobo, "broiler_sale", "credit")

    def record_mortality_writedown(self, batch, log_id, amount_kobo: int, date) -> None:
        """Stub for Phase 5 double-entry: DEBIT mortality_loss / CREDIT livestock_asset."""
        self.record_transaction(batch, amount_kobo, "mortality_writedown", "debit")
