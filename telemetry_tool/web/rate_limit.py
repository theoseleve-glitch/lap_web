"""Redis sliding-window rate limiter.

Uses a Lua script operating on Redis sorted sets to implement a true
sliding window counter.  Five configurable tiers control per-route
limits.  The ``@rate_limit(tier)`` decorator rejects excess requests
with HTTP 429, ``RATE_LIMITED`` error code, and a ``Retry-After`` header.

Usage::

    from web.rate_limit import rate_limit

    @bp.route("/batch-reanalyze", methods=["POST"])
    @require_auth
    @rate_limit(tier="analyze")
    def batch_reanalyze():
        ...

Architecture notes:
- **Fail open**: if Redis is unavailable the request is allowed through.
- **Key format**: ``ratelimit:{tier}:{scope_value}`` where scope_value
  is the client IP for the ``auth`` tier and ``user_id`` for all others.
"""
from __future__ import annotations

import functools
import logging
import time
from typing import Any

from flask import g, request

from .api_utils import ErrorCode, api_error

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tier configuration
# ---------------------------------------------------------------------------

RATE_TIERS: dict[str, dict[str, int]] = {
    "auth": {"max_requests": 20, "window_seconds": 60},
    "read": {"max_requests": 300, "window_seconds": 60},
    "write": {"max_requests": 60, "window_seconds": 60},
    "analyze": {"max_requests": 5, "window_seconds": 3600},
    "upload": {"max_requests": 10, "window_seconds": 3600},
}

# ---------------------------------------------------------------------------
# Lua sliding-window script
#
# KEYS[1]  = the sorted-set key  (e.g. ratelimit:read:user_42)
# ARGV[1]  = window start timestamp (now - window_seconds)
# ARGV[2]  = current timestamp (score for ZADD)
# ARGV[3]  = unique member value  (timestamp + random, ensures uniqueness)
# ARGV[4]  = window_seconds  (used as key TTL)
#
# Returns: current request count in the window (after adding this request)
# ---------------------------------------------------------------------------

_SLIDING_WINDOW_LUA: str = """
local key = KEYS[1]
local window_start = tonumber(ARGV[1])
local now = tonumber(ARGV[2])
local member = ARGV[3]
local ttl = tonumber(ARGV[4])

-- Remove entries outside the sliding window
redis.call('ZREMRANGEBYSCORE', key, '-inf', window_start)

-- Add the current request
redis.call('ZADD', key, now, member)

-- Set key expiry so stale keys don't linger forever
redis.call('EXPIRE', key, ttl + 1)

-- Return current count in window
return redis.call('ZCARD', key)
"""


# ---------------------------------------------------------------------------
# Redis accessor — thin wrapper so tests can patch a single function
# ---------------------------------------------------------------------------

def get_redis():
    """Return the application's Redis client, or ``None`` if unavailable.

    Looks for ``g._redis`` (set by app factory) or falls back to
    ``current_app.extensions.get("redis")``.  Returns *None* when
    Redis is not configured so the decorator can fail open.
    """
    try:
        from flask import current_app
        r = getattr(g, "_redis", None)
        if r is not None:
            return r
        return current_app.extensions.get("redis")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------

def rate_limit(tier: str = "read"):
    """Decorator that enforces a sliding-window rate limit.

    Parameters
    ----------
    tier : str
        One of the keys in :data:`RATE_TIERS` — ``"auth"``, ``"read"``,
        ``"write"``, ``"analyze"``, or ``"upload"``.

    When the limit is exceeded the decorator short-circuits with a
    429 response containing the ``RATE_LIMITED`` error code and a
    ``Retry-After`` header set to the tier's window in seconds.
    """
    tier_cfg = RATE_TIERS[tier]
    max_requests = tier_cfg["max_requests"]
    window_seconds = tier_cfg["window_seconds"]

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            r = get_redis()
            if r is None:
                # Fail open — no Redis means no rate limiting
                return fn(*args, **kwargs)

            # Determine scope key
            if tier == "auth":
                scope_value = request.remote_addr or "unknown"
            else:
                scope_value = getattr(g, "current_user_id", None) or request.remote_addr or "unknown"

            redis_key = f"ratelimit:{tier}:{scope_value}"

            now = time.time()
            window_start = now - window_seconds
            member = f"{now}:{id(request)}"

            try:
                count = r.eval(
                    _SLIDING_WINDOW_LUA,
                    1,              # number of KEYS
                    redis_key,      # KEYS[1]
                    window_start,   # ARGV[1]
                    now,            # ARGV[2]
                    member,         # ARGV[3]
                    window_seconds, # ARGV[4]
                )
                count = int(count)
            except Exception:
                logger.warning(
                    "Rate limit Redis error for tier=%s key=%s — failing open",
                    tier, redis_key, exc_info=True,
                )
                return fn(*args, **kwargs)

            if count > max_requests:
                resp, status = api_error(
                    ErrorCode.RATE_LIMITED,
                    f"Rate limit exceeded for tier '{tier}'. "
                    f"Max {max_requests} requests per {window_seconds}s.",
                    status=429,
                )
                resp.headers["Retry-After"] = str(window_seconds)
                return resp, status

            return fn(*args, **kwargs)
        return wrapper
    return decorator
