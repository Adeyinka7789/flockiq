class BatchClosedError(Exception):
    """Raised when an operation requires an active batch but the batch is closed."""


class BatchAlreadyClosedError(Exception):
    """Raised when attempting to close an already-closed batch."""


class HouseOccupiedError(Exception):
    """Raised when placing a batch in a house that already has an active batch."""


class HouseCapacityExceededError(Exception):
    """Raised when initial_count exceeds the house's stated capacity."""


class MortalityExceedsLiveBirdsError(Exception):
    """Raised when a mortality count would exceed the current live bird count."""
