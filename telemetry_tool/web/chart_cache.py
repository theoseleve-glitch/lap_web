"""
chart_cache.py — Redis-backed cache for telemetry chart endpoint responses.

Telemetry data is immutable after analysis completes. Chart endpoint
responses (speed-trace, gps-trace, gg-data, delta, scores, corners) can
be cached aggressively — a cache hit eliminates the DB query AND the
in-Python computation (interpolation, unit conversion, etc.).

Usage::

    from web.chart_cache import chart_cached

    @bp.route("/sessions/<session_id>/speed-trace", methods=["GET"])
    @_safe_api
    @chart_cached(ttl=3600)
    def get_speed_trace(session_id: str) -> tuple[dict, int]:
        ...  # only runs on cache miss

Cache key: ``chart:{session_id}:{endpoint}:{sorted_query_string}``
TTL: 1 hour default (data is immutable after analysis).
Invalidation: call ``invalidate_session_cache(session_id)`` on delete/update.
Graceful: if Redis is unavailable, the decorator is a no-op.
"""

from __future__ import annotations

import hashlib
import json
import logging
from functools import wraps
from typing import Any, Callable

from flask import g, request

logger = logging.getLogger(__name__)

_CACHE_PREFIX = "chart"


def _get_redis() -> Any | None:
    """Reuse the app's existing Redis connection (same one rate_limit.py uses)."""
    r = getattr(g, "_redis", None)
    if r is not None:
        return r
    try:
        from flask import current_app
        return current_app.extensions.get("redis")
    except Exception:
        return None


def _build_key(session_id: str, endpoint: str) -> str:
    """Cache key from session + endpoint + sorted query params."""
    qs = "&".join(
        f"{k}={v}" for k, v in sorted(request.args.items())
    )
    qs_hash = hashlib.md5(qs.encode()).hexdigest()[:12] if qs else "default"
    return f"{_CACHE_PREFIX}:{session_id}:{endpoint}:{qs_hash}"


def chart_cached(ttl: int = 3600) -> Callable:
    """Decorator that caches the JSON response body in Redis.

    Only caches successful (status 200) responses. Non-200 responses
    (404, 400, etc.) are never cached.

    Args:
        ttl: Cache TTL in seconds. Default 1 hour.
    """
    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            redis = _get_redis()
            session_id = kwargs.get("session_id") or (args[0] if args else "unknown")

            if redis is not None:
                key = _build_key(session_id, fn.__name__)
                try:
                    cached = redis.get(key)
                    if cached is not None:
                        body = json.loads(cached)
                        # Guard: only serve cached data that looks like a valid
                        # API envelope (has "ok": true). Never serve cached errors.
                        if isinstance(body, dict) and body.get("ok") is True:
                            return body, 200
                        else:
                            # Stale or invalid — delete and fall through to fresh query.
                            redis.delete(key)
                except Exception:
                    logger.debug("chart_cache: Redis read failed for %s", key)

            # Cache miss — run the endpoint
            result = fn(*args, **kwargs)

            # Only cache 200 responses
            if redis is not None and isinstance(result, tuple) and len(result) == 2:
                body, status = result
                if status == 200:
                    key = _build_key(session_id, fn.__name__)
                    try:
                        # Flask jsonify returns a Response; api_response returns (dict, int).
                        # We cache the dict (before jsonify).
                        payload = json.dumps(body) if isinstance(body, dict) else body
                        redis.setex(key, ttl, payload)
                    except Exception:
                        logger.debug("chart_cache: Redis write failed for %s", key)

            return result
        return wrapper
    return decorator


def invalidate_session_cache(session_id: str) -> int:
    """Delete all cached chart responses for a session.

    Called on session delete, session update, or re-analysis.
    Returns the number of keys deleted (0 if Redis unavailable).
    """
    redis = _get_redis()
    if redis is None:
        return 0
    try:
        pattern = f"{_CACHE_PREFIX}:{session_id}:*"
        keys = list(redis.scan_iter(match=pattern, count=200))
        if keys:
            return redis.delete(*keys)
    except Exception:
        logger.debug("chart_cache: invalidation failed for session %s", session_id)
    return 0
