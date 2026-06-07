"""SQL queries for gamification tables (driver_xp, achievements, drill_executions)."""
from __future__ import annotations

from typing import Any


def upsert_driver_xp(conn, driver_id: int, workspace_id: int,
                      xp_delta: int, level: int,
                      streak: int, longest: int,
                      last_date: str | None,
                      pit_passes: int | None = None) -> None:
    """Insert or update driver XP row. Adds xp_delta to existing total.

    pit_passes: when provided, sets the counter to this exact value (managed
    by update_streak).  When None the existing pit_passes value is preserved
    (XP-only upserts must not clobber the counter).
    """
    if pit_passes is None:
        sql = """
            INSERT INTO driver_xp (workspace_id, driver_id, total_xp, level,
                                    current_streak, longest_streak, last_session_date, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT (workspace_id, driver_id) DO UPDATE SET
                total_xp = driver_xp.total_xp + excluded.total_xp,
                level = excluded.level,
                current_streak = excluded.current_streak,
                longest_streak = excluded.longest_streak,
                last_session_date = COALESCE(excluded.last_session_date, driver_xp.last_session_date),
                updated_at = datetime('now')
        """
        conn.execute(sql, (workspace_id, driver_id, xp_delta, level,
                           streak, longest, last_date))
    else:
        sql = """
            INSERT INTO driver_xp (workspace_id, driver_id, total_xp, level,
                                    current_streak, longest_streak, last_session_date,
                                    pit_passes, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT (workspace_id, driver_id) DO UPDATE SET
                total_xp = driver_xp.total_xp + excluded.total_xp,
                level = excluded.level,
                current_streak = excluded.current_streak,
                longest_streak = excluded.longest_streak,
                last_session_date = COALESCE(excluded.last_session_date, driver_xp.last_session_date),
                pit_passes = excluded.pit_passes,
                updated_at = datetime('now')
        """
        conn.execute(sql, (workspace_id, driver_id, xp_delta, level,
                           streak, longest, last_date, pit_passes))


def get_driver_xp(conn, driver_id: int, workspace_id: int) -> dict[str, Any] | None:
    """Fetch driver XP row or None.  Always includes pit_passes (0 if the
    column is absent on older rows — migration 071 adds it with DEFAULT 0)."""
    sql = """
        SELECT id, workspace_id, driver_id, total_xp, level,
               current_streak, longest_streak, last_session_date, updated_at,
               COALESCE(pit_passes, 0) AS pit_passes
        FROM driver_xp WHERE driver_id = ? AND workspace_id = ?
    """
    row = conn.execute(sql, (driver_id, workspace_id)).fetchone()
    return dict(row) if row else None


def insert_achievement(conn, driver_id: int, workspace_id: int,
                       key: str, session_id: int | None = None) -> bool:
    """Insert achievement. Returns True if newly inserted (not duplicate)."""
    sql = """
        INSERT INTO achievements (workspace_id, driver_id, achievement_key, session_id)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (workspace_id, driver_id, achievement_key) DO NOTHING
    """
    result = conn.execute(sql, (workspace_id, driver_id, key, session_id))
    return result.rowcount > 0


def get_achievements(conn, driver_id: int, workspace_id: int) -> list[dict]:
    """All unlocked achievements for a driver."""
    sql = """
        SELECT achievement_key, unlocked_at, session_id
        FROM achievements
        WHERE driver_id = ? AND workspace_id = ?
        ORDER BY unlocked_at DESC
    """
    return [dict(r) for r in conn.execute(sql, (driver_id, workspace_id)).fetchall()]


def insert_drill_execution(conn, workspace_id: int, driver_id: int,
                           plan_id: int, week_number: int, drill_index: int,
                           session_id: int | None, status: str,
                           notes: str | None = None) -> int:
    """Log a drill execution. Returns the new row id."""
    sql = """
        INSERT INTO drill_executions
            (workspace_id, driver_id, plan_id, week_number, drill_index,
             session_id, status, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING id
    """
    result = conn.execute(sql, (workspace_id, driver_id, plan_id,
                                week_number, drill_index, session_id,
                                status, notes))
    row = result.fetchone()
    if row is None:
        return 0
    return row[0] if not isinstance(row, dict) else row.get("id")


def get_plan_executions(conn, plan_id: int, workspace_id: int) -> list[dict]:
    """All drill executions for a plan."""
    sql = """
        SELECT de.*, s.csv_filename, s.session_date
        FROM drill_executions de
        LEFT JOIN sessions s ON de.session_id = s.session_id
        WHERE de.plan_id = ? AND de.workspace_id = ?
        ORDER BY de.week_number, de.drill_index, de.created_at
    """
    return [dict(r) for r in conn.execute(sql, (plan_id, workspace_id)).fetchall()]


def count_driver_sessions(conn, driver_id: int, workspace_id: int) -> int:
    """Count total sessions for a driver.

    Note: workspace_id filtering is handled by PG RLS policies
    (SQLite schema does not have workspace_id on sessions).
    """
    sql = "SELECT COUNT(*) AS cnt FROM sessions WHERE driver_id = ?"
    row = conn.execute(sql, (driver_id,)).fetchone()
    if row is None:
        return 0
    return row["cnt"] if isinstance(row, dict) else row[0]


def get_driver_best_lap(conn, driver_id: int, workspace_id: int) -> float | None:
    """Get driver's all-time best lap time.

    Note: workspace_id filtering is handled by PG RLS policies
    (SQLite schema does not have workspace_id on sessions).
    """
    sql = """
        SELECT MIN(best_lap_time_s) AS best
        FROM sessions WHERE driver_id = ? AND best_lap_time_s IS NOT NULL
    """
    row = conn.execute(sql, (driver_id,)).fetchone()
    if row is None:
        return None
    val = row["best"] if isinstance(row, dict) else row[0]
    return float(val) if val is not None else None
