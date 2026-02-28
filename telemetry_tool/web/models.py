"""
Data access layer — plain-SQL functions that read/write the SQLite DB.

No ORM.  Every function takes an explicit ``sqlite3.Connection`` so
callers (routes, pipeline, tests) control transaction scope.
"""

from __future__ import annotations

import json
import logging
import math
import sqlite3
from typing import Any, Optional

import numpy as np

from db import queries as Q

logger = logging.getLogger(__name__)


# ── helpers ──────────────────────────────────────────────────────
def _safe_float(v: Any) -> Optional[float]:
    """Convert to float; return None for NaN / None / missing."""
    if v is None:
        return None
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _json_dumps(obj: Any) -> Optional[str]:
    """Serialize to JSON string, or None."""
    if obj is None:
        return None
    try:
        return json.dumps(obj, default=str)
    except (TypeError, ValueError):
        return None


def _np_to_json(arr) -> str:
    """Convert a numpy array (or list) to a JSON list of floats."""
    if hasattr(arr, "tolist"):
        lst = arr.tolist()
    else:
        lst = list(arr)
    # Replace NaN/inf with null for JSON safety.
    clean = [x if (isinstance(x, (int, float)) and math.isfinite(x)) else None
             for x in lst]
    return json.dumps(clean)


# ── drivers ──────────────────────────────────────────────────────
def upsert_driver(conn: sqlite3.Connection, driver_name: str) -> int:
    """Insert driver if not exists; return driver_id."""
    conn.execute(Q.UPSERT_DRIVER, {"driver_name": driver_name})
    row = conn.execute(
        Q.SELECT_DRIVER_BY_NAME, {"driver_name": driver_name}
    ).fetchone()
    return row["driver_id"]


def _get_all_drivers_simple(conn: sqlite3.Connection) -> list[dict]:
    """Return all drivers with basic aggregate stats (lightweight)."""
    rows = conn.execute(Q.SELECT_ALL_DRIVERS).fetchall()
    return [dict(r) for r in rows]


# ── tracks ───────────────────────────────────────────────────────
def upsert_track(conn: sqlite3.Connection, track: dict) -> None:
    """Insert or update a track from a fingerprint dict."""
    fp = track.get("fingerprint", {})
    bbox = fp.get("bbox", {})
    conn.execute(Q.UPSERT_TRACK, {
        "track_id":     track["track_id"],
        "track_name":   track.get("track_name", track["track_id"]),
        "lap_length_m": fp.get("lap_length_m", 0.0),
        "bbox_lat_min": bbox.get("lat_min"),
        "bbox_lat_max": bbox.get("lat_max"),
        "bbox_lon_min": bbox.get("lon_min"),
        "bbox_lon_max": bbox.get("lon_max"),
        "start_lat":    fp.get("start_lat"),
        "start_lon":    fp.get("start_lon"),
        "sample_count": fp.get("sample_count"),
        "lap_count":    fp.get("lap_count"),
        "has_joker":    bool(track.get("has_joker", False)),
        "joker_distance_delta_m": track.get("joker_distance_delta_m"),
        "joker_time_delta_s":     track.get("joker_time_delta_s"),
    })


def get_all_tracks(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(Q.SELECT_ALL_TRACKS).fetchall()
    return [dict(r) for r in rows]


def rename_track(conn: sqlite3.Connection, track_id: str, new_name: str) -> None:
    """Rename a track in the tracks table and persist to tracks.json."""
    clean_name = new_name.strip()
    conn.execute(
        "UPDATE tracks SET track_name = :name, updated_at = datetime('now') "
        "WHERE track_id = :tid",
        {"name": clean_name, "tid": track_id},
    )
    # Persist to tracks.json so the rename survives server restarts.
    _update_tracks_json(track_id, clean_name)


def _update_tracks_json(track_id: str, new_name: str) -> None:
    """Update the track name in the file-based tracks.json."""
    try:
        from track_detection import load_track_database, save_track_database
        db = load_track_database()
        for entry in db:
            if entry.get("track_id") == track_id:
                entry["track_name"] = new_name
                break
        save_track_database(db)
    except Exception as exc:
        logger.warning("Could not update tracks.json for %s: %s", track_id, exc)


def merge_duplicate_tracks(conn: sqlite3.Connection) -> int:
    """
    Merge duplicate 'Unknown Track' entries that share overlapping GPS.

    Groups Unknown Tracks by bbox overlap (centroid within 500m).
    For each group, keeps the first entry and reassigns all sessions
    from duplicate entries to the kept entry, then deletes duplicates.

    Returns the number of tracks merged away.
    """
    import math

    unknowns = conn.execute(
        "SELECT track_id, track_name, start_lat, start_lon, "
        "       bbox_lat_min, bbox_lat_max, bbox_lon_min, bbox_lon_max, "
        "       lap_length_m "
        "FROM tracks WHERE track_name LIKE '%nknown%' OR track_name LIKE '%unknown%' "
        "ORDER BY created_at"
    ).fetchall()
    unknowns = [dict(r) for r in unknowns]

    if len(unknowns) < 2:
        return 0

    def _haversine(lat1, lon1, lat2, lon2):
        if any(v is None for v in (lat1, lon1, lat2, lon2)):
            return float("inf")
        R = 6371000.0
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (math.sin(dlat / 2) ** 2 +
             math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
             math.sin(dlon / 2) ** 2)
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    def _centroid(t):
        """Get centroid from start coords, or fallback to bbox center."""
        lat = t.get("start_lat")
        lon = t.get("start_lon")
        if lat is not None and lon is not None:
            return lat, lon
        # Fallback to bbox centroid
        lat_min = t.get("bbox_lat_min")
        lat_max = t.get("bbox_lat_max")
        lon_min = t.get("bbox_lon_min")
        lon_max = t.get("bbox_lon_max")
        if all(v is not None for v in (lat_min, lat_max, lon_min, lon_max)):
            return (lat_min + lat_max) / 2, (lon_min + lon_max) / 2
        return None, None

    # Group by proximity (centroid within 500m) or all-null coords
    groups: list[list[dict]] = []
    assigned = set()
    null_group: list[dict] = []  # tracks with no GPS at all
    for i, t in enumerate(unknowns):
        if i in assigned:
            continue
        lat, lon = _centroid(t)
        if lat is None:
            null_group.append(t)
            assigned.add(i)
            continue
        group = [t]
        assigned.add(i)
        for j, other in enumerate(unknowns):
            if j in assigned:
                continue
            olat, olon = _centroid(other)
            if olat is None:
                continue
            dist = _haversine(lat, lon, olat, olon)
            if dist < 500:
                group.append(other)
                assigned.add(j)
        if len(group) > 1:
            groups.append(group)
    # Group all no-GPS unknowns together
    if len(null_group) > 1:
        groups.append(null_group)

    merged = 0
    for group in groups:
        keep = group[0]
        for dup in group[1:]:
            # Reassign sessions from dup -> keep
            conn.execute(
                "UPDATE sessions SET track_id = :keep WHERE track_id = :dup",
                {"keep": keep["track_id"], "dup": dup["track_id"]},
            )
            # Delete the duplicate track entry
            conn.execute(
                "DELETE FROM tracks WHERE track_id = :tid",
                {"tid": dup["track_id"]},
            )
            merged += 1

    return merged


def get_track_by_id(conn: sqlite3.Connection, track_id: str) -> Optional[dict]:
    row = conn.execute(
        Q.SELECT_TRACK_BY_ID, {"track_id": track_id}
    ).fetchone()
    return dict(row) if row else None


def sync_tracks_from_json(conn: sqlite3.Connection) -> int:
    """
    Import tracks from the file-based tracks.json into SQLite.

    Returns the number of tracks synced.
    """
    try:
        from track_detection import load_track_database
        db = load_track_database()
    except (ImportError, Exception) as exc:
        logger.debug("Could not load tracks.json: %s", exc)
        return 0

    count = 0
    for entry in db:
        upsert_track(conn, entry)
        count += 1
    conn.commit()
    logger.info("Synced %d tracks from tracks.json to SQLite.", count)
    return count


# ── sessions ─────────────────────────────────────────────────────
def upsert_session(
    conn: sqlite3.Connection,
    summary: dict[str, Any],
    driver_id: int,
) -> str:
    """Persist a pipeline summary to the sessions table."""
    meta = summary.get("session_meta", {})
    score = summary.get("score_result") or {}
    ctx = summary.get("session_context")

    session_id = ""
    if ctx and hasattr(ctx, "session_id"):
        session_id = ctx.session_id
    elif meta.get("session_id"):
        session_id = meta["session_id"]
    else:
        # Fallback: generate from CSV filename + timestamp.
        import datetime
        csv_name = str(summary.get("csv_path", "unknown"))
        session_id = f"{datetime.datetime.now():%Y-%m-%d_%H%M%S}"

    # Compute basic lap stats — EXCLUDING flagged laps (incomplete,
    # invalid, anomalous, deviated) so best/mean reflect valid data only.
    lap_times = summary.get("lap_times") or []
    resampled = summary.get("resampled_laps") or {}
    sorted_lap_keys = sorted(resampled.keys()) if resampled else list(range(len(lap_times)))

    # Gather all exclusion sets from pipeline analysis.
    _excluded: set = set()
    for _key in ("incomplete_lap_analysis", "invalid_lap_analysis",
                 "anomalous_lap_analysis", "line_deviation_analysis"):
        _analysis = summary.get(_key) or {}
        for _sub in ("incomplete_laps", "invalid_laps", "flagged_laps",
                     "dist_flagged", "time_flagged", "deviated_laps"):
            _s = _analysis.get(_sub)
            if _s:
                _excluded.update(_s)
    # Also check trim_report for outlaps/inlaps.
    _trim = summary.get("trim_report") or {}
    _outlap_a = _trim.get("outlap_analysis") or {}
    for _sub in ("outlap_numbers", "inlap_numbers", "flagged_only"):
        _s = _outlap_a.get(_sub)
        if _s:
            _excluded.update(_s)

    # Exclude the confirmed joker lap from stats.
    _joker_lap = summary.get("joker_lap_number")
    if _joker_lap is not None:
        _excluded.add(_joker_lap)

    valid_times = []
    for i, t in enumerate(lap_times):
        if not t or not math.isfinite(t) or t <= 0:
            continue
        lap_key = sorted_lap_keys[i] if i < len(sorted_lap_keys) else i
        if lap_key in _excluded:
            continue
        valid_times.append(t)

    n_laps = len(valid_times)
    best_s = min(valid_times) if valid_times else None
    mean_s = sum(valid_times) / n_laps if n_laps > 0 else None

    # Weather.
    weather_json = None
    weather = meta.get("weather")
    if weather is not None:
        if hasattr(weather, "__dict__"):
            weather_json = _json_dumps(vars(weather))
        else:
            weather_json = _json_dumps(weather)

    # HTML report path.
    html_path = summary.get("html_path")
    if html_path:
        html_path = str(html_path)

    theo_metrics = summary.get("theoretical_metrics") or {}

    conn.execute(Q.INSERT_SESSION, {
        "session_id":        session_id,
        "csv_filename":      str(summary.get("csv_path", "")),
        "driver_id":         driver_id,
        "track_id":          summary.get("track_id"),
        "session_type":      meta.get("session_type", "practice"),
        "track_state":       meta.get("track_state", "dry"),
        "session_date":      meta.get("session_date") or meta.get("date") or session_id[:10],
        "n_laps":            n_laps,
        "best_lap_time_s":   _safe_float(best_s),
        "mean_lap_time_s":   _safe_float(mean_s),
        "total_score":       _safe_float(score.get("total_score")),
        "grade":             score.get("grade"),
        "weather_json":      weather_json,
        "notes":             meta.get("notes"),
        "html_report_path":  html_path,
        "simulation_method": theo_metrics.get("simulation_method"),
        "joker_lap_number":  _joker_lap,
    })
    return session_id


def get_sessions(
    conn: sqlite3.Connection,
    limit: int = 25,
    offset: int = 0,
) -> list[dict]:
    rows = conn.execute(
        Q.SELECT_SESSIONS, {"limit": limit, "offset": offset}
    ).fetchall()
    return [dict(r) for r in rows]


def get_session_by_id(
    conn: sqlite3.Connection,
    session_id: str,
) -> Optional[dict]:
    row = conn.execute(
        Q.SELECT_SESSION_BY_ID, {"session_id": session_id}
    ).fetchone()
    return dict(row) if row else None


def update_session_field(
    conn: sqlite3.Connection,
    session_id: str,
    field_name: str,
    value: Any,
) -> None:
    """Update a single editable field on a session."""
    allowed = {
        "session_date", "driver_id", "track_id",
        "session_type", "track_state", "notes",
    }
    if field_name not in allowed:
        raise ValueError(f"Field {field_name!r} not editable on sessions.")
    # driver_id should be int; track_id stays as text.
    if field_name == "driver_id" and value is not None:
        value = int(value)
    sql = f"UPDATE sessions SET {field_name} = :value WHERE session_id = :session_id"
    conn.execute(sql, {"session_id": session_id, "value": value or None})


def count_sessions(conn: sqlite3.Connection) -> int:
    row = conn.execute(Q.COUNT_SESSIONS).fetchone()
    return row[0] if row else 0


def get_dashboard_stats(conn: sqlite3.Connection) -> dict:
    row = conn.execute(Q.DASHBOARD_STATS).fetchone()
    return dict(row) if row else {}


# ── laps ─────────────────────────────────────────────────────────
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
        is_valid = 1
        invalid_reason = None
        is_joker = 0

        if joker_lap_number is not None and lap_num == joker_lap_number:
            is_joker = 1
            is_valid = 0
            invalid_reason = "Joker lap"
        elif lap_num in all_dist_flagged:
            is_valid = 0
            if stint_boundary_laps and _near_stint_boundary(lap_num):
                invalid_reason = "Pitted lap"
            else:
                invalid_reason = dist_labels[lap_num]
        elif lap_num in anomalous_time:
            is_valid = 0
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
            "is_best":          1 if lap_num == best_key else 0,
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


# ── GPS traces ───────────────────────────────────────────────────
def insert_gps_traces(
    conn: sqlite3.Connection,
    session_id: str,
    summary: dict[str, Any],
) -> int:
    """
    Extract GPS coordinates from resampled_laps and persist.

    Looks for columns like 'Latitude (deg)', 'Longitude (deg)',
    'distance_m', and speed columns in the resampled DataFrames.
    """
    resampled = summary.get("resampled_laps") or {}
    count = 0

    for lap_num, df in resampled.items():
        if df is None or len(df) == 0:
            continue

        # Find GPS columns (RaceChrono naming).
        lat_col = None
        lon_col = None
        dist_col = None
        spd_col = None

        for c in df.columns:
            cl = c.lower()
            if "latitude" in cl and "deg" in cl:
                lat_col = c
            elif "longitude" in cl and "deg" in cl:
                lon_col = c
            elif cl in ("distance_m", "distance"):
                dist_col = c
            elif cl in ("speed_mps", "speed (m/s)", "speed"):
                spd_col = c

        # Must have at least lat + lon.
        if lat_col is None or lon_col is None:
            continue

        lats = df[lat_col].values
        lons = df[lon_col].values

        # Distance: use column or synthesize from index/row number.
        if dist_col and dist_col in df.columns:
            dists = df[dist_col].values
        elif hasattr(df.index, "name") and df.index.name == "distance_m":
            dists = df.index.values
        else:
            dists = np.arange(len(df), dtype=float)

        # Speed.
        if spd_col and spd_col in df.columns:
            speeds = df[spd_col].values
        else:
            # Try to find any speed column.
            for c in df.columns:
                if "speed" in c.lower():
                    speeds = df[c].values
                    break
            else:
                speeds = np.zeros(len(df))

        # Acceleration columns for G-G diagram.
        accel_lat_col = None
        accel_long_col = None
        for c in df.columns:
            cl = c.lower()
            if accel_lat_col is None and (
                "accel_lat" in cl
                or ("lateral" in cl and "accel" in cl)
                or cl == "lateral acceleration (g) *calc"
            ):
                accel_lat_col = c
            if accel_long_col is None and (
                "accel_long" in cl
                or ("longitudinal" in cl and "accel" in cl)
                or cl == "acceleration (m/s²)"
            ):
                accel_long_col = c

        accel_lat_json = _np_to_json(df[accel_lat_col].values) if accel_lat_col else None
        accel_long_json = _np_to_json(df[accel_long_col].values) if accel_long_col else None

        conn.execute(Q.INSERT_GPS_TRACE, {
            "session_id":      session_id,
            "lap_number":      int(lap_num),
            "latitudes_json":  _np_to_json(lats),
            "longitudes_json": _np_to_json(lons),
            "distances_json":  _np_to_json(dists),
            "speeds_json":     _np_to_json(speeds),
            "accel_lat_json":  accel_lat_json,
            "accel_long_json": accel_long_json,
        })
        count += 1

    return count


def get_gps_trace(
    conn: sqlite3.Connection,
    session_id: str,
    lap_number: int,
) -> Optional[dict]:
    row = conn.execute(
        Q.SELECT_GPS_TRACE,
        {"session_id": session_id, "lap_number": lap_number},
    ).fetchone()
    if row is None:
        return None
    result = {
        "latitudes":  json.loads(row["latitudes_json"]),
        "longitudes": json.loads(row["longitudes_json"]),
        "distances":  json.loads(row["distances_json"]),
        "speeds":     json.loads(row["speeds_json"]),
    }
    if row["accel_lat_json"]:
        result["accel_lat"] = json.loads(row["accel_lat_json"])
    if row["accel_long_json"]:
        result["accel_long"] = json.loads(row["accel_long_json"])
    return result


def get_gps_lap_numbers(
    conn: sqlite3.Connection,
    session_id: str,
) -> list[int]:
    rows = conn.execute(
        Q.SELECT_GPS_LAPS_FOR_SESSION, {"session_id": session_id}
    ).fetchall()
    return [r["lap_number"] for r in rows]


# ── score details ────────────────────────────────────────────────
def insert_score_details(
    conn: sqlite3.Connection,
    session_id: str,
    summary: dict[str, Any],
) -> None:
    score = summary.get("score_result")
    if not score:
        return

    subs = score.get("sub_scores", {})

    def _sub(key: str, field: str):
        return _safe_float(subs.get(key, {}).get(field))

    conn.execute(Q.INSERT_SCORE_DETAILS, {
        "session_id":        session_id,
        "pace_score":        _sub("pace", "score"),
        "pace_max":          _sub("pace", "max"),
        "consistency_score": _sub("consistency", "score"),
        "consistency_max":   _sub("consistency", "max"),
        "execution_score":   _sub("execution", "score"),
        "execution_max":     _sub("execution", "max"),
        "robustness_score":  _sub("robustness", "score"),
        "robustness_max":    _sub("robustness", "max"),
        "strengths_json":    _json_dumps(score.get("strengths")),
        "weaknesses_json":   _json_dumps(score.get("weaknesses")),
        "adaptation_score":  _safe_float(
            subs.get("adaptation", {}).get("score")
        ),
    })


def get_score_details(
    conn: sqlite3.Connection,
    session_id: str,
) -> Optional[dict]:
    row = conn.execute(
        Q.SELECT_SCORE_DETAILS, {"session_id": session_id}
    ).fetchone()
    if row is None:
        return None
    d = dict(row)
    # Parse JSON fields.
    for key in ("strengths_json", "weaknesses_json"):
        if d.get(key):
            try:
                d[key.replace("_json", "")] = json.loads(d[key])
            except (json.JSONDecodeError, TypeError):
                d[key.replace("_json", "")] = []
    return d


# ── condition phases ─────────────────────────────────────────────
def insert_condition_phases(
    conn: sqlite3.Connection,
    session_id: str,
    summary: dict[str, Any],
) -> int:
    """Insert condition phase rows from pipeline summary."""
    phases_df = summary.get("phases_df")
    if phases_df is None or (hasattr(phases_df, "empty") and phases_df.empty):
        return 0

    count = 0
    if hasattr(phases_df, "iterrows"):
        for _, row in phases_df.iterrows():
            conn.execute(Q.INSERT_CONDITION_PHASE, {
                "session_id":    session_id,
                "phase_id":      int(row.get("phase_id", count)),
                "lap_start":     int(row.get("lap_start", 0)),
                "lap_end":       int(row.get("lap_end", 0)),
                "label":         row.get("phase_track_state")
                                 or row.get("label"),
                "confidence":    _safe_float(row.get("confidence")),
                "median_pace_s": _safe_float(row.get("median_s")
                                             or row.get("median_pace_s")),
            })
            count += 1
    return count


def get_condition_phases(
    conn: sqlite3.Connection,
    session_id: str,
) -> list[dict]:
    rows = conn.execute(
        Q.SELECT_CONDITION_PHASES, {"session_id": session_id}
    ).fetchall()
    return [dict(r) for r in rows]


# ── weekends ────────────────────────────────────────────────────

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


# ── track records ───────────────────────────────────────────────

def upsert_track_record(
    conn: sqlite3.Connection,
    track_id: str,
    record_time_s: float,
    record_holder: Optional[str] = None,
    record_date: Optional[str] = None,
    vehicle_class: Optional[str] = None,
    source: Optional[str] = None,
) -> None:
    conn.execute(Q.UPSERT_TRACK_RECORD, {
        "track_id":       track_id,
        "record_time_s":  record_time_s,
        "record_holder":  record_holder,
        "record_date":    record_date,
        "vehicle_class":  vehicle_class or "default",
        "source":         source,
    })


def delete_track_record(conn: sqlite3.Connection, record_id: int) -> None:
    conn.execute(Q.DELETE_TRACK_RECORD, {"id": record_id})


def get_track_records(
    conn: sqlite3.Connection,
    track_id: str,
) -> list[dict]:
    rows = conn.execute(
        Q.SELECT_TRACK_RECORDS, {"track_id": track_id}
    ).fetchall()
    return [dict(r) for r in rows]


# ── condition markers ───────────────────────────────────────────

def insert_condition_marker(
    conn: sqlite3.Connection,
    session_id: str,
    lap_number: int,
    new_state: str,
    notes: Optional[str] = None,
) -> None:
    conn.execute(Q.INSERT_CONDITION_MARKER, {
        "session_id":  session_id,
        "lap_number":  lap_number,
        "new_state":   new_state,
        "notes":       notes,
    })


def insert_condition_markers(
    conn: sqlite3.Connection,
    session_id: str,
    markers: "dict[int, str]",
) -> None:
    """Bulk-insert manual condition markers from ``{lap: state}`` mapping."""
    for lap_number, new_state in markers.items():
        conn.execute(Q.INSERT_CONDITION_MARKER, {
            "session_id":  session_id,
            "lap_number":  int(lap_number),
            "new_state":   str(new_state),
            "notes":       "manual --condition-change",
        })


def get_condition_markers(
    conn: sqlite3.Connection,
    session_id: str,
) -> list[dict]:
    rows = conn.execute(
        Q.SELECT_CONDITION_MARKERS, {"session_id": session_id}
    ).fetchall()
    return [dict(r) for r in rows]


# ── Phase 3: Driver profiles ─────────────────────────────────────

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


# ── Phase 3: Driver progression ──────────────────────────────────

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


# ── Phase 3: Driving style features ─────────────────────────────

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
    d["strengths"] = json.loads(d.get("strengths_json") or "[]")
    d["weaknesses"] = json.loads(d.get("weaknesses_json") or "[]")
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
        d["strengths"] = json.loads(d.get("strengths_json") or "[]")
        d["weaknesses"] = json.loads(d.get("weaknesses_json") or "[]")
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


# ── Phase 4: Theoretical data ────────────────────────────────────

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
    if d.get("speed_profile_json"):
        d["speeds"] = json.loads(d["speed_profile_json"])
    if d.get("distance_json"):
        d["distances"] = json.loads(d["distance_json"])
    if d.get("metrics_json"):
        d["metrics"] = json.loads(d["metrics_json"])
    if d.get("corner_coaching_json"):
        d["corner_coaching"] = json.loads(d["corner_coaching_json"])
    if d.get("delta_map_json"):
        d["delta_map_summary"] = json.loads(d["delta_map_json"])
    if d.get("session_scalars_json"):
        d["session_scalars"] = json.loads(d["session_scalars_json"])
    return d


# ── Phase 4: Reference lines ────────────────────────────────────

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
        "latitudes":  json.loads(row["latitudes_json"]),
        "longitudes": json.loads(row["longitudes_json"]),
        "distances":  json.loads(row["distances_json"]),
        "speeds":     json.loads(row["speeds_json"]) if row["speeds_json"] else None,
    }


def auto_set_track_reference(
    conn: sqlite3.Connection,
    session_id: str,
) -> Optional[str]:
    """Auto-assign this session as the track's dry/wet reference line.

    Called after a reference line is successfully persisted. If the track
    does not already have a reference for this session's condition
    (dry or wet), adopt this session's reference line.

    Returns the condition column set ('dry'/'wet') or None if no change.
    """
    row = conn.execute(
        "SELECT s.track_id, s.track_state "
        "FROM sessions s WHERE s.session_id = :sid",
        {"sid": session_id},
    ).fetchone()
    if not row:
        return None

    track_id = row["track_id"]
    track_state = (row["track_state"] or "dry").lower().strip()

    if not track_id:
        return None

    # Map condition to column: 'dry' for dry/damp, 'wet' for wet/greasy/mixed
    if track_state in ("wet", "greasy", "mixed"):
        col = "wet_ref_session_id"
        condition = "wet"
    else:
        col = "dry_ref_session_id"
        condition = "dry"

    # Check if the track already has a reference for this condition.
    track = conn.execute(
        f"SELECT {col} FROM tracks WHERE track_id = :tid",
        {"tid": track_id},
    ).fetchone()
    if track is None:
        return None

    if track[col] is not None:
        return None  # Already has a reference for this condition

    # Set this session as the track's condition reference.
    conn.execute(
        f"UPDATE tracks SET {col} = :sid, updated_at = datetime('now') "
        "WHERE track_id = :tid",
        {"sid": session_id, "tid": track_id},
    )
    return condition


# ------------------------------------------------------------------
# Session sectors (Phase 5 — visualization)
# ------------------------------------------------------------------

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


# ── corner metrics ───────────────────────────────────────────────
def insert_corner_metrics(
    conn: sqlite3.Connection,
    session_id: str,
    summary: dict[str, Any],
) -> int:
    """
    Extract per-lap corner metrics from the pipeline summary and persist them.

    The pipeline must populate ``summary["per_lap_corner_metrics"]`` as a
    list of dicts with keys matching the ``corner_metrics`` table columns.
    """
    metrics = summary.get("per_lap_corner_metrics")
    if not metrics:
        return 0

    count = 0
    for row in metrics:
        conn.execute(Q.INSERT_CORNER_METRIC, {
            "session_id":      session_id,
            "lap_number":      int(row.get("lap_number", 0)),
            "corner_id":       int(row.get("corner_id", 0)),
            "brake_point_m":   _safe_float(row.get("brake_point_m")
                                           or row.get("braking_point_actual_m")),
            "brake_intensity": _safe_float(row.get("brake_intensity")),
            "entry_speed_mps": _safe_float(row.get("entry_speed_mps")
                                           or row.get("actual_entry_speed_mps")),
            "apex_speed_mps":  _safe_float(row.get("apex_speed_mps")
                                           or row.get("actual_apex_speed_mps")),
            "exit_speed_mps":  _safe_float(row.get("exit_speed_mps")
                                           or row.get("actual_exit_speed_mps")),
            "throttle_onset_m": _safe_float(row.get("throttle_onset_m")),
            "exit_accel_mps2": _safe_float(row.get("exit_accel_mps2")),
            "grip_utilization": _safe_float(row.get("grip_utilization")
                                            or row.get("grip_utilisation_pct")),
            "time_loss_ms":    _safe_float(row.get("time_loss_ms")),
            "coaching_hint":   row.get("coaching_hint", ""),
        })
        count += 1

    return count


# ── Stint Analysis ───────────────────────────────────────────────

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


# ── track start/finish editing ────────────────────────────────
def update_track_start_finish(
    conn: sqlite3.Connection, track_id: str, lat: float, lon: float
) -> None:
    """Update start/finish position; preserve originals on first edit."""
    row = conn.execute(
        "SELECT start_lat, start_lon, original_start_lat FROM tracks WHERE track_id = ?",
        (track_id,),
    ).fetchone()
    if row is None:
        return
    # On first edit, save originals.
    if row["original_start_lat"] is None:
        conn.execute(
            "UPDATE tracks SET original_start_lat = start_lat, "
            "original_start_lon = start_lon WHERE track_id = ?",
            (track_id,),
        )
    conn.execute(
        "UPDATE tracks SET start_lat = ?, start_lon = ?, "
        "updated_at = datetime('now') WHERE track_id = ?",
        (lat, lon, track_id),
    )


def reset_track_start_finish(conn: sqlite3.Connection, track_id: str) -> None:
    """Reset start/finish to auto-detected originals."""
    conn.execute(
        "UPDATE tracks SET start_lat = original_start_lat, "
        "start_lon = original_start_lon WHERE track_id = ? "
        "AND original_start_lat IS NOT NULL",
        (track_id,),
    )


# ── track sectors ─────────────────────────────────────────────
def get_track_sectors(conn: sqlite3.Connection, track_id: str) -> list[dict]:
    """Return sectors for a track ordered by sector_index."""
    rows = conn.execute(
        "SELECT * FROM track_sectors WHERE track_id = ? ORDER BY sector_index",
        (track_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def upsert_track_sector(
    conn: sqlite3.Connection, track_id: str, lat: float, lon: float,
    distance_m: Optional[float] = None,
) -> int:
    """Add a sector point and auto-assign next index. Returns new sector ID."""
    next_idx = conn.execute(
        "SELECT COALESCE(MAX(sector_index), -1) + 1 FROM track_sectors WHERE track_id = ?",
        (track_id,),
    ).fetchone()[0]
    label = f"S{next_idx + 1}"
    cur = conn.execute(
        "INSERT INTO track_sectors (track_id, sector_index, latitude, longitude, distance_m, label) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (track_id, next_idx, lat, lon, distance_m, label),
    )
    return cur.lastrowid


def delete_track_sector(conn: sqlite3.Connection, track_id: str, sector_id: int) -> None:
    """Delete a sector and re-index remaining sectors."""
    conn.execute("DELETE FROM track_sectors WHERE id = ? AND track_id = ?", (sector_id, track_id))
    # Re-index remaining sectors.
    rows = conn.execute(
        "SELECT id FROM track_sectors WHERE track_id = ? ORDER BY sector_index",
        (track_id,),
    ).fetchall()
    for i, r in enumerate(rows):
        conn.execute(
            "UPDATE track_sectors SET sector_index = ?, label = ? WHERE id = ?",
            (i, f"S{i + 1}", r["id"]),
        )


# ── track deletion ────────────────────────────────────────────
def delete_track_cascade(conn: sqlite3.Connection, track_id: str) -> dict:
    """Delete a track and all dependent data. Returns counts of deleted rows."""
    counts = {}
    # Order matters: delete children before parent.
    for table, col in [
        ("corner_metrics", "session_id"),
        ("corner_best_practices", "track_id"),
        ("gps_traces", "session_id"),
        ("score_details", "session_id"),
        ("condition_phases", "session_id"),
        ("laps", "session_id"),
        ("data_health", "session_id"),
        ("session_tags", "session_id"),
        ("session_sectors", "session_id"),
        ("theoretical_data", "session_id"),
        ("reference_lines", "session_id"),
        ("stint_analysis", "session_id"),
        ("session_annotations", "session_id"),
        ("session_weather", "session_id"),
        ("vehicle_setups", "session_id"),
        ("what_if_scenarios", "session_id"),
        ("driving_style_features", "session_id"),
        ("driver_progression", "session_id"),
        ("weekend_sessions", "session_id"),
        ("condition_markers", "session_id"),
    ]:
        if col == "track_id":
            c = conn.execute(f"DELETE FROM {table} WHERE track_id = ?", (track_id,))
        else:
            c = conn.execute(
                f"DELETE FROM {table} WHERE {col} IN "
                f"(SELECT session_id FROM sessions WHERE track_id = ?)",
                (track_id,),
            )
        counts[table] = c.rowcount

    # Sessions themselves.
    c = conn.execute("DELETE FROM sessions WHERE track_id = ?", (track_id,))
    counts["sessions"] = c.rowcount

    # Track-level tables.
    c = conn.execute("DELETE FROM track_key_corners WHERE track_id = ?", (track_id,))
    counts["track_key_corners"] = c.rowcount
    c = conn.execute("DELETE FROM track_sectors WHERE track_id = ?", (track_id,))
    counts["track_sectors"] = c.rowcount
    c = conn.execute("DELETE FROM track_records WHERE track_id = ?", (track_id,))
    counts["track_records"] = c.rowcount

    # The track itself.
    conn.execute("DELETE FROM tracks WHERE track_id = ?", (track_id,))
    counts["tracks"] = 1

    return counts


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


# ── kart CRUD ─────────────────────────────────────────────────
def create_kart(
    conn: sqlite3.Connection,
    kart_name: str,
    predefined_kart_id: Optional[int] = None,
    manufacturer: Optional[str] = None,
    model: Optional[str] = None,
    engine: Optional[str] = None,
    power_hp: Optional[float] = None,
    kart_weight_kg: Optional[float] = None,
    notes: Optional[str] = None,
) -> int:
    """Create a kart. If predefined_kart_id is set, auto-fill specs from reference."""
    if predefined_kart_id is not None:
        ref = conn.execute(
            "SELECT manufacturer, model, engine, power_hp, kart_weight_kg "
            "FROM predefined_karts WHERE predefined_kart_id = ?",
            (predefined_kart_id,),
        ).fetchone()
        if ref:
            manufacturer = manufacturer or ref["manufacturer"]
            model = model or ref["model"]
            engine = engine or ref["engine"]
            power_hp = power_hp if power_hp is not None else ref["power_hp"]
            kart_weight_kg = kart_weight_kg if kart_weight_kg is not None else ref["kart_weight_kg"]

    import os
    if os.environ.get("USE_PG", "0") == "1":
        row = conn.execute(
            "INSERT INTO karts (kart_name, predefined_kart_id, manufacturer, model, "
            "engine, power_hp, kart_weight_kg, notes) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
            "RETURNING kart_id",
            (kart_name, predefined_kart_id, manufacturer, model, engine,
             power_hp, kart_weight_kg, notes),
        ).fetchone()
        return row["kart_id"] if row else 0
    else:
        cur = conn.execute(
            "INSERT INTO karts (kart_name, predefined_kart_id, manufacturer, model, "
            "engine, power_hp, kart_weight_kg, notes) VALUES (?,?,?,?,?,?,?,?)",
            (kart_name, predefined_kart_id, manufacturer, model, engine,
             power_hp, kart_weight_kg, notes),
        )
        return cur.lastrowid


def get_kart_by_id(conn: sqlite3.Connection, kart_id: int) -> Optional[dict]:
    row = conn.execute("SELECT * FROM karts WHERE kart_id = ?", (kart_id,)).fetchone()
    return dict(row) if row else None


def get_all_karts(conn) -> list[dict]:
    import os
    if os.environ.get("USE_PG", "0") == "1":
        # PG uses kart_sessions junction table; explicit GROUP BY columns
        rows = conn.execute(
            "SELECT k.kart_id, k.kart_name, k.predefined_kart_id, k.manufacturer, "
            "k.model, k.engine, k.power_hp, k.kart_weight_kg, k.notes, k.created_at, "
            "COUNT(ks.session_id) as session_count "
            "FROM karts k LEFT JOIN kart_sessions ks ON k.kart_id = ks.kart_id "
            "GROUP BY k.kart_id, k.kart_name, k.predefined_kart_id, k.manufacturer, "
            "k.model, k.engine, k.power_hp, k.kart_weight_kg, k.notes, k.created_at "
            "ORDER BY k.kart_name",
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT k.*, COUNT(s.session_id) as session_count "
            "FROM karts k LEFT JOIN sessions s ON k.kart_id = s.kart_id "
            "GROUP BY k.kart_id ORDER BY k.kart_name",
        ).fetchall()
    return [dict(r) for r in rows]


def update_kart(conn: sqlite3.Connection, kart_id: int, data: dict) -> None:
    allowed = {"kart_name", "manufacturer", "model", "engine", "power_hp", "kart_weight_kg", "notes"}
    sets = []
    vals = []
    for field, value in data.items():
        if field in allowed:
            sets.append(f"{field} = ?")
            vals.append(value)
    if sets:
        vals.append(kart_id)
        conn.execute(f"UPDATE karts SET {', '.join(sets)} WHERE kart_id = ?", vals)


def delete_kart(conn: sqlite3.Connection, kart_id: int) -> None:
    """Delete a kart and unlink any sessions."""
    conn.execute("UPDATE sessions SET kart_id = NULL WHERE kart_id = ?", (kart_id,))
    conn.execute("DELETE FROM karts WHERE kart_id = ?", (kart_id,))


def get_predefined_karts_grouped(conn: sqlite3.Connection) -> dict:
    """Return predefined karts grouped by segment."""
    rows = conn.execute(
        "SELECT * FROM predefined_karts ORDER BY segment, manufacturer, model"
    ).fetchall()
    segments: dict[str, list] = {}
    for r in rows:
        d = dict(r)
        seg = d.get("segment") or "Other"
        segments.setdefault(seg, []).append(d)
    return segments


def link_session_kart(conn: sqlite3.Connection, session_id: str, kart_id: Optional[int]) -> None:
    """Link or unlink a session to a kart."""
    conn.execute(
        "UPDATE sessions SET kart_id = ? WHERE session_id = ?",
        (kart_id, session_id),
    )


# ── driver deletion ──────────────────────────────────────────
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
    for table in ["driving_style_features", "driver_progression", "driver_profiles",
                   "development_plans"]:
        c = conn.execute(f"DELETE FROM {table} WHERE driver_id = ?", (driver_id,))
        counts[table] = c.rowcount

    # The driver itself.
    conn.execute("DELETE FROM drivers WHERE driver_id = ?", (driver_id,))
    counts["drivers"] = 1

    return counts


# ── best-ever relative performance ─────────────────────────────

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


# ── weekend session reordering ─────────────────────────────────

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


# ── track creation from predefined ────────────────────────────

def create_track_from_predefined(
    conn: sqlite3.Connection, predefined_track_id: int, custom_name: str | None = None,
) -> str:
    """Create a tracks entry linked to a predefined track. Returns track_id."""
    import uuid
    ref = conn.execute(
        "SELECT * FROM predefined_tracks WHERE predefined_track_id = ?",
        (predefined_track_id,),
    ).fetchone()
    if ref is None:
        raise ValueError("Predefined track not found")
    ref = dict(ref)

    track_id = str(uuid.uuid4())[:12]
    name = custom_name or f"{ref['track_name']} — {ref['layout_name'] or 'Default'}"
    length = ref.get("layout_length_m")

    conn.execute(
        "INSERT INTO tracks (track_id, track_name, lap_length_m, predefined_track_id) "
        "VALUES (?, ?, ?, ?)",
        (track_id, name, length or 0, predefined_track_id),
    )
    return track_id
