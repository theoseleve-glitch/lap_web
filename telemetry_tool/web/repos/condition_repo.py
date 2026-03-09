"""Condition repository — condition phases and condition markers."""

from __future__ import annotations

import sqlite3
from typing import Any, Optional

from db import queries as Q
from web.repos._helpers import _safe_float

import logging

logger = logging.getLogger(__name__)


def insert_condition_phases(
    conn: sqlite3.Connection,
    session_id: str,
    summary: dict[str, Any],
) -> int:
    """Insert condition phase rows from pipeline summary."""
    phases_df = summary.get("phases_df")
    if phases_df is None or (hasattr(phases_df, "empty") and phases_df.empty):
        return 0

    count = 0
    if hasattr(phases_df, "iterrows"):
        for _, row in phases_df.iterrows():
            conn.execute(Q.INSERT_CONDITION_PHASE, {
                "session_id":    session_id,
                "phase_id":      int(row.get("phase_id", count)),
                "lap_start":     int(row.get("lap_start", 0)),
                "lap_end":       int(row.get("lap_end", 0)),
                "label":         row.get("phase_track_state")
                                 or row.get("label"),
                "confidence":    _safe_float(row.get("confidence")),
                "median_pace_s": _safe_float(row.get("median_s")
                                             or row.get("median_pace_s")),
            })
            count += 1
    return count


def get_condition_phases(
    conn: sqlite3.Connection,
    session_id: str,
) -> list[dict]:
    rows = conn.execute(
        Q.SELECT_CONDITION_PHASES, {"session_id": session_id}
    ).fetchall()
    return [dict(r) for r in rows]


def insert_condition_marker(
    conn: sqlite3.Connection,
    session_id: str,
    lap_number: int,
    new_state: str,
    notes: Optional[str] = None,
) -> None:
    conn.execute(Q.INSERT_CONDITION_MARKER, {
        "session_id":  session_id,
        "lap_number":  lap_number,
        "new_state":   new_state,
        "notes":       notes,
    })


def insert_condition_markers(
    conn: sqlite3.Connection,
    session_id: str,
    markers: "dict[int, str]",
) -> None:
    """Bulk-insert manual condition markers from ``{lap: state}`` mapping."""
    for lap_number, new_state in markers.items():
        conn.execute(Q.INSERT_CONDITION_MARKER, {
            "session_id":  session_id,
            "lap_number":  int(lap_number),
            "new_state":   str(new_state),
            "notes":       "manual --condition-change",
        })


def get_condition_markers(
    conn: sqlite3.Connection,
    session_id: str,
) -> list[dict]:
    rows = conn.execute(
        Q.SELECT_CONDITION_MARKERS, {"session_id": session_id}
    ).fetchall()
    return [dict(r) for r in rows]
