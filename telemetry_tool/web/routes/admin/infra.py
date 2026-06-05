"""Admin infrastructure routes — storage, maintenance mode.

Endpoints:
- GET  /admin/infra/storage — storage breakdown
- GET  /admin/infra/maintenance — maintenance mode status
- POST /admin/infra/maintenance — toggle maintenance mode
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from flask import Blueprint, g, request

from web.api_utils import ErrorCode, api_error, api_response

from .middleware import require_admin_role, require_superadmin

logger = logging.getLogger(__name__)

bp = Blueprint("admin_infra", __name__)

MAINTENANCE_KEY = "lap:maintenance_mode"


def _get_conn():
    from web.db_pg import get_pg_connection
    return get_pg_connection()


def _get_redis():
    try:
        import redis

        from web.config import Config
        return redis.Redis.from_url(Config.REDIS_URL, socket_timeout=2, decode_responses=True)
    except Exception:
        return None


def _serialize_row(row):
    r = dict(row) if not isinstance(row, dict) else row
    result = {}
    for k, v in r.items():
        if hasattr(v, "isoformat"):
            result[k] = v.isoformat()
        else:
            result[k] = v
    return result


def _raw_conn():
    """Return a raw psycopg2 connection on the maintenance DSN.

    Admin infra queries need cross-workspace visibility, so they must not
    use the per-request PgConnectionWrapper (RLS-scoped to one workspace by
    the tenant middleware). The telemetry_maint role is BYPASSRLS but
    non-superuser — the app role itself can no longer see across tenants.
    """
    import psycopg2
    from psycopg2.extras import RealDictCursor

    from web.db_pg import _get_maint_url
    return psycopg2.connect(_get_maint_url(), cursor_factory=RealDictCursor)


def _collect_storage_metrics(conn) -> dict:
    """Collect comprehensive storage metrics from DB + filesystem.

    Uses a raw connection (not the request-scoped one) to bypass RLS
    so admin gets cross-workspace aggregates.
    """
    import os
    import shutil

    metrics: dict = {}

    # Use raw connection to bypass RLS
    raw = _raw_conn()
    cur = raw.cursor()

    # 1. PostgreSQL database size
    cur.execute("SELECT pg_database_size(current_database()) AS size")
    row = cur.fetchone()
    metrics["db_size_bytes"] = row["size"] if row else 0

    # 2. Top 10 largest tables
    cur.execute(
        "SELECT relname AS table_name, "
        "pg_total_relation_size(c.oid) AS total_bytes, "
        "pg_relation_size(c.oid) AS data_bytes, "
        "pg_indexes_size(c.oid) AS index_bytes "
        "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'public' AND c.relkind = 'r' "
        "ORDER BY pg_total_relation_size(c.oid) DESC LIMIT 10"
    )
    metrics["top_tables"] = [_serialize_row(r) for r in cur.fetchall()]

    # 3. Upload storage (from ingestion_jobs)
    cur.execute(
        "SELECT COALESCE(SUM(file_size), 0) AS total_bytes, "
        "COUNT(*) AS file_count, "
        "COALESCE(AVG(file_size), 0) AS avg_bytes, "
        "COALESCE(MAX(file_size), 0) AS max_bytes "
        "FROM ingestion_jobs WHERE status = 'completed'"
    )
    row = cur.fetchone()
    metrics["uploads"] = _serialize_row(row) if row else {}

    # 4. Per-workspace storage breakdown (top 10)
    cur.execute(
        "SELECT w.display_name AS workspace_name, "
        "COALESCE(SUM(ij.file_size), 0) AS total_bytes, "
        "COUNT(ij.job_id) AS file_count "
        "FROM workspaces w LEFT JOIN ingestion_jobs ij "
        "ON ij.workspace_id = w.id AND ij.status = 'completed' "
        "GROUP BY w.id, w.display_name "
        "ORDER BY total_bytes DESC LIMIT 10"
    )
    metrics["per_user_storage"] = [_serialize_row(r) for r in cur.fetchall()]

    # 5. Filesystem disk usage (host-level)
    try:
        disk = shutil.disk_usage("/")
        metrics["disk"] = {
            "total_bytes": disk.total,
            "used_bytes": disk.used,
            "free_bytes": disk.free,
            "used_pct": round(disk.used / disk.total * 100, 1) if disk.total else 0,
        }
    except Exception:
        metrics["disk"] = None

    # 6. Upload directory size (if accessible)
    upload_dir = os.environ.get("UPLOAD_DIR", "/app/data/raw")
    try:
        dir_total = 0
        dir_count = 0
        for dirpath, _, filenames in os.walk(upload_dir):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                try:
                    dir_total += os.path.getsize(fp)
                    dir_count += 1
                except OSError:
                    pass
        metrics["upload_dir"] = {
            "path": upload_dir,
            "total_bytes": dir_total,
            "file_count": dir_count,
        }
    except Exception:
        metrics["upload_dir"] = None

    # 7. Redis memory (if available)
    try:
        r = _get_redis()
        if r:
            info = r.info("memory")
            metrics["redis"] = {
                "used_memory_bytes": info.get("used_memory", 0),
                "peak_memory_bytes": info.get("used_memory_peak", 0),
                "max_memory_bytes": info.get("maxmemory", 0),
            }
    except Exception:
        metrics["redis"] = None

    # 8. Row counts for key tables
    cur.execute(
        "SELECT "
        "(SELECT COUNT(*) FROM users WHERE deleted_at IS NULL) AS users, "
        "(SELECT COUNT(*) FROM sessions) AS sessions, "
        "(SELECT COUNT(*) FROM laps) AS laps, "
        "(SELECT COUNT(*) FROM app_events) AS events, "
        "(SELECT COUNT(*) FROM ingestion_jobs) AS uploads"
    )
    row = cur.fetchone()
    metrics["row_counts"] = _serialize_row(row) if row else {}

    # Clean up raw connection
    raw.close()

    metrics["collected_at"] = datetime.now(timezone.utc).isoformat()
    return metrics


@bp.route("/infra/storage", methods=["GET"])
@require_superadmin
@require_admin_role("root_admin", "sre_admin")
def storage_breakdown():
    """Comprehensive storage breakdown: DB, filesystem, Redis, per-user."""
    conn = _get_conn()
    snapshot = request.args.get("snapshot", "0") == "1"

    metrics = _collect_storage_metrics(conn)

    # Optionally save as snapshot for historical tracking
    if snapshot:
        try:
            conn.execute(
                "INSERT INTO system_metrics_snapshots (collected_at, metrics_json) "
                "VALUES (%(ts)s, %(data)s)",
                {"ts": datetime.now(timezone.utc), "data": json.dumps(metrics)},
            )
            conn.commit()
        except Exception:
            logger.warning("Failed to save storage snapshot", exc_info=True)

    return api_response(metrics)


@bp.route("/infra/storage/history", methods=["GET"])
@require_superadmin
@require_admin_role("root_admin", "sre_admin")
def storage_history():
    """Historical storage snapshots for trend analysis."""
    days = request.args.get("days", 30, type=int)
    days = min(days, 365)
    conn = _get_conn()

    cur.execute(
        "SELECT collected_at, metrics_json FROM system_metrics_snapshots "
        "WHERE collected_at >= now() - make_interval(days => %(days)s) "
        "ORDER BY collected_at",
        {"days": days},
    ).fetchall()

    snapshots = []
    for row in rows:
        r = _serialize_row(row)
        try:
            r["metrics"] = json.loads(r.pop("metrics_json", "{}"))
        except Exception:
            r["metrics"] = {}
        snapshots.append(r)

    return api_response({"snapshots": snapshots})


@bp.route("/infra/maintenance", methods=["GET"])
@require_superadmin
@require_admin_role("root_admin", "sre_admin")
def get_maintenance_status():
    """Get current maintenance mode status."""
    r = _get_redis()
    if not r:
        return api_response({"enabled": False, "redis_available": False})

    raw = r.get(MAINTENANCE_KEY)
    if not raw:
        return api_response({"enabled": False})

    data = json.loads(raw)
    return api_response(data)


@bp.route("/infra/maintenance", methods=["POST"])
@require_superadmin
@require_admin_role("root_admin", "sre_admin")
def toggle_maintenance():
    """Toggle maintenance mode. Audited."""
    r = _get_redis()
    if not r:
        return api_error(
            ErrorCode.SERVICE_UNAVAILABLE,
            "Redis not available",
            status=503,
        )

    body = request.get_json(silent=True) or {}
    enabled = body.get("enabled", True)
    message = body.get("message", "Maintenance in progress")

    if enabled:
        data = {
            "enabled": True,
            "message": message,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "admin_user_id": getattr(g, "current_user_id", None),
        }
        r.set(MAINTENANCE_KEY, json.dumps(data))
    else:
        r.delete(MAINTENANCE_KEY)

    # Audit
    try:
        conn = _get_conn()
        from admin.audit import log_admin_action
        log_admin_action(
            conn,
            admin_user_id=getattr(g, "current_user_id", 0),
            action="maintenance_toggled",
            details={"enabled": enabled, "message": message},
        )
        conn.commit()
    except Exception:
        logger.debug("Failed to log maintenance toggle", exc_info=True)

    return api_response({
        "enabled": enabled,
        "message": message if enabled else None,
    })
