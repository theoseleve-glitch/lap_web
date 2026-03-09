"""Retry with exponential backoff and jitter for transient failures.

Usage::

    from web.retry import retry

    @retry(max_attempts=3, base_delay=0.5)
    def call_stripe_api():
        stripe.PaymentIntent.create(...)

    # Or as a context manager:
    result = retry(max_attempts=3)(lambda: redis_client.get("key"))()
"""
from __future__ import annotations

import functools
import logging
import random
import time
from typing import Any, Callable, Sequence, Type

logger = logging.getLogger(__name__)

# Default transient exceptions that should be retried
_TRANSIENT_DEFAULTS: tuple[Type[BaseException], ...] = (
    ConnectionError,
    TimeoutError,
    OSError,
)


def retry(
    max_attempts: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 30.0,
    backoff_factor: float = 2.0,
    jitter: bool = True,
    retryable: Sequence[Type[BaseException]] | None = None,
    on_retry: Callable[[int, BaseException], None] | None = None,
) -> Callable:
    """Decorator/wrapper for retrying a function on transient failures.

    Args:
        max_attempts: Total attempts (1 = no retry).
        base_delay: Initial delay in seconds before first retry.
        max_delay: Cap on delay between retries.
        backoff_factor: Multiplier applied to delay after each retry.
        jitter: Add random jitter (0-50% of delay) to prevent thundering herd.
        retryable: Exception types to retry on. Defaults to connection/timeout errors.
        on_retry: Optional callback(attempt, exception) called before each retry.
    """
    retry_on = tuple(retryable) if retryable else _TRANSIENT_DEFAULTS

    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            delay = base_delay
            last_exc: BaseException | None = None

            for attempt in range(1, max_attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except retry_on as exc:
                    last_exc = exc
                    if attempt >= max_attempts:
                        logger.warning(
                            "retry(%s): all %d attempts failed",
                            getattr(fn, "__name__", "anonymous"), max_attempts,
                        )
                        raise

                    actual_delay = min(delay, max_delay)
                    if jitter:
                        actual_delay += random.uniform(0, actual_delay * 0.5)

                    if on_retry:
                        on_retry(attempt, exc)

                    logger.info(
                        "retry(%s): attempt %d/%d failed (%s), "
                        "retrying in %.2fs",
                        getattr(fn, "__name__", "anonymous"), attempt, max_attempts,
                        type(exc).__name__, actual_delay,
                    )
                    time.sleep(actual_delay)
                    delay *= backoff_factor

            # Should not reach here, but just in case
            if last_exc:
                raise last_exc  # pragma: no cover

        return wrapper
    return decorator
