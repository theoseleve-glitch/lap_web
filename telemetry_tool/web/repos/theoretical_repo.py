"""Theoretical data repository — theoretical lap and reference lines."""

from __future__ import annotations

import math
import sqlite3
from typing import Any, Optional

import numpy as np

from db import queries as Q
from web.repos._helpers import _safe_float, _json_dumps, _np_to_json, _parse_json_or_list

import logging

logger = logging.getLogger(__name__)


def insert_theoretical_data(
    conn: sqlite3.Connection,
    session_id: str,
    summary: dict[str, Any],
) -> None:
    """Persist theoretical lap metrics and speed profile."""
    theo_metrics = summary.get("theoretical_metrics") or {}
    theo_lap = summary.get("theoretical_lap")
    if not theo_metrics:
        return

    # Extract speed profile from theoretical_lap DataFrame.
    speed_profile_json = None
    distance_json = None
    if theo_lap is not None and hasattr(theo_lap, "columns"):
        import pandas as pd

        # Find the distance and speed columns.
        dist_col = None
        spd_col = None
        for c in theo_lap.columns:
            cl = c.lower()
            if dist_col is None and ("distance" in cl):
                dist_col = c
            if spd_col is None and ("v_env" in cl or "speed" in cl):
                spd_col = c
        if dist_col:
            distance_json = _np_to_json(theo_lap[dist_col].values)
        if spd_col:
            speed_profile_json = _np_to_json(theo_lap[spd_col].values)

    # Compute gap % — use only valid (non-excluded) laps.
    best_time = theo_metrics.get("best_s")
    lap_times = summary.get("lap_times") or []

    # Gather excluded laps so we can skip them.
    _excluded_t: set = set()
    for _key in ("incomplete_lap_analysis", "invalid_lap_analysis",
                 "anomalous_lap_analysis", "line_deviation_analysis"):
        _analysis = summary.get(_key) or {}
        for _sub in ("incomplete_laps", "invalid_laps", "flagged_laps",
                     "dist_flagged", "time_flagged", "deviated_laps"):
            _s = _analysis.get(_sub)
            if _s:
                _excluded_t.update(_s)
    _trim = summary.get("trim_report") or {}
    for _sub in ("outlap", "inlap", "outlaps", "inlaps", "removed"):
        _v = _trim.get(_sub)
        if isinstance(_v, (set, list)):
            _excluded_t.update(_v)
        elif isinstance(_v, int):
            _excluded_t.add(_v)

    resampled = summary.get("resampled_laps") or {}
    sorted_keys = sorted(resampled.keys()) if resampled else list(range(1, len(lap_times) + 1))

    valid = []
    for i, t in enumerate(lap_times):
        lap_num = sorted_keys[i] if i < len(sorted_keys) else i + 1
        if lap_num in _excluded_t:
            continue
        if t and isinstance(t, (int, float)) and math.isfinite(t) and t > 0:
            valid.append(t)
    actual_best = min(valid) if valid else None
    gap_pct = None
    if best_time and actual_best and best_time > 0:
        gap_pct = round((actual_best - best_time) / best_time * 100, 2)

    # Serialize new kart_envelope fields
    corner_coaching = summary.get("corner_coaching")
    corner_coaching_json = _json_dumps(corner_coaching) if corner_coaching else None
    session_scalars = summary.get("session_scalars")
    session_scalars_json = _json_dumps(session_scalars) if session_scalars else None
    # Delta map summary: store top-N time loss segments (not the full DataFrame)
    delta_map_json = None
    delta_map = summary.get("delta_map")
    if delta_map is not None and hasattr(delta_map, "to_dict"):
        try:
            if "segment" in delta_map.columns and "delta_s" in delta_map.columns:
                seg_summary = (
                    delta_map.groupby("segment")
                    .agg({"delta_s": "sum", "distance_m": "mean"})
                    .reset_index()
                    .sort_values("delta_s", ascending=False)
                    .head(10)
                    .to_dict(orient="records")
                )
                delta_map_json = _json_dumps(seg_summary)
        except Exception:
            pass

    conn.execute(Q.INSERT_THEORETICAL_DATA, {
        "session_id":              session_id,
        "theoretical_time_s":      _safe_float(best_time),
        "actual_best_time_s":      _safe_float(actual_best),
        "gap_pct":                 _safe_float(gap_pct),
        "simulation_method":       theo_metrics.get("simulation_method"),
        "speed_profile_json":      speed_profile_json,
        "distance_json":           distance_json,
        "metrics_json":            _json_dumps(theo_metrics),
        "corner_coaching_json":    corner_coaching_json,
        "delta_map_json":          delta_map_json,
        "session_scalars_json":    session_scalars_json,
    })


def get_theoretical_data(
    conn: sqlite3.Connection,
    session_id: str,
) -> Optional[dict]:
    row = conn.execute(
        Q.SELECT_THEORETICAL_DATA, {"session_id": session_id}
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    # Parse JSON fields for API consumption.
    # Use _parse_json_or_list to handle both SQLite TEXT and PG JSONB.
    if d.get("speed_profile_json"):
        d["speeds"] = _parse_json_or_list(d["speed_profile_json"])
    if d.get("distance_json"):
        d["distances"] = _parse_json_or_list(d["distance_json"])
    if d.get("metrics_json"):
        d["metrics"] = _parse_json_or_list(d["metrics_json"])
    if d.get("corner_coaching_json"):
        d["corner_coaching"] = _parse_json_or_list(d["corner_coaching_json"])
    if d.get("delta_map_json"):
        d["delta_map_summary"] = _parse_json_or_list(d["delta_map_json"])
    if d.get("session_scalars_json"):
        d["session_scalars"] = _parse_json_or_list(d["session_scalars_json"])
    return d


def insert_reference_line(
    conn: sqlite3.Connection,
    session_id: str,
    summary: dict[str, Any],
) -> None:
    """Persist the reference line (median racing line) GPS coords."""
    ref_line = summary.get("reference_line")
    if ref_line is None:
        return
    if not hasattr(ref_line, "columns"):
        return

    lat_col = None
    lon_col = None
    dist_col = None
    spd_col = None
    for c in ref_line.columns:
        cl = c.lower()
        if "lat_ref" in cl or ("latitude" in cl and "deg" in cl):
            lat_col = c
        elif "lon_ref" in cl or ("longitude" in cl and "deg" in cl):
            lon_col = c
        elif "distance" in cl:
            dist_col = c
        elif "speed" in cl:
            spd_col = c

    if lat_col is None or lon_col is None:
        return

    lats = ref_line[lat_col].values
    lons = ref_line[lon_col].values
    dists = ref_line[dist_col].values if dist_col else np.arange(len(lats), dtype=float)
    spds = _np_to_json(ref_line[spd_col].values) if spd_col else None

    conn.execute(Q.INSERT_REFERENCE_LINE, {
        "session_id":      session_id,
        "latitudes_json":  _np_to_json(lats),
        "longitudes_json": _np_to_json(lons),
        "distances_json":  _np_to_json(dists),
        "speeds_json":     spds,
    })


def get_reference_line(
    conn: sqlite3.Connection,
    session_id: str,
) -> Optional[dict]:
    row = conn.execute(
        Q.SELECT_REFERENCE_LINE, {"session_id": session_id}
    ).fetchone()
    if not row:
        return None
    return {
        "latitudes":  _parse_json_or_list(row["latitudes_json"]),
        "longitudes": _parse_json_or_list(row["longitudes_json"]),
        "distances":  _parse_json_or_list(row["distances_json"]),
        "speeds":     _parse_json_or_list(row["speeds_json"]),
    }
