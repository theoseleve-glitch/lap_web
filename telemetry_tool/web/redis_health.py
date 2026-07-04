"""Shared Redis-health alerting for fail-open security mechanisms.

Rate limiting (web/rate_limit.py), account lockout (auth/lockout.py), and
idempotency (web/idempotency.py) all FAIL OPEN when Redis is unavailable.
This is an explicit, reviewed decision, not an oversight:

- rate_limit / lockout: failing CLOSED would lock every user out of
  login/writes during a Redis blip. Availability wins over these specific
  defenses during an infra incident -- a temporary window of reduced
  brute-force/DoS protection is preferable to a total outage.
- idempotency: failing open only risks duplicate processing (never data
  loss), so there is no meaningful "closed" alternative worth the
  complexity.

Because web/metrics.py's counters are THEMSELVES Redis-backed, they cannot
be used to alert on a Redis outage -- the alert would silently no-op at
exactly the moment it's needed. This module logs at ERROR level (visible to
any log aggregator regardless of Redis) and best-effort forwards to Sentry
via sentry_sdk.capture_message, which submits over HTTPS independent of the
app's own Redis instance.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def alert_redis_failopen(component: str, detail: str = "") -> None:
    """Record that *component* fell back to its fail-open path because Redis
    was unavailable. Never raises -- this runs inside another function's own
    error-handling path and must not introduce a new failure mode.

    Args:
        component: short label for the call site, e.g. "rate_limit",
            "lockout", "idempotency".
        detail: optional extra context (e.g. the exception message).
    """
    message = f"Redis fail-open: {component}"
    if detail:
        message = f"{message} ({detail})"
    logger.error(message)
    try:
        import sentry_sdk
        sentry_sdk.capture_message(message, level="error")
    except Exception:
        # sentry_sdk not installed/initialized, or the capture call itself
        # failed -- must never raise into the caller's fail-open path (that
        # would turn "degrade gracefully" into "crash instead").
        pass
