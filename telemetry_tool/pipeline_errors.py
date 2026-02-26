"""Pipeline error hierarchy and error classification.

Provides a structured exception hierarchy for pipeline operations:
- TransientError: temporary failures eligible for retry (network, disk, etc.)
- FatalError: permanent failures that should not be retried (corrupt data, etc.)
- InteractionRequired: pipeline needs user input to continue

Also provides classify_error() to map arbitrary exceptions into error classes.
"""

from __future__ import annotations


class PipelineError(Exception):
    """Base class for all pipeline-specific errors."""

    retry_eligible: bool = False
    error_class: str = "unknown"


class TransientError(PipelineError):
    """Temporary failure that should be retried (network, Redis, disk)."""

    retry_eligible: bool = True
    error_class: str = "transient"


class FatalError(PipelineError):
    """Permanent failure — no retry (corrupt data, impossible state)."""

    retry_eligible: bool = False
    error_class: str = "fatal"


class InteractionRequired(PipelineError):
    """Pipeline needs user input to continue (e.g., joker confirmation)."""

    retry_eligible: bool = False
    error_class: str = "interaction"

    def __init__(self, reason: str, payload: dict) -> None:
        super().__init__(f"Interaction required: {reason}")
        self.reason = reason
        self.payload = payload


# Builtin exception types that indicate transient (retryable) failures.
_TRANSIENT_BUILTINS = (ConnectionError, TimeoutError)

# Class names that indicate transient failures (for libraries like redis
# whose ConnectionError does NOT inherit from Python's builtin ConnectionError).
_TRANSIENT_NAMES = {"ConnectionError", "TimeoutError", "RedisError"}


def classify_error(exc: BaseException) -> str:
    """Classify an exception into an error class string.

    Returns:
        - exc.error_class for PipelineError subclasses
        - "transient" for ConnectionError, TimeoutError, their subclasses,
          and redis-specific exceptions (RedisError, redis.ConnectionError)
        - "fatal" for everything else
    """
    if isinstance(exc, PipelineError):
        return exc.error_class
    if isinstance(exc, _TRANSIENT_BUILTINS):
        return "transient"
    # Check class name hierarchy for libraries with non-standard inheritance
    for cls in type(exc).__mro__:
        if cls.__name__ in _TRANSIENT_NAMES:
            return "transient"
    return "fatal"
