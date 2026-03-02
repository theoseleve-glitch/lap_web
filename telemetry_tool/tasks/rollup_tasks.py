"""Celery task: refresh rollup tables for all workspaces."""

import logging
from telemetry_tool.tasks.celery_app import celery

logger = logging.getLogger(__name__)


@celery.task(name="tasks.rollup_tasks.refresh_all_rollups", queue="default")
def refresh_all_rollups():
    """Safety-net: recompute rollups for every workspace."""
    from telemetry_tool.web.rollups import refresh_rollups
    from telemetry_tool.web.db_pg import get_pg_conn
    conn = get_pg_conn()
    try:
        rows = conn.execute("SELECT id FROM workspaces").fetchall()
        for row in rows:
            ws_id = row["id"] if isinstance(row, dict) else row[0]
            refresh_rollups(conn, ws_id)
        conn.commit()
        logger.info("Refreshed rollups for %d workspaces", len(rows))
    except Exception:
        logger.exception("Failed to refresh all rollups")
    finally:
        conn.close()
