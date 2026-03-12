"""Dead Letter Queue — captures tasks that exhaust retry budget.

Uses Celery's ``task_failure`` signal to persist failed tasks into the
``dead_letter_queue`` PG table.  Provides helpers to list, inspect, and
replay dead-lettered tasks.

Wire up by calling ``register_dlq_signals()`` after the Celery app is
created.
"""

from __future__ import annotations

import json
import logging
import os
import traceback as tb_module
from datetime import datetime, timezone
from typing import Any, Optional

from celery import Celery
from celery.signals import task_failure

logger = logging.getLogger(__name__)


def _get_pg_conn():
    """Obtain a fresh PG connection (import-time safe)."""
    if os.environ.get("USE_PG", "0") not in ("1", "true", "yes"):
        return None
    try:
        from web.db_pg import get_pg_connection

        return get_pg_connection()
    except Exception:
        logger.debug("Could not obtain PG connection for DLQ", exc_info=True)
        return None


def _safe_json(obj: Any) -> str:
    """JSON-serialise, falling back to repr for non-serialisable objects."""
    try:
        return json.dumps(obj, default=str)
    except Exception:
        return repr(obj)


# ---------------------------------------------------------------------------
# Signal handler
# ---------------------------------------------------------------------------


@task_failure.connect
def on_task_failure(sender=None, task_id=None, exception=None, args=None,
                    kwargs=None, traceback=None, einfo=None, **kw):
    """Persist a failed task into the dead_letter_queue table.

    Only fires when the task has truly exhausted retries (Celery only
    emits ``task_failure`` on the *final* failure, not on each retry).
    """
    conn = _get_pg_conn()
    if conn is None:
        logger.warning(
            "DLQ: no PG connection — cannot persist task %s (%s)",
            task_id,
            sender.name if sender else "unknown",
        )
        return

    try:
        # Extract workspace_id from kwargs if available
        ws_id = None
        if isinstance(kwargs, dict):
            ws_id = kwargs.get("workspace_id")

        exc_type = type(exception).__name__ if exception else None
        exc_msg = str(exception)[:4000] if exception else None
        tb_str = None
        if traceback is not None:
            try:
                tb_str = "".join(tb_module.format_tb(traceback))[:8000]
            except Exception:
                tb_str = str(einfo)[:8000] if einfo else None

        task_name = sender.name if sender else "unknown"
        max_retries = getattr(sender, "max_retries", None) if sender else None
        retries = getattr(sender.request, "retries", 0) if sender else 0
        queue_name = getattr(sender.request, "delivery_info", {}).get("routing_key")

        from sqlalchemy import text as sa_text

        conn.execute(
            sa_text(
                "INSERT INTO dead_letter_queue "
                "  (task_id, task_name, queue, args, kwargs, "
                "   exception_type, exception_message, traceback, "
                "   retries, max_retries, workspace_id) "
                "VALUES "
                "  (:task_id, :task_name, :queue, :args, :kwargs, "
                "   :exc_type, :exc_msg, :tb, "
                "   :retries, :max_retries, :ws_id)"
            ),
            {
                "task_id": task_id,
                "task_name": task_name,
                "queue": queue_name,
                "args": _safe_json(args),
                "kwargs": _safe_json(kwargs),
                "exc_type": exc_type,
                "exc_msg": exc_msg,
                "tb": tb_str,
                "retries": retries,
                "max_retries": max_retries,
                "ws_id": ws_id,
            },
        )
        conn.commit()
        logger.info("DLQ: persisted failed task %s (%s)", task_id, task_name)
    except Exception:
        logger.error("DLQ: failed to persist task %s", task_id, exc_info=True)
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Query / replay helpers
# ---------------------------------------------------------------------------


def list_dead_letters(
    conn, status: str = "dead", limit: int = 50
) -> list[dict]:
    """List dead-lettered tasks, newest first."""
    from sqlalchemy import text as sa_text

    cursor = conn.execute(
        sa_text(
            "SELECT id, task_id, task_name, queue, exception_type, "
            "       exception_message, retries, max_retries, "
            "       failed_at, status, workspace_id "
            "FROM dead_letter_queue "
            "WHERE status = :status "
            "ORDER BY failed_at DESC "
            "LIMIT :limit"
        ),
        {"status": status, "limit": limit},
    )
    rows = cursor.fetchall()
    return [dict(r) if not isinstance(r, dict) else r for r in rows]


def get_dead_letter(conn, dlq_id: int) -> Optional[dict]:
    """Fetch a single DLQ entry by ID (includes full traceback)."""
    from sqlalchemy import text as sa_text

    cursor = conn.execute(
        sa_text("SELECT * FROM dead_letter_queue WHERE id = :id"),
        {"id": dlq_id},
    )
    row = cursor.fetchone()
    if row is None:
        return None
    return dict(row) if not isinstance(row, dict) else row


def replay_dead_letter(conn, dlq_id: int, celery_app: Celery) -> bool:
    """Re-dispatch a dead-lettered task and mark it as replayed.

    Returns True if the task was successfully re-dispatched.
    """
    from sqlalchemy import text as sa_text

    entry = get_dead_letter(conn, dlq_id)
    if entry is None or entry.get("status") != "dead":
        return False

    task_name = entry["task_name"]
    try:
        args = json.loads(entry["args"]) if entry.get("args") else []
        kwargs = json.loads(entry["kwargs"]) if entry.get("kwargs") else {}
    except (json.JSONDecodeError, TypeError):
        logger.error("DLQ: cannot parse args/kwargs for entry %d", dlq_id)
        return False

    # Re-send the task
    celery_app.send_task(task_name, args=args, kwargs=kwargs)

    # Mark as replayed
    conn.execute(
        sa_text(
            "UPDATE dead_letter_queue "
            "SET status = 'replayed', replayed_at = now() "
            "WHERE id = :id"
        ),
        {"id": dlq_id},
    )
    conn.commit()
    logger.info("DLQ: replayed task %s (entry %d)", task_name, dlq_id)
    return True


def purge_old_entries(conn, days: int = 90) -> int:
    """Delete DLQ entries older than ``days``. Returns count deleted."""
    from sqlalchemy import text as sa_text

    cursor = conn.execute(
        sa_text(
            "DELETE FROM dead_letter_queue "
            "WHERE failed_at < now() - make_interval(days => :days) "
            "RETURNING id"
        ),
        {"days": days},
    )
    deleted = cursor.fetchall()
    conn.commit()
    return len(deleted)
