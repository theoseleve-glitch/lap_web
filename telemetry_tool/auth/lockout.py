"""Account lockout — Redis-backed brute-force protection.

After MAX_ATTEMPTS failed logins within WINDOW_SECONDS for a given
(email, IP) pair, that pair is locked for LOCKOUT_SECONDS.  The hard lock
is scoped by IP as well as email: an attacker who only knows a victim's
email address can lock out their OWN IP for that email, but cannot lock
the victim out of a login attempt from the victim's own IP/device.  (A
full CAPTCHA/step-up flow that also watches for the same email being
attacked from many different IPs is a larger follow-up — see the fix
report.)

Uses the same Redis sorted-set sliding window pattern as the rate limiter.

Fails open to a BOUNDED degraded mode: if Redis is unavailable, a small
in-process, per-worker fixed-window limiter keyed by (email, IP) throttles
attempts instead of letting them through unbounded.  This is intentionally
looser/faster than the real 15-minute/30-minute Redis lockout — it only
needs to bound the brute-force *rate* during an outage, not reproduce the
full lockout policy, and it must not require cross-worker coordination.
"""
from __future__ import annotations

import logging
import threading
import time

from web.redis_health import alert_redis_failopen, record_degraded_mode

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
WINDOW_SECONDS = 900       # 15 minutes
LOCKOUT_SECONDS = 1800     # 30 minutes

# Degraded-mode (Redis down) fallback — deliberately smaller/faster than
# the real lockout above; see module docstring.
_DEGRADED_MAX_ATTEMPTS = 5
_DEGRADED_WINDOW_SECONDS = 60

_degraded_lock = threading.Lock()
_degraded_buckets: dict[str, list[float]] = {}


def _get_redis():
    """Return the application's Redis client, or None."""
    try:
        from flask import current_app, g
        r = getattr(g, "_redis", None)
        if r is not None:
            return r
        return current_app.extensions.get("redis")
    except Exception:
        return None


def _key(email: str, ip: str | None = None) -> str:
    """Hard-lock key, scoped by (email, IP) — see module docstring."""
    return f"login_attempts:{email.lower()}:{ip or 'unknown'}"


def _degraded_key(email: str, ip: str | None) -> str:
    return f"{email.lower()}:{ip or 'unknown'}"


def _degraded_peek(email: str, ip: str | None) -> int | None:
    """Check (without recording) the in-process degraded-mode bucket.

    Returns seconds-remaining if throttled, else None.
    """
    record_degraded_mode("lockout")
    key = _degraded_key(email, ip)
    now = time.time()
    window_start = now - _DEGRADED_WINDOW_SECONDS
    with _degraded_lock:
        bucket = [t for t in _degraded_buckets.get(key, ()) if t > window_start]
        _degraded_buckets[key] = bucket
        count = len(bucket)
    if count >= _DEGRADED_MAX_ATTEMPTS:
        return _DEGRADED_WINDOW_SECONDS
    return None


def _degraded_record(email: str, ip: str | None) -> None:
    key = _degraded_key(email, ip)
    now = time.time()
    window_start = now - _DEGRADED_WINDOW_SECONDS
    with _degraded_lock:
        bucket = [t for t in _degraded_buckets.get(key, ()) if t > window_start]
        bucket.append(now)
        _degraded_buckets[key] = bucket


def check_lockout(email: str, ip: str | None = None) -> int | None:
    """Check if an (email, IP) pair is locked out.

    Returns seconds remaining if locked, or None if not locked.  Falls back
    to the bounded in-process degraded-mode limiter (rather than failing
    fully open) if Redis is unavailable.
    """
    r = _get_redis()
    if r is None:
        return _degraded_peek(email, ip)

    try:
        key = _key(email, ip)
        now = time.time()
        window_start = now - WINDOW_SECONDS

        # Count recent failed attempts
        r.zremrangebyscore(key, "-inf", window_start)
        count = r.zcard(key)

        if count >= MAX_ATTEMPTS:
            # Check when the oldest attempt in window was — lockout starts then
            oldest = r.zrange(key, 0, 0, withscores=True)
            if oldest:
                lockout_start = oldest[0][1]
                lockout_end = lockout_start + LOCKOUT_SECONDS
                remaining = int(lockout_end - now)
                if remaining > 0:
                    return remaining
            # Lockout expired — clear the set
            r.delete(key)
        return None
    except Exception as exc:
        logger.exception("Lockout check failed (falling back to bounded degraded mode)")
        alert_redis_failopen("lockout", str(exc))
        return _degraded_peek(email, ip)


def record_failed_attempt(email: str, ip: str | None = None) -> None:
    """Record a failed login attempt for the (email, IP) pair."""
    r = _get_redis()
    if r is None:
        _degraded_record(email, ip)
        return

    try:
        key = _key(email, ip)
        now = time.time()
        # Add with score=now, member=now (unique enough for our purposes)
        r.zadd(key, {f"{now}": now})
        r.expire(key, LOCKOUT_SECONDS + WINDOW_SECONDS)
    except Exception:
        logger.exception("Failed to record login attempt (falling back to degraded mode)")
        _degraded_record(email, ip)


def clear_attempts(email: str, ip: str | None = None) -> None:
    """Clear failed attempts for this (email, IP) pair on successful login."""
    r = _get_redis()
    if r is None:
        return

    try:
        r.delete(_key(email, ip))
    except Exception:
        logger.exception("Failed to clear login attempts")
