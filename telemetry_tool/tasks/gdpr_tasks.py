"""GDPR Celery tasks — data export and account purge.

``export_user_data`` gathers all user data from PostgreSQL, reduces GPS
precision, packages into a ZIP file, and updates the ``data_exports`` row.

``purge_deleted_accounts`` runs on Celery beat daily and hard-deletes
accounts where ``deleted_at`` is older than 30 days.

Usage::

    from tasks.gdpr_tasks import export_user_data, purge_deleted_accounts

    # Dispatch export
    export_user_data.delay(user_id=1, export_id="exp_001")

    # Celery beat config
    beat_schedule = {
        "purge-deleted-accounts": {
            "task": "tasks.gdpr_tasks.purge_deleted_accounts",
            "schedule": crontab(hour=3, minute=0),
        },
    }
"""
from __future__ import annotations

import json
import logging
import os
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

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


def get_pg_connection():
    """Get a PostgreSQL connection from the shared pool.

    Tests patch this function to inject a mock.
    """
    from web.db_pg import get_pg_connection as _get_pg
    return _get_pg()


# ---------------------------------------------------------------------------
# GPS precision reduction (data minimization)
# ---------------------------------------------------------------------------

def _reduce_gps_precision(data: dict[str, Any]) -> dict[str, Any]:
    """Reduce GPS coordinate precision to 3 decimal places.

    Applies to ``gps_lat``, ``gps_lon``, ``latitudes``, and ``longitudes``
    fields.  Returns a new dict (does not mutate the input).
    """
    result = dict(data)

    for key in ("gps_lat", "gps_lon"):
        if key in result and result[key] is not None:
            result[key] = round(float(result[key]), 3)

    for key in ("latitudes", "longitudes"):
        if key in result and isinstance(result[key], list):
            result[key] = [
                round(float(v), 3) if v is not None else None
                for v in result[key]
            ]

    return result


# ---------------------------------------------------------------------------
# Export status update helper
# ---------------------------------------------------------------------------

def _update_export_status(
    conn,
    export_id: str,
    status: str,
    file_path: str | None = None,
    expires_at: datetime | None = None,
):
    """Update a data_exports row with new status and optional file_path."""
    from sqlalchemy import text

    params: dict[str, Any] = {
        "export_id": export_id,
        "status": status,
    }
    set_clauses = ["status = :status", "updated_at = now()"]

    if file_path is not None:
        set_clauses.append("file_path = :file_path")
        params["file_path"] = file_path

    if expires_at is not None:
        set_clauses.append("expires_at = :expires_at")
        params["expires_at"] = expires_at

    if status == "completed":
        set_clauses.append("completed_at = now()")

    sql = f"UPDATE data_exports SET {', '.join(set_clauses)} WHERE id = :export_id"
    conn.execute(text(sql), params)
    conn.commit()


# ---------------------------------------------------------------------------
# ZIP writer
# ---------------------------------------------------------------------------

def _write_zip(
    zip_path: str,
    profile: dict[str, Any],
    sessions: list[dict[str, Any]],
    laps: list[dict[str, Any]],
    scores: list[dict[str, Any]],
    annotations: list[dict[str, Any]],
    teams: list[dict[str, Any]],
):
    """Write a GDPR export ZIP file containing JSON files per resource.

    All GPS fields are already precision-reduced before this is called.
    """
    def _default(obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return str(obj)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("profile.json", json.dumps(profile, indent=2, default=_default))
        zf.writestr("sessions.json", json.dumps(sessions, indent=2, default=_default))
        zf.writestr("laps.json", json.dumps(laps, indent=2, default=_default))
        zf.writestr("scores.json", json.dumps(scores, indent=2, default=_default))
        zf.writestr("annotations.json", json.dumps(annotations, indent=2, default=_default))
        zf.writestr("teams.json", json.dumps(teams, indent=2, default=_default))


# ---------------------------------------------------------------------------
# Task: export_user_data
# ---------------------------------------------------------------------------

def _export_user_data_impl(user_id: int, export_id: str) -> dict[str, Any]:
    """Export all data for a user into a downloadable ZIP file.

    Steps:
        1. Set export status to 'processing'
        2. Query all user data from PG
        3. Reduce GPS precision to 3 decimal places
        4. Package into ZIP
        5. Update data_exports row with file_path and status='completed'
        6. Set expires_at to 7 days from now

    Args:
        user_id: The user whose data to export.
        export_id: The data_exports row ID.

    Returns:
        Dict with export_id and file_path.
    """
    from sqlalchemy import text

    conn = get_pg_connection()

    # 1. Mark as processing
    _update_export_status(conn, export_id, "processing")

    try:
        # 2. Query user profile
        user = conn.execute(
            text("SELECT id, email, display_name, created_at FROM users WHERE id = :uid"),
            {"uid": user_id},
        ).fetchone()
        profile = dict(user) if user else {"id": user_id, "note": "user not found"}

        # Query sessions
        session_rows = conn.execute(
            text(
                "SELECT * FROM sessions s "
                "JOIN workspace_members wm ON s.workspace_id = wm.workspace_id "
                "WHERE wm.user_id = :uid"
            ),
            {"uid": user_id},
        ).fetchall()
        sessions = [dict(r) for r in session_rows]

        # Query laps (for user's sessions)
        laps = []
        for sess in sessions:
            lap_rows = conn.execute(
                text("SELECT * FROM laps WHERE session_id = :sid"),
                {"sid": sess["session_id"]},
            ).fetchall()
            laps.extend([_reduce_gps_precision(dict(r)) for r in lap_rows])

        # Query scores
        scores = []
        for sess in sessions:
            score_rows = conn.execute(
                text("SELECT * FROM score_details WHERE session_id = :sid"),
                {"sid": sess["session_id"]},
            ).fetchall()
            scores.extend([dict(r) for r in score_rows])

        # Query annotations
        annotations = []
        for sess in sessions:
            ann_rows = conn.execute(
                text("SELECT * FROM session_annotations WHERE session_id = :sid"),
                {"sid": sess["session_id"]},
            ).fetchall()
            annotations.extend([dict(r) for r in ann_rows])

        # Query team memberships
        team_rows = conn.execute(
            text(
                "SELECT t.name, t.slug, tm.role, tm.joined_at "
                "FROM team_members tm JOIN teams t ON tm.team_id = t.id "
                "WHERE tm.user_id = :uid"
            ),
            {"uid": user_id},
        ).fetchall()
        teams = [dict(r) for r in team_rows]

        # 3. Reduce GPS precision on sessions
        sessions = [_reduce_gps_precision(s) for s in sessions]

        # 4. Write ZIP
        export_dir = os.environ.get("TELEMETRY_EXPORT_DIR", "/tmp/telemetry_exports")
        os.makedirs(export_dir, exist_ok=True)
        zip_filename = f"export_{user_id}_{export_id}.zip"
        zip_path = os.path.join(export_dir, zip_filename)

        _write_zip(zip_path, profile, sessions, laps, scores, annotations, teams)

        # 5. Update status to completed
        expires_at = datetime.now(timezone.utc) + timedelta(days=7)
        _update_export_status(
            conn, export_id, "completed",
            file_path=zip_path,
            expires_at=expires_at,
        )

        logger.info("GDPR export completed: user_id=%s, export_id=%s", user_id, export_id)
        return {"export_id": export_id, "file_path": zip_path}

    except Exception as exc:
        logger.error("GDPR export failed: user_id=%s, error=%s", user_id, exc)
        _update_export_status(conn, export_id, "failed")
        raise


# ---------------------------------------------------------------------------
# Task: purge_deleted_accounts
# ---------------------------------------------------------------------------

def _purge_deleted_accounts_impl() -> dict[str, int]:
    """Hard-delete user accounts where deleted_at is older than 30 days.

    Steps:
        1. Query users WHERE deleted_at < now() - 30 days
        2. For each: cascade delete workspace data, sessions, scores, files
        3. Hard delete user row
        4. Log count of purged accounts

    Returns:
        Dict with ``{"purged": N}``
    """
    from sqlalchemy import text

    conn = get_pg_connection()
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)

    # 1. Find accounts past grace period
    rows = conn.execute(
        text("SELECT id, email FROM users WHERE deleted_at IS NOT NULL AND deleted_at < :cutoff"),
        {"cutoff": cutoff},
    ).fetchall()
    users_to_purge = [dict(r) for r in rows]

    if not users_to_purge:
        logger.info("No accounts to purge (0 past 30-day window)")
        return {"purged": 0}

    purged = 0
    for user in users_to_purge:
        uid = user["id"]
        try:
            # 2. Cascade delete workspace data
            ws_rows = conn.execute(
                text("SELECT id FROM workspaces WHERE owner_id = :uid"),
                {"uid": uid},
            ).fetchall()
            workspace_ids = [r["id"] for r in ws_rows]

            for ws_id in workspace_ids:
                session_rows = conn.execute(
                    text("SELECT session_id FROM sessions WHERE workspace_id = :ws"),
                    {"ws": ws_id},
                ).fetchall()
                for sess in session_rows:
                    sid = sess.get("session_id") if isinstance(sess, dict) else getattr(sess, "session_id", None)
                    if sid is None:
                        continue
                    for table in [
                        "gps_traces", "laps", "score_details",
                        "corner_metrics", "session_annotations",
                        "session_tags", "theoretical_data",
                        "reference_lines", "driving_style_features",
                    ]:
                        conn.execute(
                            text(f"DELETE FROM {table} WHERE session_id = :sid"),
                            {"sid": sid},
                        )
                conn.execute(
                    text("DELETE FROM sessions WHERE workspace_id = :ws"),
                    {"ws": ws_id},
                )
                conn.execute(
                    text("DELETE FROM workspace_members WHERE workspace_id = :ws"),
                    {"ws": ws_id},
                )
                conn.execute(
                    text("DELETE FROM workspaces WHERE id = :ws"),
                    {"ws": ws_id},
                )

            conn.execute(
                text("DELETE FROM team_members WHERE user_id = :uid"),
                {"uid": uid},
            )
            conn.execute(
                text("DELETE FROM data_exports WHERE user_id = :uid"),
                {"uid": uid},
            )
            conn.execute(
                text("DELETE FROM refresh_tokens WHERE user_id = :uid"),
                {"uid": uid},
            )

            # 3. Hard delete user row
            conn.execute(
                text("DELETE FROM users WHERE id = :uid"),
                {"uid": uid},
            )
            conn.commit()

            purged += 1
            logger.info("Purged account: user_id=%s, email=%s", uid, user.get("email"))

        except Exception as exc:
            logger.error("Failed to purge user_id=%s: %s", uid, exc)
            try:
                conn.rollback()
            except Exception:
                pass
            continue

    logger.info("Account purge complete: %d accounts purged", purged)
    return {"purged": purged}




# ---------------------------------------------------------------------------
# Task: enforce_raw_data_retention
# ---------------------------------------------------------------------------

def _iter_workspace_tiers(conn) -> list[dict[str, Any]]:
    """Return workspace IDs with their effective normalized tier key."""
    from auth.entitlements import normalize_tier

    rows = conn.execute(
        "SELECT w.id AS workspace_id, "
        "COALESCE(w.plan_tier, owner.billing_plan, 'demo') AS tier "
        "FROM workspaces w "
        "LEFT JOIN users owner ON owner.id = w.owner_user_id"
    ).fetchall()
    out = []
    for row in rows:
        data = dict(row)
        out.append({"workspace_id": data["workspace_id"], "tier": normalize_tier(data.get("tier"))})
    return out


def _write_retention_audit(conn, workspace_id: int, tier: str, deleted_rows: int, deleted_files: int) -> None:
    """Best-effort audit trail write for retention enforcement."""
    from sqlalchemy import text

    try:
        conn.execute(
            text(
                "INSERT INTO audit_log (event_type, workspace_id, details_json, created_at) "
                "VALUES ('raw_retention_enforced', :ws, :details, now())"
            ),
            {
                "ws": workspace_id,
                "details": json.dumps({
                    "tier": tier,
                    "deleted_rows": deleted_rows,
                    "deleted_files": deleted_files,
                }),
            },
        )
    except Exception:
        logger.info(
            "Retention audit (fallback-log): workspace_id=%s tier=%s deleted_rows=%s deleted_files=%s",
            workspace_id, tier, deleted_rows, deleted_files,
        )


def _enforce_raw_data_retention_impl() -> dict[str, int]:
    """Delete raw telemetry artifacts based on per-tier SLA retention windows."""
    from sqlalchemy import text
    from auth.entitlements import get_policy_for_tier

    conn = get_pg_connection()
    workspace_tiers = _iter_workspace_tiers(conn)

    total_deleted_rows = 0
    total_deleted_files = 0

    raw_base = Path(os.environ.get("TELEMETRY_RAW_DIR", "data/raw"))

    for item in workspace_tiers:
        ws_id = int(item["workspace_id"])
        tier = item["tier"]
        policy = get_policy_for_tier(tier)
        cutoff = datetime.now(timezone.utc) - timedelta(days=policy.raw_retention_days)

        deleted_rows = 0
        for table in ("raw_telemetry", "gps_traces"):
            try:
                result = conn.execute(
                    text(
                        f"DELETE FROM {table} WHERE workspace_id = :ws "
                        "AND created_at < :cutoff"
                    ),
                    {"ws": ws_id, "cutoff": cutoff},
                )
                deleted_rows += int(getattr(result, "rowcount", 0) or 0)
            except Exception:
                continue

        deleted_files = 0
        ws_dir = raw_base / str(ws_id)
        if ws_dir.exists() and ws_dir.is_dir():
            for path in ws_dir.glob("**/*"):
                if not path.is_file():
                    continue
                if datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc) < cutoff:
                    try:
                        path.unlink()
                        deleted_files += 1
                    except Exception:
                        continue

        _write_retention_audit(conn, ws_id, tier, deleted_rows, deleted_files)
        total_deleted_rows += deleted_rows
        total_deleted_files += deleted_files

    conn.commit()
    logger.info(
        "Retention enforcement complete: workspaces=%s deleted_rows=%s deleted_files=%s",
        len(workspace_tiers), total_deleted_rows, total_deleted_files,
    )
    return {
        "workspaces": len(workspace_tiers),
        "deleted_rows": total_deleted_rows,
        "deleted_files": total_deleted_files,
    }

# ---------------------------------------------------------------------------
# Register as Celery tasks (or plain functions when Celery unavailable)
# ---------------------------------------------------------------------------

if _USE_CELERY and _celery_app is not None:
    @_celery_app.task(bind=True, name="tasks.gdpr_tasks.export_user_data")
    def export_user_data(self, user_id: int, export_id: str) -> dict[str, Any]:
        return _export_user_data_impl(user_id, export_id)

    @_celery_app.task(name="tasks.gdpr_tasks.purge_deleted_accounts")
    def purge_deleted_accounts() -> dict[str, int]:
        return _purge_deleted_accounts_impl()

    @_celery_app.task(name="tasks.gdpr_tasks.enforce_raw_data_retention")
    def enforce_raw_data_retention() -> dict[str, int]:
        return _enforce_raw_data_retention_impl()
else:
    # Fallback: plain functions for testing without Celery
    def export_user_data(user_id: int, export_id: str) -> dict[str, Any]:  # type: ignore[misc]
        return _export_user_data_impl(user_id, export_id)

    def purge_deleted_accounts() -> dict[str, int]:  # type: ignore[misc]
        return _purge_deleted_accounts_impl()

    def enforce_raw_data_retention() -> dict[str, int]:  # type: ignore[misc]
        return _enforce_raw_data_retention_impl()
