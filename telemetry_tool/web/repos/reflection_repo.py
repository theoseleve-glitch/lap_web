"""Reflection + competitor persistence (W3 Feeling→Scoring)."""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from db import queries as Q
from web.repos._helpers import _json_dumps, _safe_float


def upsert_reflection(conn: sqlite3.Connection, session_id: str, feeling: dict[str, Any]) -> None:
    """Write the driver's feeling + self-reported race result onto the session."""
    is_dnf = feeling.get("race_is_dnf")
    conn.execute(Q.UPDATE_SESSION_REFLECTION, {
        "session_id": session_id,
        "result_tags": _json_dumps(feeling.get("result_tags") or []),
        "driver_perceived_conditions": feeling.get("driver_perceived_conditions"),
        "felt_performance_rating": feeling.get("felt_performance_rating"),
        "race_position": feeling.get("race_position"),
        "race_total_competitors": feeling.get("race_total_competitors"),
        "race_gap_to_leader_s": _safe_float(feeling.get("race_gap_to_leader_s")),
        "race_gap_to_nearest_s": _safe_float(feeling.get("race_gap_to_nearest_s")),
        "race_laps_completed": feeling.get("race_laps_completed"),
        "race_is_dnf": (1 if is_dnf else 0) if is_dnf is not None else None,
    })


def get_reflection(conn: sqlite3.Connection, session_id: str) -> dict[str, Any]:
    """Return the session's reflection fields; result_tags parsed to a list."""
    row = conn.execute(Q.SELECT_SESSION_REFLECTION, {"session_id": session_id}).fetchone()
    if row is None:
        return {"result_tags": [], "driver_perceived_conditions": None,
                "felt_performance_rating": None, "race_position": None,
                "race_total_competitors": None, "race_gap_to_leader_s": None,
                "race_gap_to_nearest_s": None, "race_laps_completed": None,
                "race_is_dnf": None}
    d = dict(row)
    raw = d.get("result_tags")
    try:
        d["result_tags"] = json.loads(raw) if raw else []
    except (json.JSONDecodeError, TypeError):
        d["result_tags"] = []
    return d


def replace_competitors(conn: sqlite3.Connection, session_id: str,
                        competitors: list[dict[str, Any]]) -> int:
    """Delete existing competitors for the session and insert the given list."""
    conn.execute(Q.DELETE_SESSION_COMPETITORS, {"session_id": session_id})
    count = 0
    for c in competitors or []:
        name = (c.get("competitor_name") or "").strip()
        if not name:
            continue
        conn.execute(Q.INSERT_SESSION_COMPETITOR, {
            "session_id": session_id,
            "competitor_name": name[:120],
            "final_position": c.get("final_position"),
            "gap_to_this_driver_s": _safe_float(c.get("gap_to_this_driver_s")),
            "notes": (c.get("notes") or "")[:500] or None,
        })
        count += 1
    return count


def get_competitors(conn: sqlite3.Connection, session_id: str) -> list[dict[str, Any]]:
    """All competitor rows for the session, ordered by finishing position."""
    rows = conn.execute(Q.SELECT_SESSION_COMPETITORS, {"session_id": session_id}).fetchall()
    return [dict(r) for r in rows]
