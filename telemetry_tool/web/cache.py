"""Redis-backed cache layer with tag-based invalidation.

Provides a simple cache interface for frequently accessed API data
(track info, dashboard stats, scoring results) with configurable TTL
and tag-based invalidation.

Usage::

    from web.cache import api_cache

    # Simple get/set
    data = api_cache.get("dashboard:stats:ws1")
    if data is None:
        data = compute_expensive_stats()
        api_cache.set("dashboard:stats:ws1", data, ttl=300, tags=["dashboard", "ws:1"])

    # Invalidate by tag (e.g., after session upload in workspace 1)
    api_cache.invalidate_tag("ws:1")

    # Decorator for auto-caching
    @api_cache.cached(ttl=300, key_func=lambda sid: f"session:{sid}")
    def get_session_scores(session_id):
        ...
"""
from __future__ import annotations

import functools
import json
import logging
import os
from typing import Any, Callable

logger = logging.getLogger(__name__)

_PREFIX = "cache:"
_TAG_PREFIX = "tag:"


class ApiCache:
    """Redis-backed cache with tag-based invalidation.

    Falls back to a no-op cache when Redis is unavailable.
    """

    def __init__(self):
        self._redis = None

    def _get_redis(self):
        if self._redis is not None:
            return self._redis
        try:
            import redis
            url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
            self._redis = redis.from_url(url, decode_responses=True)
            self._redis.ping()
            return self._redis
        except Exception:
            logger.debug("Redis unavailable — cache disabled")
            self._redis = None
            return None

    def get(self, key: str) -> Any | None:
        """Retrieve a cached value. Returns None on miss or Redis unavailability."""
        r = self._get_redis()
        if r is None:
            return None
        try:
            raw = r.get(f"{_PREFIX}{key}")
            if raw is None:
                return None
            return json.loads(raw)
        except Exception:
            logger.debug("Cache get failed for %s", key)
            return None

    def set(
        self,
        key: str,
        value: Any,
        ttl: int = 300,
        tags: list[str] | None = None,
    ) -> None:
        """Store a value with optional TTL (seconds) and tags for invalidation."""
        r = self._get_redis()
        if r is None:
            return
        try:
            full_key = f"{_PREFIX}{key}"
            r.setex(full_key, ttl, json.dumps(value, default=str))
            # Register key under each tag for invalidation
            if tags:
                pipe = r.pipeline()
                for tag in tags:
                    tag_key = f"{_TAG_PREFIX}{tag}"
                    pipe.sadd(tag_key, full_key)
                    pipe.expire(tag_key, ttl * 2)  # tag set lives longer than entries
                pipe.execute()
        except Exception:
            logger.debug("Cache set failed for %s", key)

    def delete(self, key: str) -> None:
        """Delete a specific cache entry."""
        r = self._get_redis()
        if r is None:
            return
        try:
            r.delete(f"{_PREFIX}{key}")
        except Exception:
            pass

    def invalidate_tag(self, tag: str) -> int:
        """Delete all cache entries associated with a tag. Returns count deleted."""
        r = self._get_redis()
        if r is None:
            return 0
        try:
            tag_key = f"{_TAG_PREFIX}{tag}"
            members = r.smembers(tag_key)
            if not members:
                return 0
            pipe = r.pipeline()
            for key in members:
                pipe.delete(key)
            pipe.delete(tag_key)
            pipe.execute()
            return len(members)
        except Exception:
            logger.debug("Cache invalidate_tag failed for %s", tag)
            return 0

    def cached(
        self,
        ttl: int = 300,
        key_func: Callable[..., str] | None = None,
        tags_func: Callable[..., list[str]] | None = None,
    ) -> Callable:
        """Decorator that caches function results.

        Args:
            ttl: Cache TTL in seconds.
            key_func: Function to compute cache key from args. Defaults to function name + args.
            tags_func: Function to compute tags from args for invalidation.
        """
        def decorator(fn: Callable) -> Callable:
            @functools.wraps(fn)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                if key_func:
                    cache_key = key_func(*args, **kwargs)
                else:
                    cache_key = f"{fn.__name__}:{args}:{kwargs}"

                result = self.get(cache_key)
                if result is not None:
                    return result

                result = fn(*args, **kwargs)

                tags = tags_func(*args, **kwargs) if tags_func else None
                self.set(cache_key, result, ttl=ttl, tags=tags)
                return result
            return wrapper
        return decorator


# Module-level singleton
api_cache = ApiCache()
