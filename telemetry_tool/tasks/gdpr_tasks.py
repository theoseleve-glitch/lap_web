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


def get_maint_connection():
    """Get a standalone BYPASSRLS maintenance connection (telemetry_maint).

    Used by the cross-tenant beat tasks (purge / retention) that must touch
    rows across ALL workspaces. The app role is RLS-scoped and fails closed
    when the workspace GUC is unset, so those sweeps require the maint role.
    Caller MUST close it via ``return_pg_connection``. Thin local wrapper
    (mirrors ``get_pg_connection`` above) so tests can patch it.
    """
    from web.db_pg import get_maint_connection as _get_maint
    return _get_maint()


def return_pg_connection(conn) -> None:
    """Close a standalone connection (rollback + close). Local wrapper."""
    from web.db_pg import return_pg_connection as _return_pg
    _return_pg(conn)


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
    telemetry: dict[str, list[dict[str, Any]]] | None = None,
):
    """Write a GDPR export ZIP file containing JSON files per resource.

    All GPS fields are already precision-reduced before this is called.
    ``telemetry`` is an optional map of ``{table_name: rows}`` for the bulk
    per-session data (gps_traces, weather, corner metrics, theoretical lines)
    that Art. 15/20 portability requires — omitting these made the export
    materially incomplete.
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
        for _name, _rows in (telemetry or {}).items():
            zf.writestr(f"{_name}.json", json.dumps(_rows, indent=2, default=_default))


# ---------------------------------------------------------------------------
# Export workspace resolution
# ---------------------------------------------------------------------------

def _resolve_export_workspace_id(user_id: int) -> int | None:
    """Resolve the workspace to scope a user's GDPR export under RLS.

    The export covers the user's personal workspace. Under the telemetry_app
    role the working connection cannot read RLS tables (sessions/laps/...) until
    ``app.current_workspace_id`` is set, but the task args only carry user_id —
    and ``data_exports`` has **no workspace_id column** to read it from (reading
    it there was the bug that returned empty exports post-RLS-cutover). Resolve
    the user's default workspace (falling back to their earliest membership) via
    the BYPASSRLS maintenance connection, then the caller pins the GUC. Returns
    ``None`` only if the user has no workspace, in which case the caller leaves
    the GUC unset and the RLS reads fail closed (empty export) rather than leak.
    """
    from sqlalchemy import text

    maint = None
    try:
        maint = get_maint_connection()
        row = maint.execute(
            text("SELECT default_workspace_id FROM users WHERE id = :uid"),
            {"uid": user_id},
        ).fetchone()
        ws = dict(row).get("default_workspace_id") if row else None
        if ws is None:
            mrow = maint.execute(
                text(
                    "SELECT workspace_id FROM workspace_members "
                    "WHERE user_id = :uid ORDER BY workspace_id LIMIT 1"
                ),
                {"uid": user_id},
            ).fetchone()
            ws = dict(mrow).get("workspace_id") if mrow else None
        return int(ws) if ws is not None else None
    except Exception as exc:
        logger.warning(
            "Could not resolve export workspace for user_id=%s via maint role: %s",
            user_id, exc,
        )
        return None
    finally:
        if maint is not None:
            return_pg_connection(maint)


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

    # RLS: this is a per-WORKSPACE export, not cross-tenant. The first write
    # below (_update_export_status → UPDATE data_exports) and every read after
    # it (sessions/laps/score_details/session_annotations) are RLS tables, so
    # the working connection needs app.current_workspace_id set or it fails
    # closed. data_exports has no workspace_id column, so resolve the user's
    # workspace via a short-lived BYPASSRLS maintenance connection, then pin the
    # GUC here (connection-scoped, not SET LOCAL, so it survives the multiple
    # commits _update_export_status performs).
    workspace_id = _resolve_export_workspace_id(user_id)
    if workspace_id is not None:
        conn.execute(
            "SET app.current_workspace_id = %(ws)s",
            {"ws": str(workspace_id)},
        )

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

        # Bulk per-session telemetry — the user's actual lap data (GPS traces,
        # weather, corner metrics, theoretical lines). Required for a complete
        # Art. 15/20 export; previously omitted. Missing/absent tables are
        # skipped gracefully so a schema gap can't fail the whole export.
        telemetry: dict[str, list[dict[str, Any]]] = {
            "gps_traces": [],
            "session_weather": [],
            "corner_metrics": [],
            "theoretical_data": [],
        }
        for sess in sessions:
            sid = sess["session_id"]
            for _table in telemetry:
                try:
                    _rows = conn.execute(
                        text(f"SELECT * FROM {_table} WHERE session_id = :sid"),
                        {"sid": sid},
                    ).fetchall()
                    telemetry[_table].extend(_reduce_gps_precision(dict(r)) for r in _rows)
                except Exception:
                    logger.debug("export: telemetry table %s unavailable for %s", _table, sid)

        # 3. Reduce GPS precision on sessions
        sessions = [_reduce_gps_precision(s) for s in sessions]

        # 4. Write ZIP
        export_dir = os.environ.get("TELEMETRY_EXPORT_DIR", "/tmp/telemetry_exports")
        os.makedirs(export_dir, exist_ok=True)
        zip_filename = f"export_{user_id}_{export_id}.zip"
        zip_path = os.path.join(export_dir, zip_filename)

        _write_zip(zip_path, profile, sessions, laps, scores, annotations, teams, telemetry=telemetry)

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

def _cancel_stripe_subscription(subscription_id, user_id) -> None:
    """Best-effort cancel of a Stripe subscription for a purged account.

    Swallows every error — billing cleanup must never block the legal data
    purge. Mirrors the api_key wiring used in ``web/routes/billing.py``.
    """
    if not subscription_id:
        return
    secret = os.environ.get("STRIPE_SECRET_KEY", "")
    if not secret:
        logger.warning(
            "Stripe not configured; leaving sub %s for purged user_id=%s",
            subscription_id, user_id,
        )
        return
    try:
        import stripe
        stripe.api_key = secret
        stripe.Subscription.delete(subscription_id)
        logger.info(
            "Cancelled Stripe subscription %s for purged user_id=%s",
            subscription_id, user_id,
        )
    except Exception as exc:  # noqa: BLE001 — never block the purge
        logger.warning(
            "Stripe cancel failed for user_id=%s sub=%s: %s",
            user_id, subscription_id, exc,
        )


def _purge_user_export_files(user_id) -> int:
    """Delete the user's export ZIPs from the export dir; return count removed.

    Export filenames follow ``export_{user_id}_{export_id}.zip`` (see
    ``export_user_data``), so a per-user glob erases them all.
    """
    export_dir = Path(os.environ.get("TELEMETRY_EXPORT_DIR", "/tmp/telemetry_exports"))
    if not export_dir.is_dir():
        return 0
    removed = 0
    for p in export_dir.glob(f"export_{user_id}_*.zip"):
        try:
            p.unlink()
            removed += 1
        except OSError as exc:
            logger.warning("Could not delete export file %s: %s", p, exc)
    return removed


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

    # RLS: this beat task is cross-tenant BY DESIGN — it iterates ALL
    # soft-deleted users and DELETEs from RLS-enabled tables (sessions, laps,
    # gps_traces, score_details, corner_metrics, session_annotations, ...)
    # across every workspace. The RLS-scoped app role fails closed without a
    # per-workspace GUC, so use the BYPASSRLS maintenance role and always
    # close it in the finally below.
    conn = get_maint_connection()
    try:
        return _purge_deleted_accounts_with_conn(conn)
    finally:
        return_pg_connection(conn)


def _purge_deleted_accounts_with_conn(conn) -> dict[str, int]:
    """Run the account-purge sweep on an already-open (maint) connection."""
    from sqlalchemy import text

    from web.repos.delete_cascade import delete_entity_cascade
    from web.storage_quota import purge_workspace_files

    cutoff = datetime.now(timezone.utc) - timedelta(days=30)

    # 1. Find accounts past grace period
    rows = conn.execute(
        text(
            "SELECT id, email, stripe_subscription_id FROM users "
            "WHERE deleted_at IS NOT NULL AND deleted_at < :cutoff"
        ),
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
            # Stop billing on the account being erased. Best-effort and fully
            # isolated: a Stripe outage must never block the legal data purge.
            _cancel_stripe_subscription(user.get("stripe_subscription_id"), uid)

            # 2. Cascade delete workspace data
            ws_rows = conn.execute(
                text("SELECT id FROM workspaces WHERE owner_user_id = :uid"),
                {"uid": uid},
            ).fetchall()
            workspace_ids = [r["id"] for r in ws_rows]

            # Capture session ids BEFORE deleting the session rows — the
            # durable on-disk data is the session-keyed sidecar dir
            # (<sidecar_root>/<session_id>/), which can't be resolved once the
            # rows are gone. Used by purge_workspace_files below.
            ws_session_ids: dict[int, list[str]] = {}

            for ws_id in workspace_ids:
                # Capture session ids for the on-disk sidecar purge BEFORE the
                # cascade deletes the rows.
                session_rows = conn.execute(
                    text("SELECT session_id FROM sessions WHERE workspace_id = :ws"),
                    {"ws": ws_id},
                ).fetchall()
                for sess in session_rows:
                    sid = sess.get("session_id") if isinstance(sess, dict) else getattr(sess, "session_id", None)
                    if sid is not None:
                        ws_session_ids.setdefault(ws_id, []).append(str(sid))
                # CANONICAL full teardown (single source of truth) instead of a
                # hand-maintained list. delete_entity_cascade("workspace") (a)
                # cascades each session so session-tier RESTRICT children
                # (e.g. user_corners → FK sessions) are cleared, then (b) deletes
                # the workspace-tier RESTRICT children (usage_events/monthly,
                # entitlement_overrides, audit_log, exports, *_stats_rollup,
                # driver_xp, achievements, drill_executions, device_pairings,
                # workspace_members), then (c) DELETEs the workspace (the DB
                # CASCADEs the ~50 ON DELETE CASCADE children). It RAISES if the
                # workspace row survives, so a future un-listed RESTRICT child
                # surfaces loudly instead of silently rolling back the purge —
                # the GDPR Art. 17 stall that the old hardcoded list caused at
                # BOTH the session and workspace tiers.
                delete_entity_cascade(conn, "workspace", ws_id)

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

            # 4. Erase on-disk data AFTER the DB rows are gone. The workspace
            #    subtrees (raw + cache + results) and the user's export ZIPs
            #    would otherwise outlive the account — a GDPR violation and a
            #    storage leak. Best-effort: files-already-gone is fine.
            freed = 0
            for ws_id in workspace_ids:
                try:
                    freed += purge_workspace_files(
                        int(ws_id), session_ids=ws_session_ids.get(ws_id, [])
                    )
                except Exception as fexc:  # noqa: BLE001 — never block the purge
                    logger.warning("File purge failed for ws=%s: %s", ws_id, fexc)
            try:
                _purge_user_export_files(uid)
            except Exception as fexc:  # noqa: BLE001
                logger.warning("Export-file purge failed for user_id=%s: %s", uid, fexc)

            purged += 1
            logger.info(
                "Purged account: user_id=%s, email=%s, files_freed=%d bytes",
                uid, user.get("email"), freed,
            )

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
    from auth.entitlements import KNOWN_PLANS

    rows = conn.execute(
        "SELECT w.id AS workspace_id, "
        "COALESCE(w.billing_plan, owner.plan_tier, 'locked') AS tier "
        "FROM workspaces w "
        "LEFT JOIN users owner ON owner.id = w.owner_user_id"
    ).fetchall()
    out = []
    for row in rows:
        data = dict(row)
        tier = data.get("tier", "locked")
        # Normalize unknown tiers to the locked floor (no free tier).
        if tier not in KNOWN_PLANS:
            tier = "locked"
        out.append({"workspace_id": data["workspace_id"], "tier": tier})
    return out


def _write_retention_audit(conn, workspace_id: int, tier: str, deleted_rows: int, deleted_files: int) -> None:
    """Best-effort audit trail write for retention enforcement."""
    from sqlalchemy import text

    try:
        conn.execute(
            text(
                "INSERT INTO audit_log (action, workspace_id, new_value, created_at) "
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

    from auth.entitlements import get_plan_entitlements

    # RLS: this daily sweep iterates ALL workspaces and DELETEs from gps_traces
    # (RLS) plus writes audit_log (RLS) per workspace. Use the BYPASSRLS
    # maintenance role — consistent with tasks/retention_tasks.py — because the
    # RLS-scoped app role can only see one workspace and fails closed with the
    # GUC unset. The per-ws DELETE and the audit INSERT both pass workspace_id
    # explicitly (see _write_retention_audit), so no GUC is needed on maint.
    conn = get_maint_connection()
    try:
        return _enforce_raw_data_retention_with_conn(conn)
    finally:
        return_pg_connection(conn)


def _enforce_raw_data_retention_with_conn(conn) -> dict[str, int]:
    """Run the retention sweep on an already-open (maint) connection."""
    from sqlalchemy import text

    from auth.entitlements import get_plan_entitlements

    workspace_tiers = _iter_workspace_tiers(conn)

    total_deleted_rows = 0
    total_deleted_files = 0

    raw_base = Path(os.environ.get("TELEMETRY_RAW_DIR", "data/raw"))

    for item in workspace_tiers:
        ws_id = int(item["workspace_id"])
        tier = item["tier"]
        entitlements = get_plan_entitlements(tier)
        cutoff = datetime.now(timezone.utc) - timedelta(days=entitlements["raw_retention_days"])

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
# Task: cleanup_expired_exports
# ---------------------------------------------------------------------------

def _cleanup_expired_exports_impl(export_dir: str | None = None) -> dict[str, int]:
    """Delete export ZIP files past their 7-day expiry.

    Scans the export directory for .zip files with mtime older than 7 days
    and deletes them. Non-zip files are left untouched.

    Args:
        export_dir: Override export directory (used in tests).

    Returns:
        Dict with ``{"deleted": N}``
    """
    if export_dir is None:
        export_dir = os.environ.get("TELEMETRY_EXPORT_DIR", "/tmp/telemetry_exports")

    export_path = Path(export_dir)
    if not export_path.is_dir():
        logger.info("Export directory does not exist: %s", export_dir)
        return {"deleted": 0}

    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    deleted = 0

    for f in export_path.glob("*.zip"):
        try:
            mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
            if mtime < cutoff:
                f.unlink()
                deleted += 1
                logger.info("Deleted expired export: %s", f.name)
        except Exception as exc:
            logger.error("Failed to delete export %s: %s", f.name, exc)

    logger.info("Export cleanup complete: %d files deleted", deleted)
    return {"deleted": deleted}


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

    @_celery_app.task(name="tasks.gdpr_tasks.cleanup_expired_exports")
    def cleanup_expired_exports() -> dict[str, int]:
        return _cleanup_expired_exports_impl()
else:
    def export_user_data(user_id: int, export_id: str) -> dict[str, Any]:  # type: ignore[misc]
        return _export_user_data_impl(user_id, export_id)

    def purge_deleted_accounts() -> dict[str, int]:  # type: ignore[misc]
        return _purge_deleted_accounts_impl()

    def enforce_raw_data_retention() -> dict[str, int]:  # type: ignore[misc]
        return _enforce_raw_data_retention_impl()

    def cleanup_expired_exports() -> dict[str, int]:  # type: ignore[misc]
        return _cleanup_expired_exports_impl()
