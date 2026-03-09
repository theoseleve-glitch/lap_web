"""Lap repository — insert/query per-lap rows."""

from __future__ import annotations

import math
import sqlite3
from typing import Any, Optional

from db import queries as Q
from web.repos._helpers import _safe_float

import logging

logger = logging.getLogger(__name__)


def insert_laps(
    conn: sqlite3.Connection,
    session_id: str,
    summary: dict[str, Any],
) -> int:
    """Insert per-lap rows from the pipeline summary. Returns count."""
    lap_metrics = summary.get("lap_metrics") or []
    best_key = summary.get("best_lap_key")
    lap_to_phase = summary.get("lap_to_phase") or {}

    # Build sets of invalid laps from the trim report.
    trim_report = summary.get("trim_report") or {}
    outlap_analysis = trim_report.get("outlap_analysis") or {}
    outlap_set = set(outlap_analysis.get("outlap_numbers") or [])
    inlap_set = set(outlap_analysis.get("inlap_numbers") or [])
    flagged_set = set(outlap_analysis.get("flagged_only") or [])

    # Invalid laps from identify_invalid_laps() — track cuts, incidents,
    # and manual exclusions.  Previously missing, causing these laps to be
    # stored as is_valid=1 even though the pipeline excluded them.
    invalid_analysis = summary.get("invalid_lap_analysis") or {}
    invalid_set = set(invalid_analysis.get("invalid_laps") or [])
    track_cut_set = set(invalid_analysis.get("track_cuts") or [])
    incident_set = set(invalid_analysis.get("incidents") or [])
    manual_set = set(invalid_analysis.get("manual") or [])

    # Additional exclusion sets from pipeline analysis steps.
    incomplete_analysis = summary.get("incomplete_lap_analysis") or {}
    incomplete_set = set(incomplete_analysis.get("incomplete_laps") or [])

    anomalous_analysis = summary.get("anomalous_lap_analysis") or {}
    anomalous_dist = set(anomalous_analysis.get("dist_flagged") or [])
    anomalous_time = set(anomalous_analysis.get("time_flagged") or [])

    deviation_analysis = summary.get("line_deviation_analysis") or {}
    deviated_set = set(deviation_analysis.get("deviated_laps") or [])

    joker_lap_number = summary.get("joker_lap_number")

    # Merge all distance-based anomalies into a single set with sub-labels.
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

    # Endurance mode: detect pit laps near manual stint boundaries.
    # When stints are manually entered, expect an abnormal lap within
    # ±3 laps of each stint boundary and relabel it as "Pitted lap".
    meta = summary.get("session_meta") or {}
    session_type = meta.get("session_type", "practice")
    endurance_types = {"endurance", "endurance_race", "endurance_stint"}
    stint_boundary_laps: set[int] = set()

    if session_type in endurance_types:
        drivers = meta.get("drivers") or []
        for drv in drivers:
            lr = drv.get("lap_range")
            if lr and len(lr) == 2:
                # The last lap of each stint (except the very last driver)
                # is a boundary where a pit stop likely happened.
                stint_boundary_laps.add(lr[1])
                # The first lap of each stint is also near a pit.
                stint_boundary_laps.add(lr[0])

    def _near_stint_boundary(lap: int) -> bool:
        """Check if lap is within ±3 of any stint boundary."""
        for boundary in stint_boundary_laps:
            if abs(lap - boundary) <= 3:
                return True
        return False

    count = 0
    for lm in lap_metrics:
        lap_num = lm.get("lap_number")
        if lap_num is None:
            continue

        # Determine validity and reason.
        # Pass 1: Distance anomalies (in/out/pit/cut/short laps)
        # Pass 2: Time anomalies (crashes, incidents)
        # Endurance: relabel anomalies near stint boundaries as "Pitted lap"
        is_valid = True
        invalid_reason = None
        is_joker = False

        if joker_lap_number is not None and lap_num == joker_lap_number:
            is_joker = True
            is_valid = False
            invalid_reason = "Joker lap"
        elif lap_num in invalid_set:
            # Track cuts, incidents, and manual exclusions from
            # identify_invalid_laps() — checked BEFORE distance/time
            # anomalies so the more specific label wins.
            is_valid = False
            if stint_boundary_laps and _near_stint_boundary(lap_num):
                invalid_reason = "Pitted lap"
            elif lap_num in manual_set:
                invalid_reason = "Manual exclusion"
            elif lap_num in track_cut_set:
                invalid_reason = "Track cut"
            elif lap_num in incident_set:
                invalid_reason = "Incident"
            else:
                invalid_reason = "Invalid"
        elif lap_num in all_dist_flagged:
            is_valid = False
            if stint_boundary_laps and _near_stint_boundary(lap_num):
                invalid_reason = "Pitted lap"
            else:
                invalid_reason = dist_labels[lap_num]
        elif lap_num in anomalous_time:
            is_valid = False
            if stint_boundary_laps and _near_stint_boundary(lap_num):
                invalid_reason = "Pitted lap"
            else:
                invalid_reason = "Time anomaly"

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
