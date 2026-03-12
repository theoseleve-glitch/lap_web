"""Periodic tasks for dead-letter-queue maintenance."""

from __future__ import annotations

import logging

from celery_app import celery

logger = logging.getLogger(__name__)


@celery.task(name="tasks.dead_letter_tasks.purge_dead_letters", queue="default")
def purge_dead_letters(days: int = 90) -> dict:
    """Remove DLQ entries older than *days*.

    Returns ``{"deleted": N}`` for observability.
    """
    try:
        from tasks.dead_letter import purge_old_entries
        from web.db_pg import get_pg_connection

        conn = get_pg_connection()
        try:
            count = purge_old_entries(conn, days=days)
        finally:
            conn.close()

        logger.info("DLQ purge: deleted %d entries older than %d days", count, days)
        return {"deleted": count}
    except Exception:
        logger.error("DLQ purge failed", exc_info=True)
        return {"deleted": 0, "error": "see logs"}
