"""Idempotency-key middleware for write endpoints.

Accepts an ``Idempotency-Key`` header and caches the full response
(status + body) in Redis, scoped to the workspace.  Duplicate requests
with the same key replay the cached response without re-executing the
handler.  A short-lived processing lock prevents concurrent duplicates.

Usage::

    from web.idempotency import idempotent

    @bp.route("/teams", methods=["POST"])
    @require_auth
    @idempotent
    def create_team():
        ...
"""
from __future__ import annotations

import functools
import json
import logging
from typing import Any

from flask import g, jsonify, request

from web.redis_health import alert_redis_failopen

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# TTL constants
# ---------------------------------------------------------------------------

_RESPONSE_TTL = 86400  # 24 hours — cached response lifetime
_LOCK_TTL = 60         # 60 seconds — processing lock lifetime

# ---------------------------------------------------------------------------
# Redis accessor (lazy, patchable in tests)
# ---------------------------------------------------------------------------

_redis_client = None


def get_redis():
    """Return the Redis client, creating it lazily on first call.

    Tests patch this function to inject a mock.
    """
    global _redis_client
    if _redis_client is None:
        import redis
        _redis_client = redis.Redis(decode_responses=True)
    return _redis_client


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------

def idempotent(fn):
    """Decorator that enforces idempotency via ``Idempotency-Key`` header.

    Flow
    ----
    1. If the header is missing, pass through — no idempotency.
    2. Check Redis for a cached response.  If found, replay it.
    3. Try ``SET NX`` on a lock key (60s TTL).  If the lock exists,
       return 409 ``IDEMPOTENCY_CONFLICT``.
    4. Execute the handler.
       - 2xx–4xx → cache response (24h TTL).
       - 5xx → do **not** cache (allow retry).
    5. Delete the lock key.
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        idemp_key = request.headers.get("Idempotency-Key")
        if not idemp_key:
            return fn(*args, **kwargs)

        workspace_id = getattr(g, "workspace_id", "default")
        cache_key = f"idempotency:{workspace_id}:{idemp_key}"
        lock_key = f"idempotency:lock:{workspace_id}:{idemp_key}"

        try:
            r = get_redis()
        except Exception:
            logger.warning("Redis unavailable for idempotency — passing through")
            alert_redis_failopen("idempotency")
            return fn(*args, **kwargs)

        # --- 1. Check for cached response ---
        try:
            cached = r.get(cache_key)
        except Exception:
            logger.warning("Redis read failed for idempotency — passing through")
            return fn(*args, **kwargs)
        if cached is not None:
            try:
                payload = json.loads(cached)
                resp = jsonify(payload["body"])
                resp.status_code = payload["status"]
                try:
                    from web.metrics import incr_counter
                    incr_counter("idempotency_replay")
                except Exception:
                    pass
                return resp
            except Exception:
                logger.warning("Corrupt idempotency cache for %s", cache_key)

        # --- 2. Acquire processing lock ---
        try:
            lock_acquired = r.set(lock_key, "1", nx=True, ex=_LOCK_TTL)
        except Exception:
            logger.warning("Redis lock failed for idempotency — passing through")
            return fn(*args, **kwargs)

        if not lock_acquired:
            from web.api_utils import ErrorCode, api_error
            return api_error(
                ErrorCode.IDEMPOTENCY_CONFLICT,
                "A request with this idempotency key is already being processed",
                status=409,
            )

        # --- 3. Execute handler ---
        try:
            result = fn(*args, **kwargs)

            # Normalize Flask return conventions
            if isinstance(result, tuple):
                response = result[0]
                status = result[1] if len(result) > 1 else 200
            else:
                response = result
                status = response.status_code if hasattr(response, "status_code") else 200

            # Get the response body
            if hasattr(response, "get_json"):
                body = response.get_json()
            else:
                body = response

            actual_status = status if isinstance(status, int) else int(status)

            # --- 4. Cache if not 5xx ---
            if actual_status < 500:
                try:
                    cache_payload = json.dumps({"status": actual_status, "body": body})
                    r.set(cache_key, cache_payload, ex=_RESPONSE_TTL)
                except Exception:
                    logger.warning("Redis cache write failed for idempotency key %s", idemp_key)

            return result

        finally:
            # --- 5. Always release lock ---
            try:
                r.delete(lock_key)
            except Exception:
                logger.warning("Redis lock release failed for idempotency key %s", idemp_key)

    return wrapper
