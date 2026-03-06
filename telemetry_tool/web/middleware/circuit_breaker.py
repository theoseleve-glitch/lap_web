"""Lightweight circuit breaker for external dependencies.

Tracks failures per dependency (db, redis, stripe, etc.) and opens
the circuit after a threshold, returning fast 503s instead of
waiting for timeouts.

Usage::

    from web.middleware.circuit_breaker import circuit_breaker, CircuitOpen

    with circuit_breaker("redis"):
        redis_client.ping()
"""
from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class CircuitOpen(Exception):
    """Raised when the circuit is open and the call is rejected."""

    def __init__(self, dependency: str):
        self.dependency = dependency
        super().__init__(f"Circuit open for {dependency}")


class _CircuitState:
    __slots__ = ("failures", "last_failure", "opened_at", "state")

    def __init__(self):
        self.failures: int = 0
        self.last_failure: float = 0.0
        self.opened_at: float = 0.0
        self.state: str = "closed"  # closed | open | half-open


# Global registry: dependency_name -> _CircuitState
_circuits: dict[str, _CircuitState] = {}
_lock = threading.Lock()

# Defaults — can be overridden per dependency
FAILURE_THRESHOLD = 5
RECOVERY_TIMEOUT = 30.0  # seconds before half-open probe


def _get_circuit(name: str) -> _CircuitState:
    if name not in _circuits:
        with _lock:
            if name not in _circuits:
                _circuits[name] = _CircuitState()
    return _circuits[name]


@contextmanager
def circuit_breaker(
    dependency: str,
    failure_threshold: int = FAILURE_THRESHOLD,
    recovery_timeout: float = RECOVERY_TIMEOUT,
):
    """Context manager that implements a circuit breaker.

    Raises :class:`CircuitOpen` immediately if the circuit is open.
    On success, resets the failure counter.
    On exception, increments failures and may open the circuit.
    """
    cb = _get_circuit(dependency)

    now = time.monotonic()

    if cb.state == "open":
        if now - cb.opened_at >= recovery_timeout:
            cb.state = "half-open"
            logger.info("Circuit %s: half-open (probing)", dependency)
        else:
            raise CircuitOpen(dependency)

    try:
        yield
    except CircuitOpen:
        raise
    except Exception:
        cb.failures += 1
        cb.last_failure = now
        if cb.failures >= failure_threshold:
            cb.state = "open"
            cb.opened_at = now
            logger.warning(
                "Circuit %s: OPEN after %d failures", dependency, cb.failures
            )
        raise
    else:
        if cb.state == "half-open":
            logger.info("Circuit %s: closed (probe succeeded)", dependency)
        cb.failures = 0
        cb.state = "closed"


def get_circuit_status() -> dict[str, dict]:
    """Return current status of all circuits (for /healthz)."""
    return {
        name: {
            "state": cb.state,
            "failures": cb.failures,
        }
        for name, cb in _circuits.items()
    }
