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


def _pipeline_validity(
    summary: dict[str, Any],
) -> dict[int, tuple[bool, str]]:
    """Build lap validity from pipeline analysis dicts.

    Priority order (highest wins):
    1. Joker lap
    2. Invalid lap analysis (track cuts, incidents, manual exclusions)
    3. Incomplete lap analysis
    4. Distance anomalies (outlaps, inlaps, pit laps, track deviation)
    5. Time anomalies
    6. Endurance pit relabeling (near stint boundary → "Pitted lap")

    Returns {lap_number: (is_valid, invalid_reason)} for flagged laps only.
    Laps not in the dict are considered valid.
    """
    result: dict[int, tuple[bool, str]] = {}

    # ── Extract pipeline analysis dicts ──────────────────────────
    trim_report = summary.get("trim_report") or {}
    outlap_analysis = trim_report.get("outlap_analysis") or {}
    outlap_set = set(outlap_analysis.get("outlap_numbers") or [])
    inlap_set = set(outlap_analysis.get("inlap_numbers") or [])
    flagged_set = set(outlap_analysis.get("flagged_only") or [])

    invalid_analysis = summary.get("invalid_lap_analysis") or {}
    invalid_set = set(invalid_analysis.get("invalid_laps") or [])
    track_cut_set = set(invalid_analysis.get("track_cuts") or [])
    incident_set = set(invalid_analysis.get("incidents") or [])
    manual_set = set(invalid_analysis.get("manual") or [])

    incomplete_analysis = summary.get("incomplete_lap_analysis") or {}
    incomplete_set = set(incomplete_analysis.get("incomplete_laps") or [])

    anomalous_analysis = summary.get("anomalous_lap_analysis") or {}
    anomalous_dist = set(anomalous_analysis.get("dist_flagged") or [])
    anomalous_time = set(anomalous_analysis.get("time_flagged") or [])

    deviation_analysis = summary.get("line_deviation_analysis") or {}
    deviated_set = set(deviation_analysis.get("deviated_laps") or [])

    # ── Distance-based anomalies with sub-labels ─────────────────
    # Priority within distance: outlap/inlap > pit lap > track deviation
    #                           > incomplete > generic distance anomaly
    dist_labels: dict[int, str] = {}
    for lap_num in anomalous_dist:
        dist_labels[lap_num] = "Distance anomaly"
    for lap_num in incomplete_set:
        dist_labels[lap_num] = "Incomplete"
    for lap_num in deviated_set:
        dist_labels[lap_num] = "Track deviation"
    for lap_num in flagged_set:
        dist_labels[lap_num] = "Pit lap"
    for lap_num in outlap_set:
        if lap_num in inlap_set:
            dist_labels[lap_num] = "Inlap"
        else:
            dist_labels[lap_num] = "Outlap"

    all_dist_flagged = set(dist_labels.keys())

    # ── Endurance pit detection ──────────────────────────────────
    meta = summary.get("session_meta") or {}
    session_type = meta.get("session_type", "practice")
    endurance_types = {"endurance", "endurance_race", "endurance_stint"}
    stint_boundary_laps: set[int] = set()

    if session_type in endurance_types:
        drivers = meta.get("drivers") or []
        for drv in drivers:
            lr = drv.get("lap_range")
            if lr and len(lr) == 2:
                stint_boundary_laps.add(lr[1])
                stint_boundary_laps.add(lr[0])

    def _near_stint_boundary(lap: int) -> bool:
        for boundary in stint_boundary_laps:
            if abs(lap - boundary) <= 3:
                return True
        return False

    # ── Build per-lap results ────────────────────────────────────
    all_flagged = invalid_set | all_dist_flagged | anomalous_time | incomplete_set
    for lap_num in all_flagged:
        if lap_num in invalid_set:
            if stint_boundary_laps and _near_stint_boundary(lap_num):
                result[lap_num] = (False, "Pitted lap")
            elif lap_num in manual_set:
                result[lap_num] = (False, "Manual exclusion")
            elif lap_num in track_cut_set:
                result[lap_num] = (False, "Track cut")
            elif lap_num in incident_set:
                result[lap_num] = (False, "Incident")
            else:
                result[lap_num] = (False, "Invalid")
        elif lap_num in all_dist_flagged:
            if stint_boundary_laps and _near_stint_boundary(lap_num):
                result[lap_num] = (False, "Pitted lap")
            else:
                result[lap_num] = (False, dist_labels[lap_num])
        elif lap_num in anomalous_time:
            if stint_boundary_laps and _near_stint_boundary(lap_num):
                result[lap_num] = (False, "Pitted lap")
            else:
                result[lap_num] = (False, "Time anomaly")

    return result


def _has_pipeline_analysis(summary: dict[str, Any]) -> bool:
    """Check if the summary contains any populated pipeline analysis dicts."""
    for key in ("invalid_lap_analysis", "incomplete_lap_analysis",
                "anomalous_lap_analysis", "line_deviation_analysis"):
        analysis = summary.get(key) or {}
        for v in analysis.values():
            if isinstance(v, (list, set)) and len(v) > 0:
                return True
    trim = summary.get("trim_report") or {}
    outlap = trim.get("outlap_analysis") or {}
    for v in outlap.values():
        if isinstance(v, (list, set)) and len(v) > 0:
            return True
    return False


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

    # ── Blended validity detection ──────────────────────────────
    # Layer 1: Pipeline analysis dicts (outlaps, track cuts,
    # incidents, anomalous laps) — rich, label-specific.
    # Layer 2: Rolling-average catches anything the pipeline missed
    # (e.g. laps that slipped through pipeline detection).
    # Pipeline labels take priority; rolling-avg fills gaps.
    pipeline_validity = _pipeline_validity(summary)
    rolling_validity = _rolling_avg_validity(lap_metrics)

    # Merge: pipeline wins where it has data, rolling-avg fills rest
    validity: dict[int, tuple[bool, str | None]] = {}
    all_lap_nums = {lm.get("lap_number") for lm in lap_metrics if lm.get("lap_number") is not None}
    for lap_num in all_lap_nums:
        if lap_num in pipeline_validity:
            # Pipeline flagged this lap — use its label
            validity[lap_num] = pipeline_validity[lap_num]
        elif lap_num in rolling_validity:
            # Rolling-avg caught something the pipeline didn't
            validity[lap_num] = rolling_validity[lap_num]
        else:
            validity[lap_num] = (True, None)

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
