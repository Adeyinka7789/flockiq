class FlockIQError(Exception):
    """Base exception for all FlockIQ business logic errors."""


class TenantContextError(FlockIQError):
    """Raised when a tenant-scoped operation is attempted without an active context."""


class InsufficientBirdCountError(FlockIQError):
    """Raised when a mortality log would push current_count below zero."""


class BatchClosedError(FlockIQError):
    """Raised when data is logged against a batch whose status is 'closed'."""


class VaccinationWindowError(FlockIQError):
    """Raised when a vaccination record falls outside the valid administration window."""


class WithdrawalPeriodActiveError(FlockIQError):
    """Raised when a sale is recorded while a drug withdrawal period is still active."""
