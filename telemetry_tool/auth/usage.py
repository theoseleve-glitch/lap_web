"""Usage tracking -- increment counters, read snapshots, check limits.

Operates on the ``usage_counters`` table (migration 021).  All functions
accept a DB connection as the first argument so they work with both PG
and mock connections in tests.
"""
from __future__ import annotations

from datetime import datetime, timezone

from auth.entitlements import METRIC_TO_ENTITLEMENT, get_plan_entitlements


def get_current_period() -> str:
    """Return current billing period as 'YYYY-MM'."""
    now = datetime.now(timezone.utc)
    return f"{now.year}-{now.month:02d}"


def get_usage_count(
    conn, workspace_id: int, metric: str, period: str | None = None
) -> int:
    """Return the current count for *metric* in *period* (defaults to current month)."""
    if period is None:
        period = get_current_period()
    cur = conn.execute(
        "SELECT count FROM usage_counters "
        "WHERE workspace_id = %(ws)s AND metric = %(m)s AND period = %(p)s",
        {"ws": workspace_id, "m": metric, "p": period},
    )
    row = cur.fetchone()
    if row is None:
        return 0
    # Handle both dict-like rows and index-based rows
    if isinstance(row, dict):
        return row.get("count", 0)
    return row["count"]


def increment_usage(
    conn, workspace_id: int, metric: str, amount: int = 1
) -> int:
    """Atomically increment *metric* counter.  Returns new count."""
    period = get_current_period()
    conn.execute(
        "INSERT INTO usage_counters (workspace_id, metric, period, count, updated_at) "
        "VALUES (%(ws)s, %(m)s, %(p)s, %(amt)s, NOW()) "
        "ON CONFLICT (workspace_id, metric, period) "
        "DO UPDATE SET count = usage_counters.count + %(amt)s, updated_at = NOW()",
        {"ws": workspace_id, "m": metric, "p": period, "amt": amount},
    )
    # Note: no conn.commit() here — let the request teardown handle commit.
    # Calling commit() mid-request resets SET LOCAL RLS context.
    return get_usage_count(conn, workspace_id, metric, period)


def get_usage_snapshot(conn, workspace_id: int, plan: str) -> dict:
    """Return usage snapshot for all tracked metrics.

    Returns dict like::

        {
            "reports": {"used": 7, "limit": 10, "remaining": 3, "resets": "2026-03-01"},
            "uploads": {"used": 2, "limit": 10, "remaining": 8, "resets": "2026-03-01"},
        }
    """
    ent = get_plan_entitlements(plan)
    period = get_current_period()

    # Calculate reset date (first of next month)
    now = datetime.now(timezone.utc)
    if now.month == 12:
        reset_date = f"{now.year + 1}-01-01"
    else:
        reset_date = f"{now.year}-{now.month + 1:02d}-01"

    snapshot = {}
    for metric, ent_key in METRIC_TO_ENTITLEMENT.items():
        used = get_usage_count(conn, workspace_id, metric, period)
        limit = ent.get(ent_key, 0)
        if limit == -1:
            remaining = -1
        else:
            remaining = max(0, limit - used)
        snapshot[metric] = {
            "used": used,
            "limit": limit,
            "remaining": remaining,
            "resets": reset_date,
        }
    return snapshot
