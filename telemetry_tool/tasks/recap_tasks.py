"""Weekly recap — 'your week in the kart' digest (Phase 2b).

A pure aggregation helper (unit-testable on sqlite mem_conn) plus a Celery
beat task that runs Monday on the maint connection (BYPASSRLS, cross-tenant),
upserts one weekly_recap row per active driver (idempotent via the UNIQUE
constraint on (workspace_id, driver_id, iso_week) from migration 071), and
emails a digest via the existing mailer when the user has weekly_digest enabled.

Email is sent AT MOST ONCE per iso_week per driver: guarded by the ``emailed``
column — only send if not already emailed, then set emailed=true after success.
Per-driver failures are non-fatal: one failure logs + continues the rest.
"""
from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pure aggregation helper (sqlite-compatible; no Celery dependency)
# ---------------------------------------------------------------------------

def build_recap_payload(
    conn,
    driver_id: int,
    workspace_id: int,
    week_start: str,
    week_end: str,
) -> dict[str, Any]:
    """Aggregate one driver's last-week activity into a recap payload dict.

    Parameters
    ----------
    conn:
        Open connection (PgConnectionWrapper in prod, sqlite3.Connection in
        tests). Must support ``.execute(sql, params)`` with named params
        (``:``) *or* positional (``%s``).  To keep this pure and sqlite-
        compatible we use named params throughout.
    driver_id, workspace_id:
        Scoping keys.
    week_start, week_end:
        ISO-format date strings (``YYYY-MM-DD``).  Quests / achievements
        completed_at >= week_start AND < week_end.

    Returns
    -------
    dict with keys: quests_completed, current_streak, next_focus,
                    week_start, week_end.
    """

    def _scalar(sql: str, params: dict, default: Any = 0) -> Any:
        row = conn.execute(sql, params).fetchone()
        if not row:
            return default
        v = row[list(row.keys())[0]] if isinstance(row, dict) else row[0]
        return v if v is not None else default

    # Quests completed inside the week window.
    quests_completed = int(_scalar(
        "SELECT COUNT(*) FROM quests "
        "WHERE driver_id = :d AND workspace_id = :w "
        "AND status = 'completed' AND completed_at >= :a AND completed_at < :b",
        {"d": driver_id, "w": workspace_id, "a": week_start, "b": week_end},
    ))

    # Current streak from driver_xp.
    streak = 0
    xp_row = conn.execute(
        "SELECT current_streak FROM driver_xp "
        "WHERE driver_id = :d AND workspace_id = :w",
        {"d": driver_id, "w": workspace_id},
    ).fetchone()
    if xp_row:
        streak = int(
            (xp_row["current_streak"] if isinstance(xp_row, dict) else xp_row[0]) or 0
        )

    # Top pending quest: focused first, then most recently created.
    focus_row = conn.execute(
        "SELECT human_text FROM quests "
        "WHERE driver_id = :d AND workspace_id = :w AND status = 'active' "
        "ORDER BY focused DESC, created_at DESC LIMIT 1",
        {"d": driver_id, "w": workspace_id},
    ).fetchone()
    next_focus: str | None = None
    if focus_row:
        next_focus = (
            focus_row["human_text"] if isinstance(focus_row, dict) else focus_row[0]
        )

    # Stars earned this week: count of corner_mastery tier upgrades whose
    # achieved_at falls in [week_start, week_end).  corner_mastery.achieved_at
    # is set (or updated) exactly when a corner advances to a new tier, making
    # it the canonical "mastery star earned" timestamp for Phase-1 gamification.
    # One-time catalog achievements (achievements table, 15 total, UNIQUE per
    # driver) are not counted here because they are lifetime milestones, not
    # repeatable weekly stars.
    stars_earned = int(_scalar(
        "SELECT COUNT(*) FROM corner_mastery "
        "WHERE driver_id = :d AND workspace_id = :w "
        "AND tier != 'none' "
        "AND achieved_at >= :a AND achieved_at < :b",
        {"d": driver_id, "w": workspace_id, "a": week_start, "b": week_end},
    ))

    # XP gained this week — gamification-XP proxy (no per-event XP ledger exists).
    # Source: SUM of xp on quests completed in-window.  Quest rows carry an
    # integer xp column (migration 070); this is the most faithful weekly-scoped
    # XP figure available without a separate events/ledger table.
    # Corner-mastery star XP (XP_STAR = bronze 25 / silver 75 / gold 150) is
    # NOT included here because corner_mastery stores no per-row XP amount and
    # joining to the catalog would require hardcoding tier→XP — an acceptable
    # simplification for Phase 2b, but the quest sum alone is already the primary
    # weekly gamification signal.  If a ledger is added in future, replace this
    # with a direct SUM on the ledger table.
    xp_gained = int(_scalar(
        "SELECT COALESCE(SUM(xp), 0) FROM quests "
        "WHERE driver_id = :d AND workspace_id = :w "
        "AND status = 'completed' AND completed_at >= :a AND completed_at < :b",
        {"d": driver_id, "w": workspace_id, "a": week_start, "b": week_end},
        default=0,
    ))

    return {
        "quests_completed": quests_completed,
        "current_streak": streak,
        "next_focus": next_focus,
        "stars_earned": stars_earned,
        "xp_gained": xp_gained,
        "week_start": week_start,
        "week_end": week_end,
    }


# ---------------------------------------------------------------------------
# Weekly recap email
# ---------------------------------------------------------------------------

def _build_recap_html(display_name: str, payload: dict) -> str:
    """Return the HTML body for the weekly digest email."""
    from auth.email import FRONTEND_URL, _esc

    streak = payload.get("current_streak", 0)
    quests = payload.get("quests_completed", 0)
    next_focus = payload.get("next_focus")
    week_start = payload.get("week_start", "")

    streak_line = f"{streak} week{'s' if streak != 1 else ''} in a row" if streak else "—"
    quests_line = (
        f"{quests} quest{'s' if quests != 1 else ''} completed" if quests else "No quests completed yet"
    )
    focus_block = (
        f'<p style="color: #8A8F98; font-size: 13px; margin: 8px 0 0;">'
        f'Next focus: <strong style="color: #FACC15;">{_esc(next_focus)}</strong></p>'
        if next_focus else ""
    )

    return f"""\
<div style="font-family: -apple-system, sans-serif; max-width: 480px; margin: 0 auto;">
  <h2 style="color: #F3F0E8;">Your week in the kart{', ' + _esc(display_name) if display_name else ''}</h2>
  <p style="color: #8A8F98; font-size: 13px; margin: 0 0 12px;">Week of {_esc(week_start)}</p>
  <div style="background: #1A1D24; border-radius: 8px; padding: 16px; margin: 12px 0;">
    <p style="color: #B6FF2E; font-size: 20px; font-weight: 700; margin: 0 0 4px;">{_esc(streak_line)}</p>
    <p style="color: #8A8F98; font-size: 13px; margin: 0 0 8px;">{_esc(quests_line)}</p>
    {focus_block}
  </div>
  <a href="{FRONTEND_URL}/app/dashboard"
     style="display: inline-block; background: #B6FF2E; color: #0B0C0F;
            padding: 12px 24px; border-radius: 6px; text-decoration: none;
            font-weight: 600; margin: 16px 0;">
    Open Dashboard
  </a>
  <p style="color: #8A8F98; font-size: 11px; margin-top: 24px;">
    You're receiving this because weekly digest emails are enabled.
    Manage your preferences in your <a href="{FRONTEND_URL}/app/settings" style="color: #8A8F98;">account settings</a>.
  </p>
</div>"""


# ---------------------------------------------------------------------------
# Celery beat task (registered only when Celery is importable)
# ---------------------------------------------------------------------------

try:
    from celery_app import celery

    @celery.task(queue="default", bind=True, max_retries=1)
    def weekly_recap(self):
        """Build + persist (+ email) a recap per active driver.

        Runs Monday 06:00 UTC via Celery beat.  Uses the maint connection
        (BYPASSRLS) to see all workspaces — this is a cross-tenant beat task
        and MUST NOT use a per-workspace GUC-pinned connection.

        Idempotency: UPSERT on (workspace_id, driver_id, iso_week) — re-running
        in the same week overwrites the payload but does NOT re-send email
        (``emailed`` flag checked before send; set to true after success).

        Per-driver non-fatal: one failure logs + continues the rest.
        """
        from datetime import date, timedelta

        from web.db_pg import (
            get_maint_connection,
            return_pg_connection,
        )

        # Compute week boundaries (last complete Mon→Mon window).
        today = date.today()
        # ISO week of *last* week (Monday to Sunday already done).
        last_monday = today - timedelta(days=today.weekday() + 7)
        this_monday = today - timedelta(days=today.weekday())
        week_start = last_monday.isoformat()
        week_end = this_monday.isoformat()
        # ISO week string for the window (e.g. "2026-W23").
        iso_week = last_monday.strftime("%G-W%V")

        # ── Maint connection: cross-tenant, BYPASSRLS ──
        # Mirrors the reconcile_storage_usage pattern in usage_tasks.py.
        # get_maint_connection() returns a PgConnectionWrapper backed by the
        # telemetry_maint DSN (BYPASSRLS, NOSUPERUSER).
        conn = get_maint_connection()
        n_written = n_emailed = n_skipped = 0
        try:
            # Gather active drivers: anyone with a session in the last 7 days.
            pairs_rows = conn.execute(
                "SELECT DISTINCT workspace_id, driver_id FROM driver_xp "
                "WHERE last_session_date >= :cutoff",
                {"cutoff": week_start},
            ).fetchall()
            pairs = [
                (
                    (r["workspace_id"] if isinstance(r, dict) else r[0]),
                    (r["driver_id"] if isinstance(r, dict) else r[1]),
                )
                for r in pairs_rows
            ]
            logger.info("weekly_recap: %d active driver(s) for %s", len(pairs), iso_week)

            for ws_id, drv_id in pairs:
                try:
                    emailed_this_driver = _process_driver(
                        conn,
                        ws_id=ws_id,
                        drv_id=drv_id,
                        iso_week=iso_week,
                        week_start=week_start,
                        week_end=week_end,
                    )
                    conn.commit()
                    n_written += 1
                    n_emailed += emailed_this_driver  # plain local counter, no shared state
                except Exception as exc:  # noqa: BLE001
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                    n_skipped += 1
                    logger.warning(
                        "weekly_recap skipped ws=%s drv=%s: %s", ws_id, drv_id, exc
                    )

            logger.info(
                "weekly_recap done: wrote=%d emailed=%d skipped=%d iso_week=%s",
                n_written, n_emailed, n_skipped, iso_week,
            )
            return {"recaps": n_written, "emailed": n_emailed, "skipped": n_skipped}
        finally:
            return_pg_connection(conn)

    # ── Per-driver helper (keeps the loop body readable) ─────────────────────

    def _process_driver(
        conn,
        ws_id: int,
        drv_id: int,
        iso_week: str,
        week_start: str,
        week_end: str,
    ) -> int:
        """Upsert the recap row and email if needed.

        Returns 1 if an email was sent this call, 0 otherwise.  The caller
        accumulates a plain local int — there is no cross-invocation shared
        state, so running the task twice on the same Celery worker never
        inflates the returned ``emailed`` count.
        """
        payload = build_recap_payload(conn, drv_id, ws_id, week_start, week_end)

        # UPSERT — idempotent per (workspace_id, driver_id, iso_week).
        conn.execute(
            "INSERT INTO weekly_recap (workspace_id, driver_id, iso_week, payload) "
            "VALUES (:ws, :drv, :wk, :pl) "
            "ON CONFLICT (workspace_id, driver_id, iso_week) "
            "DO UPDATE SET payload = EXCLUDED.payload",
            {
                "ws": ws_id,
                "drv": drv_id,
                "wk": iso_week,
                "pl": json.dumps(payload),
            },
        )

        # Check emailed flag: only send if not already emailed this week.
        emailed_row = conn.execute(
            "SELECT emailed FROM weekly_recap "
            "WHERE workspace_id = :ws AND driver_id = :drv AND iso_week = :wk",
            {"ws": ws_id, "drv": drv_id, "wk": iso_week},
        ).fetchone()
        already_emailed = bool(
            (emailed_row["emailed"] if isinstance(emailed_row, dict) else emailed_row[0])
            if emailed_row else False
        )

        if not already_emailed and _should_email(conn, ws_id, drv_id):
            sent = _send_recap_email(conn, drv_id, ws_id, iso_week, payload)
            if sent:
                conn.execute(
                    "UPDATE weekly_recap SET emailed = :t "
                    "WHERE workspace_id = :ws AND driver_id = :drv AND iso_week = :wk",
                    {"t": True, "ws": ws_id, "drv": drv_id, "wk": iso_week},
                )
                return 1
        return 0

    def _should_email(conn, ws_id: int, drv_id: int) -> bool:
        """Return True if the workspace owner has weekly_digest enabled (default True).

        Resolves via workspace_id → workspace_members (role='owner') → users.preferences.
        Falls back to True (send) when the preference is absent or unreadable.
        The drv_id parameter is retained for call-site compatibility but is not
        used in the query — the recipient is always the workspace owner.
        """
        try:
            row = conn.execute(
                "SELECT u.preferences FROM workspace_members wm "
                "JOIN users u ON u.id = wm.user_id "
                "WHERE wm.workspace_id = :ws AND wm.role = 'owner' "
                "LIMIT 1",
                {"ws": ws_id},
            ).fetchone()
            if not row:
                return True  # no owner record → send (conservative)
            prefs_raw = row["preferences"] if isinstance(row, dict) else row[0]
            if not prefs_raw:
                return True
            prefs = prefs_raw if isinstance(prefs_raw, dict) else json.loads(prefs_raw)
            notif = prefs.get("notifications") or {}
            return bool(notif.get("weekly_digest", True))
        except Exception:
            logger.debug("_should_email fallback to True", exc_info=True)
            return True

    def _send_recap_email(
        conn, drv_id: int, ws_id: int, iso_week: str, payload: dict
    ) -> bool:
        """Look up the workspace owner's email + display_name and send the digest.

        Resolves via workspace_id → workspace_members (role='owner') → users.
        The drv_id parameter is retained for call-site compatibility and logging.
        Returns True on success.
        """
        try:
            row = conn.execute(
                "SELECT u.email, u.display_name FROM workspace_members wm "
                "JOIN users u ON u.id = wm.user_id "
                "WHERE wm.workspace_id = :ws AND wm.role = 'owner' "
                "LIMIT 1",
                {"ws": ws_id},
            ).fetchone()
            if not row:
                logger.debug(
                    "weekly_recap email skip: no user for ws=%s drv=%s", ws_id, drv_id
                )
                return False
            email = row["email"] if isinstance(row, dict) else row[0]
            display_name = (
                (row["display_name"] if isinstance(row, dict) else row[1]) or ""
            )
            if not email:
                return False
            from auth.email import _send
            html = _build_recap_html(display_name, payload)
            return _send(email, "Your week in the kart — LAP recap", html)
        except Exception:
            logger.warning(
                "weekly_recap email failed ws=%s drv=%s", ws_id, drv_id, exc_info=True
            )
            return False

except ImportError:
    logger.debug("Celery not available — weekly_recap beat task not registered")
