class BatchNotLayerError(Exception):
    """Raised when trying to log egg production for a non-layer batch."""


class ProductionBatchClosedError(Exception):
    """Raised when trying to log production on a closed or inactive batch."""


class DuplicateProductionLogError(Exception):
    """Raised when a production log already exists for the same batch and date."""
