"""Celery task: refresh rollup tables for all workspaces."""

import logging

from celery_app import celery

logger = logging.getLogger(__name__)


@celery.task(name="tasks.rollup_tasks.refresh_all_rollups", queue="default")
def refresh_all_rollups():
    """Safety-net: recompute rollups for every workspace.

    Sets the RLS workspace context per iteration: the rollup tables are
    FORCE-RLS, so each workspace's INSERTs must run under that workspace's
    GUC (the ``workspaces`` enumeration itself is not RLS-scoped).
    """
    from auth.workspace import set_workspace_context
    from web.db_pg import get_pg_connection as get_pg_conn
    from web.rollups import refresh_rollups
    conn = get_pg_conn()
    try:
        rows = conn.execute("SELECT id FROM workspaces").fetchall()
        for row in rows:
            ws_id = row["id"] if isinstance(row, dict) else row[0]
            set_workspace_context(conn, ws_id)
            refresh_rollups(conn, ws_id)
        conn.commit()
        logger.info("Refreshed rollups for %d workspaces", len(rows))
    except Exception:
        logger.exception("Failed to refresh all rollups")
    finally:
        conn.close()
