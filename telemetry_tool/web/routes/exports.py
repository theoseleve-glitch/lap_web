"""Export API endpoints — generate, list, and download data exports.

Endpoints:
    POST   /api/v1/exports/generate         - Start an async export
    GET    /api/v1/exports                   - List user's exports
    GET    /api/v1/exports/<id>/download     - Download a completed export

All endpoints require authentication (g.current_user_id, g.workspace_id
from middleware).  Export generation is dispatched as a Celery task on the
``default`` queue.
"""
from __future__ import annotations

import logging
import os
from functools import wraps

from flask import Blueprint, g, request, send_file
from sqlalchemy import text

from web.api_utils import ErrorCode, api_error, api_response
from web.rate_limit import rate_limit

logger = logging.getLogger(__name__)

bp = Blueprint("exports", __name__, url_prefix="/api/v1")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_DATA_TYPES = frozenset({"sessions", "laps", "drivers", "tracks", "scores"})
_VALID_FORMATS = frozenset({"csv", "json", "pdf", "parquet"})

_FORMAT_MIMETYPES = {
    "csv": "text/csv",
    "json": "application/json",
    "parquet": "application/octet-stream",
    "pdf": "application/pdf",
}


def _get_conn():
    """Return a PG connection via the web.db_pg module."""
    from web.db_pg import get_pg_connection
    return get_pg_connection()


def _safe_api(f):
    """Catch unhandled exceptions in API routes -- log + return structured error."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except Exception:
            req_id = getattr(g, "request_id", "?")
            logger.exception(
                "Unhandled error in %s [%s %s] request_id=%s",
                f.__name__, request.method, request.path, req_id,
            )
            return api_error(ErrorCode.INTERNAL_ERROR,
                             "Internal server error", status=500)
    return wrapper


# ---------------------------------------------------------------------------
# POST /api/v1/exports/generate
# ---------------------------------------------------------------------------


@bp.route("/exports/generate", methods=["POST"])
@rate_limit(tier="write")
@_safe_api
def generate_export():
    """Start an async export job.

    Request body::

        {
            "type": "sessions",    // sessions|laps|drivers|tracks|scores
            "format": "csv"        // csv|json|pdf|parquet
        }

    Returns::

        {"id": "...", "status": "pending"}
    """
    body = request.get_json(silent=True)
    if not body:
        return api_error(ErrorCode.VALIDATION_ERROR,
                         "Request body must be JSON", status=400)

    data_type = body.get("type", "").strip().lower()
    file_format = body.get("format", "").strip().lower()

    if data_type not in _VALID_DATA_TYPES:
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            f"Invalid type. Must be one of: {', '.join(sorted(_VALID_DATA_TYPES))}",
            status=400,
        )

    if file_format not in _VALID_FORMATS:
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            f"Invalid format. Must be one of: {', '.join(sorted(_VALID_FORMATS))}",
            status=400,
        )

    conn = _get_conn()
    user_id = getattr(g, "current_user_id", None)
    workspace_id = getattr(g, "workspace_id", None)

    # Insert export record (id is autoincrement Integer per migration 026)
    conn.execute(
        text(
            "INSERT INTO exports (user_id, workspace_id, data_type, format, status) "
            "VALUES (:user_id, :workspace_id, :data_type, :format, 'pending')"
        ),
        {
            "user_id": user_id,
            "workspace_id": workspace_id,
            "data_type": data_type,
            "format": file_format,
        },
    )
    conn.commit()

    # Retrieve the auto-generated id
    row = conn.execute(
        text(
            "SELECT id FROM exports WHERE user_id = :user_id "
            "ORDER BY created_at DESC LIMIT 1"
        ),
        {"user_id": user_id},
    ).fetchone()
    export_id = row["id"] if row else None

    if export_id is None:
        return api_error(ErrorCode.INTERNAL_ERROR,
                         "Failed to create export record", status=500)

    # Dispatch Celery task
    try:
        from tasks.export_tasks import generate_export as _generate_task
        if hasattr(_generate_task, "delay"):
            _generate_task.delay(export_id)
        else:
            # Synchronous fallback (no Celery)
            _generate_task(export_id)
    except Exception:
        logger.exception("Failed to dispatch export task for %s", export_id)
        conn.execute(
            text("UPDATE exports SET status = 'failed', error = 'Task dispatch failed' WHERE id = :id"),
            {"id": export_id},
        )
        conn.commit()
        return api_error(ErrorCode.SERVICE_UNAVAILABLE,
                         "Export task dispatch failed", status=503)

    return api_response({"id": export_id, "status": "pending"}, status=202)


# ---------------------------------------------------------------------------
# GET /api/v1/exports
# ---------------------------------------------------------------------------


@bp.route("/exports", methods=["GET"])
@rate_limit(tier="read")
@_safe_api
def list_exports():
    """List the current user's exports, newest first (max 50).

    Returns::

        {"exports": [{id, data_type, format, status, file_size, created_at, completed_at}, ...]}
    """
    conn = _get_conn()
    user_id = getattr(g, "current_user_id", None)

    cursor = conn.execute(
        text(
            "SELECT id, data_type, format, status, file_size, "
            "error, created_at, completed_at "
            "FROM exports "
            "WHERE user_id = :user_id "
            "ORDER BY created_at DESC "
            "LIMIT 50"
        ),
        {"user_id": user_id},
    )
    rows = cursor.fetchall()
    exports = []
    for row in rows:
        r = dict(row) if not isinstance(row, dict) else row
        # Serialise datetimes to ISO strings
        for key in ("created_at", "completed_at"):
            if r.get(key) is not None and hasattr(r[key], "isoformat"):
                r[key] = r[key].isoformat()
        # Sanitize error — don't leak internal details (stack traces,
        # connection strings, SQL errors) to end users.
        if r.get("error"):
            r["error"] = "Export failed — contact support if this persists."
        exports.append(r)

    return api_response({"exports": exports})


# ---------------------------------------------------------------------------
# GET /api/v1/exports/<export_id>/download
# ---------------------------------------------------------------------------


@bp.route("/exports/<export_id>/download", methods=["GET"])
@rate_limit(tier="read")
@_safe_api
def download_export(export_id: str):
    """Download a completed export file.

    Validates that the export belongs to the requesting user and that the
    status is 'ready'.  Returns the file as an attachment.
    """
    conn = _get_conn()
    user_id = getattr(g, "current_user_id", None)

    row = conn.execute(
        text(
            "SELECT id, user_id, status, file_path, format, data_type "
            "FROM exports "
            "WHERE id = :id"
        ),
        {"id": export_id},
    ).fetchone()

    if row is None:
        return api_error(ErrorCode.NOT_FOUND, "Export not found", status=404)

    export = dict(row) if not isinstance(row, dict) else row

    # Ownership check
    if export.get("user_id") != user_id:
        return api_error(ErrorCode.FORBIDDEN,
                         "You do not have access to this export", status=403)

    if export.get("status") != "ready":
        return api_error(
            ErrorCode.NOT_READY,
            f"Export is not ready (status: {export.get('status')})",
            status=409,
        )

    file_path = export.get("file_path")
    if not file_path or not os.path.isfile(file_path):
        return api_error(ErrorCode.NOT_FOUND,
                         "Export file not found on disk", status=404)

    # Path traversal guard: export files must live under data/exports/
    _EXPORT_DIR = os.path.realpath(
        os.path.join(os.path.dirname(__file__), "..", "..", "data", "exports")
    )
    if not os.path.realpath(file_path).startswith(_EXPORT_DIR):
        logger.warning("Export path traversal attempt: %s", file_path)
        return api_error(ErrorCode.NOT_FOUND,
                         "Export file not found on disk", status=404)

    file_format = export.get("format", "csv")
    data_type = export.get("data_type", "export")
    mimetype = _FORMAT_MIMETYPES.get(file_format, "application/octet-stream")
    ext = {"csv": ".csv", "json": ".json", "parquet": ".parquet", "pdf": ".pdf"}.get(
        file_format, ""
    )
    download_name = f"{data_type}_{export_id[:8]}{ext}"

    return send_file(
        file_path,
        mimetype=mimetype,
        as_attachment=True,
        download_name=download_name,
    )
