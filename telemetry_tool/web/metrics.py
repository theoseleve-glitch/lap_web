"""Lightweight Redis-backed metrics collection.

Provides counters and histograms using Redis INCR + sorted-set operations.
Buckets are keyed by hour (``metrics:{name}:{YYYY-MM-DDTHH}``) with a 48-hour
TTL so stale data auto-expires.

The ``record_request`` after-request hook auto-increments HTTP counters.
The ``/admin/metrics`` endpoint returns a snapshot of recent metrics.

All operations fail silently when Redis is unavailable — metrics are
best-effort and must never block request processing.

Usage::

    from web.metrics import init_metrics

    # In app factory
    init_metrics(app)
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from flask import Flask, g, jsonify, request

logger = logging.getLogger(__name__)

# TTL for metric keys (48 hours)
_BUCKET_TTL = 48 * 3600


# ---------------------------------------------------------------------------
# Redis helpers (fail-silent)
# ---------------------------------------------------------------------------


def _get_redis(app=None):
    """Get the app's Redis client, or None."""
    if app is not None:
        return app.extensions.get("redis")
    try:
        from flask import current_app
        return current_app.extensions.get("redis")
    except RuntimeError:
        return None


def _bucket_key(name: str, ts: datetime | None = None) -> str:
    """Build an hourly-bucketed Redis key."""
    if ts is None:
        ts = datetime.now(timezone.utc)
    hour = ts.strftime("%Y-%m-%dT%H")
    return f"metrics:{name}:{hour}"


def incr_counter(name: str, amount: int = 1, redis_client=None) -> None:
    """Increment a named counter in the current hourly bucket."""
    r = redis_client or _get_redis()
    if r is None:
        return
    try:
        key = _bucket_key(name)
        pipe = r.pipeline(transaction=False)
        pipe.incrby(key, amount)
        pipe.expire(key, _BUCKET_TTL)
        pipe.execute()
    except Exception:
        pass  # Fail silently


def record_histogram(name: str, value: float, redis_client=None) -> None:
    """Record a value in a histogram (sorted set, score = value)."""
    r = redis_client or _get_redis()
    if r is None:
        return
    try:
        key = _bucket_key(f"hist:{name}")
        member = f"{value:.3f}:{time.monotonic_ns()}"
        pipe = r.pipeline(transaction=False)
        pipe.zadd(key, {member: value})
        pipe.expire(key, _BUCKET_TTL)
        pipe.execute()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------


def get_counter_values(name: str, hours: int = 24, redis_client=None) -> dict:
    """Read counter values for the last N hours.

    Returns::

        {"total": int, "buckets": {"2026-02-27T14": int, ...}}
    """
    r = redis_client or _get_redis()
    if r is None:
        return {"total": 0, "buckets": {}}
    try:
        now = datetime.now(timezone.utc)
        buckets = {}
        total = 0
        pipe = r.pipeline(transaction=False)
        keys = []
        for h in range(hours):
            from datetime import timedelta
            ts = now - timedelta(hours=h)
            key = _bucket_key(name, ts)
            keys.append(ts.strftime("%Y-%m-%dT%H"))
            pipe.get(key)
        values = pipe.execute()
        for label, val in zip(keys, values):
            count = int(val) if val else 0
            buckets[label] = count
            total += count
        return {"total": total, "buckets": buckets}
    except Exception:
        return {"total": 0, "buckets": {}}


def get_histogram_stats(name: str, hours: int = 1, redis_client=None) -> dict:
    """Compute p50/p95/p99/max from the histogram sorted set.

    Returns::

        {"count": int, "p50": float, "p95": float, "p99": float, "max": float}
    """
    r = redis_client or _get_redis()
    if r is None:
        return {"count": 0}
    try:
        now = datetime.now(timezone.utc)
        all_values = []
        for h in range(hours):
            from datetime import timedelta
            ts = now - timedelta(hours=h)
            key = _bucket_key(f"hist:{name}", ts)
            members = r.zrangebyscore(key, "-inf", "+inf", withscores=True)
            all_values.extend(score for _, score in members)

        if not all_values:
            return {"count": 0}

        all_values.sort()
        n = len(all_values)
        return {
            "count": n,
            "p50": all_values[int(n * 0.50)],
            "p95": all_values[min(int(n * 0.95), n - 1)],
            "p99": all_values[min(int(n * 0.99), n - 1)],
            "max": all_values[-1],
        }
    except Exception:
        return {"count": 0}


# ---------------------------------------------------------------------------
# Auto-instrumentation hook
# ---------------------------------------------------------------------------


def init_metrics(app: Flask) -> None:
    """Register after_request hook to auto-record HTTP metrics."""

    @app.after_request
    def _record_metrics(response):
        try:
            r = _get_redis(app)
            if r is None:
                return response

            # Counter: total requests by status class
            status_class = f"{response.status_code // 100}xx"
            incr_counter(f"http_{status_class}", redis_client=r)
            incr_counter("http_total", redis_client=r)

            # Counter: errors (4xx/5xx)
            if response.status_code >= 400:
                incr_counter("http_errors", redis_client=r)
            if response.status_code >= 500:
                incr_counter("http_5xx", redis_client=r)

            # Histogram: request duration
            start = getattr(g, "_request_start_time", None)
            if start is not None:
                duration_ms = (time.monotonic() - start) * 1000
                record_histogram("request_duration_ms", duration_ms, redis_client=r)

        except Exception:
            pass  # Never block responses

        return response

    # Register the metrics admin endpoint
    from flask import Blueprint
    metrics_bp = Blueprint("admin_metrics", __name__, url_prefix="/admin")

    @metrics_bp.route("/metrics")
    def admin_metrics():
        """Return a snapshot of recent metrics.

        This endpoint is intended for internal monitoring dashboards.
        In production, it should be protected by IP allowlist or admin auth.
        """
        r = _get_redis(app)
        if r is None:
            return jsonify({"error": "Redis not available"}), 503

        data = {
            "http": {
                "total_24h": get_counter_values("http_total", hours=24, redis_client=r),
                "errors_24h": get_counter_values("http_errors", hours=24, redis_client=r),
                "5xx_24h": get_counter_values("http_5xx", hours=24, redis_client=r),
            },
            "latency": {
                "last_hour": get_histogram_stats("request_duration_ms", hours=1, redis_client=r),
            },
            "jobs": _get_job_metrics(r),
            "webhooks": {
                "processed_24h": get_counter_values("webhook_processed", hours=24, redis_client=r),
                "failed_24h": get_counter_values("webhook_failed", hours=24, redis_client=r),
                "latency": get_histogram_stats("webhook_latency_ms", hours=1, redis_client=r),
                "retry_queue": _get_webhook_queue_metrics(r),
            },
            "billing": {
                "checkout_sessions_24h": get_counter_values("checkout_session_created", hours=24, redis_client=r),
                "plan_required_errors_24h": get_counter_values("plan_required_error", hours=24, redis_client=r),
                "portal_sessions_24h": get_counter_values("portal_session_created", hours=24, redis_client=r),
                "plan_switches_24h": get_counter_values("plan_switch_validated", hours=24, redis_client=r),
                "billing_profile_updates_24h": get_counter_values("billing_profile_updated", hours=24, redis_client=r),
                "upgrade_funnel": {
                    "checkout_started_24h": get_counter_values("checkout_session_created", hours=24, redis_client=r),
                    "subscription_activated_24h": get_counter_values("subscription_activated", hours=24, redis_client=r),
                },
                "payment_recovery": {
                    "past_due_24h": get_counter_values("subscription_past_due", hours=24, redis_client=r),
                    "recovered_24h": get_counter_values("subscription_recovered", hours=24, redis_client=r),
                },
                "entitlement_cache": {
                    "hits_24h": get_counter_values("entitlement_cache_hit", hours=24, redis_client=r),
                    "misses_24h": get_counter_values("entitlement_cache_miss", hours=24, redis_client=r),
                    "invalidations_24h": get_counter_values("entitlement_cache_invalidation", hours=24, redis_client=r),
                },
                "idempotency": {
                    "replayed_24h": get_counter_values("idempotency_replay", hours=24, redis_client=r),
                },
                "time_to_activate": get_histogram_stats("time_to_activate_s", hours=24, redis_client=r),
            },
        }
        return jsonify(data), 200

    app.register_blueprint(metrics_bp)


def _get_webhook_queue_metrics(redis_client) -> dict:
    """Count pending retries and dead-lettered webhooks from PG."""
    try:
        from web.db_pg import get_pg_connection
        conn = get_pg_connection()
        row = conn.execute(
            "SELECT "
            "COUNT(*) FILTER (WHERE processing_status = 'failed' AND next_retry_at IS NOT NULL) AS pending_retry, "
            "COUNT(*) FILTER (WHERE processing_status = 'deadletter') AS deadlettered "
            "FROM stripe_webhook_log"
        ).fetchone()
        if row:
            r = dict(row) if not isinstance(row, dict) else row
            return {
                "pending_retry": r.get("pending_retry", 0),
                "deadlettered": r.get("deadlettered", 0),
            }
    except Exception:
        pass
    return {"pending_retry": 0, "deadlettered": 0}


def _get_job_metrics(redis_client) -> dict:
    """Gather job metrics from PostgreSQL."""
    try:
        from web.db_pg import get_pg_connection
        conn = get_pg_connection()
        row = conn.execute(
            "SELECT "
            "COUNT(*) FILTER (WHERE status IN ('queued', 'running', 'processing')) AS active, "
            "COUNT(*) FILTER (WHERE status = 'failed' AND updated_at > NOW() - INTERVAL '24 hours') AS failed_24h, "
            "COUNT(*) FILTER (WHERE status = 'completed' AND updated_at > NOW() - INTERVAL '24 hours') AS completed_24h "
            "FROM ingestion_jobs"
        ).fetchone()
        if row:
            r = dict(row) if not isinstance(row, dict) else row
            return {
                "active": r.get("active", 0),
                "failed_24h": r.get("failed_24h", 0),
                "completed_24h": r.get("completed_24h", 0),
            }
    except Exception:
        pass
    return {"active": 0, "failed_24h": 0, "completed_24h": 0}
