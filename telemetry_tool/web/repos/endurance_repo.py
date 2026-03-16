"""Endurance stint detection, storage, and driver assignment."""
from __future__ import annotations

import sqlite3
from typing import Any

DEFAULT_PIT_THRESHOLD_S = 120.0


def detect_and_store_stints(
    conn: sqlite3.Connection,
    session_id: str,
    lap_times: dict[int, float],
    pit_threshold_s: float = DEFAULT_PIT_THRESHOLD_S,
) -> list[dict[str, Any]]:
    """Detect pit laps, create stint boundaries, store in DB.

    Replaces any existing stints for this session (idempotent).
    """
    # Clear existing stints
    conn.execute(
        "DELETE FROM endurance_stints WHERE session_id = :sid",
        {"sid": session_id},
    )

    # Sort laps by number
    sorted_laps = sorted(lap_times.items())

    # Classify pit laps
    pit_laps = {ln for ln, t in sorted_laps if t > pit_threshold_s}

    # Group valid laps into stints
    stints: list[dict[str, Any]] = []
    current_laps: list[int] = []

    for lap_num, lap_time in sorted_laps:
        if lap_num in pit_laps:
            # End current stint
            if current_laps:
                stints.append({
                    "stint_number": len(stints) + 1,
                    "start_lap": current_laps[0],
                    "end_lap": current_laps[-1],
                    "lap_count": len(current_laps),
                    "pit_lap_number": lap_num,
                    "pit_lap_time_s": lap_time,
                })
                current_laps = []
        else:
            current_laps.append(lap_num)

    # Final stint (no trailing pit)
    if current_laps:
        stints.append({
            "stint_number": len(stints) + 1,
            "start_lap": current_laps[0],
            "end_lap": current_laps[-1],
            "lap_count": len(current_laps),
            "pit_lap_number": None,
            "pit_lap_time_s": None,
        })

    # Persist
    for s in stints:
        conn.execute(
            "INSERT INTO endurance_stints "
            "(session_id, stint_number, start_lap, end_lap, lap_count, "
            " pit_lap_number, pit_lap_time_s) "
            "VALUES (:sid, :sn, :sl, :el, :lc, :pln, :plt)",
            {
                "sid": session_id,
                "sn": s["stint_number"],
                "sl": s["start_lap"],
                "el": s["end_lap"],
                "lc": s["lap_count"],
                "pln": s["pit_lap_number"],
                "plt": s["pit_lap_time_s"],
            },
        )
    conn.commit()

    # Store threshold on session
    conn.execute(
        "UPDATE sessions SET pit_threshold_s = :pt WHERE session_id = :sid",
        {"pt": pit_threshold_s, "sid": session_id},
    )
    conn.commit()

    return stints


def get_stints(
    conn: sqlite3.Connection,
    session_id: str,
) -> list[dict[str, Any]]:
    """Return all stints for a session, ordered by stint_number."""
    rows = conn.execute(
        "SELECT * FROM endurance_stints "
        "WHERE session_id = :sid ORDER BY stint_number",
        {"sid": session_id},
    ).fetchall()
    return [dict(r) for r in rows]


def assign_driver_to_stint(
    conn: sqlite3.Connection,
    session_id: str,
    stint_number: int,
    driver_name: str | None = None,
    driver_id: int | None = None,
    condition: str | None = None,
) -> None:
    """Assign a driver and/or condition to a stint."""
    sets: list[str] = []
    vals: dict[str, Any] = {"sid": session_id, "sn": stint_number}

    if driver_name is not None:
        sets.append("driver_name = :dn")
        vals["dn"] = driver_name
    if driver_id is not None:
        sets.append("driver_id = :did")
        vals["did"] = driver_id
    if condition is not None:
        sets.append("condition = :cond")
        vals["cond"] = condition

    if sets:
        conn.execute(
            f"UPDATE endurance_stints SET {', '.join(sets)} "
            "WHERE session_id = :sid AND stint_number = :sn",
            vals,
        )
        conn.commit()


def bulk_assign_drivers(
    conn: sqlite3.Connection,
    session_id: str,
    assignments: list[dict[str, Any]],
) -> int:
    """Bulk assign drivers + conditions to stints.

    Each assignment: {stint_number, driver_name?, driver_id?, condition?}
    """
    count = 0
    for a in assignments:
        assign_driver_to_stint(
            conn, session_id,
            stint_number=a["stint_number"],
            driver_name=a.get("driver_name"),
            driver_id=a.get("driver_id"),
            condition=a.get("condition"),
        )
        count += 1
    return count


def get_endurance_config(
    conn: sqlite3.Connection,
    session_id: str,
) -> dict[str, Any]:
    """Return endurance configuration for a session."""
    row = conn.execute(
        "SELECT pit_threshold_s FROM sessions WHERE session_id = :sid",
        {"sid": session_id},
    ).fetchone()
    return {
        "pit_threshold_s": (row["pit_threshold_s"] if row and row["pit_threshold_s"]
                            else DEFAULT_PIT_THRESHOLD_S),
    }
