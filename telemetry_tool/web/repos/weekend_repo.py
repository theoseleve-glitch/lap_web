"""Weekend repository — race weekend CRUD and session linking."""

from __future__ import annotations

import sqlite3
from typing import Optional

from db import queries as Q

import logging

logger = logging.getLogger(__name__)


def create_weekend(
    conn: sqlite3.Connection,
    name: str,
    track_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    notes: Optional[str] = None,
) -> int:
    """Create a weekend entry. Returns the new weekend_id."""
    cur = conn.execute(Q.INSERT_WEEKEND, {
        "name":       name,
        "track_id":   track_id,
        "start_date": start_date,
        "end_date":   end_date,
        "notes":      notes,
    })
    return cur.lastrowid


def update_weekend(
    conn: sqlite3.Connection,
    weekend_id: int,
    name: str,
    track_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    notes: Optional[str] = None,
) -> None:
    conn.execute(Q.UPDATE_WEEKEND, {
        "weekend_id": weekend_id,
        "name":       name,
        "track_id":   track_id,
        "start_date": start_date,
        "end_date":   end_date,
        "notes":      notes,
    })


def delete_weekend(conn: sqlite3.Connection, weekend_id: int) -> None:
    conn.execute(Q.DELETE_ALL_WEEKEND_SESSIONS, {"weekend_id": weekend_id})
    conn.execute(Q.DELETE_WEEKEND, {"weekend_id": weekend_id})


def get_all_weekends(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(Q.SELECT_ALL_WEEKENDS).fetchall()
    return [dict(r) for r in rows]


def get_weekend_by_id(
    conn: sqlite3.Connection,
    weekend_id: int,
) -> Optional[dict]:
    row = conn.execute(
        Q.SELECT_WEEKEND_BY_ID, {"weekend_id": weekend_id}
    ).fetchone()
    return dict(row) if row else None


def add_session_to_weekend(
    conn: sqlite3.Connection,
    weekend_id: int,
    session_id: str,
    session_order: int = 0,
) -> None:
    conn.execute(Q.INSERT_WEEKEND_SESSION, {
        "weekend_id":    weekend_id,
        "session_id":    session_id,
        "session_order": session_order,
    })


def remove_session_from_weekend(
    conn: sqlite3.Connection,
    weekend_id: int,
    session_id: str,
) -> None:
    conn.execute(Q.DELETE_WEEKEND_SESSION, {
        "weekend_id": weekend_id,
        "session_id": session_id,
    })


def get_weekend_sessions(
    conn: sqlite3.Connection,
    weekend_id: int,
) -> list[dict]:
    rows = conn.execute(
        Q.SELECT_WEEKEND_SESSIONS, {"weekend_id": weekend_id}
    ).fetchall()
    return [dict(r) for r in rows]


def swap_weekend_session_order(
    conn: sqlite3.Connection, weekend_id: int, session_id: str, direction: str
) -> None:
    """Swap a session with its neighbor (up or down)."""
    sessions = get_weekend_sessions(conn, weekend_id)
    idx = next((i for i, s in enumerate(sessions) if s["session_id"] == session_id), None)
    if idx is None:
        return

    swap_idx = idx - 1 if direction == "up" else idx + 1
    if swap_idx < 0 or swap_idx >= len(sessions):
        return

    # Swap session_order values.
    a_order = sessions[idx]["session_order"]
    b_order = sessions[swap_idx]["session_order"]
    conn.execute(
        "UPDATE weekend_sessions SET session_order = ? WHERE weekend_id = ? AND session_id = ?",
        (b_order, weekend_id, sessions[idx]["session_id"]),
    )
    conn.execute(
        "UPDATE weekend_sessions SET session_order = ? WHERE weekend_id = ? AND session_id = ?",
        (a_order, weekend_id, sessions[swap_idx]["session_id"]),
    )


def reorder_weekend_sessions(
    conn: sqlite3.Connection, weekend_id: int, session_ids: list[str]
) -> None:
    """Set session_order based on the given list order."""
    for idx, sid in enumerate(session_ids):
        conn.execute(
            "UPDATE weekend_sessions SET session_order = ? WHERE weekend_id = ? AND session_id = ?",
            (idx, weekend_id, sid),
        )
