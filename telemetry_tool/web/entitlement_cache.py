"""Redis-backed entitlement cache with webhook-driven invalidation.

Cache key: ``ent:{user_id}`` → JSON entitlement snapshot.
TTL: 120 seconds (configurable).
Invalidated on: webhook billing events, billing-mutating endpoint success.

Usage::

    from web.entitlement_cache import cached_entitlements, invalidate_entitlements

    ents = cached_entitlements(user_id, workspace_id)  # cache-first
    invalidate_entitlements(user_id)                    # on billing change
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_CACHE_TTL = 120  # seconds
_LOCK_TTL = 5     # singleflight lock

# ── Redis accessor ───────────────────────────────────────────────────


def _get_redis():
    """Get the Flask app's Redis client."""
    try:
        from flask import current_app
        return current_app.extensions.get("redis")
    except RuntimeError:
        return None


# ── Cache operations ─────────────────────────────────────────────────


def _cache_key(user_id: int) -> str:
    return f"ent:{user_id}"


def _lock_key(user_id: int) -> str:
    return f"ent:lock:{user_id}"


def cached_entitlements(user_id: int, workspace_id: int | None = None) -> dict:
    """Return entitlements from cache or DB (cache-aside pattern).

    Uses a singleflight lock to prevent cache stampede: only one
    request computes and caches when multiple arrive simultaneously.
    """
    r = _get_redis()
    if r is None:
        return _fetch_from_db(user_id, workspace_id)

    key = _cache_key(user_id)

    # 1. Try cache
    try:
        cached = r.get(key)
        if cached is not None:
            try:
                from web.metrics import incr_counter
                incr_counter("entitlement_cache_hit", redis_client=r)
            except Exception:
                pass
            return json.loads(cached)
    except Exception:
        logger.debug("Redis read failed for entitlement cache", exc_info=True)

    # 2. Cache miss — acquire singleflight lock
    try:
        from web.metrics import incr_counter
        incr_counter("entitlement_cache_miss", redis_client=r)
    except Exception:
        pass

    lock = _lock_key(user_id)
    try:
        acquired = r.set(lock, "1", nx=True, ex=_LOCK_TTL)
    except Exception:
        acquired = True  # Fail open

    if not acquired:
        # Another request is computing — wait briefly then check cache
        time.sleep(0.05)
        try:
            cached = r.get(key)
            if cached is not None:
                return json.loads(cached)
        except Exception:
            pass

    # 3. Fetch from DB
    ents = _fetch_from_db(user_id, workspace_id)

    # 4. Store in cache
    try:
        payload = json.dumps(ents, default=str)
        r.set(key, payload, ex=_CACHE_TTL)
    except Exception:
        logger.debug("Redis write failed for entitlement cache", exc_info=True)
    finally:
        try:
            r.delete(lock)
        except Exception:
            pass

    return ents


def invalidate_entitlements(user_id: int) -> None:
    """Delete cached entitlements for a user (webhook/billing change)."""
    r = _get_redis()
    if r is None:
        return
    try:
        r.delete(_cache_key(user_id))
        try:
            from web.metrics import incr_counter
            incr_counter("entitlement_cache_invalidation", redis_client=r)
        except Exception:
            pass
    except Exception:
        logger.debug("Redis delete failed for entitlement cache", exc_info=True)


def invalidate_by_stripe_customer(customer_id: str) -> None:
    """Invalidate entitlement cache for a Stripe customer ID.

    Looks up user_id from DB, then invalidates.
    """
    try:
        from web.db_pg import get_pg_connection
        conn = get_pg_connection()
        cur = conn.execute(
            "SELECT id FROM users WHERE stripe_customer_id = %(cid)s",
            {"cid": customer_id},
        )
        row = cur.fetchone()
        if row:
            uid = (dict(row) if not isinstance(row, dict) else row)["id"]
            invalidate_entitlements(uid)
    except Exception:
        logger.debug("Failed to invalidate cache by customer_id", exc_info=True)


# ── Internal ─────────────────────────────────────────────────────────


def _fetch_from_db(user_id: int, workspace_id: int | None = None) -> dict:
    """Fetch entitlements from DB (not cached)."""
    from auth.entitlements import get_user_entitlements

    try:
        from flask import current_app
        if current_app.config.get("USE_PG"):
            from web.db_pg import get_pg_connection
            conn = get_pg_connection()
        else:
            from web.db import get_db_connection
            conn = get_db_connection()
    except RuntimeError:
        from web.db_pg import get_pg_connection
        conn = get_pg_connection()

    return get_user_entitlements(conn, user_id, workspace_id)
