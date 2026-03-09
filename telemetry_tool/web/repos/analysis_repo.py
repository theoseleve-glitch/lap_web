"""Analysis repository — stint analysis and analysis_json blob."""

from __future__ import annotations

import json
import sqlite3
from typing import Optional

import logging

logger = logging.getLogger(__name__)


def insert_stint_analysis(
    conn: sqlite3.Connection,
    session_id: str,
    stint_metrics: list[dict],
) -> int:
    """Persist stint metrics into the stint_analysis table.

    Parameters
    ----------
    conn : sqlite3.Connection
    session_id : str
    stint_metrics : list[dict]
        Each dict must have keys matching the ``stint_analysis`` columns.

    Returns
    -------
    int
        Number of rows inserted.
    """
    # Delete existing stints for this session first
    conn.execute(
        "DELETE FROM stint_analysis WHERE session_id = :sid",
        {"sid": session_id},
    )
    inserted = 0
    for sm in stint_metrics:
        conn.execute(
            """INSERT OR REPLACE INTO stint_analysis
               (session_id, stint_number, lap_start, lap_end, lap_count,
                best_lap, best_time_s, mean_time_s, median_time_s, std_time_s,
                cv_pct, pace_fade_pct, tyre_cliff_lap, tyre_cliff_severity_pct,
                pace_trend_slope, coaching_hint)
               VALUES (:sid, :stint_number, :lap_start, :lap_end, :lap_count,
                :best_lap, :best_time_s, :mean_time_s, :median_time_s, :std_time_s,
                :cv_pct, :pace_fade_pct, :tyre_cliff_lap, :tyre_cliff_severity_pct,
                :pace_trend_slope, :coaching_hint)""",
            {
                "sid": session_id,
                "stint_number": sm.get("stint_number", 0),
                "lap_start": sm.get("lap_start", 0),
                "lap_end": sm.get("lap_end", 0),
                "lap_count": sm.get("lap_count", 0),
                "best_lap": sm.get("best_lap"),
                "best_time_s": sm.get("best_time_s"),
                "mean_time_s": sm.get("mean_time_s"),
                "median_time_s": sm.get("median_time_s"),
                "std_time_s": sm.get("std_time_s"),
                "cv_pct": sm.get("cv_pct"),
                "pace_fade_pct": sm.get("pace_fade_pct"),
                "tyre_cliff_lap": sm.get("tyre_cliff_lap"),
                "tyre_cliff_severity_pct": sm.get("tyre_cliff_severity_pct"),
                "pace_trend_slope": sm.get("pace_trend_slope"),
                "coaching_hint": sm.get("coaching_hint", ""),
            },
        )
        inserted += 1
    conn.commit()
    return inserted


def get_stint_analysis(
    conn: sqlite3.Connection,
    session_id: str,
) -> list[dict]:
    """Retrieve stint metrics for a session.

    Returns
    -------
    list[dict]
        One dict per stint, ordered by stint_number.
    """
    rows = conn.execute(
        """SELECT * FROM stint_analysis
           WHERE session_id = :sid
           ORDER BY stint_number""",
        {"sid": session_id},
    ).fetchall()
    return [dict(r) for r in rows]


def get_analysis_json(
    conn: sqlite3.Connection,
    session_id: str,
) -> Optional[dict]:
    """Read and parse the analysis_json blob from the sessions table."""
    try:
        row = conn.execute(
            "SELECT analysis_json FROM sessions WHERE session_id = :sid",
            {"sid": session_id},
        ).fetchone()
    except Exception:
        return None
    if not row or not row["analysis_json"]:
        return None
    try:
        return json.loads(row["analysis_json"])
    except (json.JSONDecodeError, TypeError):
        return None


def insert_analysis_json(
    conn: sqlite3.Connection,
    session_id: str,
    analysis: dict,
) -> None:
    """Persist the supplementary analysis blob to sessions.analysis_json."""
    blob = json.dumps(analysis, default=str)
    conn.execute(
        "UPDATE sessions SET analysis_json = :blob WHERE session_id = :sid",
        {"blob": blob, "sid": session_id},
    )
