"""Lap repository — insert/query per-lap rows."""

from __future__ import annotations

import math
import sqlite3
from typing import Any, Optional

from db import queries as Q
from web.repos._helpers import _safe_float

import logging

logger = logging.getLogger(__name__)


def _rolling_avg_validity(
    lap_metrics: list[dict[str, Any]],
    window: int = 5,
    lo: float = 0.90,
    hi: float = 1.10,
) -> dict[int, tuple[bool, str | None]]:
    """Determine lap validity using rolling average of valid laps.

    For each lap (processed in lap_number order), compute the rolling
    average of time and distance from the last ``window`` *valid* laps.
    A lap is valid if both its time AND distance fall within [lo, hi]
    of the rolling average.  Invalid laps are excluded from the rolling
    window so one bad lap cannot cascade-invalidate subsequent good laps.

    Returns {lap_number: (is_valid, invalid_reason)}.
    """
    # Sort by lap number and extract time+distance
    ordered = sorted(lap_metrics, key=lambda lm: lm.get("lap_number", 0))

    valid_times: list[float] = []   # rolling window of valid lap times
    valid_dists: list[float] = []   # rolling window of valid lap distances
    result: dict[int, tuple[bool, str | None]] = {}

    for lm in ordered:
        lap_num = lm.get("lap_number")
        if lap_num is None:
            continue

        time_s = _safe_float(lm.get("lap_time_s"))
        dist_m = _safe_float(lm.get("line_length_m"))

        # Skip laps with missing data — mark invalid
        if time_s is None or time_s <= 0:
            result[lap_num] = (False, "No lap time")
            continue
        if dist_m is None or dist_m <= 0:
            # Distance may be missing for some sessions — only check time
            dist_m = None

        # Not enough valid laps yet to form a rolling average — accept
        # the first few laps to seed the window (need at least 2).
        if len(valid_times) < 2:
            result[lap_num] = (True, None)
            valid_times.append(time_s)
            if dist_m is not None:
                valid_dists.append(dist_m)
            continue

        # Compute rolling averages from last N valid laps
        recent_times = valid_times[-window:]
        avg_time = sum(recent_times) / len(recent_times)

        time_ok = (avg_time * lo) <= time_s <= (avg_time * hi)

        dist_ok = True  # default if no distance data available
        reason_parts: list[str] = []

        if dist_m is not None and len(valid_dists) >= 2:
            recent_dists = valid_dists[-window:]
            avg_dist = sum(recent_dists) / len(recent_dists)
            dist_ok = (avg_dist * lo) <= dist_m <= (avg_dist * hi)

        if not time_ok:
            reason_parts.append("Time anomaly")
        if not dist_ok:
            reason_parts.append("Distance anomaly")

        if time_ok and dist_ok:
            result[lap_num] = (True, None)
            valid_times.append(time_s)
            if dist_m is not None:
                valid_dists.append(dist_m)
        else:
            result[lap_num] = (False, " + ".join(reason_parts))
            # Do NOT add to rolling window — keeps it robust

    return result


def insert_laps(
    conn: sqlite3.Connection,
    session_id: str,
    summary: dict[str, Any],
) -> int:
    """Insert per-lap rows from the pipeline summary. Returns count."""
    lap_metrics = summary.get("lap_metrics") or []
    best_key = summary.get("best_lap_key")
    lap_to_phase = summary.get("lap_to_phase") or {}
    joker_lap_number = summary.get("joker_lap_number")

    # ── Rolling-average validity detection ───────────────────────
    # Replaces the old pipeline-based detection which relied on upstream
    # analysis dicts that were often empty or unreliable.
    # Algorithm: rolling avg of last 5 valid laps, valid = within
    # [90%, 110%] of avg for BOTH time AND distance.
    validity = _rolling_avg_validity(lap_metrics)

    count = 0
    for lm in lap_metrics:
        lap_num = lm.get("lap_number")
        if lap_num is None:
            continue

        is_joker = False
        is_valid, invalid_reason = validity.get(lap_num, (True, None))

        # Joker laps override — always invalid with specific reason
        if joker_lap_number is not None and lap_num == joker_lap_number:
            is_joker = True
            is_valid = False
            invalid_reason = "Joker lap"

        conn.execute(Q.INSERT_LAP, {
            "session_id":       session_id,
            "lap_number":       lap_num,
            "lap_time_s":       _safe_float(lm.get("lap_time_s")),
            "speed_mean_mps":   _safe_float(lm.get("speed_mean_mps")),
            "speed_max_mps":    _safe_float(lm.get("speed_max_mps")),
            "braking_max_mps2": _safe_float(lm.get("braking_max_mps2")),
            "accel_max_mps2":   _safe_float(lm.get("accel_max_mps2")),
            "line_length_m":    _safe_float(lm.get("line_length_m")),
            "is_valid":         is_valid,
            "is_best":          lap_num == best_key,
            "phase_id":         lap_to_phase.get(lap_num),
            "invalid_reason":   invalid_reason,
            "is_joker":         is_joker,
        })
        count += 1
    return count


def get_laps_for_session(
    conn: sqlite3.Connection,
    session_id: str,
) -> list[dict]:
    rows = conn.execute(
        Q.SELECT_LAPS_FOR_SESSION, {"session_id": session_id}
    ).fetchall()
    return [dict(r) for r in rows]


def get_gps_lap_numbers(
    conn: sqlite3.Connection,
    session_id: str,
) -> list[int]:
    rows = conn.execute(
        Q.SELECT_GPS_LAPS_FOR_SESSION, {"session_id": session_id}
    ).fetchall()
    return [r["lap_number"] for r in rows]
