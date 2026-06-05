"""Telemetry data retention enforcement Celery task.

Daily task: for each workspace, resolves the plan tier's
``telemetry_retention_days``, finds sessions with raw data older than
the retention window, sends warning emails (7 days before), and
deletes raw telemetry data past the deadline.

Default retention: 12 months from session ``created_at``.
Override via plan tier's ``telemetry_retention_days`` or entitlement overrides.

Preserves: processed reports, scores, laps, annotations (indefinite retention).
Deletes: gps_traces, raw_telemetry_chunks, session files on disk, cached artifacts.
Marks sessions as ``retention_expired`` (idempotent — skips already-expired).

All retention actions are logged to ``retention_audit`` (24-month retention on
audit logs themselves). Each enforcement run gets a unique ``run_id``.

Environment:
    RETENTION_DRY_RUN=1           — log what would be deleted without actually deleting
    RETENTION_DEFAULT_DAYS=365    — default retention when plan has no explicit value
    TELEMETRY_RAW_DIR=data/raw    — base directory for raw upload files
    TELEMETRY_CACHE_DIR=data/cache — base directory for analysis cache files
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import date, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

_DRY_RUN = os.environ.get("RETENTION_DRY_RUN", "0") == "1"

# Default retention: 12 months (365 days)
_DEFAULT_RETENTION_DAYS = int(os.environ.get("RETENTION_DEFAULT_DAYS", "365"))

# Batch size to avoid loading all sessions at once
_BATCH_SIZE = 100

# Tables containing raw telemetry data (safe to delete)
_RAW_DATA_TABLES = [
    "gps_traces",
    "reference_lines",
    "driving_style_features",
    "theoretical_data",
    "corner_metrics",
    "session_weather",
    "session_weather_laps",
    "data_health",
]

# Tables containing derived artifacts (deleted on full purge)
_DERIVED_TABLES = [
    "session_sectors",
    "condition_phases",
    "condition_markers",
    "stint_analysis",
    "session_tags",
]


def _get_pg_conn():
    """Raw psycopg2 connection on the maintenance DSN (telemetry_maint).

    Retention enforcement deletes across ALL workspaces by design, so it
    needs the BYPASSRLS (but non-superuser) maintenance role — the app role
    is row-security-scoped and cannot see other tenants' rows.
    """
    import psycopg2
    import psycopg2.extras

    from web.db_pg import _get_maint_url

    conn = psycopg2.connect(_get_maint_url())
    conn.autocommit = False
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    return conn


def _get_workspace_retention(conn, workspace_id: int) -> int | None:
    """Resolve effective retention days for a workspace.

    Checks entitlement_overrides first, then falls back to plan_definitions.
    Returns None for unlimited (B2B / override).
    """
    cur = conn.cursor()

    # Check workspace-level override
    cur.execute(
        "SELECT override_value FROM entitlement_overrides "
        "WHERE workspace_id = %s AND override_key = 'telemetry_retention_days' "
        "AND (expires_at IS NULL OR expires_at > NOW()) "
        "LIMIT 1",
        (workspace_id,),
    )
    row = cur.fetchone()
    if row:
        import json
        try:
            val = json.loads(row["override_value"])
            if isinstance(val, dict):
                val = val.get("value")
            return None if val is None else int(val)
        except (ValueError, TypeError, json.JSONDecodeError):
            pass

    # Resolve from workspace owner's plan tier
    cur.execute(
        "SELECT u.plan_tier FROM workspaces w "
        "JOIN users u ON w.owner_user_id = u.id "
        "WHERE w.id = %s",
        (workspace_id,),
    )
    row = cur.fetchone()
    if row is None:
        return _DEFAULT_RETENTION_DAYS  # Fallback to default retention

    plan_tier = row.get("plan_tier") or "locked"

    cur.execute(
        "SELECT telemetry_retention_days FROM plan_definitions WHERE tier = %s",
        (plan_tier,),
    )
    row = cur.fetchone()
    if row is None:
        return 30

    return row.get("telemetry_retention_days")  # None = unlimited


def _find_expiring_sessions(conn, workspace_id: int, cutoff_date, limit: int):
    """Find sessions past the retention cutoff that aren't already expired."""
    cur = conn.cursor()
    cur.execute(
        "SELECT session_id, csv_filename, created_at FROM sessions "
        "WHERE workspace_id = %s "
        "AND created_at < %s "
        "AND (retention_expired IS NULL OR retention_expired = FALSE) "
        "ORDER BY created_at ASC "
        "LIMIT %s",
        (workspace_id, cutoff_date, limit),
    )
    return cur.fetchall()


def _find_warning_sessions(conn, workspace_id: int, warning_date, cutoff_date, limit: int):
    """Find sessions that will expire within the warning window (7 days)."""
    cur = conn.cursor()
    cur.execute(
        "SELECT session_id, csv_filename, created_at FROM sessions "
        "WHERE workspace_id = %s "
        "AND created_at >= %s AND created_at < %s "
        "AND (retention_expired IS NULL OR retention_expired = FALSE) "
        "AND (retention_warning_sent IS NULL OR retention_warning_sent = FALSE) "
        "ORDER BY created_at ASC "
        "LIMIT %s",
        (workspace_id, cutoff_date, warning_date, limit),
    )
    return cur.fetchall()


def _delete_raw_data(conn, session_id: str, dry_run: bool = False) -> int:
    """Delete raw telemetry data for a session. Returns total rows deleted."""
    cur = conn.cursor()
    total_deleted = 0

    for table in _RAW_DATA_TABLES:
        if dry_run:
            cur.execute(
                f"SELECT COUNT(*) AS cnt FROM {table} WHERE session_id = %s",
                (session_id,),
            )
            row = cur.fetchone()
            total_deleted += row["cnt"] if row else 0
        else:
            cur.execute(
                f"DELETE FROM {table} WHERE session_id = %s",
                (session_id,),
            )
            total_deleted += cur.rowcount

    return total_deleted


def _mark_session_expired(conn, session_id: str):
    """Mark a session as retention-expired (keeps session row + reports)."""
    cur = conn.cursor()
    cur.execute(
        "UPDATE sessions SET retention_expired = TRUE WHERE session_id = %s",
        (session_id,),
    )


def _mark_warning_sent(conn, session_ids: list[str]):
    """Mark sessions as having received a retention warning email."""
    if not session_ids:
        return
    cur = conn.cursor()
    cur.execute(
        "UPDATE sessions SET retention_warning_sent = TRUE "
        "WHERE session_id = ANY(%s)",
        (session_ids,),
    )


def _log_audit(conn, workspace_id: int, action: str, details: dict):
    """Record retention action in audit_log (legacy compatibility)."""
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO audit_log (workspace_id, action, new_value) "
        "VALUES (%s, %s, %s)",
        (workspace_id, action, json.dumps(details)),
    )


def _log_retention_audit(
    conn,
    run_id: str,
    workspace_id: int | None,
    subject_type: str,
    subject_id: str,
    action: str,
    reason: str,
    result: str,
    *,
    actor: str = "system",
    details: dict | None = None,
    request_id: str | None = None,
):
    """Record a retention action in the dedicated retention_audit table."""
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO retention_audit "
        "(run_id, workspace_id, subject_type, subject_id, action, "
        "reason, actor, result, details_json, request_id) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            run_id, workspace_id, subject_type, subject_id, action,
            reason, actor, result,
            json.dumps(details) if details else None,
            request_id,
        ),
    )


def _delete_session_files(
    session_id: str,
    workspace_id: int,
    *,
    dry_run: bool = False,
) -> int:
    """Delete raw upload files and cached artifacts for a session.

    Scans TELEMETRY_RAW_DIR and TELEMETRY_CACHE_DIR for files matching
    the session_id. Returns count of files deleted.
    """
    deleted = 0
    raw_dir = Path(os.environ.get("TELEMETRY_RAW_DIR", "data/raw"))
    cache_dir = Path(os.environ.get("TELEMETRY_CACHE_DIR", "data/cache"))

    for base_dir in (raw_dir, cache_dir):
        ws_dir = base_dir / str(workspace_id)
        if not ws_dir.is_dir():
            continue
        for path in ws_dir.glob(f"*{session_id}*"):
            if not path.is_file():
                continue
            if dry_run:
                logger.info("DRY RUN: would delete %s", path)
                deleted += 1
            else:
                try:
                    path.unlink()
                    deleted += 1
                except OSError as exc:
                    logger.warning("Failed to delete %s: %s", path, exc)

    return deleted


def _enforce_retention_impl() -> dict:
    """Core retention enforcement logic.

    Each run gets a unique run_id. All actions are logged to retention_audit.
    Returns summary dict with counts of warnings sent and sessions expired.
    """
    run_id = str(uuid.uuid4())[:12]
    conn = _get_pg_conn()
    try:
        cur = conn.cursor()
        today = date.today()

        # Get all workspaces
        cur.execute("SELECT id FROM workspaces")
        workspaces = cur.fetchall()

        total_warned = 0
        total_expired = 0
        total_rows_deleted = 0

        for ws in workspaces:
            ws_id = ws["id"]
            retention_days = _get_workspace_retention(conn, ws_id)

            # NULL = unlimited (B2B) — skip
            if retention_days is None:
                continue

            cutoff_date = today - timedelta(days=retention_days)
            warning_date = today - timedelta(days=retention_days - 7)

            # ── Send warning emails (7 days before expiry) ──────────────
            warning_sessions = _find_warning_sessions(
                conn, ws_id, warning_date, cutoff_date, _BATCH_SIZE,
            )
            if warning_sessions:
                # Get workspace owner email
                cur.execute(
                    "SELECT u.email, u.display_name FROM workspaces w "
                    "JOIN users u ON w.owner_user_id = u.id "
                    "WHERE w.id = %s",
                    (ws_id,),
                )
                owner = cur.fetchone()
                if owner:
                    try:
                        from auth.email import send_retention_warning
                        sessions_info = [
                            {"session_id": s["session_id"],
                             "file_name": s.get("csv_filename", "Unknown"),
                             "created_at": str(s["created_at"])}
                            for s in warning_sessions
                        ]
                        days_remaining = 7
                        if not _DRY_RUN:
                            send_retention_warning(
                                owner["email"], sessions_info, days_remaining,
                            )
                            _mark_warning_sent(
                                conn,
                                [s["session_id"] for s in warning_sessions],
                            )
                            conn.commit()
                        total_warned += len(warning_sessions)
                        logger.info(
                            "Retention warning: workspace=%d sessions=%d%s",
                            ws_id, len(warning_sessions),
                            " (DRY RUN)" if _DRY_RUN else "",
                        )
                    except Exception:
                        logger.warning(
                            "Failed to send retention warning for workspace=%d",
                            ws_id, exc_info=True,
                        )

            # ── Delete expired raw data ─────────────────────────────────
            expired_sessions = _find_expiring_sessions(
                conn, ws_id, cutoff_date, _BATCH_SIZE,
            )
            if not expired_sessions:
                continue

            ws_rows_deleted = 0
            ws_files_deleted = 0
            expired_ids = []

            for session in expired_sessions:
                sid = session["session_id"]

                # Log identify action
                _log_retention_audit(
                    conn, run_id, ws_id, "session", sid, "identify",
                    "retention_expired", "success",
                    details={"retention_days": retention_days},
                )

                rows_deleted = _delete_raw_data(conn, sid, dry_run=_DRY_RUN)
                files_deleted = _delete_session_files(
                    sid, ws_id, dry_run=_DRY_RUN,
                )
                ws_rows_deleted += rows_deleted
                ws_files_deleted += files_deleted

                if not _DRY_RUN:
                    _mark_session_expired(conn, sid)

                # Log delete action
                _log_retention_audit(
                    conn, run_id, ws_id, "session", sid, "delete",
                    "retention_expired",
                    "success" if not _DRY_RUN else "skipped",
                    details={
                        "rows_deleted": rows_deleted,
                        "files_deleted": files_deleted,
                        "dry_run": _DRY_RUN,
                    },
                )
                expired_ids.append(sid)

            if not _DRY_RUN:
                # Send deletion notification email
                cur.execute(
                    "SELECT u.email, u.display_name FROM workspaces w "
                    "JOIN users u ON w.owner_user_id = u.id "
                    "WHERE w.id = %s",
                    (ws_id,),
                )
                owner = cur.fetchone()
                if owner:
                    try:
                        from auth.email import send_retention_deleted
                        sessions_info = [
                            {"session_id": s["session_id"],
                             "file_name": s.get("csv_filename", "Unknown"),
                             "created_at": str(s["created_at"])}
                            for s in expired_sessions
                        ]
                        send_retention_deleted(owner["email"], sessions_info)
                    except Exception:
                        logger.warning(
                            "Failed to send deletion notification for workspace=%d",
                            ws_id, exc_info=True,
                        )

                _log_audit(conn, ws_id, "retention_enforced", {
                    "run_id": run_id,
                    "sessions_expired": len(expired_ids),
                    "rows_deleted": ws_rows_deleted,
                    "files_deleted": ws_files_deleted,
                    "retention_days": retention_days,
                })
                conn.commit()

            total_expired += len(expired_ids)
            total_rows_deleted += ws_rows_deleted

            logger.info(
                "Retention enforced: workspace=%d expired=%d rows=%d files=%d%s",
                ws_id, len(expired_ids), ws_rows_deleted, ws_files_deleted,
                " (DRY RUN)" if _DRY_RUN else "",
            )

        logger.info(
            "Retention enforcement complete: run_id=%s warned=%d expired=%d rows=%d%s",
            run_id, total_warned, total_expired, total_rows_deleted,
            " (DRY RUN)" if _DRY_RUN else "",
        )
        return {
            "run_id": run_id,
            "warned": total_warned,
            "expired": total_expired,
            "rows_deleted": total_rows_deleted,
            "dry_run": _DRY_RUN,
        }

    except Exception as exc:
        conn.rollback()
        logger.error("Retention enforcement failed: %s", exc, exc_info=True)
        raise
    finally:
        conn.close()


def _cleanup_retention_audit_impl() -> dict:
    """Delete retention_audit rows older than 24 months.

    Audit logs have their own retention: 24 months from performed_at.
    Idempotent and safe to rerun.
    """
    conn = _get_pg_conn()
    try:
        cur = conn.cursor()
        cutoff = date.today() - timedelta(days=730)  # ~24 months
        cur.execute(
            "DELETE FROM retention_audit WHERE performed_at < %s",
            (cutoff,),
        )
        deleted = cur.rowcount
        conn.commit()
        logger.info("Retention audit cleanup: deleted %d rows older than %s", deleted, cutoff)
        return {"deleted": deleted, "cutoff": str(cutoff)}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── Register as Celery task or plain function ─────────────────────────

try:
    from celery_app import celery

    @celery.task(queue="default", bind=True, max_retries=2)
    def enforce_telemetry_retention(self):
        """Daily Celery Beat task: delete raw telemetry past plan retention."""
        try:
            return _enforce_retention_impl()
        except Exception as exc:
            raise self.retry(exc=exc, countdown=300)

    @celery.task(queue="default", max_retries=1)
    def cleanup_retention_audit():
        """Monthly task: trim retention_audit rows older than 24 months."""
        return _cleanup_retention_audit_impl()

except ImportError:
    logger.debug("Celery not available — retention task not registered")

    def enforce_telemetry_retention():
        """Stub when Celery is not available."""
        return _enforce_retention_impl()

    def cleanup_retention_audit():
        """Stub when Celery is not available."""
        return _cleanup_retention_audit_impl()
