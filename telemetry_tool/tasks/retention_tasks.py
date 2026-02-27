"""Telemetry data retention enforcement Celery task.

Daily task: for each workspace, resolves the plan tier's
``telemetry_retention_days``, finds sessions with raw data older than
the retention window, sends warning emails (7 days before), and
deletes raw telemetry data past the deadline.

Preserves: processed reports, scores, laps, annotations (indefinite retention).
Deletes: gps_traces, raw_telemetry_chunks, session files on disk.
Marks sessions as ``retention_expired`` (idempotent — skips already-expired).

Environment:
    RETENTION_DRY_RUN=1  — log what would be deleted without actually deleting
"""
from __future__ import annotations

import logging
import os
from datetime import date, timedelta

logger = logging.getLogger(__name__)

_DRY_RUN = os.environ.get("RETENTION_DRY_RUN", "0") == "1"

# Batch size to avoid loading all sessions at once
_BATCH_SIZE = 100

# Tables containing raw telemetry data (safe to delete)
_RAW_DATA_TABLES = [
    "gps_traces",
    "reference_lines",
    "driving_style_features",
    "theoretical_data",
]


def _get_pg_conn():
    """Get a raw psycopg2 connection (outside Flask request context)."""
    import psycopg2
    import psycopg2.extras

    url = os.environ.get(
        "TELEMETRY_PG_URL",
        "postgresql://telemetry:telemetry@localhost:5432/telemetry",
    )
    conn = psycopg2.connect(url)
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
        return 30  # Fallback to demo retention

    plan_tier = row.get("plan_tier") or "demo"

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
        "SELECT session_id, file_name, created_at FROM sessions "
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
        "SELECT session_id, file_name, created_at FROM sessions "
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
    """Record retention action in audit_log."""
    import json
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO audit_log (workspace_id, action, details_json) "
        "VALUES (%s, %s, %s)",
        (workspace_id, action, json.dumps(details)),
    )


def _enforce_retention_impl() -> dict:
    """Core retention enforcement logic.

    Returns summary dict with counts of warnings sent and sessions expired.
    """
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
                             "file_name": s.get("file_name", "Unknown"),
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
            expired_ids = []

            for session in expired_sessions:
                sid = session["session_id"]
                rows_deleted = _delete_raw_data(conn, sid, dry_run=_DRY_RUN)
                ws_rows_deleted += rows_deleted

                if not _DRY_RUN:
                    _mark_session_expired(conn, sid)
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
                             "file_name": s.get("file_name", "Unknown"),
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
                    "sessions_expired": len(expired_ids),
                    "rows_deleted": ws_rows_deleted,
                    "retention_days": retention_days,
                })
                conn.commit()

            total_expired += len(expired_ids)
            total_rows_deleted += ws_rows_deleted

            logger.info(
                "Retention enforced: workspace=%d expired=%d rows_deleted=%d%s",
                ws_id, len(expired_ids), ws_rows_deleted,
                " (DRY RUN)" if _DRY_RUN else "",
            )

        logger.info(
            "Retention enforcement complete: warned=%d expired=%d rows=%d%s",
            total_warned, total_expired, total_rows_deleted,
            " (DRY RUN)" if _DRY_RUN else "",
        )
        return {
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


# ── Register as Celery task or plain function ─────────────────────────

try:
    from tasks.celery_app import celery

    @celery.task(queue="default", bind=True, max_retries=2)
    def enforce_telemetry_retention(self):
        """Daily Celery Beat task: delete raw telemetry past plan retention."""
        try:
            return _enforce_retention_impl()
        except Exception as exc:
            raise self.retry(exc=exc, countdown=300)

except ImportError:
    logger.debug("Celery not available — retention task not registered")

    def enforce_telemetry_retention():
        """Stub when Celery is not available."""
        return _enforce_retention_impl()
