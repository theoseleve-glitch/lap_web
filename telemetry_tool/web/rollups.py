"""Refresh driver_stats_rollup and track_stats_rollup for a workspace."""

import logging

logger = logging.getLogger(__name__)


def refresh_driver_rollup(conn, workspace_id: int) -> None:
    """Recompute driver_stats_rollup for one workspace."""
    conn.execute(
        "DELETE FROM driver_stats_rollup WHERE workspace_id = %(ws)s",
        {"ws": workspace_id},
    )
    conn.execute(
        """
        INSERT INTO driver_stats_rollup
            (workspace_id, driver_id, session_count, total_laps,
             best_time_s, avg_score, avg_consistency, last_session_date)
        SELECT
            s.workspace_id,
            s.driver_id,
            COUNT(DISTINCT s.id),
            COALESCE(SUM(s.lap_count), 0),
            MIN(s.best_lap_time_s),
            AVG(sd.total_score),
            AVG(sd.consistency_score),
            MAX(s.session_date)
        FROM sessions s
        LEFT JOIN score_details sd ON sd.session_id = s.id
        WHERE s.workspace_id = %(ws)s
          AND s.driver_id IS NOT NULL
        GROUP BY s.workspace_id, s.driver_id
        """,
        {"ws": workspace_id},
    )


def refresh_track_rollup(conn, workspace_id: int) -> None:
    """Recompute track_stats_rollup for one workspace."""
    conn.execute(
        "DELETE FROM track_stats_rollup WHERE workspace_id = %(ws)s",
        {"ws": workspace_id},
    )
    conn.execute(
        """
        INSERT INTO track_stats_rollup
            (workspace_id, track_id, session_count, best_time_s,
             avg_score, last_session_date, unique_drivers)
        SELECT
            s.workspace_id,
            s.track_id,
            COUNT(DISTINCT s.id),
            MIN(s.best_lap_time_s),
            AVG(sd.total_score),
            MAX(s.session_date),
            COUNT(DISTINCT s.driver_id)
        FROM sessions s
        LEFT JOIN score_details sd ON sd.session_id = s.id
        WHERE s.workspace_id = %(ws)s
          AND s.track_id IS NOT NULL
        GROUP BY s.workspace_id, s.track_id
        """,
        {"ws": workspace_id},
    )


def refresh_rollups(conn, workspace_id: int) -> None:
    """Refresh all rollup tables for a workspace. Safe to call anytime."""
    try:
        refresh_driver_rollup(conn, workspace_id)
        refresh_track_rollup(conn, workspace_id)
        logger.info("Refreshed rollups for workspace %s", workspace_id)
    except Exception:
        logger.exception("Failed to refresh rollups for workspace %s", workspace_id)
