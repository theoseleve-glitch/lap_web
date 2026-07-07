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
import threading
import time

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Degraded-mode metric (NOT Redis-backed on purpose)
#
# rate_limit.py's ``auth`` tier and auth/lockout.py no longer fail fully
# open when Redis is unavailable -- they fall back to a small in-process,
# per-worker bounded limiter (see ``_degraded_auth_gate`` in rate_limit.py
# and ``_degraded_peek``/``_degraded_record`` in lockout.py). This tracker
# records how many requests were served by that fallback and how long
# (monotonic-clock seconds) the CURRENT degraded-mode episode has been
# running per component, so an operator can see "we were in degraded auth
# mode for N seconds" without needing Redis to be back up to read it.
#
# ``record_recovery`` (called from the success path once Redis answers
# again) closes out the episode: ``seconds`` freezes instead of growing
# forever, ``recovered`` flips True, and the NEXT outage starts its own
# fresh window rather than accumulating on top of every prior one.
# ---------------------------------------------------------------------------

_degraded_lock = threading.Lock()
_degraded_state: dict[str, dict[str, float | bool]] = {}


def record_degraded_mode(component: str) -> None:
    """Record one request handled by *component*'s degraded-mode fallback.

    Never raises -- called from inside another fail-open path.
    """
    try:
        now = time.monotonic()
        with _degraded_lock:
            state = _degraded_state.get(component)
            if state is None:
                state = {"requests": 0, "degraded_since": now}
                _degraded_state[component] = state
            elif state.get("recovered"):
                # A new outage starting after a prior one recovered --
                # restart the timing window so "seconds" measures THIS
                # episode, not cumulative time since the very first
                # degraded call this worker ever made. The lifetime
                # ``requests`` total is intentionally kept, not reset.
                state["degraded_since"] = now
            state["requests"] += 1
            state["seconds"] = now - state["degraded_since"]
            state["recovered"] = False
    except Exception:
        pass


def record_recovery(component: str) -> None:
    """Mark *component* as recovered now that a Redis-backed operation has
    succeeded again, closing out the current degraded-mode window.

    Freezes ``seconds`` at the just-ended episode's duration and sets
    ``recovered: True`` so :func:`get_degraded_mode_stats` can report
    "recovered" instead of an ever-growing counter -- the ``seconds``
    field previously grew forever because nothing ever reset it, so
    dashboards could never show a Redis outage had ended. The cumulative
    ``requests`` total (all episodes, lifetime of this worker) is left
    untouched. No-op if *component* was never recorded as degraded (or is
    already marked recovered). Never raises -- called from a success path
    and must never turn "Redis is back" into a crash.
    """
    try:
        now = time.monotonic()
        with _degraded_lock:
            state = _degraded_state.get(component)
            if state is None or state.get("recovered"):
                return
            state["seconds"] = now - state["degraded_since"]
            state["recovered"] = True
    except Exception:
        pass


def get_degraded_mode_stats() -> dict[str, dict[str, float | bool]]:
    """Snapshot of per-component degraded-mode counters (best-effort,
    per-worker only -- not aggregated across the fleet)."""
    with _degraded_lock:
        return {k: dict(v) for k, v in _degraded_state.items()}


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
