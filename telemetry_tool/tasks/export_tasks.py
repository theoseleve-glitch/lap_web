"""Async export generation tasks.

Generates CSV, JSON, Parquet, or PDF export files for workspace data
(sessions, laps, drivers, tracks, scores).  The Celery task writes the
export file to disk, then updates the ``exports`` table with the file
path, size, and status.

Usage::

    from tasks.export_tasks import generate_export

    generate_export.delay(export_id="exp_001")
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

EXPORT_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "exports")

# ---------------------------------------------------------------------------
# Celery app import (graceful fallback for testing)
# ---------------------------------------------------------------------------

_USE_CELERY = False
try:
    from celery_app import celery as _celery_app
    _USE_CELERY = True
except Exception:
    _celery_app = None


# ---------------------------------------------------------------------------
# PG connection helper
# ---------------------------------------------------------------------------


def _get_pg_connection():
    """Return a PG connection via the web.db_pg module.

    Tests patch this function to inject a mock.
    """
    from web.db_pg import get_pg_connection
    return get_pg_connection()


# ---------------------------------------------------------------------------
# Data queries (respect RLS via the connection-scoped app.current_workspace_id
# GUC set in _generate_export_impl before any RLS table is touched)
# ---------------------------------------------------------------------------

_DATA_QUERIES: dict[str, str] = {
    "sessions": (
        "SELECT s.session_id, s.csv_filename, d.driver_name, t.track_name, "
        "s.session_date, s.n_laps, s.best_lap_time_s, s.total_score, s.grade "
        "FROM sessions s "
        "LEFT JOIN drivers d ON s.driver_id = d.driver_id "
        "LEFT JOIN tracks t ON s.track_id = t.track_id "
        "ORDER BY s.session_date DESC"
    ),
    "laps": (
        "SELECT session_id, lap_number, lap_time_s, speed_mean_mps, "
        "speed_max_mps, is_valid "
        "FROM laps ORDER BY session_id, lap_number"
    ),
    "drivers": (
        "SELECT driver_id, driver_name, created_at "
        "FROM drivers ORDER BY driver_name"
    ),
    "tracks": (
        "SELECT track_id, track_name, lap_length_m, created_at "
        "FROM tracks ORDER BY track_name"
    ),
    "scores": (
        "SELECT session_id, total_score, grade, pace_score, "
        "consistency_score, execution_score, robustness_score "
        "FROM score_details ORDER BY session_id"
    ),
}

_VALID_DATA_TYPES = frozenset(_DATA_QUERIES.keys())
_VALID_FORMATS = frozenset({"csv", "json", "parquet", "pdf"})


# ---------------------------------------------------------------------------
# File generators
# ---------------------------------------------------------------------------


def _generate_csv(rows: list[dict[str, Any]], file_path: str) -> None:
    """Write rows to a CSV file using DictWriter."""
    if not rows:
        Path(file_path).write_text("", encoding="utf-8")
        return

    fieldnames = list(rows[0].keys())
    with open(file_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _generate_json(rows: list[dict[str, Any]], file_path: str) -> None:
    """Write rows as a JSON array with datetime serialisation."""
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, default=str)


def _generate_parquet(rows: list[dict[str, Any]], file_path: str) -> None:
    """Write rows to a Parquet file via PyArrow."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    table = pa.Table.from_pylist(rows)
    pq.write_table(table, file_path)


def _generate_pdf(rows: list[dict[str, Any]], file_path: str) -> None:
    """Write rows to a PDF file using reportlab, fallback to JSON."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.units import inch
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

        if not rows:
            # Empty PDF with no table
            doc = SimpleDocTemplate(file_path, pagesize=landscape(A4))
            doc.build([])
            return

        headers = list(rows[0].keys())
        table_data = [headers]
        for row in rows:
            table_data.append([str(row.get(h, "")) for h in headers])

        doc = SimpleDocTemplate(file_path, pagesize=landscape(A4))
        t = Table(table_data)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 9),
            ("FONTSIZE", (0, 1), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ]))
        doc.build([t])

    except ImportError:
        # reportlab not installed -- fallback to JSON
        logger.warning("reportlab not installed, falling back to JSON for PDF export")
        _generate_json(rows, file_path)


_FORMAT_GENERATORS = {
    "csv": _generate_csv,
    "json": _generate_json,
    "parquet": _generate_parquet,
    "pdf": _generate_pdf,
}

_FORMAT_EXTENSIONS = {
    "csv": ".csv",
    "json": ".json",
    "parquet": ".parquet",
    "pdf": ".pdf",
}


# ---------------------------------------------------------------------------
# Core implementation
# ---------------------------------------------------------------------------


def _generate_export_impl(export_id: str) -> dict[str, Any]:
    """Generate an export file.

    Steps:
        0. Resolve the export's owning workspace_id cross-tenant and set the
           connection-scoped RLS GUC (the export row lives in the RLS
           ``exports`` table, so it can't be read on the app connection
           until the GUC is set -- chicken-and-egg).
        1. Fetch export record by ID
        2. Update status to 'generating'
        3. Query data based on data_type
        4. Generate file in requested format
        5. Update DB: status='ready', file_path, file_size, completed_at
        On error: status='failed', error message

    Args:
        export_id: The exports row ID.

    Returns:
        Dict with export_id, file_path, and file_size.
    """
    from sqlalchemy import text

    os.makedirs(EXPORT_DIR, exist_ok=True)
    conn = _get_pg_connection()

    # 0. Resolve the owning workspace_id BEFORE touching any RLS table.
    #    Under the P0 RLS cutover the app role is NOBYPASSRLS, so the very
    #    first `SELECT * FROM exports` fails closed unless the connection GUC
    #    `app.current_workspace_id` is already set.  The export row that
    #    carries workspace_id is itself in the RLS `exports` table, so read
    #    just that one column over a BYPASSRLS maintenance connection.
    from web.db_pg import get_maint_connection, return_pg_connection

    maint = get_maint_connection()
    try:
        ws_row = maint.execute(
            text("SELECT workspace_id FROM exports WHERE id = :id"),
            {"id": export_id},
        ).fetchone()
    finally:
        return_pg_connection(maint)

    if ws_row is None:
        logger.error("Export record not found: %s", export_id)
        return {"export_id": export_id, "error": "not_found"}

    ws_row = dict(ws_row) if not isinstance(ws_row, dict) else ws_row
    workspace_id = ws_row.get("workspace_id")

    # Set the RLS context connection-scoped (NOT SET LOCAL): this task does
    # several commits (status updates), and a SET LOCAL would be cleared at
    # the first commit boundary -- a plain SET survives until the connection
    # closes, keeping every subsequent RLS query scoped to this workspace.
    if workspace_id is not None:
        conn.execute(
            text("SET app.current_workspace_id = :ws"),
            {"ws": str(workspace_id)},
        )

    # 1. Fetch export record (now permitted by RLS for this workspace)
    row = conn.execute(
        text("SELECT * FROM exports WHERE id = :id"),
        {"id": export_id},
    ).fetchone()

    if row is None:
        logger.error("Export record not found: %s", export_id)
        return {"export_id": export_id, "error": "not_found"}

    export = dict(row) if not isinstance(row, dict) else row
    data_type = export.get("data_type")
    file_format = export.get("format")
    user_id = export.get("user_id")

    if data_type not in _VALID_DATA_TYPES:
        _update_export_status(conn, export_id, "failed",
                              error_message=f"Invalid data_type: {data_type}")
        return {"export_id": export_id, "error": "invalid_data_type"}

    if file_format not in _VALID_FORMATS:
        _update_export_status(conn, export_id, "failed",
                              error_message=f"Invalid format: {file_format}")
        return {"export_id": export_id, "error": "invalid_format"}

    # 2. Update status to 'generating'
    _update_export_status(conn, export_id, "generating")

    try:
        # 3. Query data (RLS context already set connection-scoped in step 0)
        query = _DATA_QUERIES[data_type]
        cursor = conn.execute(text(query))
        rows = [dict(r) if not isinstance(r, dict) else r
                for r in cursor.fetchall()]

        # 4. Generate file
        ext = _FORMAT_EXTENSIONS[file_format]
        filename = f"export_{export_id}_{data_type}{ext}"
        file_path = os.path.join(EXPORT_DIR, filename)

        generator = _FORMAT_GENERATORS[file_format]
        generator(rows, file_path)

        file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0

        # 5. Update DB with success
        conn.execute(
            text(
                "UPDATE exports SET "
                "  status = 'ready',"
                "  file_path = :file_path,"
                "  file_size = :file_size,"
                "  completed_at = now() "
                "WHERE id = :id"
            ),
            {
                "id": export_id,
                "file_path": file_path,
                "file_size": file_size,
            },
        )
        conn.commit()

        logger.info(
            "Export completed: id=%s type=%s format=%s rows=%d size=%d",
            export_id, data_type, file_format, len(rows), file_size,
        )
        return {
            "export_id": export_id,
            "file_path": file_path,
            "file_size": file_size,
        }

    except Exception as exc:
        logger.error("Export failed: id=%s error=%s", export_id, exc)
        _update_export_status(conn, export_id, "failed",
                              error_message=str(exc)[:500])
        raise


def _update_export_status(
    conn,
    export_id: str,
    status: str,
    error_message: str | None = None,
) -> None:
    """Update an exports row with new status and optional error message."""
    from sqlalchemy import text

    params: dict[str, Any] = {
        "id": export_id,
        "status": status,
    }
    set_clauses = ["status = :status"]

    if error_message is not None:
        set_clauses.append("error = :error")
        params["error"] = error_message

    sql = f"UPDATE exports SET {', '.join(set_clauses)} WHERE id = :id"
    conn.execute(text(sql), params)
    conn.commit()


# ---------------------------------------------------------------------------
# Register as Celery tasks (or plain functions when Celery unavailable)
# ---------------------------------------------------------------------------

if _USE_CELERY and _celery_app is not None:
    @_celery_app.task(
        bind=True,
        name="tasks.export_tasks.generate_export",
        queue="default",
        max_retries=2,
    )
    def generate_export(self, export_id: str) -> dict[str, Any]:
        """Celery task wrapper for export generation."""
        try:
            return _generate_export_impl(export_id)
        except Exception as exc:
            logger.error(
                "Export task failed (attempt %d/%d): %s",
                self.request.retries + 1,
                self.max_retries + 1,
                exc,
            )
            raise self.retry(exc=exc, countdown=30 * (self.request.retries + 1))
else:
    def generate_export(export_id: str) -> dict[str, Any]:  # type: ignore[misc]
        """Synchronous fallback when Celery is unavailable."""
        return _generate_export_impl(export_id)
