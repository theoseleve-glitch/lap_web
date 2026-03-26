"""Redis sliding-window rate limiter.

Uses a Lua script operating on Redis sorted sets to implement a true
sliding window counter.  Five configurable tiers control per-route
limits.  The ``@rate_limit(tier)`` decorator rejects excess requests
with HTTP 429, ``RATE_LIMITED`` error code, and a ``Retry-After`` header.

**Plan-aware**: base limits are multiplied by the user's plan-tier
multiplier (``g.plan_tier`` → ``PLAN_RATE_MULTIPLIERS``).  A DEMO user
gets the base limit, WORLD-CLASS gets 5×, B2B gets 10×.

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
import math
import time
from typing import Any

from flask import g, request

from .api_utils import ErrorCode, api_error

logger = logging.getLogger(__name__)


def log_security_event(*args, **kwargs):
    """Lazy proxy to avoid circular imports."""
    try:
        from admin.audit import log_security_event as _log
        _log(*args, **kwargs)
    except Exception:
        logger.debug("Failed to log security event", exc_info=True)

# ---------------------------------------------------------------------------
# Tier configuration
# ---------------------------------------------------------------------------

RATE_TIERS: dict[str, dict[str, int]] = {
    "auth": {"max_requests": 20, "window_seconds": 60},
    "read": {"max_requests": 300, "window_seconds": 60},
    "write": {"max_requests": 60, "window_seconds": 60},
    "analyze": {"max_requests": 5, "window_seconds": 3600},
    "upload": {"max_requests": 10, "window_seconds": 3600},
    "device_pair": {"max_requests": 5, "window_seconds": 3600},
    "device_poll": {"max_requests": 20, "window_seconds": 60},
    "sync_upload": {"max_requests": 30, "window_seconds": 3600},
}

# Plan-tier multipliers — applied to base limits above.
# Matches rate_multiplier values in plan_definitions table.
PLAN_RATE_MULTIPLIERS: dict[str, float] = {
    "free": 1.0,
    "demo": 1.0,
    "racer": 2.0,
    "world-class": 5.0,
    "world_class": 5.0,
    "b2b": 10.0,
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

def _get_effective_limit(base_max: int, tier_name: str) -> int:
    """Apply the user's plan-tier multiplier to a base rate limit.

    Reads ``g.plan_tier`` (set by tenant middleware).  Falls back to
    1.0x if the plan tier is unknown or unavailable.
    """
    plan_tier = getattr(g, "plan_tier", None) or "demo"
    multiplier = PLAN_RATE_MULTIPLIERS.get(plan_tier, 1.0)
    return math.ceil(base_max * multiplier)


def rate_limit(tier: str = "read"):
    """Decorator that enforces a sliding-window rate limit.

    Parameters
    ----------
    tier : str
        One of the keys in :data:`RATE_TIERS` — ``"auth"``, ``"read"``,
        ``"write"``, ``"analyze"``, or ``"upload"``.

    The base limit is multiplied by the user's plan-tier multiplier
    (from ``g.plan_tier``).  DEMO users get the base limit, WORLD-CLASS
    get 5x, B2B get 10x.

    When the limit is exceeded the decorator short-circuits with a
    429 response containing the ``RATE_LIMITED`` error code and a
    ``Retry-After`` header set to the tier's window in seconds.
    """
    tier_cfg = RATE_TIERS[tier]
    base_max_requests = tier_cfg["max_requests"]
    window_seconds = tier_cfg["window_seconds"]

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            r = get_redis()
            if r is None:
                return fn(*args, **kwargs)

            # Apply plan-aware multiplier (auth tier is always IP-based, no plan)
            if tier == "auth":
                max_requests = base_max_requests
                scope_value = request.remote_addr or "unknown"
            else:
                max_requests = _get_effective_limit(base_max_requests, tier)
                # Prefer workspace_id for team-scoped limits, fall back to user_id, then IP
                ws_id = getattr(g, "workspace_id", None)
                user_id = getattr(g, "current_user_id", None)
                if ws_id:
                    scope_value = f"ws:{ws_id}"
                elif user_id:
                    scope_value = str(user_id)
                else:
                    scope_value = request.remote_addr or "unknown"

            redis_key = f"ratelimit:{tier}:{scope_value}"

            now = time.time()
            window_start = now - window_seconds
            member = f"{now}:{id(request)}"

            try:
                # Redis EVAL command (Lua script), not Python eval()
                count = int(r.eval(  # noqa: S307
                    _SLIDING_WINDOW_LUA,
                    1,              # number of KEYS
                    redis_key,      # KEYS[1]
                    window_start,   # ARGV[1]
                    now,            # ARGV[2]
                    member,         # ARGV[3]
                    window_seconds, # ARGV[4]
                ))
            except Exception:
                logger.warning(
                    "Rate limit Redis error for tier=%s key=%s — failing open",
                    tier, redis_key, exc_info=True,
                )
                return fn(*args, **kwargs)

            remaining = max(0, max_requests - count)
            reset_at = int(now + window_seconds)

            if count > max_requests:
                plan_tier = getattr(g, "plan_tier", "demo")
                logger.info(
                    "Rate limited: tier=%s plan=%s scope=%s count=%d limit=%d",
                    tier, plan_tier, scope_value, count, max_requests,
                )
                log_security_event("rate_limited",
                                   user_id=getattr(g, "current_user_id", None),
                                   ip_address=request.remote_addr,
                                   details={"tier": tier, "count": count, "limit": max_requests})
                resp, status = api_error(
                    ErrorCode.RATE_LIMITED,
                    f"Rate limit exceeded for tier '{tier}'. "
                    f"Max {max_requests} requests per {window_seconds}s.",
                    status=429,
                )
                resp.headers["Retry-After"] = str(window_seconds)
                resp.headers["X-RateLimit-Limit"] = str(max_requests)
                resp.headers["X-RateLimit-Remaining"] = "0"
                resp.headers["X-RateLimit-Reset"] = str(reset_at)
                return resp, status

            response = fn(*args, **kwargs)
            # Attach rate-limit headers to successful responses
            if hasattr(response, "headers"):
                response.headers["X-RateLimit-Limit"] = str(max_requests)
                response.headers["X-RateLimit-Remaining"] = str(remaining)
                response.headers["X-RateLimit-Reset"] = str(reset_at)
            elif isinstance(response, tuple) and len(response) >= 1 and hasattr(response[0], "headers"):
                response[0].headers["X-RateLimit-Limit"] = str(max_requests)
                response[0].headers["X-RateLimit-Remaining"] = str(remaining)
                response[0].headers["X-RateLimit-Reset"] = str(reset_at)
            return response
        return wrapper
    return decorator
