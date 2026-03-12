"""Refresh driver_stats_rollup and track_stats_rollup for a workspace."""

import logging

logger = logging.getLogger(__name__)

_TOTAL_SCORE_EXPR = (
    "(sd.pace_score + sd.consistency_score + sd.execution_score"
    " + sd.robustness_score + COALESCE(sd.adaptation_score, 0))"
)


def refresh_driver_rollup(conn, workspace_id: int) -> None:
    """Recompute driver_stats_rollup for one workspace."""
    conn.execute(
        "DELETE FROM driver_stats_rollup WHERE workspace_id = %(ws)s",
        {"ws": workspace_id},
    )
    conn.execute(
        f"""
        INSERT INTO driver_stats_rollup
            (workspace_id, driver_id, session_count, total_laps,
             best_time_s, avg_score, avg_consistency, last_session_date)
        SELECT
            s.workspace_id,
            s.driver_id,
            COUNT(DISTINCT s.session_id),
            COALESCE(SUM(s.n_laps), 0),
            MIN(s.best_lap_time_s),
            AVG({_TOTAL_SCORE_EXPR}),
            AVG(sd.consistency_score),
            MAX(s.session_date)::date
        FROM sessions s
        LEFT JOIN score_details sd ON sd.session_id = s.session_id
        WHERE s.workspace_id = %(ws)s
          AND s.driver_id IS NOT NULL
          AND s.deleted_at IS NULL
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
        f"""
        INSERT INTO track_stats_rollup
            (workspace_id, track_id, session_count, best_time_s,
             avg_score, last_session_date, unique_drivers)
        SELECT
            s.workspace_id,
            s.track_id,
            COUNT(DISTINCT s.session_id),
            MIN(s.best_lap_time_s),
            AVG({_TOTAL_SCORE_EXPR}),
            MAX(s.session_date)::date,
            COUNT(DISTINCT s.driver_id)
        FROM sessions s
        LEFT JOIN score_details sd ON sd.session_id = s.session_id
        WHERE s.workspace_id = %(ws)s
          AND s.track_id IS NOT NULL
          AND s.deleted_at IS NULL
        GROUP BY s.workspace_id, s.track_id
        """,
        {"ws": workspace_id},
    )


def refresh_rollups(conn, workspace_id: int) -> None:
    """Refresh all rollup tables for a workspace.

    Wrapped in a SAVEPOINT so a failure cannot poison the PG connection
    (which would break subsequent queries or teardown on the same conn).
    """
    try:
        conn.execute("SAVEPOINT sp_rollups")
        refresh_driver_rollup(conn, workspace_id)
        refresh_track_rollup(conn, workspace_id)
        conn.execute("RELEASE SAVEPOINT sp_rollups")
        conn.commit()
        logger.info("Refreshed rollups for workspace %s", workspace_id)
    except Exception:
        try:
            conn.execute("ROLLBACK TO SAVEPOINT sp_rollups")
            conn.execute("RELEASE SAVEPOINT sp_rollups")
        except Exception:
            pass
        logger.exception("Failed to refresh rollups for workspace %s", workspace_id)
