"""Account lockout — Redis-backed brute-force protection.

After MAX_ATTEMPTS failed logins within WINDOW_SECONDS, the account is locked
for LOCKOUT_SECONDS.  Uses the same Redis sorted-set sliding window pattern
as the rate limiter.

Fails open: if Redis is unavailable, lockout checks are skipped so that
legitimate users can still log in.
"""
from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
WINDOW_SECONDS = 900       # 15 minutes
LOCKOUT_SECONDS = 1800     # 30 minutes


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


def _key(email: str) -> str:
    return f"login_attempts:{email.lower()}"


def check_lockout(email: str) -> int | None:
    """Check if an account is locked out.

    Returns seconds remaining if locked, or None if not locked.
    Fails open (returns None) if Redis is unavailable.
    """
    r = _get_redis()
    if r is None:
        return None

    try:
        key = _key(email)
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
    except Exception:
        logger.exception("Lockout check failed (failing open)")
        return None


def record_failed_attempt(email: str) -> None:
    """Record a failed login attempt."""
    r = _get_redis()
    if r is None:
        return

    try:
        key = _key(email)
        now = time.time()
        # Add with score=now, member=now (unique enough for our purposes)
        r.zadd(key, {f"{now}": now})
        r.expire(key, LOCKOUT_SECONDS + WINDOW_SECONDS)
    except Exception:
        logger.exception("Failed to record login attempt")


def clear_attempts(email: str) -> None:
    """Clear failed attempts on successful login."""
    r = _get_redis()
    if r is None:
        return

    try:
        r.delete(_key(email))
    except Exception:
        logger.exception("Failed to clear login attempts")
