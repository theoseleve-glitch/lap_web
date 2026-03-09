"""Session sector repository — sector split points for sessions."""

from __future__ import annotations

import sqlite3
from typing import Optional

from db import queries as Q

import logging

logger = logging.getLogger(__name__)


def get_session_sectors(
    conn: sqlite3.Connection,
    session_id: str,
) -> list[dict]:
    """Return all sector split points for a session, ordered by index."""
    rows = conn.execute(
        Q.SELECT_SESSION_SECTORS, {"session_id": session_id}
    ).fetchall()
    return [dict(r) for r in rows]


def upsert_session_sector(
    conn: sqlite3.Connection,
    session_id: str,
    sector_index: int,
    distance_m: float,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    label: Optional[str] = None,
) -> None:
    """Insert or update a single sector split point."""
    conn.execute(Q.INSERT_SESSION_SECTOR, {
        "session_id":   session_id,
        "sector_index": sector_index,
        "distance_m":   distance_m,
        "latitude":     latitude,
        "longitude":    longitude,
        "label":        label,
    })


def delete_session_sector(
    conn: sqlite3.Connection,
    sector_id: int,
) -> None:
    """Delete a sector by its primary key."""
    conn.execute(Q.DELETE_SESSION_SECTOR, {"id": sector_id})


def reindex_session_sectors(
    conn: sqlite3.Connection,
    session_id: str,
) -> list[dict]:
    """
    Re-index all sectors for a session so sector_index is 0, 1, 2, ...
    ordered by distance_m.  Returns the updated list.
    """
    rows = conn.execute(
        "SELECT id, distance_m FROM session_sectors "
        "WHERE session_id = :sid ORDER BY distance_m",
        {"sid": session_id},
    ).fetchall()
    for idx, row in enumerate(rows):
        label = f"S{idx + 1}"
        conn.execute(
            "UPDATE session_sectors SET sector_index = :idx, label = :label "
            "WHERE id = :id",
            {"idx": idx, "label": label, "id": row["id"]},
        )
    return get_session_sectors(conn, session_id)
