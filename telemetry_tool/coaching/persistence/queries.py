"""Corner progression persistence — store and retrieve cross-session corner metrics."""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def store_corner_progression(
    conn,
    workspace_id: str | int,
    driver_id: int,
    track_id: int,
    session_id: int,
    session_date: str,
    corners: list[dict],
) -> None:
    """Store corner metrics for a session.

    Uses INSERT ... ON CONFLICT to be idempotent on re-processing.
    Works with both SQLite (INSERT OR REPLACE) and PG (ON CONFLICT).
    """
    for corner in corners:
        params = {
            "workspace_id": workspace_id,
            "driver_id": driver_id,
            "track_id": track_id,
            "session_id": session_id,
            "session_date": session_date,
            "corner_id": corner["corner_id"],
            "apex_speed_mps": corner.get("apex_speed_mps"),
            "entry_speed_mps": corner.get("entry_speed_mps"),
            "exit_speed_mps": corner.get("exit_speed_mps"),
            "braking_point_m": corner.get("braking_point_m"),
            "time_loss_s": corner.get("time_loss_s"),
            "grip_utilisation_pct": corner.get("grip_utilisation_pct"),
            "trail_brake_score": corner.get("trail_brake_score"),
            "primary_cause": corner.get("primary_cause"),
            "theoretical_apex_mps": corner.get("theoretical_apex_mps"),
            "theoretical_entry_mps": corner.get("theoretical_entry_mps"),
            "theoretical_exit_mps": corner.get("theoretical_exit_mps"),
        }

        sql = """
            INSERT INTO corner_progression (
                workspace_id, driver_id, track_id, session_id, session_date,
                corner_id, apex_speed_mps, entry_speed_mps, exit_speed_mps,
                braking_point_m, time_loss_s, grip_utilisation_pct,
                trail_brake_score, primary_cause,
                theoretical_apex_mps, theoretical_entry_mps, theoretical_exit_mps
            ) VALUES (
                :workspace_id, :driver_id, :track_id, :session_id, :session_date,
                :corner_id, :apex_speed_mps, :entry_speed_mps, :exit_speed_mps,
                :braking_point_m, :time_loss_s, :grip_utilisation_pct,
                :trail_brake_score, :primary_cause,
                :theoretical_apex_mps, :theoretical_entry_mps, :theoretical_exit_mps
            ) ON CONFLICT (workspace_id, driver_id, track_id, session_id, corner_id)
            DO UPDATE SET
                apex_speed_mps = EXCLUDED.apex_speed_mps,
                entry_speed_mps = EXCLUDED.entry_speed_mps,
                exit_speed_mps = EXCLUDED.exit_speed_mps,
                braking_point_m = EXCLUDED.braking_point_m,
                time_loss_s = EXCLUDED.time_loss_s,
                grip_utilisation_pct = EXCLUDED.grip_utilisation_pct,
                trail_brake_score = EXCLUDED.trail_brake_score,
                primary_cause = EXCLUDED.primary_cause,
                theoretical_apex_mps = EXCLUDED.theoretical_apex_mps,
                theoretical_entry_mps = EXCLUDED.theoretical_entry_mps,
                theoretical_exit_mps = EXCLUDED.theoretical_exit_mps
        """

        try:
            conn.execute(sql, params)
        except Exception:
            logger.warning("Failed to store corner progression for corner %s",
                           corner["corner_id"], exc_info=True)


def get_corner_history(
    conn,
    driver_id: int,
    track_id: int,
    corner_id: int,
    limit: int = 20,
) -> list[dict]:
    """Retrieve historical corner metrics ordered by session date.

    Returns list of dicts with all corner_progression columns.
    """
    sql = """
        SELECT corner_id, session_id, session_date,
               apex_speed_mps, entry_speed_mps, exit_speed_mps,
               braking_point_m, time_loss_s, grip_utilisation_pct,
               trail_brake_score, primary_cause,
               theoretical_apex_mps, theoretical_entry_mps, theoretical_exit_mps
        FROM corner_progression
        WHERE driver_id = :driver_id
          AND track_id = :track_id
          AND corner_id = :corner_id
        ORDER BY session_date ASC
        LIMIT :limit
    """
    try:
        rows = conn.execute(sql, {
            "driver_id": driver_id,
            "track_id": track_id,
            "corner_id": corner_id,
            "limit": limit,
        })
        return [dict(row) for row in rows]
    except Exception:
        logger.warning("Failed to get corner history for corner %s",
                       corner_id, exc_info=True)
        return []


def get_driver_corner_trends(
    conn,
    driver_id: int,
    track_id: int,
    corner_ids: list[int],
) -> dict[int, list[dict]]:
    """Get trend data for multiple corners at once.

    Returns {corner_id: [history_rows]} for each corner with 3+ sessions.
    """
    result = {}
    for cid in corner_ids:
        history = get_corner_history(conn, driver_id, track_id, cid)
        if len(history) >= 3:
            result[cid] = history
    return result
