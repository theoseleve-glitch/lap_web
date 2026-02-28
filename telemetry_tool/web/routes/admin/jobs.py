"""Admin jobs routes — cross-workspace job management.

Endpoints:
- GET  /admin/jobs — list jobs with filters
- GET  /admin/jobs/stats — aggregate statistics
- GET  /admin/jobs/:id — job detail
- POST /admin/jobs/:id/retry — re-dispatch failed job
- POST /admin/jobs/:id/cancel — cancel running job
"""
from __future__ import annotations

import logging

from flask import Blueprint, g, request

from web.api_utils import api_response, api_error, ErrorCode
from .middleware import require_superadmin, require_admin_role

logger = logging.getLogger(__name__)

bp = Blueprint("admin_jobs", __name__)


def _get_conn():
    from web.db_pg import get_pg_connection
    return get_pg_connection()


def _serialize_row(row):
    """Convert a row dict, handling datetime serialization."""
    r = dict(row) if not isinstance(row, dict) else row
    result = {}
    for k, v in r.items():
        if hasattr(v, "isoformat"):
            result[k] = v.isoformat()
        else:
            result[k] = v
    return result


@bp.route("/jobs", methods=["GET"])
@require_superadmin
def list_jobs():
    """List jobs cross-workspace. Filters: status, user_id, workspace_id, time range."""
    conn = _get_conn()
    status = request.args.get("status")
    user_id = request.args.get("user_id", type=int)
    workspace_id = request.args.get("workspace_id", type=int)
    limit = request.args.get("limit", 50, type=int)
    limit = min(limit, 200)
    cursor = request.args.get("cursor")

    conditions = []
    params = {"limit": limit}

    if status:
        conditions.append("status = %(status)s")
        params["status"] = status

    if user_id:
        conditions.append("user_id = %(user_id)s")
        params["user_id"] = user_id

    if workspace_id:
        conditions.append("workspace_id = %(workspace_id)s")
        params["workspace_id"] = workspace_id

    if cursor:
        conditions.append("created_at < %(cursor)s")
        params["cursor"] = cursor

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    rows = conn.execute(
        f"SELECT job_id, file_name, status, user_id, workspace_id, "
        f"created_at, started_at, completed_at, error_message, "
        f"EXTRACT(EPOCH FROM (COALESCE(completed_at, NOW()) - started_at)) AS duration_s "
        f"FROM ingestion_jobs {where} "
        f"ORDER BY created_at DESC LIMIT %(limit)s",
        params,
    ).fetchall()

    return api_response([_serialize_row(r) for r in rows])


@bp.route("/jobs/stats", methods=["GET"])
@require_superadmin
def job_stats():
    """Aggregate job statistics for the last 24 hours."""
    conn = _get_conn()

    row = conn.execute(
        "SELECT COUNT(*) AS total, "
        "COUNT(*) FILTER (WHERE status = 'failed') AS failed, "
        "COUNT(*) FILTER (WHERE status IN ('queued', 'running')) AS queue_depth, "
        "PERCENTILE_CONT(0.5) WITHIN GROUP "
        "  (ORDER BY EXTRACT(EPOCH FROM (completed_at - started_at))) "
        "  FILTER (WHERE completed_at IS NOT NULL) AS p50_duration, "
        "PERCENTILE_CONT(0.95) WITHIN GROUP "
        "  (ORDER BY EXTRACT(EPOCH FROM (completed_at - started_at))) "
        "  FILTER (WHERE completed_at IS NOT NULL) AS p95_duration "
        "FROM ingestion_jobs "
        "WHERE created_at > NOW() - INTERVAL '24 hours'"
    ).fetchone()

    stats = _serialize_row(row)

    # Top error classes
    error_rows = conn.execute(
        "SELECT SUBSTRING(error_message FROM '^[^:]+') AS error_class, "
        "COUNT(*) AS cnt "
        "FROM ingestion_jobs "
        "WHERE status = 'failed' AND error_message IS NOT NULL "
        "AND created_at > NOW() - INTERVAL '24 hours' "
        "GROUP BY error_class ORDER BY cnt DESC LIMIT 5"
    ).fetchall()

    stats["top_errors"] = [_serialize_row(r) for r in error_rows]

    total = stats.get("total", 0) or 0
    failed = stats.get("failed", 0) or 0
    stats["failure_rate_pct"] = round((failed / total * 100) if total > 0 else 0, 1)

    return api_response(stats)


@bp.route("/jobs/<job_id>", methods=["GET"])
@require_superadmin
def get_job_detail(job_id: str):
    """Detailed job view."""
    conn = _get_conn()

    row = conn.execute(
        "SELECT job_id, file_name, status, user_id, workspace_id, "
        "error_message, celery_task_id, retry_count, "
        "created_at, started_at, completed_at, "
        "peak_rss_mb, throughput_mb_s "
        "FROM ingestion_jobs WHERE job_id = %(jid)s",
        {"jid": job_id},
    ).fetchone()

    if not row:
        return api_error(ErrorCode.NOT_FOUND, "Job not found", status=404)

    return api_response(_serialize_row(row))


@bp.route("/jobs/<job_id>/retry", methods=["POST"])
@require_superadmin
@require_admin_role("root_admin", "sre_admin")
def retry_job(job_id: str):
    """Re-dispatch a failed job. Requires reason. Audited."""
    conn = _get_conn()
    body = request.get_json(silent=True) or {}
    reason = body.get("reason", "Admin retry")

    row = conn.execute(
        "SELECT job_id, status, retry_count, file_name, user_id, workspace_id "
        "FROM ingestion_jobs WHERE job_id = %(jid)s",
        {"jid": job_id},
    ).fetchone()

    if not row:
        return api_error(ErrorCode.NOT_FOUND, "Job not found", status=404)

    job = dict(row) if not isinstance(row, dict) else row

    if job["status"] not in ("failed", "error"):
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            f"Cannot retry job with status '{job['status']}'",
            status=400,
        )

    # Reset to pending
    conn.execute(
        "UPDATE ingestion_jobs SET status = 'queued', "
        "error_message = NULL, retry_count = retry_count + 1 "
        "WHERE job_id = %(jid)s",
        {"jid": job_id},
    )
    conn.commit()

    # Audit
    try:
        from admin.audit import log_admin_action
        log_admin_action(
            conn, admin_user_id=getattr(g, "current_user_id", None),
            action="job_retried",
            target_type="job", target_id=job_id,
            reason=reason,
        )
        conn.commit()
    except Exception:
        logger.debug("Failed to log job retry", exc_info=True)

    return api_response({"job_id": job_id, "new_status": "queued"})


@bp.route("/jobs/<job_id>/cancel", methods=["POST"])
@require_superadmin
@require_admin_role("root_admin", "sre_admin")
def cancel_job(job_id: str):
    """Cancel a running job. Requires reason. Audited."""
    conn = _get_conn()
    body = request.get_json(silent=True) or {}
    reason = body.get("reason", "Admin cancel")

    row = conn.execute(
        "SELECT job_id, status, celery_task_id "
        "FROM ingestion_jobs WHERE job_id = %(jid)s",
        {"jid": job_id},
    ).fetchone()

    if not row:
        return api_error(ErrorCode.NOT_FOUND, "Job not found", status=404)

    job = dict(row) if not isinstance(row, dict) else row

    if job["status"] not in ("queued", "running", "processing"):
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            f"Cannot cancel job with status '{job['status']}'",
            status=400,
        )

    # Revoke Celery task if available
    celery_task_id = job.get("celery_task_id")
    if celery_task_id:
        try:
            from celery_app import celery
            celery.control.revoke(celery_task_id, terminate=True)
        except Exception:
            logger.debug("Failed to revoke Celery task", exc_info=True)

    conn.execute(
        "UPDATE ingestion_jobs SET status = 'cancelled', "
        "error_message = %(reason)s WHERE job_id = %(jid)s",
        {"reason": f"Cancelled by admin: {reason}", "jid": job_id},
    )
    conn.commit()

    # Audit
    try:
        from admin.audit import log_admin_action
        log_admin_action(
            conn, admin_user_id=getattr(g, "current_user_id", None),
            action="job_cancelled",
            target_type="job", target_id=job_id,
            reason=reason,
        )
        conn.commit()
    except Exception:
        logger.debug("Failed to log job cancellation", exc_info=True)

    return api_response({"job_id": job_id, "new_status": "cancelled"})
