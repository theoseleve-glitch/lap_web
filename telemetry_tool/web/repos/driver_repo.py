"""Driver repository — driver CRUD, profiles, progression, driving style."""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Optional

from db import queries as Q
from web.repos._helpers import _safe_float, _parse_json_or_list

import logging

logger = logging.getLogger(__name__)


def upsert_driver(conn: sqlite3.Connection, driver_name: str) -> int:
    """Insert driver if not exists; return driver_id.

    On PostgreSQL the unique constraint is workspace-scoped
    ``(workspace_id, driver_name)`` so we use a PG-specific query.
    On SQLite the constraint is just ``(driver_name)``.
    """
    import os
    if os.environ.get("USE_PG", "0") == "1":
        conn.execute(
            "INSERT INTO drivers (driver_name) VALUES (:driver_name) "
            "ON CONFLICT (workspace_id, driver_name) DO NOTHING",
            {"driver_name": driver_name},
        )
    else:
        conn.execute(Q.UPSERT_DRIVER, {"driver_name": driver_name})
    row = conn.execute(
        Q.SELECT_DRIVER_BY_NAME, {"driver_name": driver_name}
    ).fetchone()
    return row["driver_id"]


def _get_all_drivers_simple(conn: sqlite3.Connection) -> list[dict]:
    """Return all drivers with basic aggregate stats (lightweight)."""
    rows = conn.execute(Q.SELECT_ALL_DRIVERS).fetchall()
    return [dict(r) for r in rows]


def upsert_driver_profile(
    conn: sqlite3.Connection,
    driver_id: int,
    profile_data: dict[str, Any],
) -> None:
    """Create or update a driver profile with computed and user fields."""
    params = {
        "driver_id": driver_id,
        "weight_kg": _safe_float(profile_data.get("weight_kg")),
        "kart_class": profile_data.get("kart_class"),
        "experience_level": profile_data.get("experience_level"),
        "goals": profile_data.get("goals"),
        "preferred_tracks": profile_data.get("preferred_tracks"),
        "custom_notes": profile_data.get("custom_notes"),
        "email": profile_data.get("email"),
        "phone": profile_data.get("phone"),
        "id_code": profile_data.get("id_code"),
        "pace_delta_mean_s": _safe_float(profile_data.get("pace_delta_mean_s")),
        "consistency_rating": _safe_float(profile_data.get("consistency_rating")),
        "aggression_index": _safe_float(profile_data.get("aggression_index")),
        "smoothness_index": _safe_float(profile_data.get("smoothness_index")),
        "improvement_trend": profile_data.get("improvement_trend"),
        "total_sessions": profile_data.get("total_sessions", 0),
        "total_laps": profile_data.get("total_laps", 0),
        "best_ever_time_s": _safe_float(profile_data.get("best_ever_time_s")),
        "best_ever_track_id": profile_data.get("best_ever_track_id"),
        "wet_skill_proxy": _safe_float(profile_data.get("wet_skill_proxy")),
    }
    conn.execute(Q.UPSERT_DRIVER_PROFILE, params)


def get_driver_profile(
    conn: sqlite3.Connection,
    driver_id: int,
) -> Optional[dict]:
    row = conn.execute(
        Q.SELECT_DRIVER_PROFILE, {"driver_id": driver_id}
    ).fetchone()
    return dict(row) if row else None


def update_driver_profile_field(
    conn: sqlite3.Connection,
    driver_id: int,
    field_name: str,
    value: Any,
) -> None:
    """Update a single editable field on a driver profile."""
    allowed = {
        "weight_kg", "kart_class", "experience_level",
        "goals", "preferred_tracks", "custom_notes",
        "email", "phone", "id_code",
    }
    if field_name not in allowed:
        raise ValueError(f"Field {field_name!r} not editable.")
    sql = Q.UPDATE_DRIVER_PROFILE_FIELDS.replace("{field}", field_name)
    conn.execute(sql, {"driver_id": driver_id, "value": value})


def insert_driver_progression(
    conn: sqlite3.Connection,
    driver_id: int,
    session_id: str,
    data: dict[str, Any],
) -> None:
    conn.execute(Q.INSERT_DRIVER_PROGRESSION, {
        "driver_id":          driver_id,
        "session_id":         session_id,
        "session_date":       data.get("session_date"),
        "track_id":           data.get("track_id"),
        "pace_delta_s":       _safe_float(data.get("pace_delta_s")),
        "consistency_cv_pct": _safe_float(data.get("consistency_cv_pct")),
        "aggression_index":   _safe_float(data.get("aggression_index")),
        "smoothness_index":   _safe_float(data.get("smoothness_index")),
        "total_score":        _safe_float(data.get("total_score")),
        "n_laps":             data.get("n_laps"),
    })


def get_driver_progression(
    conn: sqlite3.Connection,
    driver_id: int,
) -> list[dict]:
    rows = conn.execute(
        Q.SELECT_DRIVER_PROGRESSION, {"driver_id": driver_id}
    ).fetchall()
    return [dict(r) for r in rows]


def insert_driving_style_features(
    conn: sqlite3.Connection,
    driver_id: int,
    session_id: str,
    style_data: dict[str, Any],
) -> None:
    features = style_data.get("features", {})
    conn.execute(Q.INSERT_DRIVING_STYLE_FEATURES, {
        "driver_id":                      driver_id,
        "session_id":                     session_id,
        "trail_braking_depth":            _safe_float(features.get("trail_braking_depth")),
        "brake_point_consistency":        _safe_float(features.get("brake_point_consistency")),
        "brake_pressure_buildup_rate":    _safe_float(features.get("brake_pressure_buildup_rate")),
        "apex_speed_ratio":               _safe_float(features.get("apex_speed_ratio")),
        "turn_in_aggressiveness":         _safe_float(features.get("turn_in_aggressiveness")),
        "throttle_onset_delay_m":         _safe_float(features.get("throttle_onset_delay_m")),
        "exit_acceleration_efficiency":   _safe_float(features.get("exit_acceleration_efficiency")),
        "line_variation_index":           _safe_float(features.get("line_variation_index")),
        "early_vs_late_stint_pace":       _safe_float(features.get("early_vs_late_stint_pace")),
        "smoothness_composite":           _safe_float(features.get("smoothness_composite")),
        "style_label":                    style_data.get("style_label"),
        "style_confidence":               _safe_float(style_data.get("style_confidence")),
        "strengths_json":                 json.dumps(style_data.get("strengths", [])),
        "weaknesses_json":                json.dumps(style_data.get("weaknesses", [])),
    })


def get_driving_style(
    conn: sqlite3.Connection,
    driver_id: int,
    session_id: str,
) -> Optional[dict]:
    row = conn.execute(
        Q.SELECT_DRIVING_STYLE, {"driver_id": driver_id, "session_id": session_id}
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["strengths"] = _parse_json_or_list(d.get("strengths_json") or "[]")
    d["weaknesses"] = _parse_json_or_list(d.get("weaknesses_json") or "[]")
    return d


def get_driver_style_history(
    conn: sqlite3.Connection,
    driver_id: int,
) -> list[dict]:
    rows = conn.execute(
        Q.SELECT_DRIVER_STYLE_HISTORY, {"driver_id": driver_id}
    ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["strengths"] = _parse_json_or_list(d.get("strengths_json") or "[]")
        d["weaknesses"] = _parse_json_or_list(d.get("weaknesses_json") or "[]")
        result.append(d)
    return result


def get_all_drivers(conn: sqlite3.Connection) -> list[dict]:
    """Get all drivers with session counts and optional profile info."""
    rows = conn.execute(Q.SELECT_ALL_DRIVERS).fetchall()
    drivers = []
    for r in rows:
        d = dict(r)
        # Try to get profile data
        profile = get_driver_profile(conn, d["driver_id"])
        if profile:
            d["has_profile"] = True
            d["style_label"] = None
            d["total_laps"] = profile.get("total_laps", 0)
            # Get latest style
            styles = get_driver_style_history(conn, d["driver_id"])
            if styles:
                d["style_label"] = styles[-1].get("style_label")
        else:
            d["has_profile"] = False
            d["style_label"] = None
            d["total_laps"] = 0
        drivers.append(d)
    return drivers


def delete_driver_cascade(conn: sqlite3.Connection, driver_id: int) -> dict:
    """Delete a driver and all dependent data. Returns counts of deleted rows."""
    counts = {}

    # Get all session IDs for this driver.
    session_rows = conn.execute(
        "SELECT session_id FROM sessions WHERE driver_id = ?", (driver_id,)
    ).fetchall()
    sids = [r["session_id"] for r in session_rows]

    # Delete session-level children.
    session_tables = [
        "corner_metrics", "gps_traces", "score_details", "condition_phases",
        "laps", "data_health", "session_tags", "session_sectors",
        "theoretical_data", "reference_lines", "stint_analysis",
        "session_annotations", "session_weather", "vehicle_setups",
        "what_if_scenarios", "condition_markers", "weekend_sessions",
    ]
    for table in session_tables:
        c = conn.execute(
            f"DELETE FROM {table} WHERE session_id IN "
            f"(SELECT session_id FROM sessions WHERE driver_id = ?)",
            (driver_id,),
        )
        counts[table] = c.rowcount

    # Sessions themselves.
    c = conn.execute("DELETE FROM sessions WHERE driver_id = ?", (driver_id,))
    counts["sessions"] = c.rowcount

    # Driver-level tables.
    for table in ["driver_badges", "driving_style_features", "driver_progression",
                   "driver_profiles", "development_plans"]:
        c = conn.execute(f"DELETE FROM {table} WHERE driver_id = ?", (driver_id,))
        counts[table] = c.rowcount

    # The driver itself.
    conn.execute("DELETE FROM drivers WHERE driver_id = ?", (driver_id,))
    counts["drivers"] = 1

    return counts


def compute_best_ever_relative(
    conn: sqlite3.Connection, driver_id: int
) -> dict:
    """Compute relative best-ever (% of track record) and records held."""
    driver = conn.execute(
        "SELECT driver_name FROM drivers WHERE driver_id = ?", (driver_id,)
    ).fetchone()
    driver_name = driver["driver_name"] if driver else ""

    # Per-track best times for this driver.
    track_bests = conn.execute(
        "SELECT s.track_id, t.track_name, MIN(s.best_lap_time_s) as best_time "
        "FROM sessions s JOIN tracks t ON s.track_id = t.track_id "
        "WHERE s.driver_id = ? AND s.best_lap_time_s IS NOT NULL "
        "GROUP BY s.track_id",
        (driver_id,),
    ).fetchall()

    best_pct = None
    best_track_name = None
    best_driver_time = None
    best_record_time = None
    best_absolute_s = None

    # Find absolute best.
    if track_bests:
        best_abs_row = min(track_bests, key=lambda r: r["best_time"])
        best_absolute_s = best_abs_row["best_time"]

    # Compute relative % for tracks with records.
    for tb in track_bests:
        record = conn.execute(
            "SELECT MIN(record_time_s) as record_time FROM track_records WHERE track_id = ?",
            (tb["track_id"],),
        ).fetchone()
        if record and record["record_time"] and record["record_time"] > 0:
            pct = (tb["best_time"] / record["record_time"]) * 100
            if best_pct is None or pct < best_pct:
                best_pct = round(pct, 2)
                best_track_name = tb["track_name"]
                best_driver_time = tb["best_time"]
                best_record_time = record["record_time"]

    # Records held by this driver.
    records_held = []
    held_rows = conn.execute(
        "SELECT tr.*, t.track_name FROM track_records tr "
        "JOIN tracks t ON tr.track_id = t.track_id "
        "WHERE tr.record_holder = ?",
        (driver_name,),
    ).fetchall()
    records_held = [dict(r) for r in held_rows]

    return {
        "best_pct": best_pct,
        "best_track_name": best_track_name,
        "best_driver_time": best_driver_time,
        "best_record_time": best_record_time,
        "best_absolute_s": best_absolute_s,
        "records_held": records_held,
    }
