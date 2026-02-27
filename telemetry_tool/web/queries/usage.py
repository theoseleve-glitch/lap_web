"""Usage tracking query functions.

Provides monthly usage lookups and event recording with automatic
upsert into the usage_monthly aggregate table.
"""
from __future__ import annotations

import json
import logging
from datetime import date

logger = logging.getLogger(__name__)


def get_monthly_usage(conn, workspace_id: int, event_type: str) -> int:
    """Return current month's usage count for a specific event type.

    Returns 0 if no usage recorded yet this month.
    """
    period_start = date.today().replace(day=1).isoformat()
    cur = conn.execute(
        "SELECT total FROM usage_monthly "
        "WHERE workspace_id = :wid AND event_type = :etype "
        "AND period_start = :period",
        {"wid": workspace_id, "etype": event_type, "period": period_start},
    )
    row = cur.fetchone()
    return row["total"] if row else 0


def record_usage_event(
    conn,
    user_id: int,
    workspace_id: int,
    event_type: str,
    cost: int = 1,
    metadata: dict | None = None,
) -> None:
    """Insert a usage_event and upsert usage_monthly aggregate.

    This is the single entry point for all billable-action recording.
    """
    meta_json = json.dumps(metadata) if metadata else None

    # Insert the event
    conn.execute(
        "INSERT INTO usage_events (user_id, workspace_id, event_type, cost, metadata_json) "
        "VALUES (:uid, :wid, :etype, :cost, :meta)",
        {
            "uid": user_id,
            "wid": workspace_id,
            "etype": event_type,
            "cost": cost,
            "meta": meta_json,
        },
    )

    # Upsert monthly aggregate
    period_start = date.today().replace(day=1).isoformat()
    conn.execute(
        "INSERT INTO usage_monthly (workspace_id, period_start, event_type, total) "
        "VALUES (:wid, :period, :etype, :cost) "
        "ON CONFLICT (workspace_id, period_start, event_type) "
        "DO UPDATE SET total = usage_monthly.total + :cost",
        {
            "wid": workspace_id,
            "period": period_start,
            "etype": event_type,
            "cost": cost,
        },
    )
