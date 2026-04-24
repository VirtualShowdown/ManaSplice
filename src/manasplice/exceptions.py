class PySplitError(Exception):
    """Base exception for ManaSplice."""


class TargetResolutionError(PySplitError):
    """Raised when a target cannot be resolved."""


class FunctionExtractionError(PySplitError):
    """Raised when a function cannot be extracted."""
