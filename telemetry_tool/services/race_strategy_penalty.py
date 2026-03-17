"""Penalty tracking service functions.

Pure business logic for race penalty CRUD.  No Flask imports -- accepts a
DB connection as first argument and returns plain dicts.

SQL uses ``?`` positional parameters; the ``sql_compat`` layer
auto-translates to ``%(name)s`` / ``%s`` for PostgreSQL at call time.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

_parent = str(Path(__file__).resolve().parents[1])
if _parent not in sys.path:
    sys.path.insert(0, _parent)

from services.race_strategy import get_race, _compute_elapsed_s

logger = logging.getLogger(__name__)


def add_penalty(
    conn,
    race_id: int,
    penalty_type: str,
    laps_deducted: int = 0,
    reason: str | None = None,
    passage_duration_s: int | None = None,
) -> dict | None:
    """Record a penalty against a race.

    Parameters
    ----------
    conn : DB connection
    race_id : int
    penalty_type : str
        One of 'passage', 'time', 'laps', 'warning', etc.
    laps_deducted : int
        Number of laps to deduct (0 for non-lap penalties).
    reason : str | None
        Human-readable reason for the penalty.
    passage_duration_s : int | None
        Duration of passage penalty in seconds (only for 'passage' type).

    Returns
    -------
    dict | None
        ``{"ok": True, "elapsed_s": N, "penalty_type": "..."}`` on success,
        None if race not found.
    """
    race = get_race(conn, race_id)
    if not race:
        return None

    elapsed = _compute_elapsed_s(race.get("race_start_ts"), race)

    # Find current active stint order (if any)
    active = conn.execute(
        "SELECT stint_order FROM race_stints WHERE race_id = ? AND status = 'active'",
        (race_id,),
    ).fetchone()
    stint_order = None
    if active:
        stint_order = active["stint_order"] if isinstance(active, dict) else active[0]

    conn.execute(
        "INSERT INTO race_penalties "
        "(race_id, stint_order, elapsed_s, penalty_type, laps_deducted, "
        " passage_duration_s, reason) VALUES (?,?,?,?,?,?,?)",
        (race_id, stint_order, elapsed, penalty_type,
         laps_deducted, passage_duration_s, reason),
    )
    conn.commit()
    return {"ok": True, "elapsed_s": elapsed, "penalty_type": penalty_type}


def clear_penalty(conn, race_id: int, penalty_id: int) -> dict | None:
    """Mark a penalty as cleared (e.g. passage served).

    Parameters
    ----------
    conn : DB connection
    race_id : int
    penalty_id : int

    Returns
    -------
    dict | None
        ``{"ok": True, "cleared_at_s": N}`` on success, None if not found.
    """
    race = get_race(conn, race_id)
    if not race:
        return None

    elapsed = _compute_elapsed_s(race.get("race_start_ts"), race)

    row = conn.execute(
        "SELECT * FROM race_penalties WHERE id = ? AND race_id = ?",
        (penalty_id, race_id),
    ).fetchone()
    if not row:
        return None

    conn.execute(
        "UPDATE race_penalties SET cleared = 1, cleared_at_s = ? WHERE id = ?",
        (elapsed, penalty_id),
    )
    conn.commit()
    return {"ok": True, "cleared_at_s": elapsed}


def get_penalties(conn, race_id: int) -> list[dict]:
    """Return all penalties for a race, ordered by elapsed time.

    Parameters
    ----------
    conn : DB connection
    race_id : int

    Returns
    -------
    list[dict]
    """
    rows = conn.execute(
        "SELECT * FROM race_penalties WHERE race_id = ? ORDER BY elapsed_s",
        (race_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_active_passage(conn, race_id: int) -> dict | None:
    """Return the oldest uncleared passage penalty, or None.

    Parameters
    ----------
    conn : DB connection
    race_id : int

    Returns
    -------
    dict | None
    """
    row = conn.execute(
        "SELECT * FROM race_penalties "
        "WHERE race_id = ? AND penalty_type = 'passage' AND cleared = 0 "
        "ORDER BY elapsed_s LIMIT 1",
        (race_id,),
    ).fetchone()
    return dict(row) if row else None
