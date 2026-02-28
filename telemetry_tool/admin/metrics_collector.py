"""Admin metrics collector — system, DB, security, upload, and Celery metrics.

Collects periodic snapshots and stores them in system_metrics_snapshots.
Designed to run as a Celery beat task every 60 seconds, but all functions
are testable standalone (no Celery dependency in the module itself).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

try:
    import psutil
except ImportError:
    psutil = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Individual collectors
# ---------------------------------------------------------------------------


def _collect_system_metrics() -> dict:
    """Collect CPU, memory, and disk usage via psutil."""
    if psutil is None:
        return {"error": "psutil not available"}
    try:
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        return {
            "cpu_percent": psutil.cpu_percent(interval=0),
            "memory_percent": mem.percent,
            "memory_total_bytes": mem.total,
            "memory_available_bytes": mem.available,
            "disk_percent": disk.percent,
            "disk_total_bytes": disk.total,
            "disk_free_bytes": disk.free,
        }
    except Exception:
        logger.debug("System metrics collection failed", exc_info=True)
        return {"error": "collection failed"}


def _collect_db_metrics(conn) -> dict:
    """Collect database metrics: connections, job aggregates, DB size."""
    try:
        # Active connections
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM pg_stat_activity "
            "WHERE datname = current_database()"
        ).fetchone()
        r = dict(row) if not isinstance(row, dict) else row
        active_connections = r.get("cnt", 0)

        # Job status aggregates (last 24h)
        rows = conn.execute(
            "SELECT status, COUNT(*) AS cnt FROM ingestion_jobs "
            "WHERE created_at > NOW() - INTERVAL '24 hours' "
            "GROUP BY status"
        ).fetchall()
        jobs = {}
        for row in rows:
            r = dict(row) if not isinstance(row, dict) else row
            jobs[r["status"]] = r["cnt"]

        # DB size
        size_row = conn.execute(
            "SELECT pg_database_size(current_database()) AS size"
        ).fetchone()
        sr = dict(size_row) if not isinstance(size_row, dict) else size_row
        db_size = sr.get("size", 0)

        return {
            "active_connections": active_connections,
            "jobs": jobs,
            "db_size_bytes": db_size,
        }
    except Exception:
        logger.debug("DB metrics collection failed", exc_info=True)
        return {"error": "collection failed"}


def _collect_security_metrics(conn) -> dict:
    """Collect security event counts from the last 24 hours."""
    try:
        rows = conn.execute(
            "SELECT event_type, COUNT(*) AS cnt FROM security_events "
            "WHERE created_at > NOW() - INTERVAL '24 hours' "
            "GROUP BY event_type"
        ).fetchall()
        result = {}
        for row in rows:
            r = dict(row) if not isinstance(row, dict) else row
            result[f"{r['event_type']}_24h"] = r["cnt"]
        return result
    except Exception:
        logger.debug("Security metrics collection failed", exc_info=True)
        return {"error": "collection failed"}


def _collect_upload_metrics(conn) -> dict:
    """Collect upload/ingestion stats for today."""
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS total, "
            "COUNT(*) FILTER (WHERE status = 'failed') AS errors "
            "FROM ingestion_jobs "
            "WHERE created_at >= CURRENT_DATE"
        ).fetchone()
        r = dict(row) if not isinstance(row, dict) else row
        return {
            "today": r.get("total", 0),
            "errors": r.get("errors", 0),
        }
    except Exception:
        logger.debug("Upload metrics collection failed", exc_info=True)
        return {"error": "collection failed"}


def _collect_celery_metrics(redis_client) -> dict:
    """Collect Celery queue lengths from Redis."""
    if redis_client is None:
        return {"error": "redis not available"}
    try:
        return {
            "queue_pipeline": redis_client.llen("pipeline"),
            "queue_default": redis_client.llen("default"),
        }
    except Exception:
        logger.debug("Celery metrics collection failed", exc_info=True)
        return {"error": "collection failed"}


# ---------------------------------------------------------------------------
# Snapshot lifecycle
# ---------------------------------------------------------------------------


def collect_snapshot(conn, redis_client=None) -> dict:
    """Collect all metrics into a single snapshot dict.

    This is the main entry point. Does NOT require Celery — testable standalone.
    """
    return {
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "system": _collect_system_metrics(),
        "database": _collect_db_metrics(conn),
        "security": _collect_security_metrics(conn),
        "uploads": _collect_upload_metrics(conn),
        "celery": _collect_celery_metrics(redis_client),
    }


def store_snapshot(conn, snapshot: dict) -> None:
    """Insert a snapshot into system_metrics_snapshots."""
    conn.execute(
        "INSERT INTO system_metrics_snapshots (metrics_json) "
        "VALUES (%(metrics)s)",
        {"metrics": json.dumps(snapshot)},
    )
    conn.commit()


def prune_old_snapshots(conn, max_age_days: int = 7) -> int:
    """Delete snapshots older than max_age_days. Returns count deleted."""
    cur = conn.execute(
        "DELETE FROM system_metrics_snapshots "
        "WHERE collected_at < NOW() - INTERVAL '1 day' * %(days)s",
        {"days": max_age_days},
    )
    conn.commit()
    return cur.rowcount


# ---------------------------------------------------------------------------
# Celery task registration
# ---------------------------------------------------------------------------

_USE_CELERY = False
try:
    from celery_app import celery as _celery_app
    _USE_CELERY = True
except Exception:
    _celery_app = None


def _collect_and_store():
    """Run a full collect-store-prune cycle."""
    from web.db_pg import get_pg_connection
    conn = get_pg_connection()
    try:
        redis_client = None
        try:
            import redis as redis_lib
            from web.config import Config
            redis_client = redis_lib.Redis.from_url(
                Config.REDIS_URL, socket_timeout=2, decode_responses=True
            )
        except Exception:
            pass

        snapshot = collect_snapshot(conn, redis_client)
        store_snapshot(conn, snapshot)
        prune_old_snapshots(conn)
        return snapshot
    finally:
        try:
            conn.close()
        except Exception:
            pass


if _USE_CELERY and _celery_app is not None:
    @_celery_app.task(name="admin.metrics_collector.collect_system_metrics_task")
    def collect_system_metrics_task():
        return _collect_and_store()
else:
    def collect_system_metrics_task():  # type: ignore[misc]
        return _collect_and_store()
