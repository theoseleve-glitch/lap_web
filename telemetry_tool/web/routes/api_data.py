"""JSON API routes for frontend JavaScript (GPS traces, speed data)."""

from __future__ import annotations

import json
import logging
import math
import os
from datetime import datetime
from pathlib import Path

import numpy as np
from flask import Blueprint, abort, current_app, jsonify, request
from werkzeug.utils import secure_filename

from web.db import get_db_connection
from web.models import (
    delete_session_sector,
    get_gps_trace,
    get_gps_lap_numbers,
    get_laps_for_session,
    get_reference_line,
    get_session_by_id,
    get_session_sectors,
    get_theoretical_data,
    get_track_records,
    reindex_session_sectors,
    upsert_session_sector,
)

logger = logging.getLogger(__name__)

bp = Blueprint("api", __name__, url_prefix="/api")


# ---------------------------------------------------------------------------
# Deprecation header helper — signals clients to migrate to /api/v1/
# ---------------------------------------------------------------------------

def _deprecation_headers(v1_path: str) -> dict[str, str]:
    """Build standard deprecation headers pointing to the v1 successor.

    Returns a dict with three headers:
    - ``Deprecation: true``
    - ``Sunset: 2026-09-01``
    - ``Link: <v1_path>; rel="successor-version"``
    """
    return {
        "Deprecation": "true",
        "Sunset": "2026-09-01",
        "Link": f'<{v1_path}>; rel="successor-version"',
    }


def _with_deprecation(response, v1_path: str):
    """Attach deprecation headers to a Flask response and return it.

    Works with both ``Response`` objects and ``(response, status)`` tuples
    returned by ``jsonify(...), status``.
    """
    headers = _deprecation_headers(v1_path)
    if isinstance(response, tuple):
        resp_obj = response[0]
        status = response[1] if len(response) > 1 else 200
        resp_obj.headers.update(headers)
        return resp_obj, status
    else:
        response.headers.update(headers)
        return response


@bp.route("/session/<session_id>/gps/<int:lap_number>")
def gps_data(session_id: str, lap_number: int):
    """Return GPS trace for a single lap as JSON."""
    conn = get_db_connection()
    data = get_gps_trace(conn, session_id, lap_number)
    if data is None:
        return jsonify({"error": "GPS data not found"}), 404
    return jsonify(data)


@bp.route("/session/<session_id>/gps_laps")
def gps_laps(session_id: str):
    """Return list of lap numbers that have GPS data."""
    conn = get_db_connection()
    laps = get_gps_lap_numbers(conn, session_id)
    return _with_deprecation(
        jsonify({"laps": laps}),
        f"/api/v1/sessions/{session_id}/laps/gps",
    )


@bp.route("/session/<session_id>/speed_trace")
def speed_trace(session_id: str):
    """
    Return speed vs distance data for charting.

    Returns the best lap's GPS-based speed trace and
    all laps' speed data for overlay.
    """
    conn = get_db_connection()
    session = get_session_by_id(conn, session_id)
    if session is None:
        return _with_deprecation(
            (jsonify({"error": "Session not found"}), 404),
            f"/api/v1/sessions/{session_id}/speed-trace",
        )

    laps = get_laps_for_session(conn, session_id)
    gps_lap_nums = get_gps_lap_numbers(conn, session_id)

    best_lap = None
    for lap in laps:
        if lap.get("is_best"):
            best_lap = lap["lap_number"]
            break

    # Build speed traces from GPS data.
    traces = {}
    for lap_num in gps_lap_nums:
        gps = get_gps_trace(conn, session_id, lap_num)
        if gps:
            traces[lap_num] = {
                "distances": gps["distances"],
                "speeds": gps["speeds"],
            }

    return _with_deprecation(
        jsonify({
            "laps": traces,
            "best_lap_number": best_lap,
            "session_id": session_id,
        }),
        f"/api/v1/sessions/{session_id}/speed-trace",
    )


@bp.route("/session/<session_id>/lap_times")
def lap_times(session_id: str):
    """Return lap times as JSON for charting."""
    conn = get_db_connection()
    laps = get_laps_for_session(conn, session_id)
    return _with_deprecation(
        jsonify({
            "laps": [
                {
                    "lap_number": l["lap_number"],
                    "lap_time_s": l["lap_time_s"],
                    "is_best": bool(l.get("is_best")),
                    "is_valid": bool(l.get("is_valid", True)),
                    "invalid_reason": l.get("invalid_reason"),
                    "phase_id": l.get("phase_id"),
                }
                for l in laps
                if l.get("lap_time_s") is not None
            ],
        }),
        f"/api/v1/sessions/{session_id}/lap-times",
    )


@bp.route("/session/<session_id>/cross_session")
def cross_session_data(session_id: str):
    """Return cross-session comparison data."""
    conn = get_db_connection()
    session = get_session_by_id(conn, session_id)
    if session is None:
        return jsonify({"error": "Session not found"}), 404

    result = {"session_id": session_id}

    track_id = session.get("track_id")
    driver_id = session.get("driver_id")
    best_s = session.get("best_lap_time_s")

    if track_id and best_s:
        try:
            from cross_session import compute_cross_session_metrics
            result.update(compute_cross_session_metrics(
                conn, session_id, track_id, driver_id, best_s,
            ))
        except ImportError:
            result["error"] = "cross_session module not available"
    else:
        result["error"] = "missing track or best time"

    return jsonify(result)


@bp.route("/track/<track_id>/records")
def track_records_api(track_id: str):
    """Return track records as JSON."""
    conn = get_db_connection()
    records = get_track_records(conn, track_id)
    return _with_deprecation(
        jsonify({"records": records}),
        f"/api/v1/tracks/{track_id}/records",
    )


@bp.route("/track/<track_id>/evolution")
def track_evolution(track_id: str):
    """
    Return best lap time progression over time for a track.

    Used for the track evolution chart.
    """
    conn = get_db_connection()
    rows = conn.execute(
        """SELECT s.session_id, s.session_date, s.best_lap_time_s,
                  s.total_score, s.track_state, s.session_type,
                  COALESCE(d.driver_name, 'Unknown') AS driver_name
           FROM sessions s
           LEFT JOIN drivers d ON s.driver_id = d.driver_id
           WHERE s.track_id = :track_id
             AND s.best_lap_time_s IS NOT NULL
           ORDER BY s.session_date""",
        {"track_id": track_id},
    ).fetchall()

    sessions = []
    for r in rows:
        sessions.append({
            "session_id": r["session_id"],
            "date": r["session_date"],
            "best_time_s": r["best_lap_time_s"],
            "score": r["total_score"],
            "track_state": r["track_state"],
            "session_type": r["session_type"],
            "driver": r["driver_name"],
        })

    return _with_deprecation(
        jsonify({"track_id": track_id, "sessions": sessions}),
        f"/api/v1/tracks/{track_id}/evolution",
    )


@bp.route("/track/<track_id>/geometry")
def track_geometry(track_id: str):
    """Return track reference line geometry for static track outline."""
    conn = get_db_connection()
    row = conn.execute(
        "SELECT track_name, reference_line FROM tracks WHERE track_id = ?",
        (track_id,),
    ).fetchone()
    if not row or not row["reference_line"]:
        return _with_deprecation(
            (jsonify({"error": "No geometry available"}), 404),
            f"/api/v1/tracks/{track_id}/geometry",
        )
    try:
        geo = json.loads(row["reference_line"])
    except (json.JSONDecodeError, TypeError):
        return _with_deprecation(
            (jsonify({"error": "Invalid geometry data"}), 500),
            f"/api/v1/tracks/{track_id}/geometry",
        )
    return _with_deprecation(
        jsonify({
            "track_name": row["track_name"],
            "latitudes": geo.get("latitudes", []),
            "longitudes": geo.get("longitudes", []),
        }),
        f"/api/v1/tracks/{track_id}/geometry",
    )


@bp.route("/session/<session_id>/speed_overlay")
def speed_overlay(session_id: str):
    """
    Return speed traces for this session's best lap plus
    comparable sessions' best laps, for overlay comparison.
    """
    conn = get_db_connection()
    session = get_session_by_id(conn, session_id)
    if session is None:
        return jsonify({"error": "Session not found"}), 404

    track_id = session.get("track_id")
    if not track_id:
        return jsonify({"traces": {}, "error": "no track"})

    # Current session's best lap.
    laps = get_laps_for_session(conn, session_id)
    best_lap = None
    for lap in laps:
        if lap.get("is_best"):
            best_lap = lap["lap_number"]
            break

    traces = {}
    if best_lap:
        gps = get_gps_trace(conn, session_id, best_lap)
        if gps:
            traces[session_id] = {
                "label": f"{session.get('session_date', '?')} (current)",
                "distances": gps["distances"],
                "speeds": gps["speeds"],
                "is_current": True,
            }

    # Comparable sessions.
    try:
        from cross_session import find_comparable_sessions
        comps = find_comparable_sessions(conn, session_id, track_id, limit=5)
    except ImportError:
        comps = []

    for comp in comps:
        comp_id = comp["session_id"]
        comp_laps = get_laps_for_session(conn, comp_id)
        comp_best = None
        for cl in comp_laps:
            if cl.get("is_best"):
                comp_best = cl["lap_number"]
                break
        if comp_best:
            gps = get_gps_trace(conn, comp_id, comp_best)
            if gps:
                traces[comp_id] = {
                    "label": f"{comp.get('session_date', '?')} ({comp.get('driver_name', '?')})",
                    "distances": gps["distances"],
                    "speeds": gps["speeds"],
                    "is_current": False,
                }

    return jsonify({"traces": traces, "current_session": session_id})


@bp.route("/session/<session_id>/theoretical")
def theoretical_data(session_id: str):
    """Return theoretical lap speed profile and metrics."""
    conn = get_db_connection()
    data = get_theoretical_data(conn, session_id)
    if data is None:
        return _with_deprecation(
            (jsonify({"error": "no theoretical data"}), 404),
            f"/api/v1/sessions/{session_id}/theoretical",
        )
    return _with_deprecation(
        jsonify({
            "theoretical_time_s": data.get("theoretical_time_s"),
            "actual_best_time_s": data.get("actual_best_time_s"),
            "gap_pct":            data.get("gap_pct"),
            "simulation_method":  data.get("simulation_method"),
            "speeds":             data.get("speeds"),
            "distances":          data.get("distances"),
            "metrics":            data.get("metrics"),
        }),
        f"/api/v1/sessions/{session_id}/theoretical",
    )


@bp.route("/session/<session_id>/gg_data")
def gg_data(session_id: str):
    """Return aggregated G-G scatter data from all laps with accel data."""
    import math

    conn = get_db_connection()
    gps_lap_nums = get_gps_lap_numbers(conn, session_id)

    accel_lat_all = []
    accel_long_all = []
    per_lap = {}

    def _clean(arr):
        """Replace NaN/Inf with None; values are already in G from RaceChrono."""
        out = []
        for v in arr:
            if v is None:
                out.append(None)
            else:
                fv = float(v)
                out.append(None if (math.isnan(fv) or math.isinf(fv)) else round(fv, 4))
        return out

    for lap_num in gps_lap_nums:
        gps = get_gps_trace(conn, session_id, lap_num)
        if gps and gps.get("accel_lat") and gps.get("accel_long"):
            lat_clean = _clean(gps["accel_lat"])
            long_clean = _clean(gps["accel_long"])
            accel_lat_all.extend(lat_clean)
            accel_long_all.extend(long_clean)
            per_lap[str(lap_num)] = {
                "accel_lat":  lat_clean,
                "accel_long": long_clean,
            }

    if not accel_lat_all:
        return _with_deprecation(
            jsonify({"accel_lat": [], "accel_long": [], "per_lap": {}, "n_points": 0}),
            f"/api/v1/sessions/{session_id}/gg-data",
        )

    return _with_deprecation(
        jsonify({
            "accel_lat":  accel_lat_all,
            "accel_long": accel_long_all,
            "per_lap":    per_lap,
            "n_points":   len(accel_lat_all),
        }),
        f"/api/v1/sessions/{session_id}/gg-data",
    )


@bp.route("/session/<session_id>/reference_line")
def reference_line_data(session_id: str):
    """Return the reference (median racing) line GPS coordinates."""
    conn = get_db_connection()
    data = get_reference_line(conn, session_id)
    if data is None:
        return _with_deprecation(
            (jsonify({"error": "no reference line"}), 404),
            f"/api/v1/sessions/{session_id}/reference-line",
        )
    return _with_deprecation(
        jsonify(data),
        f"/api/v1/sessions/{session_id}/reference-line",
    )


@bp.route("/session/<session_id>/best_lap_gps")
def best_lap_gps(session_id: str):
    """Return the GPS trace for the best lap."""
    conn = get_db_connection()
    laps = get_laps_for_session(conn, session_id)
    best_lap = None
    for lap in laps:
        if lap.get("is_best"):
            best_lap = lap["lap_number"]
            break

    if best_lap is None:
        return _with_deprecation(
            (jsonify({"error": "no best lap"}), 404),
            f"/api/v1/sessions/{session_id}/best-lap-gps",
        )

    gps = get_gps_trace(conn, session_id, best_lap)
    if gps is None:
        return _with_deprecation(
            (jsonify({"error": "no GPS data for best lap"}), 404),
            f"/api/v1/sessions/{session_id}/best-lap-gps",
        )

    gps["lap_number"] = best_lap
    return _with_deprecation(
        jsonify(gps),
        f"/api/v1/sessions/{session_id}/best-lap-gps",
    )


@bp.route("/session/<session_id>", methods=["DELETE"])
def delete_session(session_id: str):
    """Delete a session and all its associated data."""
    conn = get_db_connection()
    # Use simple existence check (avoids JOIN failure if driver is missing)
    row = conn.execute(
        "SELECT session_id FROM sessions WHERE session_id = :sid",
        {"sid": session_id},
    ).fetchone()
    if row is None:
        return _with_deprecation(
            (jsonify({"error": "Session not found"}), 404),
            f"/api/v1/sessions/{session_id}",
        )

    try:
        # Delete from all related tables in order (child → parent)
        related_tables = [
            "gps_traces", "laps", "score_details", "condition_phases",
            "corner_metrics", "driving_style_features",
            "theoretical_data", "reference_lines", "data_health",
            "session_tags", "session_weather", "session_sectors",
            "session_annotations", "stint_analysis", "condition_markers",
            "driver_progression", "vehicle_setups", "weekend_sessions",
            "what_if_scenarios",
        ]
        # Safety: related_tables is hardcoded above; verify no external input
        assert all(t.isidentifier() for t in related_tables), "Invalid table name"
        for table in related_tables:
            try:
                conn.execute(
                    f"DELETE FROM {table} WHERE session_id = :sid",
                    {"sid": session_id},
                )
            except Exception:
                pass  # Table may not exist yet

        # Delete the session itself
        conn.execute(
            "DELETE FROM sessions WHERE session_id = :sid",
            {"sid": session_id},
        )
        conn.commit()

        logger.info("Deleted session: %s", session_id)
        return _with_deprecation(
            jsonify({"ok": True, "session_id": session_id}),
            f"/api/v1/sessions/{session_id}",
        )
    except Exception as exc:
        logger.error("Failed to delete session %s: %s", session_id, exc)
        return _with_deprecation(
            (jsonify({"error": str(exc)}), 500),
            f"/api/v1/sessions/{session_id}",
        )


@bp.route("/sessions/search")
def sessions_search():
    """Search sessions by ID or CSV filename prefix. Returns top 20 matches."""
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return jsonify([])

    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT s.session_id, s.csv_filename, s.session_date,
               s.session_type, s.n_laps, s.best_lap_time_s,
               COALESCE(d.driver_name, 'Unknown') AS driver_name,
               t.track_name
        FROM sessions s
        LEFT JOIN drivers d ON s.driver_id = d.driver_id
        LEFT JOIN tracks t ON s.track_id = t.track_id
        WHERE s.session_id LIKE :q
           OR s.csv_filename LIKE :q
           OR COALESCE(d.driver_name, '') LIKE :q
           OR t.track_name LIKE :q
        ORDER BY s.session_date DESC
        LIMIT 20
        """,
        {"q": f"%{q}%"},
    ).fetchall()
    results = []
    for r in rows:
        rd = dict(r)
        label = rd["session_id"]
        if rd.get("driver_name"):
            label += f"  |  {rd['driver_name']}"
        if rd.get("track_name"):
            label += f"  |  {rd['track_name']}"
        if rd.get("session_date"):
            label += f"  |  {rd['session_date']}"
        rd["label"] = label
        results.append(rd)
    return jsonify(results)


@bp.route("/sessions/browse")
def sessions_browse():
    """Return sessions for the interactive session picker.

    Query params:
        q       — optional search string (filters by ID, driver, track, date)
        exclude — optional comma-separated session IDs to exclude
        limit   — max results (default 200)
    """
    q = request.args.get("q", "").strip()
    exclude_raw = request.args.get("exclude", "").strip()
    limit = request.args.get("limit", 200, type=int)
    limit = max(1, min(limit, 500))

    conn = get_db_connection()
    base_query = """
        SELECT s.session_id, s.session_date, s.session_type,
               s.n_laps, s.best_lap_time_s, s.total_score, s.grade,
               COALESCE(d.driver_name, 'Unknown') AS driver_name,
               t.track_name
        FROM sessions s
        LEFT JOIN drivers d ON s.driver_id = d.driver_id
        LEFT JOIN tracks t ON s.track_id = t.track_id
    """
    conditions = []
    params: dict[str, Any] = {}

    if q and len(q) >= 2:
        conditions.append(
            "(s.session_id LIKE :q OR s.csv_filename LIKE :q"
            " OR COALESCE(d.driver_name, '') LIKE :q"
            " OR COALESCE(t.track_name, '') LIKE :q"
            " OR s.session_date LIKE :q)"
        )
        params["q"] = f"%{q}%"

    if exclude_raw:
        exclude_ids = [x.strip() for x in exclude_raw.split(",") if x.strip()]
        if exclude_ids:
            placeholders = ", ".join(f":ex{i}" for i in range(len(exclude_ids)))
            conditions.append(f"s.session_id NOT IN ({placeholders})")
            for i, eid in enumerate(exclude_ids):
                params[f"ex{i}"] = eid

    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    query = base_query + where + " ORDER BY s.session_date DESC LIMIT :lim"
    params["lim"] = limit

    rows = conn.execute(query, params).fetchall()
    return jsonify([dict(r) for r in rows])


@bp.route("/sessions/recent")
def sessions_recent():
    """Return N most recent sessions for nav dropdown."""
    limit = request.args.get("limit", 10, type=int)
    limit = max(1, min(limit, 50))
    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT s.session_id, s.session_date, s.session_type,
               s.n_laps, s.best_lap_time_s, s.grade,
               COALESCE(d.driver_name, 'Unknown') AS driver_name,
               t.track_name
        FROM sessions s
        LEFT JOIN drivers d ON s.driver_id = d.driver_id
        LEFT JOIN tracks t ON s.track_id = t.track_id
        ORDER BY s.created_at DESC
        LIMIT :limit
        """,
        {"limit": limit},
    ).fetchall()
    return jsonify([dict(r) for r in rows])


# ------------------------------------------------------------------
# Sector CRUD
# ------------------------------------------------------------------

@bp.route("/session/<session_id>/sectors")
def get_sectors(session_id: str):
    """Return all sector splits for a session."""
    conn = get_db_connection()
    sectors = get_session_sectors(conn, session_id)
    return jsonify({"sectors": sectors})


@bp.route("/session/<session_id>/sectors", methods=["POST"])
def add_sector(session_id: str):
    """Add a new sector split point and re-index all sectors."""
    conn = get_db_connection()
    data = request.get_json(force=True) or {}
    distance_m = data.get("distance_m")
    if distance_m is None:
        return jsonify({"error": "distance_m is required"}), 400

    # Insert with a temporary high index; reindex will fix ordering.
    upsert_session_sector(
        conn, session_id,
        sector_index=9999,
        distance_m=float(distance_m),
        latitude=data.get("latitude"),
        longitude=data.get("longitude"),
        label=data.get("label"),
    )
    sectors = reindex_session_sectors(conn, session_id)
    conn.commit()
    return jsonify({"sectors": sectors})


@bp.route("/session/<session_id>/sectors/<int:sector_id>", methods=["DELETE"])
def remove_sector(session_id: str, sector_id: int):
    """Delete a sector split point and re-index the remaining ones."""
    conn = get_db_connection()
    delete_session_sector(conn, sector_id)
    sectors = reindex_session_sectors(conn, session_id)
    conn.commit()
    return jsonify({"sectors": sectors})


# ------------------------------------------------------------------
# Sector times (computed on-the-fly)
# ------------------------------------------------------------------

@bp.route("/session/<session_id>/sector_times")
def sector_times(session_id: str):
    """Compute sector times for each lap based on GPS speed + sector boundaries."""
    conn = get_db_connection()
    sectors = get_session_sectors(conn, session_id)
    gps_lap_nums = get_gps_lap_numbers(conn, session_id)

    if not sectors or not gps_lap_nums:
        return jsonify({"laps": {}, "sector_boundaries": []})

    boundaries = [0.0] + [s["distance_m"] for s in sectors]
    # Last boundary = max distance (will be set per-lap)

    result_laps = {}
    for lap_num in gps_lap_nums:
        gps = get_gps_trace(conn, session_id, lap_num)
        if not gps or not gps.get("distances") or not gps.get("speeds"):
            continue

        dists = gps["distances"]
        speeds = gps["speeds"]
        if len(dists) < 2:
            continue

        max_dist = dists[-1] if dists[-1] else 0
        lap_boundaries = boundaries + [max_dist]

        sector_results = []
        for i in range(len(lap_boundaries) - 1):
            d_start = lap_boundaries[i]
            d_end = lap_boundaries[i + 1]
            sector_time = _compute_time_in_range(dists, speeds, d_start, d_end)
            sector_results.append({
                "sector": sectors[i]["label"] if i < len(sectors) else f"S{i + 1}",
                "time_s": round(sector_time, 3),
            })

        total = sum(s["time_s"] for s in sector_results)
        result_laps[str(lap_num)] = {
            "sectors": sector_results,
            "total_s": round(total, 3),
        }

    return jsonify({
        "laps": result_laps,
        "sector_boundaries": boundaries[1:],  # exclude 0.0
    })


def _compute_time_in_range(distances, speeds, d_start, d_end):
    """Integrate time = sum(ds / speed) between distance start and end."""
    total_time = 0.0
    for i in range(len(distances) - 1):
        d0 = distances[i]
        d1 = distances[i + 1]
        if d0 is None or d1 is None:
            continue
        if d1 <= d_start or d0 >= d_end:
            continue  # Outside range

        # Clamp to sector boundaries
        seg_start = max(d0, d_start)
        seg_end = min(d1, d_end)
        ds = seg_end - seg_start
        if ds <= 0:
            continue

        s0 = speeds[i] if speeds[i] else 0
        s1 = speeds[i + 1] if i + 1 < len(speeds) and speeds[i + 1] else s0
        avg_speed = (s0 + s1) / 2.0
        if avg_speed > 0.1:  # Avoid division by near-zero
            total_time += ds / avg_speed

    return total_time


# ------------------------------------------------------------------
# Lap delta (speed + time)
# ------------------------------------------------------------------

@bp.route("/session/<session_id>/delta")
def lap_delta(session_id: str):
    """Compute speed delta and cumulative time delta between two laps."""
    lap_a = request.args.get("lap_a", type=int)
    lap_b = request.args.get("lap_b", type=int)
    if lap_a is None or lap_b is None:
        return jsonify({"error": "lap_a and lap_b are required"}), 400

    conn = get_db_connection()
    gps_a = get_gps_trace(conn, session_id, lap_a)
    gps_b = get_gps_trace(conn, session_id, lap_b)
    if not gps_a or not gps_b:
        return jsonify({"error": "GPS data not available for one or both laps"}), 404

    dists_a, speeds_a = gps_a["distances"], gps_a["speeds"]
    dists_b, speeds_b = gps_b["distances"], gps_b["speeds"]

    if not dists_a or not dists_b:
        return jsonify({"error": "empty distance data"}), 404

    # Create a common distance axis (union of both, at ~1m resolution)
    max_dist = min(dists_a[-1] or 0, dists_b[-1] or 0)
    if max_dist < 10:
        return jsonify({"error": "insufficient distance data"}), 404

    n_points = min(int(max_dist), 1000)
    common_dists = [i * max_dist / n_points for i in range(n_points + 1)]

    # Interpolate speeds onto common axis
    interp_a = _interpolate_speed(dists_a, speeds_a, common_dists)
    interp_b = _interpolate_speed(dists_b, speeds_b, common_dists)

    speed_delta = []
    time_delta = []
    cum_time_a = 0.0
    cum_time_b = 0.0

    for i in range(len(common_dists)):
        sa = interp_a[i]
        sb = interp_b[i]
        speed_delta.append(round(sa - sb, 3))

        if i > 0:
            ds = common_dists[i] - common_dists[i - 1]
            if interp_a[i - 1] > 0.1:
                cum_time_a += ds / ((interp_a[i - 1] + sa) / 2.0)
            if interp_b[i - 1] > 0.1:
                cum_time_b += ds / ((interp_b[i - 1] + sb) / 2.0)

        time_delta.append(round(cum_time_a - cum_time_b, 4))

    return jsonify({
        "distances": [round(d, 1) for d in common_dists],
        "speed_delta": speed_delta,
        "time_delta": time_delta,
        "lap_a": lap_a,
        "lap_b": lap_b,
    })


def _interpolate_speed(distances, speeds, target_dists):
    """Linear interpolation of speed values onto target distance points."""
    result = []
    j = 0
    for td in target_dists:
        # Advance j to bracket td
        while j < len(distances) - 1 and (distances[j + 1] or 0) < td:
            j += 1
        if j >= len(distances) - 1:
            result.append(speeds[-1] if speeds[-1] else 0)
            continue

        d0 = distances[j] or 0
        d1 = distances[j + 1] if j + 1 < len(distances) else d0
        s0 = speeds[j] if speeds[j] else 0
        s1 = speeds[j + 1] if j + 1 < len(speeds) and speeds[j + 1] else s0

        if d1 > d0:
            t = (td - d0) / (d1 - d0)
            t = max(0, min(1, t))
            result.append(s0 + t * (s1 - s0))
        else:
            result.append(s0)

    return result


# ------------------------------------------------------------------
# File browser
# ------------------------------------------------------------------

def _human_size(nbytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if nbytes < 1024:
            return f"{nbytes:.1f} {unit}" if unit != "B" else f"{nbytes} {unit}"
        nbytes /= 1024
    return f"{nbytes:.1f} TB"


@bp.route("/files/list")
def files_list():
    """List CSV files in data/raw/ directory."""
    raw_dir = Path(current_app.config.get("DATA_RAW_DIR", "data/raw"))
    raw_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for f in sorted(raw_dir.iterdir()):
        if f.suffix.lower() == ".csv" and f.is_file():
            stat = f.stat()
            files.append({
                "name": f.name,
                "size_bytes": stat.st_size,
                "size_human": _human_size(stat.st_size),
                "modified": stat.st_mtime,
                "modified_human": datetime.fromtimestamp(stat.st_mtime).strftime(
                    "%Y-%m-%d %H:%M"
                ),
            })
    return _with_deprecation(
        jsonify({"files": files}),
        "/api/v1/files",
    )


@bp.route("/files/upload", methods=["POST"])
def files_upload():
    """Upload a CSV file to data/raw/."""
    if "file" not in request.files:
        return jsonify({"error": "no file provided"}), 400

    f = request.files["file"]
    if not f.filename or not f.filename.lower().endswith(".csv"):
        return jsonify({"error": "only .csv files allowed"}), 400

    # Sanitize filename (werkzeug secure_filename for safety)
    safe_name = secure_filename(f.filename) or "upload.csv"
    if not safe_name.lower().endswith(".csv"):
        safe_name += ".csv"
    raw_dir = Path(current_app.config.get("DATA_RAW_DIR", "data/raw"))
    raw_dir.mkdir(parents=True, exist_ok=True)
    dest = raw_dir / safe_name
    f.save(str(dest))

    return jsonify({
        "name": safe_name,
        "size_human": _human_size(dest.stat().st_size),
    })


# ------------------------------------------------------------------
# Data health API (Feature #24)
# ------------------------------------------------------------------

@bp.route("/data-health")
def api_data_health_list():
    """Return data health metrics for all sessions."""
    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT dh.*, s.session_date, s.session_type,
               COALESCE(d.driver_name, 'Unknown') AS driver_name,
               t.track_name
        FROM data_health dh
        JOIN sessions s ON dh.session_id = s.session_id
        LEFT JOIN drivers d ON s.driver_id = d.driver_id
        LEFT JOIN tracks t ON s.track_id = t.track_id
        ORDER BY dh.overall_score ASC
        """
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@bp.route("/data-health/<session_id>")
def api_data_health_detail(session_id: str):
    """Return detailed data health report for a session."""
    conn = get_db_connection()
    row = conn.execute(
        "SELECT * FROM data_health WHERE session_id = :session_id",
        {"session_id": session_id},
    ).fetchone()
    if not row:
        return jsonify({"error": "No data health report for this session"}), 404
    result = dict(row)
    if result.get("report_json"):
        try:
            result["report"] = json.loads(result["report_json"])
        except (json.JSONDecodeError, TypeError):
            result["report"] = {}
    return jsonify(result)


# ------------------------------------------------------------------
# Batch re-analysis API (Feature #25)
# ------------------------------------------------------------------

@bp.route("/batch-reanalyze", methods=["POST"])
def api_batch_reanalyze():
    """Start batch re-analysis of selected sessions."""
    data = request.get_json(force=True) or {}
    session_ids = data.get("session_ids", [])
    if not isinstance(session_ids, list) or not all(isinstance(s, str) for s in session_ids):
        return jsonify({"error": "session_ids must be a list of strings"}), 400
    settings = data.get("settings", {})

    if not session_ids:
        return jsonify({"error": "session_ids is required"}), 400

    if len(session_ids) > 50:
        return jsonify({"error": "maximum 50 sessions per batch"}), 400

    conn = get_db_connection()

    try:
        from batch_analysis import batch_reanalyze
        result = batch_reanalyze(session_ids, conn, settings)
        return jsonify(result)
    except ImportError:
        return jsonify({"error": "batch_analysis module not available"}), 500
    except Exception as exc:
        logger.error("Batch reanalyze failed: %s", exc, exc_info=True)
        return jsonify({"error": str(exc)}), 500


@bp.route("/batch-reanalyze/status/<job_id>")
def api_batch_status(job_id: str):
    """Check the status of a batch re-analysis job."""
    try:
        from batch_analysis import get_job_status
        status = get_job_status(job_id)
        if status is None:
            return jsonify({"error": "Job not found"}), 404
        return jsonify(status)
    except ImportError:
        return jsonify({"error": "batch_analysis module not available"}), 500


# ------------------------------------------------------------------
# Session tags API
# ------------------------------------------------------------------

@bp.route("/session/<session_id>/tags")
def api_session_tags(session_id: str):
    """Return all tags for a session."""
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT * FROM session_tags WHERE session_id = :session_id ORDER BY tag",
        {"session_id": session_id},
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@bp.route("/session/<session_id>/tags", methods=["POST"])
def api_add_session_tag(session_id: str):
    """Add a tag to a session."""
    data = request.get_json(force=True) or {}
    tag = data.get("tag", "").strip()
    if not tag:
        return jsonify({"error": "tag is required"}), 400

    conn = get_db_connection()
    conn.execute(
        "INSERT OR REPLACE INTO session_tags (session_id, tag, confidence, source) "
        "VALUES (:session_id, :tag, :confidence, :source)",
        {
            "session_id": session_id,
            "tag": tag,
            "confidence": data.get("confidence", 1.0),
            "source": data.get("source", "manual"),
        },
    )
    conn.commit()
    return jsonify({"ok": True, "tag": tag})


@bp.route("/session/<session_id>/tags/<int:tag_id>", methods=["DELETE"])
def api_delete_session_tag(session_id: str, tag_id: int):
    """Delete a tag from a session."""
    conn = get_db_connection()
    conn.execute(
        "DELETE FROM session_tags WHERE id = :id AND session_id = :session_id",
        {"id": tag_id, "session_id": session_id},
    )
    conn.commit()
    return jsonify({"ok": True})


# ------------------------------------------------------------------
# Corner metrics & coaching API (Feature #1–#5)
# ------------------------------------------------------------------

@bp.route("/session/<session_id>/corner-metrics")
def api_corner_metrics(session_id: str):
    """Return per-lap corner metrics for a session."""
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT * FROM corner_metrics WHERE session_id = :sid ORDER BY lap_number, corner_id",
        {"sid": session_id},
    ).fetchall()
    if not rows:
        return jsonify({"error": "No corner metrics for this session"}), 404
    return jsonify([dict(r) for r in rows])


@bp.route("/session/<session_id>/corner-metrics/summary")
def api_corner_metrics_summary(session_id: str):
    """Return aggregated corner metrics (mean/min/max per corner)."""
    conn = get_db_connection()
    rows = conn.execute(
        """SELECT corner_id,
                  COUNT(*) AS n_laps,
                  AVG(brake_point_m) AS avg_brake_point_m,
                  MIN(brake_point_m) AS min_brake_point_m,
                  MAX(brake_point_m) AS max_brake_point_m,
                  AVG(entry_speed_mps) AS avg_entry_speed,
                  AVG(apex_speed_mps) AS avg_apex_speed,
                  AVG(exit_speed_mps) AS avg_exit_speed,
                  AVG(grip_utilization) AS avg_grip,
                  AVG(time_loss_ms) AS avg_time_loss_ms,
                  SUM(time_loss_ms) AS total_time_loss_ms
           FROM corner_metrics
           WHERE session_id = :sid
           GROUP BY corner_id
           ORDER BY corner_id""",
        {"sid": session_id},
    ).fetchall()
    if not rows:
        return jsonify({"error": "No corner metrics"}), 404
    return jsonify([dict(r) for r in rows])


@bp.route("/track/<track_id>/key-corners", methods=["GET"])
def api_get_key_corners(track_id: str):
    """Return key corners marked for this track."""
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT corner_id, label, lat, lon, dist_m "
        "FROM track_key_corners WHERE track_id = :tid ORDER BY corner_id",
        {"tid": track_id},
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@bp.route("/track/<track_id>/key-corners", methods=["POST"])
def api_set_key_corners(track_id: str):
    """Set key corners for a track.

    Body: ``{"corners": [{"corner_id": 1, "label": "Hairpin", "lat": ..., "lon": ..., "dist_m": ...}, ...]}``
    """
    conn = get_db_connection()
    data = request.get_json(silent=True) or {}
    corners = data.get("corners", [])

    # Clear existing key corners for this track
    conn.execute("DELETE FROM track_key_corners WHERE track_id = :tid", {"tid": track_id})

    for c in corners:
        cid = c.get("corner_id")
        if cid is None:
            continue
        conn.execute(
            "INSERT OR REPLACE INTO track_key_corners "
            "(track_id, corner_id, label, lat, lon, dist_m) "
            "VALUES (:tid, :cid, :label, :lat, :lon, :dist_m)",
            {
                "tid": track_id,
                "cid": int(cid),
                "label": c.get("label") or None,
                "lat": c.get("lat"),
                "lon": c.get("lon"),
                "dist_m": c.get("dist_m"),
            },
        )
    conn.commit()
    return jsonify({"ok": True, "count": len(corners)})


@bp.route("/session/<session_id>/corner-positions")
def api_corner_positions(session_id: str):
    """Return GPS lat/lon for each corner's brake point and apex.

    Uses the best lap's GPS trace to map corner distances to coordinates.
    """
    conn = get_db_connection()
    import json as _json

    # Get corner average distances from corner_metrics
    corner_rows = conn.execute(
        """SELECT corner_id,
                  AVG(brake_point_m) AS avg_brake_m,
                  MIN(brake_point_m) AS min_brake_m,
                  MAX(brake_point_m) AS max_brake_m
           FROM corner_metrics
           WHERE session_id = :sid AND brake_point_m IS NOT NULL
           GROUP BY corner_id ORDER BY corner_id""",
        {"sid": session_id},
    ).fetchall()
    if not corner_rows:
        return jsonify({"error": "No corner data"}), 404

    # Get the best lap's GPS trace for coordinate mapping
    laps = get_laps_for_session(conn, session_id)
    best_lap_num = None
    for lap in laps:
        if lap.get("is_best"):
            best_lap_num = lap["lap_number"]
            break
    if best_lap_num is None and laps:
        best_lap_num = laps[0]["lap_number"]

    gps = get_gps_trace(conn, session_id, best_lap_num)
    if not gps or not gps.get("distances") or not gps.get("latitudes"):
        return jsonify({"error": "No GPS data for coordinate mapping"}), 404

    dists = gps["distances"]
    lat_arr = gps["latitudes"]
    lon_arr = gps["longitudes"]

    import bisect
    corners = []
    for cr in corner_rows:
        bp_m = cr["avg_brake_m"]
        idx = bisect.bisect_left(dists, bp_m)
        idx = min(idx, len(lat_arr) - 1)
        corners.append({
            "corner_id": cr["corner_id"],
            "brake_point_m": round(bp_m, 1),
            "brake_point_range_m": [round(cr["min_brake_m"], 1),
                                     round(cr["max_brake_m"], 1)],
            "lat": lat_arr[idx],
            "lon": lon_arr[idx],
        })

    return jsonify({"corners": corners, "best_lap": best_lap_num})


@bp.route("/session/<session_id>/corner-replay-data")
def api_corner_replay_data(session_id: str):
    """Batch endpoint for corner replay: GPS traces + corner metrics for selected laps."""
    conn = get_db_connection()
    import bisect

    # Parse requested lap numbers (cap at 5)
    laps_param = request.args.get("laps", "")
    try:
        requested = [int(x.strip()) for x in laps_param.split(",") if x.strip()][:5]
    except ValueError:
        return jsonify({"error": "Invalid laps parameter"}), 400

    # If none requested, use all GPS laps (capped at 5)
    if not requested:
        requested = get_gps_lap_numbers(conn, session_id)[:5]
    if not requested:
        return jsonify({"error": "No GPS laps available"}), 404

    # Fetch laps info for lap times + best lap
    all_laps = get_laps_for_session(conn, session_id)
    lap_times = {}
    best_lap_num = None
    best_time = None
    for lap in all_laps:
        ln = lap["lap_number"]
        lt = lap.get("lap_time_s")
        if lt is not None:
            lap_times[str(ln)] = round(lt, 3)
            if best_time is None or lt < best_time:
                best_time = lt
                best_lap_num = ln

    # Fetch GPS traces for each requested lap
    traces = {}
    for ln in requested:
        gps = get_gps_trace(conn, session_id, ln)
        if gps:
            traces[str(ln)] = {
                "latitudes": gps.get("latitudes", []),
                "longitudes": gps.get("longitudes", []),
                "distances": gps.get("distances", []),
                "speeds": gps.get("speeds", []),
                "accel_lat": gps.get("accel_lat", []),
                "accel_long": gps.get("accel_long", []),
            }

    if not traces:
        return jsonify({"error": "No GPS data for requested laps"}), 404

    # Fetch corner metrics grouped by lap
    cm_rows = conn.execute(
        """SELECT lap_number, corner_id, brake_point_m, apex_speed_mps,
                  exit_speed_mps, entry_speed_mps, time_loss_ms
           FROM corner_metrics
           WHERE session_id = :sid AND lap_number IN ({})
           ORDER BY lap_number, corner_id""".format(
            ",".join(str(ln) for ln in requested)
        ),
        {"sid": session_id},
    ).fetchall()

    corner_metrics = {}
    for r in cm_rows:
        rd = dict(r)
        ln_str = str(rd["lap_number"])
        corner_metrics.setdefault(ln_str, []).append(rd)

    # Corner GPS positions (using best lap trace)
    ref_lap = best_lap_num or requested[0]
    ref_gps = traces.get(str(ref_lap)) or next(iter(traces.values()), None)
    corner_positions = []

    if ref_gps and ref_gps["distances"]:
        pos_rows = conn.execute(
            """SELECT corner_id, AVG(brake_point_m) AS avg_brake_m
               FROM corner_metrics WHERE session_id = :sid
               GROUP BY corner_id ORDER BY corner_id""",
            {"sid": session_id},
        ).fetchall()

        dists = ref_gps["distances"]
        lats = ref_gps["latitudes"]
        lons = ref_gps["longitudes"]
        # Build a clean (distance, index) list for bisect — skip None gaps
        clean_dists = [(d, i) for i, d in enumerate(dists) if d is not None]
        clean_vals = [d for d, _ in clean_dists]
        for pr in pos_rows:
            brake_m = pr["avg_brake_m"]
            if brake_m is None:
                continue
            bi = bisect.bisect_left(clean_vals, brake_m)
            bi = min(bi, len(clean_dists) - 1)
            idx = clean_dists[bi][1] if clean_dists else 0
            idx = min(idx, len(lats) - 1)
            corner_positions.append({
                "corner_id": pr["corner_id"],
                "brake_point_m": round(brake_m, 1),
                "lat": lats[idx],
                "lon": lons[idx],
            })

    # Check if real brake/throttle/steering data exists in traces
    # (gps_traces only stores accel_lat/accel_long — no pedal sensor data)
    has_pedal = False
    has_steering = False
    for t in traces.values():
        if t.get("brake") and any(v for v in t["brake"] if v):
            has_pedal = True
        if t.get("steering") and any(v for v in t["steering"] if v):
            has_steering = True

    return jsonify({
        "traces": traces,
        "corner_metrics": corner_metrics,
        "corner_positions": corner_positions,
        "best_lap_number": best_lap_num,
        "lap_times": lap_times,
        "has_pedal_data": has_pedal,
        "has_steering_data": has_steering,
    })


@bp.route("/session/<session_id>/brake-precision")
def api_brake_precision(session_id: str):
    """Return brake precision analysis for each corner."""
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT * FROM corner_metrics WHERE session_id = :sid ORDER BY lap_number, corner_id",
        {"sid": session_id},
    ).fetchall()
    if not rows:
        return jsonify({"error": "No corner metrics"}), 404

    # Group by lap
    by_lap: dict = {}
    for r in rows:
        rd = dict(r)
        ln = rd["lap_number"]
        by_lap.setdefault(ln, []).append(rd)

    try:
        from brake_precision import compute_brake_precision, compute_overall_brake_score
        precision = compute_brake_precision(by_lap)
        overall = compute_overall_brake_score(precision)

        # Collect per-lap brake points for scatter plot
        scatter_points: dict[int, list[dict]] = {}
        for r in rows:
            rd = dict(r)
            cid = rd.get("corner_id")
            bp = rd.get("brake_point_m")
            if cid is not None and bp is not None:
                scatter_points.setdefault(cid, []).append({
                    "lap": rd["lap_number"],
                    "brake_m": round(bp, 1),
                })

        return jsonify({
            "session_id": session_id,
            "per_corner": precision,
            "overall_score": overall,
            "scatter": scatter_points,
        })
    except ImportError:
        return jsonify({"error": "brake_precision module not available"}), 500


# ------------------------------------------------------------------
# Predefined karts / tracks / drivers for New Analysis form
# ------------------------------------------------------------------

import csv
import io
import unicodedata


def _normalize_driver_name(name: str) -> str:
    """Normalize a driver name: strip accents, lowercase, collapse whitespace."""
    # Decompose unicode then strip combining marks (accents)
    nfkd = unicodedata.normalize("NFKD", name)
    stripped = "".join(c for c in nfkd if not unicodedata.combining(c))
    return " ".join(stripped.lower().split())


@bp.route("/predefined-karts")
def api_predefined_karts():
    """Return predefined kart list, grouped by segment."""
    csv_path = Path(current_app.root_path).parent.parent / "predefined_kart_list.csv"
    if not csv_path.exists():
        return jsonify({"segments": {}, "karts": []})
    try:
        text = csv_path.read_text(encoding="utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        karts = []
        segments = {}
        for row in reader:
            if not row.get("model"):
                continue
            kart = {
                "segment": (row.get("segment") or "OTHER").strip(),
                "manufacturer": (row.get("manufacturer") or "").strip(),
                "model": row["model"].strip(),
                "engine": (row.get("engine") or "").strip(),
                "power_hp": row.get("power_hp") or None,
                "engine_type": (row.get("engine_type") or "").strip(),
                "kart_weight_kg": row.get("kart_weight_kg_no_driver") or None,
                "top_speed_kmh": row.get("top_speed_kmh") or None,
                "lateral_g_est": row.get("lateral_g_est") or None,
                "braking_g_est": row.get("braking_g_est") or None,
            }
            karts.append(kart)
            seg = kart["segment"]
            if seg not in segments:
                segments[seg] = []
            segments[seg].append(kart)
        return jsonify({"segments": segments, "karts": karts})
    except Exception as exc:
        logger.warning("Failed to load predefined karts: %s", exc)
        return jsonify({"segments": {}, "karts": [], "error": str(exc)})


@bp.route("/predefined-tracks")
def api_predefined_tracks():
    """Return predefined track list, grouped by country."""
    csv_path = Path(current_app.root_path).parent.parent / "predefined_track_list.csv"
    if not csv_path.exists():
        return jsonify({"countries": {}, "tracks": []})
    try:
        text = csv_path.read_text(encoding="utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        tracks = []
        countries = {}
        for row in reader:
            name = (row.get("Track") or "").strip()
            if not name:
                continue
            layout = (row.get("LayoutName") or "").strip()
            length_raw = (row.get("LayoutLength_m") or "").strip()
            length_m = None
            if length_raw:
                try:
                    length_m = int(float(length_raw))
                except (ValueError, TypeError):
                    pass
            track = {
                "country": (row.get("Country") or "").strip(),
                "name": name,
                "city": (row.get("City") or "").strip(),
                "layout": layout,
                "length_m": length_m,
                "direction": (row.get("Direction") or "").strip(),
                "rental": (row.get("RentalAvailable") or "").strip(),
                "owner": (row.get("OwnerAvailable") or "").strip(),
                "outdoor": (row.get("Outdoor") or "").strip(),
            }
            # Display label: "Track - Layout (Length)"
            label = name
            if layout:
                label += " - " + layout
            if length_m:
                label += f" ({length_m}m)"
            track["label"] = label
            tracks.append(track)
            country = track["country"]
            if country not in countries:
                countries[country] = []
            countries[country].append(track)
        return jsonify({"countries": countries, "tracks": tracks})
    except Exception as exc:
        logger.warning("Failed to load predefined tracks: %s", exc)
        return jsonify({"countries": {}, "tracks": [], "error": str(exc)})


@bp.route("/drivers/list")
def api_drivers_list():
    """Return all existing drivers for autocomplete/dropdown."""
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT d.driver_id, d.driver_name, COUNT(s.session_id) AS session_count "
        "FROM drivers d LEFT JOIN sessions s ON d.driver_id = s.driver_id "
        "GROUP BY d.driver_id ORDER BY d.driver_name"
    ).fetchall()
    return jsonify({"drivers": [dict(r) for r in rows]})


@bp.route("/drivers/normalize", methods=["POST"])
def api_normalize_driver():
    """Check if a driver name matches an existing one (accent-insensitive)."""
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"match": None, "normalized": ""})

    normalized = _normalize_driver_name(name)

    conn = get_db_connection()
    rows = conn.execute("SELECT driver_id, driver_name FROM drivers").fetchall()
    for r in rows:
        if _normalize_driver_name(r["driver_name"]) == normalized:
            return jsonify({
                "match": {"driver_id": r["driver_id"], "driver_name": r["driver_name"]},
                "normalized": normalized,
            })
    return jsonify({"match": None, "normalized": normalized})


@bp.route("/session/<session_id>/throttle-map")
def api_throttle_map(session_id: str):
    """Return throttle onset mapping for each corner."""
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT * FROM corner_metrics WHERE session_id = :sid ORDER BY lap_number, corner_id",
        {"sid": session_id},
    ).fetchall()
    if not rows:
        return jsonify({"error": "No corner metrics"}), 404

    by_lap: dict = {}
    for r in rows:
        rd = dict(r)
        ln = rd["lap_number"]
        by_lap.setdefault(ln, []).append(rd)

    try:
        from throttle_mapping import compute_throttle_profiles
        # Get theoretical metrics from best practices if available
        session = get_session_by_id(conn, session_id)
        track_id = session.get("track_id") if session else None
        theo = {}
        if track_id:
            bp_rows = conn.execute(
                "SELECT * FROM corner_best_practices WHERE track_id = :tid",
                {"tid": track_id},
            ).fetchall()
            for bpr in bp_rows:
                bpd = dict(bpr)
                theo[bpd["corner_id"]] = {
                    "throttle_onset_m": bpd.get("best_throttle_onset_m"),
                }

        result = compute_throttle_profiles(by_lap, theoretical_metrics=theo or None)
        result["session_id"] = session_id
        return jsonify(result)
    except ImportError:
        return jsonify({"error": "throttle_mapping module not available"}), 500


@bp.route("/session/<session_id>/corner-coaching")
def api_corner_coaching(session_id: str):
    """Return context-aware coaching hints for each corner."""
    conn = get_db_connection()
    session = get_session_by_id(conn, session_id)
    if session is None:
        return jsonify({"error": "Session not found"}), 404

    rows = conn.execute(
        """SELECT corner_id,
                  AVG(brake_point_m) AS avg_brake_point_m,
                  AVG(entry_speed_mps) AS avg_entry_speed,
                  AVG(apex_speed_mps) AS avg_apex_speed,
                  AVG(exit_speed_mps) AS avg_exit_speed,
                  AVG(grip_utilization) AS avg_grip,
                  AVG(time_loss_ms) AS avg_time_loss_ms,
                  GROUP_CONCAT(DISTINCT coaching_hint) AS hints
           FROM corner_metrics
           WHERE session_id = :sid
           GROUP BY corner_id
           ORDER BY AVG(time_loss_ms) DESC""",
        {"sid": session_id},
    ).fetchall()

    if not rows:
        return jsonify({"error": "No corner metrics"}), 404

    # Get driving style for context-aware hints
    style_label = None
    try:
        style_row = conn.execute(
            "SELECT style_label FROM driving_style_features "
            "WHERE session_id = :sid",
            {"sid": session_id},
        ).fetchone()
        if style_row:
            style_label = style_row["style_label"]
    except Exception:
        pass

    session_type = session.get("session_type", "practice")
    coaching = []
    for r in rows:
        rd = dict(r)
        rd["session_type"] = session_type
        rd["style"] = style_label
        # Use the most common coaching hint from corner_metrics
        hints = rd.pop("hints", "")
        rd["coaching_hint"] = hints.split(",")[0] if hints else ""
        coaching.append(rd)

    return jsonify({
        "session_id": session_id,
        "session_type": session_type,
        "style": style_label,
        "corners": coaching,
    })


@bp.route("/track/<track_id>/best-practices")
def api_best_practices(track_id: str):
    """Return corner best practices for a track."""
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT * FROM corner_best_practices WHERE track_id = :tid ORDER BY corner_id",
        {"tid": track_id},
    ).fetchall()
    if not rows:
        return jsonify({"error": "No best practices for this track"}), 404
    return jsonify([dict(r) for r in rows])


@bp.route("/session/<session_id>/consistency-heatmap")
def api_consistency_heatmap(session_id: str):
    """Return lap×corner consistency heatmap data."""
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT * FROM corner_metrics WHERE session_id = :sid ORDER BY lap_number, corner_id",
        {"sid": session_id},
    ).fetchall()
    if not rows:
        return jsonify({"error": "No corner metrics"}), 404

    by_lap: dict = {}
    for r in rows:
        rd = dict(r)
        ln = rd["lap_number"]
        by_lap.setdefault(ln, []).append(rd)

    try:
        from consistency_heatmap import compute_consistency_heatmap, classify_consistency
        heatmap = compute_consistency_heatmap(by_lap)
        classifications = classify_consistency(heatmap)
        heatmap["classifications"] = classifications
        heatmap["session_id"] = session_id
        return jsonify(heatmap)
    except ImportError:
        return jsonify({"error": "consistency_heatmap module not available"}), 500


# ------------------------------------------------------------------
# Stint analysis API
# ------------------------------------------------------------------

@bp.route("/session/<session_id>/stint-analysis")
def api_stint_analysis(session_id: str):
    """Return stint breakdown and per-stint metrics for a session."""
    conn = get_db_connection()
    session = get_session_by_id(conn, session_id)
    if session is None:
        return jsonify({"error": "Session not found"}), 404

    # Try DB first (cached from pipeline)
    from web.models import get_stint_analysis
    cached = get_stint_analysis(conn, session_id)
    if cached:
        return jsonify({
            "session_id": session_id,
            "n_stints": len(cached),
            "stint_metrics": cached,
        })

    # Compute on the fly from lap times
    laps = conn.execute(
        "SELECT lap_number, lap_time_s FROM laps WHERE session_id = :sid AND is_valid = 1 ORDER BY lap_number",
        {"sid": session_id},
    ).fetchall()

    if not laps:
        return jsonify({"error": "No lap data"}), 404

    lap_times_dict = {int(r["lap_number"]): float(r["lap_time_s"])
                      for r in laps if r["lap_time_s"] is not None}

    try:
        from stint_analysis import analyze_stints
        result = analyze_stints(lap_times_dict)
        return jsonify(result.to_dict())
    except ImportError:
        return jsonify({"error": "stint_analysis module not available"}), 500


@bp.route("/session/<session_id>/fatigue-analysis")
def api_fatigue_analysis(session_id: str):
    """Return driver fatigue and concentration analysis."""
    conn = get_db_connection()
    session = get_session_by_id(conn, session_id)
    if session is None:
        return _with_deprecation(
            (jsonify({"error": "Session not found"}), 404),
            f"/api/v1/sessions/{session_id}/fatigue",
        )

    laps = conn.execute(
        """SELECT lap_number, lap_time_s, speed_mean_mps, braking_max_mps2,
                  accel_max_mps2
           FROM laps WHERE session_id = :sid AND is_valid = 1
           ORDER BY lap_number""",
        {"sid": session_id},
    ).fetchall()

    if not laps:
        return _with_deprecation(
            (jsonify({"error": "No lap data"}), 404),
            f"/api/v1/sessions/{session_id}/fatigue",
        )

    lap_metrics = []
    lap_times = []
    lap_numbers = []
    for r in laps:
        rd = dict(r)
        lap_numbers.append(int(rd["lap_number"]))
        lap_times.append(float(rd["lap_time_s"]) if rd["lap_time_s"] else float("nan"))
        lap_metrics.append({
            "braking_max_mps2": rd.get("braking_max_mps2"),
            "jerk_rms_mps3": None,  # not stored in laps table
            "speed_mean_mps": rd.get("speed_mean_mps"),
        })

    try:
        from fatigue_detection import analyze_fatigue
        result = analyze_fatigue(lap_metrics, lap_times, lap_numbers)
        return _with_deprecation(
            jsonify(result.to_dict()),
            f"/api/v1/sessions/{session_id}/fatigue",
        )
    except ImportError:
        return _with_deprecation(
            (jsonify({"error": "fatigue_detection module not available"}), 500),
            f"/api/v1/sessions/{session_id}/fatigue",
        )


@bp.route("/session/<session_id>/corner-mastery")
def api_corner_mastery(session_id: str):
    """Return per-corner mastery scores and report card."""
    conn = get_db_connection()
    session = get_session_by_id(conn, session_id)
    if session is None:
        return jsonify({"error": "Session not found"}), 404

    rows = conn.execute(
        "SELECT * FROM corner_metrics WHERE session_id = :sid ORDER BY corner_id, lap_number",
        {"sid": session_id},
    ).fetchall()

    if not rows:
        return jsonify({"error": "No corner metrics"}), 404

    # Group by corner_id
    by_corner: dict = {}
    for r in rows:
        rd = dict(r)
        cid = rd["corner_id"]
        by_corner.setdefault(cid, []).append(rd)

    # Load best practices
    track_id = session.get("track_id")
    bp_data = {}
    if track_id:
        bp_rows = conn.execute(
            "SELECT * FROM corner_best_practices WHERE track_id = :tid",
            {"tid": track_id},
        ).fetchall()
        for bpr in bp_rows:
            bpd = dict(bpr)
            bp_data[bpd["corner_id"]] = bpd

    try:
        from corner_mastery import compute_corner_mastery, generate_corner_report_card
        results = compute_corner_mastery(by_corner, best_practices=bp_data)
        card = generate_corner_report_card(results)
        card["session_id"] = session_id
        return jsonify(card)
    except ImportError:
        return jsonify({"error": "corner_mastery module not available"}), 500


# ------------------------------------------------------------------
# Performance Fingerprint API
# ------------------------------------------------------------------

@bp.route("/session/<session_id>/fingerprint")
def api_fingerprint(session_id: str):
    """Return a 6-dimension performance fingerprint for a session."""
    conn = get_db_connection()
    row = conn.execute(
        "SELECT * FROM sessions WHERE session_id = :sid",
        {"sid": session_id},
    ).fetchone()
    if not row:
        return _with_deprecation(
            (jsonify({"error": "Session not found"}), 404),
            f"/api/v1/sessions/{session_id}/fingerprint",
        )
    sess = dict(row)

    # Build input data from scoring sub-scores and analysis results
    session_data = {
        "session_id": session_id,
        "driver_name": "",
    }

    # Resolve driver name
    if sess.get("driver_id"):
        dr = conn.execute(
            "SELECT driver_name FROM drivers WHERE driver_id = :did",
            {"did": sess["driver_id"]},
        ).fetchone()
        if dr:
            session_data["driver_name"] = dr["driver_name"]

    # Score sub-components from score_details table
    scoring_row = conn.execute(
        "SELECT * FROM score_details WHERE session_id = :sid",
        {"sid": session_id},
    ).fetchone()
    if scoring_row:
        sd = dict(scoring_row)
        # Compute percentages: score / max * 100
        if sd.get("pace_score") is not None and sd.get("pace_max") and sd["pace_max"] > 0:
            session_data["pace_pct"] = sd["pace_score"] / sd["pace_max"] * 100
        if sd.get("consistency_score") is not None and sd.get("consistency_max") and sd["consistency_max"] > 0:
            session_data["consistency_pct"] = sd["consistency_score"] / sd["consistency_max"] * 100
        if sd.get("robustness_score") is not None and sd.get("robustness_max") and sd["robustness_max"] > 0:
            session_data["robustness_pct"] = sd["robustness_score"] / sd["robustness_max"] * 100
        if sd.get("execution_score") is not None and sd.get("execution_max") and sd["execution_max"] > 0:
            session_data["execution_pct"] = sd["execution_score"] / sd["execution_max"] * 100
        if sd.get("adaptation_score") is not None:
            session_data["adaptation_score"] = sd["adaptation_score"]

    # Fallback: estimate from total_score if sub-scores unavailable
    if not session_data.get("pace_pct") and sess.get("total_score"):
        session_data["pace_pct"] = sess["total_score"]

    # Pace fade from stint analysis
    stint_rows = conn.execute(
        "SELECT pace_fade_pct FROM stint_analysis WHERE session_id = :sid ORDER BY stint_number",
        {"sid": session_id},
    ).fetchall()
    if stint_rows:
        fades = [r["pace_fade_pct"] for r in stint_rows if r["pace_fade_pct"] is not None]
        session_data["pace_fade_pct"] = sum(fades) / len(fades) if fades else 0.0

    # Concentration index from laps data (fatigue proxy)
    try:
        laps = conn.execute(
            "SELECT * FROM laps WHERE session_id = :sid ORDER BY lap_number",
            {"sid": session_id},
        ).fetchall()
        if laps and len(laps) >= 4:
            try:
                from fatigue_detection import analyze_fatigue
                fatigue = analyze_fatigue([dict(l) for l in laps])
                if isinstance(fatigue, dict):
                    session_data["concentration_index"] = fatigue.get(
                        "concentration_index", 50.0
                    )
                else:
                    session_data["concentration_index"] = getattr(
                        fatigue, "concentration_index", 50.0
                    )
            except Exception:
                pass
    except Exception:
        pass

    # Adaptation score from driving style features
    try:
        style_row = conn.execute(
            "SELECT * FROM driving_style_features WHERE session_id = :sid",
            {"sid": session_id},
        ).fetchone()
        if style_row:
            sd2 = dict(style_row)
            if sd2.get("smoothness_composite") is not None:
                session_data["adaptation_score"] = sd2["smoothness_composite"]
    except Exception:
        pass  # Table may not exist

    try:
        from performance_fingerprint import compute_fingerprint
        fp = compute_fingerprint(session_data)
        return _with_deprecation(
            jsonify(fp.to_dict()),
            f"/api/v1/sessions/{session_id}/fingerprint",
        )
    except ImportError:
        return _with_deprecation(
            (jsonify({"error": "performance_fingerprint module not available"}), 500),
            f"/api/v1/sessions/{session_id}/fingerprint",
        )


# ------------------------------------------------------------------
# Pit Window Calculator API
# ------------------------------------------------------------------

@bp.route("/session/<session_id>/pit-window")
def api_pit_window(session_id: str):
    """Return optimal pit window analysis for a session."""
    conn = get_db_connection()
    row = conn.execute(
        "SELECT * FROM sessions WHERE session_id = :sid",
        {"sid": session_id},
    ).fetchone()
    if not row:
        return jsonify({"error": "Session not found"}), 404

    # Gather stint data
    stints: list[list[float]] = []

    # Try stint_analysis table first for stint boundaries
    stint_rows = conn.execute(
        """SELECT stint_number, lap_start, lap_end
           FROM stint_analysis
           WHERE session_id = :sid
           ORDER BY stint_number""",
        {"sid": session_id},
    ).fetchall()

    lap_rows = conn.execute(
        """SELECT lap_number, lap_time_s
           FROM laps
           WHERE session_id = :sid AND is_valid = 1
           ORDER BY lap_number""",
        {"sid": session_id},
    ).fetchall()
    lap_map = {r["lap_number"]: r["lap_time_s"] for r in lap_rows if r["lap_time_s"]}

    if stint_rows:
        for sr in stint_rows:
            stint_laps = []
            for lap_n in range(sr["lap_start"], sr["lap_end"] + 1):
                t = lap_map.get(lap_n)
                if t is not None:
                    stint_laps.append(t)
            if stint_laps:
                stints.append(stint_laps)
    else:
        # Single stint: all valid laps
        all_times = [lap_map[k] for k in sorted(lap_map.keys())]
        if all_times:
            stints.append(all_times)

    # Parameters from query string
    pit_loss = request.args.get("pit_loss_s", 25.0, type=float)
    race_laps = request.args.get("race_laps", 0, type=int)

    try:
        from pit_window import compute_optimal_window
        result = compute_optimal_window(
            stints, pit_loss_s=pit_loss, race_laps=race_laps
        )
        d = result.to_dict()
        d["session_id"] = session_id
        return jsonify(d)
    except ImportError:
        return jsonify({"error": "pit_window module not available"}), 500


# ------------------------------------------------------------------
# Race Pace Predictor API
# ------------------------------------------------------------------

@bp.route("/session/<session_id>/pace-prediction")
def api_pace_prediction(session_id: str):
    """Return race pace prediction for a session."""
    conn = get_db_connection()
    row = conn.execute(
        "SELECT * FROM sessions WHERE session_id = :sid",
        {"sid": session_id},
    ).fetchone()
    if not row:
        return jsonify({"error": "Session not found"}), 404
    sess = dict(row)

    # Gather lap times
    lap_rows = conn.execute(
        """SELECT lap_number, lap_time_s
           FROM laps
           WHERE session_id = :sid AND is_valid = 1
           ORDER BY lap_number""",
        {"sid": session_id},
    ).fetchall()
    lap_times = [r["lap_time_s"] for r in lap_rows if r["lap_time_s"]]

    race_laps = request.args.get("race_laps", 0, type=int)
    if race_laps <= 0:
        race_laps = max(len(lap_times) * 2, 20)

    # Get historical data for same track
    historical = []
    if sess.get("track_id"):
        hist_rows = conn.execute(
            """SELECT s.session_id, s.best_lap_time_s, s.mean_lap_time_s,
                      COALESCE(d.driver_name, 'Unknown') AS driver_name
               FROM sessions s
               LEFT JOIN drivers d ON s.driver_id = d.driver_id
               WHERE s.track_id = :tid
                 AND s.session_id != :sid
                 AND s.best_lap_time_s IS NOT NULL
               ORDER BY s.session_date DESC
               LIMIT 20""",
            {"tid": sess["track_id"], "sid": session_id},
        ).fetchall()
        for hr in hist_rows:
            hd = dict(hr)
            historical.append({
                "driver_name": hd.get("driver_name", ""),
                "best_lap_time_s": hd.get("best_lap_time_s"),
                "mean_lap_time_s": hd.get("mean_lap_time_s"),
            })

    try:
        from race_pace_predictor import predict_race_result
        session_data = {
            "lap_times": lap_times,
            "driver_name": sess.get("driver_name", ""),
        }
        # Resolve driver name
        if sess.get("driver_id"):
            dr = conn.execute(
                "SELECT driver_name FROM drivers WHERE driver_id = :did",
                {"did": sess["driver_id"]},
            ).fetchone()
            if dr:
                session_data["driver_name"] = dr["driver_name"]

        result = predict_race_result(session_data, historical, race_laps)
        d = result.to_dict()
        d["session_id"] = session_id
        return jsonify(d)
    except ImportError:
        return jsonify({"error": "race_pace_predictor module not available"}), 500


# ------------------------------------------------------------------
# Race Pace Simulator API (user-driven)
# ------------------------------------------------------------------

@bp.route("/session/<session_id>/simulate-race", methods=["POST"])
def api_simulate_race(session_id: str):
    """Run a deterministic race simulation with user-defined parameters."""
    conn = get_db_connection()
    row = conn.execute(
        "SELECT * FROM sessions WHERE session_id = :sid",
        {"sid": session_id},
    ).fetchone()
    if not row:
        return jsonify({"error": "Session not found"}), 404

    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    try:
        from race_simulator import SimulationParams, simulate_race

        params = SimulationParams(
            race_laps=int(data.get("race_laps", 25)),
            pit_stop_loss_s=float(data.get("pit_stop_loss_s", 30.0)),
            num_pit_stops=int(data.get("num_pit_stops", 1)),
            tire_deg_rate_s=float(data.get("tire_deg_rate_s", 0.05)),
            fuel_effect_s=float(data.get("fuel_effect_s", 0.0)),
            target_lap_time_s=float(data.get("target_lap_time_s", 62.0)),
            consistency_cv_pct=float(data.get("consistency_cv_pct", 1.5)),
            fatigue_onset_lap=int(data.get("fatigue_onset_lap", 18)),
            stint_length=int(data.get("stint_length", 12)),
            traffic_penalty_s=float(data.get("traffic_penalty_s", 0.3)),
        )

        result = simulate_race(params)
        d = result.to_dict()
        d["session_id"] = session_id
        return jsonify(d)
    except (ValueError, TypeError) as exc:
        return jsonify({"error": f"Invalid parameter: {exc}"}), 400
    except ImportError:
        return jsonify({"error": "race_simulator module not available"}), 500


# ------------------------------------------------------------------
# Session Replay Timeline API
# ------------------------------------------------------------------

@bp.route("/session/<session_id>/timeline")
def api_session_timeline(session_id: str):
    """Return session replay timeline with events."""
    conn = get_db_connection()
    row = conn.execute(
        "SELECT * FROM sessions WHERE session_id = :sid",
        {"sid": session_id},
    ).fetchone()
    if not row:
        return jsonify({"error": "Session not found"}), 404
    sess = dict(row)

    # Gather laps
    lap_rows = conn.execute(
        """SELECT lap_number, lap_time_s, is_valid
           FROM laps
           WHERE session_id = :sid
           ORDER BY lap_number""",
        {"sid": session_id},
    ).fetchall()
    laps = [dict(r) for r in lap_rows]

    # Resolve driver name
    session_info = {"session_id": session_id, "driver_name": ""}
    if sess.get("driver_id"):
        dr = conn.execute(
            "SELECT driver_name FROM drivers WHERE driver_id = :did",
            {"did": sess["driver_id"]},
        ).fetchone()
        if dr:
            session_info["driver_name"] = dr["driver_name"]

    try:
        from session_replay import build_session_timeline
        tl = build_session_timeline(laps, session_info)
        return jsonify(tl.to_dict())
    except ImportError:
        return jsonify({"error": "session_replay module not available"}), 500


# ------------------------------------------------------------------
# Sector Performance Analysis API
# ------------------------------------------------------------------

@bp.route("/session/<session_id>/sector-analysis")
def api_sector_analysis(session_id: str):
    """Return sector-level performance analysis."""
    conn = get_db_connection()
    row = conn.execute(
        "SELECT * FROM sessions WHERE session_id = :sid",
        {"sid": session_id},
    ).fetchone()
    if not row:
        return jsonify({"error": "Session not found"}), 404

    n_sectors = request.args.get("n_sectors", 3, type=int)
    n_sectors = max(2, min(6, n_sectors))  # clamp 2-6

    lap_rows = conn.execute(
        """SELECT lap_number, lap_time_s
           FROM laps
           WHERE session_id = :sid AND is_valid = 1
           ORDER BY lap_number""",
        {"sid": session_id},
    ).fetchall()

    lap_times = [r["lap_time_s"] for r in lap_rows if r["lap_time_s"] is not None]
    lap_numbers = [r["lap_number"] for r in lap_rows]

    if not lap_times:
        return jsonify({"error": "No valid lap data"}), 404

    try:
        from sector_analysis import analyze_sector_performance
        result = analyze_sector_performance(
            lap_times, n_sectors=n_sectors, lap_numbers=lap_numbers
        )
        d = result.to_dict()
        d["session_id"] = session_id
        return jsonify(d)
    except ImportError:
        return jsonify({"error": "sector_analysis module not available"}), 500


# ------------------------------------------------------------------
# Tyre Compound Comparator API
# ------------------------------------------------------------------

@bp.route("/session/<session_id>/tyre-analysis")
def api_tyre_analysis(session_id: str):
    """Return tyre compound comparison for a session."""
    conn = get_db_connection()
    row = conn.execute(
        "SELECT * FROM sessions WHERE session_id = :sid",
        {"sid": session_id},
    ).fetchone()
    if not row:
        return jsonify({"error": "Session not found"}), 404

    lap_rows = conn.execute(
        """SELECT lap_number, lap_time_s
           FROM laps
           WHERE session_id = :sid AND is_valid = 1
           ORDER BY lap_number""",
        {"sid": session_id},
    ).fetchall()

    lap_times = [r["lap_time_s"] for r in lap_rows if r["lap_time_s"] is not None]
    lap_numbers = [r["lap_number"] for r in lap_rows]

    if not lap_times:
        return jsonify({"error": "No valid lap data"}), 404

    try:
        from tyre_comparator import analyze_tyre_performance
        result = analyze_tyre_performance(lap_times, lap_numbers)
        d = result.to_dict()
        d["session_id"] = session_id
        return jsonify(d)
    except ImportError:
        return jsonify({"error": "tyre_comparator module not available"}), 500


# ------------------------------------------------------------------
# Session Summary Report (Cycle 20)
# ------------------------------------------------------------------

@bp.route("/session/<session_id>/summary-report")
def api_summary_report(session_id: str):
    """Return comprehensive session summary report."""
    conn = get_db_connection()
    row = conn.execute(
        "SELECT s.*, COALESCE(d.driver_name, 'Unknown') AS driver_name FROM sessions s "
        "LEFT JOIN drivers d ON s.driver_id = d.driver_id "
        "WHERE s.session_id = :sid",
        {"sid": session_id},
    ).fetchone()
    if not row:
        return jsonify({"error": "Session not found"}), 404

    lap_rows = conn.execute(
        """SELECT lap_number, lap_time_s
           FROM laps
           WHERE session_id = :sid AND is_valid = 1
           ORDER BY lap_number""",
        {"sid": session_id},
    ).fetchall()

    # Get score
    score_row = conn.execute(
        """SELECT pace_score, consistency_score, execution_score, robustness_score
           FROM score_details WHERE session_id = :sid""",
        {"sid": session_id},
    ).fetchone()
    total_score = 0.0
    if score_row:
        total_score = sum(
            float(score_row[k] or 0)
            for k in ("pace_score", "consistency_score",
                      "execution_score", "robustness_score")
        )

    if not lap_rows:
        return jsonify({"error": "No valid lap data"}), 404

    try:
        from session_summary import generate_session_summary
        data = {
            "session_id": session_id,
            "driver_name": row["driver_name"],
            "session_date": row["session_date"] or "",
            "session_type": row["session_type"] or "",
            "lap_times": [r["lap_time_s"] for r in lap_rows],
            "total_score": total_score,
        }
        result = generate_session_summary(data)
        return jsonify(result.to_dict())
    except ImportError:
        return jsonify({"error": "session_summary module not available"}), 500


# ------------------------------------------------------------------
# Driving Style (Redesign — JS-rendered)
# ------------------------------------------------------------------

_STYLE_FEATURES = [
    # (db_key, human_label, hint, inverted, coaching_tips_by_tier)
    ("trail_braking_depth", "Trail Braking",
     "How deep into corners you maintain brake pressure \u2014 higher means more trail braking",
     False, {
         "low": "Start introducing trail braking: maintain light brake into corner entry",
         "below_avg": "Good awareness \u2014 try holding brake pressure 5m deeper into corners",
         "average": "Solid trail braking \u2014 extend pressure deeper through mid-corner",
         "good": "Strong trail braking technique \u2014 fine-tune release rate for smoother rotation",
         "elite": "Excellent trail braking depth \u2014 focus on consistency across all corners",
     }),
    ("brake_point_consistency", "Brake Consistency",
     "How repeatable your braking points are from lap to lap",
     False, {
         "low": "Pick a fixed reference point for each braking zone and hit it every lap",
         "below_avg": "Focus on the 2\u20133 corners where your braking varies most",
         "average": "Decent consistency \u2014 work on matching braking points in long stints",
         "good": "Consistent braker \u2014 refine the last 5% with marker-based braking",
         "elite": "Machine-like consistency \u2014 maintain this through varying conditions",
     }),
    ("brake_pressure_buildup_rate", "Brake Attack",
     "How quickly you build peak brake pressure \u2014 higher means sharper initial braking",
     False, {
         "low": "Practice building brake pressure faster \u2014 firm initial hit then modulate",
         "below_avg": "Try a crisper initial stab \u2014 aim for peak pressure within 0.2s",
         "average": "Reasonable brake attack \u2014 work on faster initial application",
         "good": "Strong brake attack \u2014 make sure it stays controlled at corner entry",
         "elite": "Excellent brake attack rate \u2014 top-tier initial application",
     }),
    ("apex_speed_ratio", "Apex Speed",
     "Corner speed relative to optimal \u2014 higher means faster through apexes",
     False, {
         "low": "You are over-slowing mid-corner \u2014 carry more speed past the apex",
         "below_avg": "Try carrying 2\u20133 km/h more through the apex on medium-speed corners",
         "average": "Reasonable apex speed \u2014 focus on the slowest corners for easy gains",
         "good": "Strong mid-corner speed \u2014 fine-tune the last km/h with smoother turn-in",
         "elite": "Exceptional apex speed \u2014 you are maximizing corner velocity",
     }),
    ("turn_in_aggressiveness", "Turn-in Aggression",
     "How sharply you initiate steering input into corners",
     False, {
         "low": "Be more decisive with initial steering \u2014 commit to the turn earlier",
         "below_avg": "Try a slightly quicker steering input at corner entry",
         "average": "Balanced turn-in \u2014 experiment with sharper input on slow corners",
         "good": "Assertive turn-in \u2014 ensure it matches your trail braking depth",
         "elite": "Aggressive and precise \u2014 great commitment to corner entry",
     }),
    ("throttle_onset_delay_m", "Throttle Pickup",
     "Distance after apex before getting on throttle \u2014 lower delay means quicker pickup",
     True, {
         "low": "Excellent throttle pickup \u2014 you are on the gas early and decisively",
         "below_avg": "Good throttle pickup \u2014 you get on power promptly after the apex",
         "average": "Reasonable pickup \u2014 try applying throttle 2\u20133m earlier on exit",
         "good": "Late to throttle \u2014 focus on earlier, progressive throttle application",
         "elite": "Very late throttle pickup \u2014 work on getting on power sooner after apex",
     }),
    ("exit_acceleration_efficiency", "Exit Drive",
     "How effectively you convert throttle application to speed on corner exit",
     False, {
         "low": "Focus on smooth, progressive throttle to avoid wheelspin on exit",
         "below_avg": "Work on straightening the wheel before applying full throttle",
         "average": "Decent exit drive \u2014 unwind the steering earlier for better traction",
         "good": "Strong exit drive \u2014 fine-tune throttle progressivity for the last 2%",
         "elite": "Excellent exit efficiency \u2014 top-tier corner exit performance",
     }),
    ("line_variation_index", "Line Variation",
     "How much your racing line changes between laps \u2014 lower means more consistent lines",
     True, {
         "low": "Razor-consistent lines \u2014 excellent repeatability lap after lap",
         "below_avg": "Good line consistency \u2014 minor variations are normal",
         "average": "Moderate variation \u2014 pick a reference line and stick to it",
         "good": "Noticeable line variation \u2014 study the fastest lap and replicate that line",
         "elite": "High line variation \u2014 focus on following the same path each lap",
     }),
    ("early_vs_late_stint_pace", "Stint Endurance",
     "Pace balance between early and late laps \u2014 closer to 0.50 means steadier performance",
     False, {
         "low": "Significant pace drop-off in late stint \u2014 work on physical endurance",
         "below_avg": "Noticeable fade \u2014 try conserving energy in early laps",
         "average": "Some late-stint fade \u2014 focus on mental consistency in final laps",
         "good": "Steady stint pace \u2014 good endurance management",
         "elite": "Excellent endurance \u2014 virtually no pace drop across the stint",
     }),
    # Smoothness suppressed from display — computation kept for internal use
]


def _qualify_value(val, inverted):
    """Map a 0\u20131 feature value to a qualitative tier."""
    if val is None:
        return "unknown", "Unknown"
    if inverted:
        if val <= 0.20:
            return "elite", "Elite"
        elif val <= 0.40:
            return "good", "Good"
        elif val <= 0.60:
            return "average", "Moderate"
        elif val <= 0.80:
            return "below_avg", "Below Avg"
        else:
            return "low", "Low"
    else:
        if val >= 0.80:
            return "elite", "Elite"
        elif val >= 0.60:
            return "good", "Good"
        elif val >= 0.40:
            return "average", "Moderate"
        elif val >= 0.20:
            return "below_avg", "Below Avg"
        else:
            return "low", "Low"


_TIER_TO_RATING = {
    "elite": "excellent",
    "good": "good",
    "average": "average",
    "below_avg": "needs_work",
    "low": "needs_work",
    "unknown": "average",
}

_STYLE_DESCRIPTIONS = {
    "smooth": "Fluid, progressive inputs with excellent control blending",
    "aggressive": "Committed, sharp inputs with decisive corner attack",
    "conservative": "Cautious, margin-focused approach prioritizing consistency",
    "adaptive": "Flexible style that adjusts to changing conditions",
}


@bp.route("/session/<session_id>/driving-style")
def api_driving_style(session_id: str):
    """Return enriched driving style features with qualitative labels and coaching tips."""
    conn = get_db_connection()

    row = conn.execute(
        "SELECT driver_id FROM sessions WHERE session_id = :sid",
        {"sid": session_id},
    ).fetchone()
    if not row:
        return jsonify({"error": "Session not found"}), 404
    if not row["driver_id"]:
        return jsonify({"error": "No driver linked to session"}), 404

    from web.models import get_driving_style
    style = get_driving_style(conn, row["driver_id"], session_id)
    if not style:
        # Fallback: driver may have been reassigned after analysis ran.
        # Try session_id-only lookup since it uniquely identifies the data.
        fb = conn.execute(
            "SELECT * FROM driving_style_features WHERE session_id = :sid",
            {"sid": session_id},
        ).fetchone()
        if fb:
            style = dict(fb)
            style["strengths"] = json.loads(style.get("strengths_json") or "[]")
            style["weaknesses"] = json.loads(style.get("weaknesses_json") or "[]")
    if not style:
        return jsonify({"error": "No driving style data for this session"}), 404

    features = []
    radar_labels = []
    radar_values = []
    for db_key, label, hint, inverted, tips in _STYLE_FEATURES:
        val = style.get(db_key)
        tier_key, tier_label = _qualify_value(val, inverted)
        tip = tips.get(tier_key, "")
        rating = _TIER_TO_RATING.get(tier_key, "average")
        features.append({
            "key": db_key,
            "label": label,
            "value": round(val, 3) if val is not None else None,
            "qualitative": tier_label,
            "rating": rating,
            "hint": hint,
            "tip": tip,
            "inverted": inverted,
        })
        radar_labels.append(label)
        radar_values.append(round(val, 3) if val is not None else 0)

    style_label = style.get("style_label") or "Unknown"
    style_key = style_label.lower().replace(" ", "_")
    style_desc = _STYLE_DESCRIPTIONS.get(style_key, "")

    return jsonify({
        "session_id": session_id,
        "style_label": style_label,
        "style_description": style_desc,
        "style_confidence": round(style.get("style_confidence") or 0, 2),
        "features": features,
        "strengths": style.get("strengths", []),
        "weaknesses": style.get("weaknesses", []),
        "radar_labels": radar_labels,
        "radar_values": radar_values,
    })


# ------------------------------------------------------------------
# Workload Estimator (Cycle 19)
# ------------------------------------------------------------------

@bp.route("/session/<session_id>/workload")
def api_workload(session_id: str):
    """Return driver workload estimation for a session."""
    conn = get_db_connection()
    row = conn.execute(
        "SELECT * FROM sessions WHERE session_id = :sid",
        {"sid": session_id},
    ).fetchone()
    if not row:
        return jsonify({"error": "Session not found"}), 404

    lap_rows = conn.execute(
        """SELECT lap_number, lap_time_s
           FROM laps
           WHERE session_id = :sid AND is_valid = 1
           ORDER BY lap_number""",
        {"sid": session_id},
    ).fetchall()

    lap_times = [r["lap_time_s"] for r in lap_rows if r["lap_time_s"] is not None]
    lap_numbers = [r["lap_number"] for r in lap_rows]

    if not lap_times:
        return jsonify({"error": "No valid lap data"}), 404

    try:
        from workload_estimator import estimate_workload
        result = estimate_workload(lap_times, lap_numbers)
        d = result.to_dict()
        d["session_id"] = session_id
        return jsonify(d)
    except ImportError:
        return jsonify({"error": "workload_estimator module not available"}), 500


# ------------------------------------------------------------------
# Session Badges (Cycle 18)
# ------------------------------------------------------------------

@bp.route("/session/<session_id>/badges")
def api_session_badges(session_id: str):
    """Return session badges and rating."""
    conn = get_db_connection()
    row = conn.execute(
        "SELECT * FROM sessions WHERE session_id = :sid",
        {"sid": session_id},
    ).fetchone()
    if not row:
        return jsonify({"error": "Session not found"}), 404

    lap_rows = conn.execute(
        """SELECT lap_number, lap_time_s
           FROM laps
           WHERE session_id = :sid AND is_valid = 1
           ORDER BY lap_number""",
        {"sid": session_id},
    ).fetchall()

    lap_times = [r["lap_time_s"] for r in lap_rows if r["lap_time_s"] is not None]

    if not lap_times:
        return jsonify({"error": "No valid lap data"}), 404

    try:
        from session_badges import compute_session_badges
        result = compute_session_badges(lap_times)
        d = result.to_dict()
        d["session_id"] = session_id
        return jsonify(d)
    except ImportError:
        return jsonify({"error": "session_badges module not available"}), 500


# ------------------------------------------------------------------
# Lap Progress (Cycle 17)
# ------------------------------------------------------------------

@bp.route("/session/<session_id>/lap-progress")
def api_lap_progress(session_id: str):
    """Return lap-over-lap progress tracking for a session."""
    conn = get_db_connection()
    row = conn.execute(
        "SELECT * FROM sessions WHERE session_id = :sid",
        {"sid": session_id},
    ).fetchone()
    if not row:
        return jsonify({"error": "Session not found"}), 404

    lap_rows = conn.execute(
        """SELECT lap_number, lap_time_s
           FROM laps
           WHERE session_id = :sid AND is_valid = 1
           ORDER BY lap_number""",
        {"sid": session_id},
    ).fetchall()

    lap_times = [r["lap_time_s"] for r in lap_rows if r["lap_time_s"] is not None]
    lap_numbers = [r["lap_number"] for r in lap_rows if r["lap_time_s"] is not None]

    if not lap_times:
        return jsonify({"error": "No valid lap data"}), 404

    try:
        from lap_progress import analyze_lap_progress
        result = analyze_lap_progress(lap_times, lap_numbers)
        d = result.to_dict()
        d["session_id"] = session_id
        return jsonify(d)
    except ImportError:
        return jsonify({"error": "lap_progress module not available"}), 500


# ------------------------------------------------------------------
# Energy Balance (Cycle 16)
# ------------------------------------------------------------------

@bp.route("/session/<session_id>/energy-balance")
def api_energy_balance(session_id: str):
    """Return energy balance analysis for a session."""
    conn = get_db_connection()
    row = conn.execute(
        "SELECT * FROM sessions WHERE session_id = :sid",
        {"sid": session_id},
    ).fetchone()
    if not row:
        return jsonify({"error": "Session not found"}), 404

    lap_rows = conn.execute(
        """SELECT lap_number, lap_time_s
           FROM laps
           WHERE session_id = :sid AND is_valid = 1
           ORDER BY lap_number""",
        {"sid": session_id},
    ).fetchall()

    lap_times = [r["lap_time_s"] for r in lap_rows if r["lap_time_s"] is not None]
    lap_numbers = [r["lap_number"] for r in lap_rows if r["lap_time_s"] is not None]

    if not lap_times:
        return jsonify({"error": "No valid lap data"}), 404

    try:
        from energy_balance import analyze_energy_balance
        result = analyze_energy_balance(lap_times, lap_numbers)
        d = result.to_dict()
        d["session_id"] = session_id
        return jsonify(d)
    except ImportError:
        return jsonify({"error": "energy_balance module not available"}), 500


# ------------------------------------------------------------------
# Speed Profile (Cycle 15)
# ------------------------------------------------------------------

@bp.route("/session/<session_id>/speed-profile")
def api_speed_profile(session_id: str):
    """Return track segment speed profile for a session."""
    conn = get_db_connection()
    row = conn.execute(
        "SELECT * FROM sessions WHERE session_id = :sid",
        {"sid": session_id},
    ).fetchone()
    if not row:
        return _with_deprecation(
            (jsonify({"error": "Session not found"}), 404),
            f"/api/v1/sessions/{session_id}/speed-profile",
        )

    lap_rows = conn.execute(
        """SELECT lap_number, lap_time_s
           FROM laps
           WHERE session_id = :sid AND is_valid = 1
           ORDER BY lap_number""",
        {"sid": session_id},
    ).fetchall()

    lap_times = [r["lap_time_s"] for r in lap_rows if r["lap_time_s"] is not None]
    lap_numbers = [r["lap_number"] for r in lap_rows]

    try:
        from speed_profile import analyze_speed_profile
        result = analyze_speed_profile(lap_times, lap_numbers)
        d = result.to_dict()
        d["session_id"] = session_id
        return _with_deprecation(
            jsonify(d),
            f"/api/v1/sessions/{session_id}/speed-profile",
        )
    except ImportError:
        return _with_deprecation(
            (jsonify({"error": "speed_profile module not available"}), 500),
            f"/api/v1/sessions/{session_id}/speed-profile",
        )


# ------------------------------------------------------------------
# Lap Time Distribution (Cycle 14)
# ------------------------------------------------------------------

@bp.route("/session/<session_id>/lap-distribution")
def api_lap_distribution(session_id: str):
    """Return lap time distribution analysis for a session."""
    conn = get_db_connection()
    row = conn.execute(
        "SELECT * FROM sessions WHERE session_id = :sid",
        {"sid": session_id},
    ).fetchone()
    if not row:
        return jsonify({"error": "Session not found"}), 404

    lap_rows = conn.execute(
        """SELECT lap_number, lap_time_s
           FROM laps
           WHERE session_id = :sid AND is_valid = 1
           ORDER BY lap_number""",
        {"sid": session_id},
    ).fetchall()

    lap_times = [r["lap_time_s"] for r in lap_rows if r["lap_time_s"] is not None]
    lap_numbers = [r["lap_number"] for r in lap_rows]

    try:
        from lap_distribution import analyze_lap_distribution
        result = analyze_lap_distribution(lap_times, lap_numbers)
        d = result.to_dict()
        d["session_id"] = session_id
        return jsonify(d)
    except ImportError:
        return jsonify({"error": "lap_distribution module not available"}), 500


# ------------------------------------------------------------------
# Session Comparison Matrix (Cycle 13)
# ------------------------------------------------------------------

@bp.route("/session/<session_id>/comparison-matrix")
def api_comparison_matrix(session_id: str):
    """Return comparison matrix for the given session vs recent sessions on the same track."""
    conn = get_db_connection()
    row = conn.execute(
        "SELECT s.*, COALESCE(d.driver_name, 'Unknown') AS driver_name "
        "FROM sessions s "
        "LEFT JOIN drivers d ON s.driver_id = d.driver_id "
        "WHERE s.session_id = :sid",
        {"sid": session_id},
    ).fetchone()
    if not row:
        return jsonify({"error": "Session not found"}), 404

    track_id = row["track_id"]
    driver_id = row["driver_id"]

    # Find recent sessions on the same track (any driver, up to 8)
    peer_rows = conn.execute(
        """SELECT s.*, COALESCE(d.driver_name, 'Unknown') AS driver_name
           FROM sessions s
           LEFT JOIN drivers d ON s.driver_id = d.driver_id
           WHERE s.track_id = :track
           ORDER BY s.session_date DESC, s.session_id
           LIMIT 8""",
        {"track": track_id},
    ).fetchall()

    if len(peer_rows) < 1:
        return jsonify({"error": "No sessions to compare"}), 200

    try:
        from session_comparison import build_comparison_matrix

        raw_data_list = []
        for pr in peer_rows:
            # Get lap stats
            lap_data = conn.execute(
                """SELECT lap_time_s FROM laps
                   WHERE session_id = :sid AND is_valid = 1
                   ORDER BY lap_number""",
                {"sid": pr["session_id"]},
            ).fetchall()
            lap_times = [r["lap_time_s"] for r in lap_data if r["lap_time_s"]]

            # Get score (compute total from components)
            score_row = conn.execute(
                """SELECT pace_score, consistency_score, execution_score, robustness_score
                   FROM score_details WHERE session_id = :sid""",
                {"sid": pr["session_id"]},
            ).fetchone()
            total_score = 0.0
            if score_row:
                total_score = sum(
                    float(score_row[k] or 0)
                    for k in ("pace_score", "consistency_score",
                              "execution_score", "robustness_score")
                )

            raw_data_list.append({
                "session_id": pr["session_id"],
                "driver_name": pr["driver_name"],
                "session_date": pr["session_date"] or "",
                "session_type": pr["session_type"] or "",
                "n_laps": len(lap_times),
                "best_lap_time_s": min(lap_times) if lap_times else 0,
                "mean_lap_time_s": float(np.mean(lap_times)) if lap_times else 0,
                "total_score": total_score,
            })

        matrix = build_comparison_matrix(raw_data_list)
        d = matrix.to_dict()
        d["focus_session_id"] = session_id
        return jsonify(d)
    except ImportError:
        return jsonify({"error": "session_comparison module not available"}), 500


# ------------------------------------------------------------------
# Weather correlation API (Feature #7)
# ------------------------------------------------------------------

@bp.route("/weather-correlation/<track_id>")
def api_weather_correlation(track_id: str):
    """Return weather-pace correlation data for a track."""
    conn = get_db_connection()
    driver_id = request.args.get("driver_id", type=int)

    if driver_id:
        rows = conn.execute(
            """SELECT sw.*, s.best_lap_time_s, s.session_date, s.session_type,
                      COALESCE(d.driver_name, 'Unknown') AS driver_name
               FROM session_weather sw
               JOIN sessions s ON sw.session_id = s.session_id
               LEFT JOIN drivers d ON s.driver_id = d.driver_id
               WHERE s.track_id = :track_id AND s.driver_id = :driver_id
               ORDER BY s.session_date""",
            {"track_id": track_id, "driver_id": driver_id},
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT sw.*, s.best_lap_time_s, s.session_date, s.session_type,
                      COALESCE(d.driver_name, 'Unknown') AS driver_name
               FROM session_weather sw
               JOIN sessions s ON sw.session_id = s.session_id
               LEFT JOIN drivers d ON s.driver_id = d.driver_id
               WHERE s.track_id = :track_id
               ORDER BY s.session_date""",
            {"track_id": track_id},
        ).fetchall()

    if not rows:
        return jsonify({"error": "No weather data for this track"}), 404

    # Minimum session guard — need at least 5 sessions for meaningful correlation
    MIN_SESSIONS_FOR_CORRELATION = 5
    if len(rows) < MIN_SESSIONS_FOR_CORRELATION:
        return jsonify({
            "error": "insufficient_sessions",
            "message": (
                f"Need at least {MIN_SESSIONS_FOR_CORRELATION} sessions with weather data "
                f"for meaningful correlation analysis. Currently have {len(rows)} session(s). "
                f"Analyse more sessions on this track to unlock weather-pace insights."
            ),
            "session_count": len(rows),
            "min_required": MIN_SESSIONS_FOR_CORRELATION,
        }), 200  # Return 200 so frontend can handle gracefully

    try:
        from weather_correlation import compute_weather_pace_correlation
        data = [dict(r) for r in rows]
        result = compute_weather_pace_correlation(data)
        result["track_id"] = track_id
        return jsonify(result)
    except ImportError:
        return jsonify({"error": "weather_correlation module not available"}), 500


# ------------------------------------------------------------------
# Trend analysis API (Feature #8)
# ------------------------------------------------------------------

@bp.route("/trends/<int:driver_id>")
def api_trends(driver_id: int):
    """Return pace trend analysis for a driver."""
    conn = get_db_connection()
    track_id = request.args.get("track_id")

    query = """
        SELECT s.session_id, s.session_date, s.best_lap_time_s,
               s.total_score, s.session_type, t.track_name
        FROM sessions s
        LEFT JOIN tracks t ON s.track_id = t.track_id
        WHERE s.driver_id = :driver_id
          AND s.best_lap_time_s IS NOT NULL
    """
    params: dict = {"driver_id": driver_id}
    if track_id:
        query += " AND s.track_id = :track_id"
        params["track_id"] = track_id
    query += " ORDER BY s.session_date"

    rows = conn.execute(query, params).fetchall()
    if not rows:
        return jsonify({"error": "No sessions found"}), 404

    # Minimum session guard — need at least 3 sessions for trend analysis
    MIN_SESSIONS_FOR_TREND = 3
    if len(rows) < MIN_SESSIONS_FOR_TREND:
        return jsonify({
            "error": "insufficient_sessions",
            "message": (
                f"Need at least {MIN_SESSIONS_FOR_TREND} sessions for meaningful trend analysis. "
                f"Currently have {len(rows)} session(s). "
                f"Analyse more sessions to unlock pace trend insights."
            ),
            "session_count": len(rows),
            "min_required": MIN_SESSIONS_FOR_TREND,
        }), 200

    try:
        from trend_analysis import compute_multi_session_trend
        data = [dict(r) for r in rows]
        result = compute_multi_session_trend(data)
        result["driver_id"] = driver_id
        return jsonify(result)
    except ImportError:
        return jsonify({"error": "trend_analysis module not available"}), 500


# ------------------------------------------------------------------
# Rival comparison API (Feature #9)
# ------------------------------------------------------------------

@bp.route("/rivals/compare")
def api_rivals_compare():
    """Compare multiple drivers on the same track."""
    track_id = request.args.get("track_id")
    driver_ids_str = request.args.get("driver_ids", "")
    if not track_id or not driver_ids_str:
        return jsonify({"error": "track_id and driver_ids required"}), 400

    try:
        driver_ids = [int(x.strip()) for x in driver_ids_str.split(",") if x.strip()]
    except ValueError:
        return jsonify({"error": "invalid driver_ids"}), 400

    if len(driver_ids) < 2 or len(driver_ids) > 5:
        return jsonify({"error": "select 2–5 drivers"}), 400

    conn = get_db_connection()
    driver_data = []
    for did in driver_ids:
        row = conn.execute(
            """SELECT s.best_lap_time_s, s.mean_lap_time_s, s.total_score,
                      COALESCE(d.driver_id, s.driver_id) AS driver_id,
                      COALESCE(d.driver_name, 'Unknown') AS driver_name
               FROM sessions s
               LEFT JOIN drivers d ON s.driver_id = d.driver_id
               WHERE s.track_id = :track_id AND s.driver_id = :driver_id
                 AND s.best_lap_time_s IS NOT NULL
               ORDER BY s.best_lap_time_s ASC
               LIMIT 1""",
            {"track_id": track_id, "driver_id": did},
        ).fetchone()
        if row:
            driver_data.append(dict(row))

    if len(driver_data) < 2:
        return jsonify({"error": "fewer than 2 drivers have data on this track"}), 404

    try:
        from rival_comparison import compare_rivals
        result = compare_rivals(driver_data)
        result["track_id"] = track_id
        return jsonify(result)
    except ImportError:
        return jsonify({"error": "rival_comparison module not available"}), 500


# ------------------------------------------------------------------
# Brake-throttle tradeoff API (Feature #10)
# ------------------------------------------------------------------

@bp.route("/session/<session_id>/brake-throttle-tradeoff")
def api_brake_throttle_tradeoff(session_id: str):
    """Return brake intensity vs exit acceleration Pareto data."""
    conn = get_db_connection()
    rows = conn.execute(
        """SELECT corner_id, brake_intensity, exit_accel_mps2,
                  apex_speed_mps, entry_speed_mps
           FROM corner_metrics
           WHERE session_id = :sid
             AND brake_intensity IS NOT NULL
             AND exit_accel_mps2 IS NOT NULL
           ORDER BY corner_id, lap_number""",
        {"sid": session_id},
    ).fetchall()
    if not rows:
        return jsonify({"error": "No brake/throttle data"}), 404

    points = [dict(r) for r in rows]

    # Compute Pareto frontier (non-dominated points)
    # A point dominates another if it has LOWER brake intensity AND HIGHER exit accel
    pareto = []
    for p in points:
        dominated = False
        for q in points:
            if (q["brake_intensity"] <= p["brake_intensity"]
                    and q["exit_accel_mps2"] >= p["exit_accel_mps2"]
                    and (q["brake_intensity"] < p["brake_intensity"]
                         or q["exit_accel_mps2"] > p["exit_accel_mps2"])):
                dominated = True
                break
        if not dominated:
            pareto.append(p)

    return jsonify({
        "session_id": session_id,
        "all_points": points,
        "pareto_frontier": pareto,
        "n_points": len(points),
        "n_pareto": len(pareto),
    })


# ------------------------------------------------------------------
# What-if simulator API (Feature #11)
# ------------------------------------------------------------------

@bp.route("/session/<session_id>/what-if", methods=["POST"])
def api_what_if(session_id: str):
    """Run what-if simulation with corner speed adjustments."""
    data = request.get_json(force=True) or {}
    adjustments = data.get("adjustments", [])

    conn = get_db_connection()
    # Get speed profile from best lap GPS
    session = get_session_by_id(conn, session_id)
    if session is None:
        return jsonify({"error": "Session not found"}), 404

    from web.models import get_laps_for_session, get_gps_trace
    laps = get_laps_for_session(conn, session_id)
    best_lap = None
    for lap in laps:
        if lap.get("is_best"):
            best_lap = lap["lap_number"]
            break
    if best_lap is None:
        return jsonify({"error": "No best lap"}), 404

    gps = get_gps_trace(conn, session_id, best_lap)
    if not gps:
        return jsonify({"error": "No GPS data"}), 404

    # Get corners from corner_metrics
    corner_rows = conn.execute(
        """SELECT corner_id, MIN(brake_point_m) as d_start,
                  MAX(brake_point_m) + 50 as d_end
           FROM corner_metrics WHERE session_id = :sid
           GROUP BY corner_id""",
        {"sid": session_id},
    ).fetchall()

    corners = [dict(r) for r in corner_rows]
    profile = {
        "distances": gps.get("distances", []),
        "speeds": gps.get("speeds", []),
        "corners": corners,
    }

    try:
        from what_if_simulator import simulate_what_if
        result = simulate_what_if(profile, adjustments)
        result["session_id"] = session_id
        return jsonify(result)
    except ImportError:
        return jsonify({"error": "what_if_simulator not available"}), 500


# ------------------------------------------------------------------
# Setup correlation API (Feature #13)
# ------------------------------------------------------------------

@bp.route("/setup-correlation/<int:driver_id>/<track_id>")
def api_setup_correlation(driver_id: int, track_id: str):
    """Return setup parameter vs pace correlations."""
    conn = get_db_connection()
    rows = conn.execute(
        """SELECT vs.*, s.best_lap_time_s
           FROM vehicle_setups vs
           JOIN sessions s ON vs.session_id = s.session_id
           WHERE vs.driver_id = :driver_id AND s.track_id = :track_id
             AND s.best_lap_time_s IS NOT NULL""",
        {"driver_id": driver_id, "track_id": track_id},
    ).fetchall()

    if not rows:
        return jsonify({"error": "No setup data for this driver/track"}), 404

    try:
        from setup_tracker import correlate_setup_vs_pace
        result = correlate_setup_vs_pace([dict(r) for r in rows])
        return jsonify(result)
    except ImportError:
        return jsonify({"error": "setup_tracker not available"}), 500


# ------------------------------------------------------------------
# Fuel model API (Feature #14)
# ------------------------------------------------------------------

@bp.route("/fuel-model/<int:driver_id>/<track_id>")
def api_fuel_model(driver_id: int, track_id: str):
    """Return fuel load vs pace model."""
    conn = get_db_connection()
    rows = conn.execute(
        """SELECT vs.fuel_load_kg, s.best_lap_time_s
           FROM vehicle_setups vs
           JOIN sessions s ON vs.session_id = s.session_id
           WHERE vs.driver_id = :driver_id AND s.track_id = :track_id
             AND vs.fuel_load_kg IS NOT NULL
             AND s.best_lap_time_s IS NOT NULL""",
        {"driver_id": driver_id, "track_id": track_id},
    ).fetchall()

    if not rows:
        return jsonify({"error": "No fuel data for this driver/track"}), 404

    try:
        from fuel_calculator import model_fuel_effect
        result = model_fuel_effect([dict(r) for r in rows])
        return jsonify(result)
    except ImportError:
        return jsonify({"error": "fuel_calculator not available"}), 500


# ------------------------------------------------------------------
# Line optimization API (Feature #15)
# ------------------------------------------------------------------

@bp.route("/session/<session_id>/line-optimization")
def api_line_optimization(session_id: str):
    """Return line deviation analysis vs reference line."""
    conn = get_db_connection()
    from web.models import get_reference_line, get_gps_trace, get_laps_for_session

    ref = get_reference_line(conn, session_id)
    if not ref:
        return jsonify({"error": "No reference line"}), 404

    laps = get_laps_for_session(conn, session_id)
    best_lap = None
    for lap in laps:
        if lap.get("is_best"):
            best_lap = lap["lap_number"]
            break
    if best_lap is None:
        return jsonify({"error": "No best lap"}), 404

    gps = get_gps_trace(conn, session_id, best_lap)
    if not gps:
        return jsonify({"error": "No GPS data"}), 404

    try:
        from line_optimization import identify_line_deviations
        actual = {"latitudes": gps.get("latitudes", []), "longitudes": gps.get("longitudes", [])}
        reference = {"latitudes": ref.get("latitudes", []), "longitudes": ref.get("longitudes", [])}
        result = identify_line_deviations(actual, reference)
        result["session_id"] = session_id
        return jsonify(result)
    except ImportError:
        return jsonify({"error": "line_optimization not available"}), 500


# ------------------------------------------------------------------
# Annotations API
# ------------------------------------------------------------------

@bp.route("/annotations/<session_id>", methods=["GET"])
def get_annotations_api(session_id):
    """Get all annotations for a session."""
    conn = get_db_connection()
    from annotations import get_annotations
    anns = get_annotations(conn, session_id)
    return jsonify({"annotations": anns})


@bp.route("/annotations/<session_id>", methods=["POST"])
def create_annotation_api(session_id):
    """Create an annotation."""
    conn = get_db_connection()
    data = request.get_json(force=True) or {}
    from annotations import create_annotation
    try:
        ann = create_annotation(
            conn, session_id,
            body=data.get("body", ""),
            title=data.get("title"),
            annotation_type=data.get("annotation_type", "note"),
            lap_number=data.get("lap_number"),
            distance_m=data.get("distance_m"),
            tags=data.get("tags"),
        )
        return jsonify(ann), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@bp.route("/annotations/item/<int:annotation_id>", methods=["PUT"])
def update_annotation_api(annotation_id):
    """Update an annotation."""
    conn = get_db_connection()
    data = request.get_json(force=True) or {}
    from annotations import update_annotation
    updated = update_annotation(conn, annotation_id, **data)
    if not updated:
        return jsonify({"error": "Not found"}), 404
    return jsonify(updated)


@bp.route("/annotations/item/<int:annotation_id>", methods=["DELETE"])
def delete_annotation_api(annotation_id):
    """Delete an annotation."""
    conn = get_db_connection()
    from annotations import delete_annotation
    if delete_annotation(conn, annotation_id):
        return jsonify({"success": True})
    return jsonify({"error": "Not found"}), 404


@bp.route("/annotations/search")
def search_annotations_api():
    """Search annotations."""
    q = request.args.get("q", "")
    limit = request.args.get("limit", 50, type=int)
    conn = get_db_connection()
    from annotations import search_annotations
    results = search_annotations(conn, q, limit)
    return jsonify({"results": results})


@bp.route("/annotations/tags")
def annotation_tags_api():
    """Get all annotation tags."""
    conn = get_db_connection()
    from annotations import get_all_tags
    tags = get_all_tags(conn)
    return jsonify({"tags": tags})


# ------------------------------------------------------------------
# Development Plans API
# ------------------------------------------------------------------

@bp.route("/dev-plans/templates")
def plan_templates_api():
    """Get available plan templates."""
    from development_plan import get_plan_templates
    return jsonify({"templates": get_plan_templates()})


@bp.route("/dev-plans/<int:driver_id>", methods=["GET"])
def get_plans_api(driver_id):
    """Get plans for a driver."""
    conn = get_db_connection()
    from development_plan import get_plans
    plans = get_plans(conn, driver_id)
    return jsonify({"plans": plans})


@bp.route("/dev-plans/<int:driver_id>", methods=["POST"])
def create_plan_api(driver_id):
    """Create a plan from template or custom."""
    conn = get_db_connection()
    data = request.get_json(force=True) or {}

    template_id = data.get("template_id")
    if template_id:
        from development_plan import create_plan_from_template
        try:
            plan = create_plan_from_template(conn, driver_id, template_id, data.get("plan_name"))
            return jsonify(plan), 201
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
    else:
        from development_plan import create_custom_plan
        try:
            plan = create_custom_plan(
                conn, driver_id,
                plan_name=data.get("plan_name", "Custom Plan"),
                weeks=data.get("weeks", []),
                level=data.get("level", "intermediate"),
            )
            return jsonify(plan), 201
        except ValueError as e:
            return jsonify({"error": str(e)}), 400


@bp.route("/dev-plans/plan/<int:plan_id>/progress", methods=["PUT"])
def update_plan_progress_api(plan_id):
    """Update plan drill progress."""
    conn = get_db_connection()
    data = request.get_json(force=True) or {}
    week_index = data.get("week_index")
    drill_index = data.get("drill_index")
    if week_index is None or drill_index is None:
        return jsonify({"error": "week_index and drill_index are required"}), 400
    from development_plan import update_plan_progress
    try:
        updated = update_plan_progress(
            conn, plan_id,
            week_index=week_index,
            drill_index=drill_index,
            completed=data.get("completed", True),
        )
        if not updated:
            return jsonify({"error": "Plan not found"}), 404
        # Check if just completed — include badge info for celebration.
        if updated.get("status") == "completed" and updated.get("completion_pct", 0) >= 100:
            badge_row = conn.execute(
                "SELECT metadata_json FROM driver_badges WHERE plan_id = ?", (plan_id,)
            ).fetchone()
            if badge_row:
                import json as _json
                updated["just_completed"] = True
                updated["badge_meta"] = _json.loads(dict(badge_row)["metadata_json"])
                updated["driver_id"] = updated.get("driver_id")
            else:
                updated["just_completed"] = False
        else:
            updated["just_completed"] = False
        return jsonify(updated)
    except (IndexError, KeyError) as e:
        return jsonify({"error": str(e)}), 400


@bp.route("/dev-plans/plan/<int:plan_id>", methods=["DELETE"])
def delete_plan_api(plan_id):
    """Delete a plan."""
    conn = get_db_connection()
    from development_plan import delete_plan
    if delete_plan(conn, plan_id):
        return jsonify({"success": True})
    return jsonify({"error": "Not found"}), 404


@bp.route("/dev-plans/driver-progress/<int:driver_id>")
def api_driver_progress(driver_id: int):
    """Track driver improvement across sessions — key metrics over time."""
    conn = get_db_connection()
    track_id = request.args.get("track_id")

    query = """
        SELECT s.session_id, s.session_date, s.session_type,
               s.best_lap_time_s, s.mean_lap_time_s, s.total_score,
               COALESCE(sd.consistency_score, 0) AS consistency_score,
               s.n_laps,
               t.track_name
        FROM sessions s
        LEFT JOIN tracks t ON s.track_id = t.track_id
        LEFT JOIN score_details sd ON s.session_id = sd.session_id
        WHERE s.driver_id = :did
          AND s.best_lap_time_s IS NOT NULL
    """
    params: dict[str, Any] = {"did": driver_id}
    if track_id:
        query += " AND s.track_id = :tid"
        params["tid"] = track_id
    query += " ORDER BY s.session_date ASC"

    rows = conn.execute(query, params).fetchall()
    if not rows:
        return jsonify({"error": "No sessions found"}), 404

    sessions_data = []
    best_ever = None
    pb_count = 0
    for r in rows:
        rd = dict(r)
        bl = rd.get("best_lap_time_s")
        if bl and (best_ever is None or bl < best_ever):
            best_ever = bl
            rd["is_pb"] = True
            pb_count += 1
        else:
            rd["is_pb"] = False
        rd["best_ever"] = best_ever
        sessions_data.append(rd)

    # Compute improvement metrics
    first_best = sessions_data[0].get("best_lap_time_s", 0)
    last_best = sessions_data[-1].get("best_lap_time_s", 0)
    improvement = first_best - (best_ever or first_best)

    # Score trend
    scores = [s.get("total_score") for s in sessions_data if s.get("total_score")]
    score_trend = "improving" if len(scores) >= 3 and scores[-1] > scores[0] else \
                  "declining" if len(scores) >= 3 and scores[-1] < scores[0] else "stable"

    return jsonify({
        "driver_id": driver_id,
        "track_id": track_id,
        "n_sessions": len(sessions_data),
        "pb_count": pb_count,
        "best_ever_s": round(best_ever, 3) if best_ever else None,
        "total_improvement_s": round(improvement, 3),
        "improvement_pct": round(improvement / first_best * 100, 2) if first_best else 0,
        "score_trend": score_trend,
        "sessions": sessions_data,
    })


@bp.route("/dev-plans/session-drills/<session_id>")
def api_session_drill_suggestions(session_id: str):
    """Suggest development drills based on session performance analysis."""
    conn = get_db_connection()
    sess = conn.execute(
        "SELECT * FROM sessions WHERE session_id = :sid", {"sid": session_id}
    ).fetchone()
    if not sess:
        return jsonify({"error": "Session not found"}), 404

    sess = dict(sess)
    # Get lap data for analysis
    laps = conn.execute(
        """SELECT lap_number, lap_time_s FROM laps
           WHERE session_id = :sid AND is_valid = 1
           ORDER BY lap_number""",
        {"sid": session_id},
    ).fetchall()
    lap_times = [r["lap_time_s"] for r in laps if r["lap_time_s"]]

    if len(lap_times) < 3:
        return jsonify({"error": "Not enough laps for analysis"}), 404

    import numpy as np
    best = min(lap_times)
    mean = float(np.mean(lap_times))
    std = float(np.std(lap_times, ddof=1)) if len(lap_times) > 1 else 0
    cv = (std / mean * 100) if mean > 0 else 0

    # Auto-suggest drills based on metrics
    suggestions = []

    if cv > 3.0:
        suggestions.append({
            "drill": "Consistency Focus",
            "reason": f"High lap time variation (CV={cv:.1f}%). Focus on repeatable lines and inputs.",
            "template": "consistency",
            "priority": "high",
        })
    elif cv > 1.5:
        suggestions.append({
            "drill": "Smooth Inputs",
            "reason": f"Moderate variation (CV={cv:.1f}%). Work on progressive throttle and brake application.",
            "template": "beginner",
            "priority": "medium",
        })

    if mean - best > 1.5:
        suggestions.append({
            "drill": "Pace Extraction",
            "reason": f"Gap of {mean - best:.2f}s between best and average. You have speed but not consistently.",
            "template": "intermediate",
            "priority": "high",
        })

    # Check for late-session fade
    if len(lap_times) >= 8:
        first_half = np.mean(lap_times[:len(lap_times) // 2])
        second_half = np.mean(lap_times[len(lap_times) // 2:])
        if second_half > first_half * 1.02:
            fade_pct = (second_half - first_half) / first_half * 100
            suggestions.append({
                "drill": "Endurance Building",
                "reason": f"Pace faded {fade_pct:.1f}% in second half. Build physical and mental endurance.",
                "template": "consistency",
                "priority": "medium",
            })

    score = sess.get("total_score", 0) or 0
    if score < 50:
        suggestions.append({
            "drill": "Foundations Review",
            "reason": f"Session score ({score:.0f}/100) suggests room for fundamental improvement.",
            "template": "beginner",
            "priority": "medium",
        })
    elif score >= 80:
        suggestions.append({
            "drill": "Advanced Limit Exploitation",
            "reason": f"Strong session ({score:.0f}/100). Ready for advanced limit work.",
            "template": "advanced",
            "priority": "low",
        })

    if not suggestions:
        suggestions.append({
            "drill": "Continue Current Plan",
            "reason": "Session metrics are healthy. Keep working on your current development plan.",
            "template": "intermediate",
            "priority": "low",
        })

    return jsonify({
        "session_id": session_id,
        "metrics": {
            "best_lap_s": round(best, 3),
            "mean_lap_s": round(mean, 3),
            "cv_pct": round(cv, 2),
            "n_laps": len(lap_times),
            "score": score,
        },
        "suggestions": suggestions,
    })


# ------------------------------------------------------------------
# Drill ↔ Session linking API (Task 5)
# ------------------------------------------------------------------


@bp.route("/dev-plans/plan/<int:plan_id>/link-session", methods=["POST"])
def link_session_api(plan_id):
    """Link an analyzed session to a specific drill."""
    conn = get_db_connection()
    data = request.get_json(force=True) or {}
    week_index = data.get("week_index")
    drill_index = data.get("drill_index")
    session_id = data.get("session_id")
    if week_index is None or drill_index is None or not session_id:
        return jsonify({"error": "week_index, drill_index, and session_id required"}), 400
    from development_plan import link_drill_session, get_plan
    try:
        result = link_drill_session(conn, plan_id, week_index, drill_index, session_id)
        if not result:
            return jsonify({"error": "Plan not found"}), 404
        plan = get_plan(conn, plan_id)
        result["completion_pct"] = plan["completion_pct"] if plan else 0
        result["just_completed"] = plan.get("status") == "completed" if plan else False
        return jsonify(result)
    except IndexError as e:
        return jsonify({"error": str(e)}), 400


@bp.route("/dev-plans/plan/<int:plan_id>/unlink-session", methods=["DELETE"])
def unlink_session_api(plan_id):
    """Remove a session link from a drill."""
    conn = get_db_connection()
    data = request.get_json(force=True) or {}
    week_index = data.get("week_index")
    drill_index = data.get("drill_index")
    session_id = data.get("session_id")
    if week_index is None or drill_index is None or not session_id:
        return jsonify({"error": "week_index, drill_index, and session_id required"}), 400
    from development_plan import unlink_drill_session
    unlink_drill_session(conn, plan_id, week_index, drill_index, session_id)
    return jsonify({"success": True})


@bp.route("/dev-plans/plan/<int:plan_id>/drill-sessions", methods=["GET"])
def drill_sessions_api(plan_id):
    """Return all linked sessions for a plan."""
    conn = get_db_connection()
    from development_plan import get_drill_sessions
    sessions = get_drill_sessions(conn, plan_id)
    return jsonify({"sessions": sessions})


# ------------------------------------------------------------------


# ------------------------------------------------------------------
# Tire Degradation Tracker API
# ------------------------------------------------------------------

@bp.route("/session/<session_id>/tire-degradation")
def api_tire_degradation(session_id: str):
    """Return tire degradation analysis for a session."""
    conn = get_db_connection()
    row = conn.execute(
        "SELECT * FROM sessions WHERE session_id = :sid",
        {"sid": session_id},
    ).fetchone()
    if not row:
        return jsonify({"error": "Session not found"}), 404

    lap_rows = conn.execute(
        """SELECT lap_number, lap_time_s
           FROM laps
           WHERE session_id = :sid AND is_valid = 1
           ORDER BY lap_number""",
        {"sid": session_id},
    ).fetchall()

    lap_times = [r["lap_time_s"] for r in lap_rows if r["lap_time_s"] is not None]
    lap_numbers = [r["lap_number"] for r in lap_rows if r["lap_time_s"] is not None]

    if len(lap_times) < 3:
        return jsonify({"error": "Not enough laps for degradation analysis"}), 404

    try:
        from tire_degradation import analyze_tire_degradation
        result = analyze_tire_degradation(lap_times, lap_numbers)
        result["session_id"] = session_id
        return jsonify(result)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# ------------------------------------------------------------------
# Driver Fitness / Endurance API
# ------------------------------------------------------------------

@bp.route("/session/<session_id>/fitness")
def api_driver_fitness(session_id: str):
    """Return driver fitness and endurance analysis for a session."""
    conn = get_db_connection()
    row = conn.execute(
        "SELECT s.*, COALESCE(d.driver_name, 'Unknown') AS driver_name "
        "FROM sessions s LEFT JOIN drivers d ON s.driver_id = d.driver_id "
        "WHERE s.session_id = :sid",
        {"sid": session_id},
    ).fetchone()
    if not row:
        return jsonify({"error": "Session not found"}), 404

    sess = dict(row)
    lap_rows = conn.execute(
        """SELECT lap_number, lap_time_s
           FROM laps
           WHERE session_id = :sid AND is_valid = 1
           ORDER BY lap_number""",
        {"sid": session_id},
    ).fetchall()

    lap_times = [r["lap_time_s"] for r in lap_rows if r["lap_time_s"] is not None]
    lap_numbers = [r["lap_number"] for r in lap_rows if r["lap_time_s"] is not None]

    if len(lap_times) < 4:
        return jsonify({"error": "Not enough laps for fitness analysis (need 4+)"}), 404

    try:
        from driver_fitness import generate_fitness_report
        result = generate_fitness_report(
            lap_times, lap_numbers, driver_name=sess.get("driver_name", "")
        )
        result["session_id"] = session_id
        return jsonify(result)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# ------------------------------------------------------------------
# Custom Dashboards API
# ------------------------------------------------------------------

@bp.route("/dashboards", methods=["GET"])
def get_dashboards_api():
    """Get all dashboards."""
    conn = get_db_connection()
    driver_id = request.args.get("driver_id", type=int)
    from dashboard_builder import get_dashboards
    dashboards = get_dashboards(conn, driver_id)
    return jsonify({"dashboards": dashboards})


@bp.route("/dashboards", methods=["POST"])
def create_dashboard_api():
    """Create a dashboard."""
    conn = get_db_connection()
    data = request.get_json(force=True) or {}
    from dashboard_builder import create_dashboard
    try:
        db = create_dashboard(
            conn,
            name=data.get("name", "New Dashboard"),
            layout=data.get("layout", []),
            driver_id=data.get("driver_id"),
            is_default=data.get("is_default", False),
        )
        return jsonify(db), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@bp.route("/dashboards/<int:dashboard_id>", methods=["PUT"])
def update_dashboard_api(dashboard_id):
    """Update a dashboard."""
    conn = get_db_connection()
    data = request.get_json(force=True) or {}
    from dashboard_builder import update_dashboard
    updated = update_dashboard(conn, dashboard_id, **data)
    if not updated:
        return jsonify({"error": "Not found"}), 404
    return jsonify(updated)


@bp.route("/dashboards/<int:dashboard_id>", methods=["DELETE"])
def delete_dashboard_api(dashboard_id):
    """Delete a dashboard."""
    conn = get_db_connection()
    from dashboard_builder import delete_dashboard
    if delete_dashboard(conn, dashboard_id):
        return jsonify({"success": True})
    return jsonify({"error": "Not found"}), 404


@bp.route("/dashboards/widgets")
def widget_registry_api():
    """Get available widget types."""
    from dashboard_builder import get_widget_registry
    return jsonify({"widgets": get_widget_registry()})


@bp.route("/dashboards/widget-data", methods=["POST"])
def widget_data_api():
    """Get data for a widget."""
    conn = get_db_connection()
    data = request.get_json(force=True)
    if data is None:
        return jsonify({"error": "Invalid or missing JSON body"}), 400
    try:
        from dashboard_builder import get_widget_data
        result = get_widget_data(conn, data.get("widget_type", ""), data.get("params", {}))
        return jsonify(result)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# ------------------------------------------------------------------
# Export API
# ------------------------------------------------------------------

@bp.route("/export/session/<session_id>", methods=["POST"])
def export_session_api(session_id):
    """Generate an export for a session with selected sections."""
    conn = get_db_connection()
    data = request.get_json(force=True) or {}
    sections = data.get("sections", [])
    export_format = data.get("format", "markdown")

    session = get_session_by_id(conn, session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404

    # Build the export content
    content = _build_export(conn, session, sections, export_format)
    return jsonify({"content": content, "format": export_format})


def _build_export(conn, session, sections, fmt):
    """Build export content from selected sections."""
    parts = []
    sess = dict(session)

    if "summary" in sections:
        parts.append(f"# Session Report: {sess.get('driver_name', 'Unknown')} - {sess.get('track_name', 'Unknown')}")
        parts.append(f"Date: {sess.get('session_date', 'N/A')}")
        parts.append(f"Type: {sess.get('session_type', 'N/A')} | State: {sess.get('track_state', 'N/A')}")
        parts.append(f"Laps: {sess.get('n_laps', 0)} | Best: {sess.get('best_lap_time_s', 'N/A')}s")
        parts.append(f"Score: {sess.get('total_score', 'N/A')} | Grade: {sess.get('grade', 'N/A')}")
        parts.append("")

    if "lap_times" in sections:
        parts.append("## Lap Times")
        laps = conn.execute(
            "SELECT lap_number, lap_time_s, is_valid, is_best FROM laps "
            "WHERE session_id = ? ORDER BY lap_number",
            (sess["session_id"],)
        ).fetchall()
        parts.append("| Lap | Time (s) | Valid | Best |")
        parts.append("|-----|----------|-------|------|")
        for lap in laps:
            lt = lap['lap_time_s']
            lt_str = f"{lt:.3f}" if lt is not None else "—"
            parts.append(f"| {lap['lap_number']} | {lt_str} | {'Yes' if lap['is_valid'] else 'No'} | {'*' if lap['is_best'] else ''} |")
        parts.append("")

    if "score_breakdown" in sections:
        parts.append("## Score Breakdown")
        score = conn.execute(
            "SELECT * FROM score_details WHERE session_id = ?",
            (sess["session_id"],)
        ).fetchone()
        if score:
            sd = dict(score)
            parts.append(f"- Pace: {sd.get('pace_score', 0):.1f} / {sd.get('pace_max', 25):.0f}")
            parts.append(f"- Consistency: {sd.get('consistency_score', 0):.1f} / {sd.get('consistency_max', 25):.0f}")
            parts.append(f"- Execution: {sd.get('execution_score', 0):.1f} / {sd.get('execution_max', 25):.0f}")
            parts.append(f"- Robustness: {sd.get('robustness_score', 0):.1f} / {sd.get('robustness_max', 25):.0f}")
        parts.append("")

    if "debrief" in sections:
        parts.append("## Debrief Notes")
        parts.append(f"Session {sess['session_id']} on {sess.get('session_date', 'N/A')}")
        parts.append("")

    return "\n".join(parts)


# ------------------------------------------------------------------
# Weight Simulation API
# ------------------------------------------------------------------

@bp.route("/drivers/brief")
def api_drivers_brief():
    """Return lightweight driver list with profile weight for weight simulator."""
    conn = get_db_connection()
    rows = conn.execute("""
        SELECT d.driver_id, d.driver_name,
               dp.weight_kg, dp.kart_class,
               MIN(s.best_lap_time_s) AS overall_best_lap
        FROM drivers d
        LEFT JOIN driver_profiles dp ON d.driver_id = dp.driver_id
        LEFT JOIN sessions s ON d.driver_id = s.driver_id
        GROUP BY d.driver_id
        ORDER BY d.driver_name
    """).fetchall()
    return jsonify([dict(r) for r in rows])


@bp.route("/weight-simulation", methods=["POST"])
def api_weight_simulation():
    """Simulate weight change effect on lap time."""
    data = request.get_json(force=True) or {}
    try:
        from weight_simulation import simulate_weight_change
        result = simulate_weight_change(
            baseline={
                "lap_time_s": data.get("lap_time_s", 0),
                "weight_kg": data.get("weight_kg", 0),
                "power_kw": data.get("power_kw"),
            },
            weight_delta_kg=data.get("weight_delta_kg", 0),
            vehicle_class=data.get("vehicle_class", "default"),
        )
        return jsonify(result)
    except ImportError:
        return jsonify({"error": "weight_simulation module not available"}), 500


@bp.route("/weight-scenarios", methods=["POST"])
def api_weight_scenarios():
    """Compare multiple weight change scenarios."""
    data = request.get_json(force=True) or {}
    try:
        from weight_simulation import compare_weight_scenarios
        result = compare_weight_scenarios(
            baseline={
                "lap_time_s": data.get("lap_time_s", 0),
                "weight_kg": data.get("weight_kg", 0),
            },
            scenarios=data.get("scenarios", []),
            vehicle_class=data.get("vehicle_class", "default"),
        )
        return jsonify(result)
    except ImportError:
        return jsonify({"error": "weight_simulation module not available"}), 500


@bp.route("/weight-sensitivity/<int:driver_id>/<track_id>")
def api_weight_sensitivity(driver_id: int, track_id: str):
    """Compute empirical weight-pace sensitivity from historical data."""
    conn = get_db_connection()
    rows = conn.execute(
        """SELECT s.best_lap_time_s, s.session_date,
                  vs.weight_kg
           FROM sessions s
           JOIN vehicle_setups vs ON s.session_id = vs.session_id
           WHERE s.driver_id = :did AND s.track_id = :tid
             AND s.best_lap_time_s IS NOT NULL
             AND vs.weight_kg IS NOT NULL
           ORDER BY s.session_date""",
        {"did": driver_id, "tid": track_id},
    ).fetchall()

    sessions = [dict(r) for r in rows]
    try:
        from weight_simulation import compute_weight_sensitivity
        result = compute_weight_sensitivity(sessions)
        result["driver_id"] = driver_id
        result["track_id"] = track_id
        return jsonify(result)
    except ImportError:
        return jsonify({"error": "weight_simulation module not available"}), 500


# ------------------------------------------------------------------
# Race Strategy API
# ------------------------------------------------------------------

@bp.route("/race-strategy/tire-data/<int:driver_id>/<track_id>")
def api_race_strategy_tire_data(driver_id: int, track_id: str):
    """Get tire degradation data from actual sessions to feed race strategy.

    Returns avg degradation rate, optimal stint length, and tire life
    estimates derived from real session data.
    """
    conn = get_db_connection()
    try:
        from tire_degradation import (
            analyze_tire_degradation,
            compute_optimal_stint_length,
            estimate_tire_life,
        )

        # Fetch sessions for this driver + track
        rows = conn.execute("""
            SELECT s.session_id, s.n_laps, s.best_lap_time_s
            FROM sessions s
            WHERE s.driver_id = :did AND s.track_id = :tid
              AND s.n_laps >= 5
            ORDER BY s.session_date DESC
            LIMIT 10
        """, {"did": driver_id, "tid": track_id}).fetchall()

        if not rows:
            return jsonify({"error": "No sessions found for this driver/track combo"}), 404

        # Collect lap times from all matching sessions
        all_analyses = []
        for row in rows:
            sid = row["session_id"]
            lap_rows = conn.execute(
                "SELECT lap_time_s FROM laps WHERE session_id = :sid ORDER BY lap_number",
                {"sid": sid},
            ).fetchall()
            lap_times = [r["lap_time_s"] for r in lap_rows if r["lap_time_s"] is not None]
            if len(lap_times) >= 5:
                analysis = analyze_tire_degradation(lap_times)
                if analysis and "degradation_rate_s_per_lap" in analysis:
                    analysis["session_id"] = sid
                    analysis["n_laps"] = len(lap_times)
                    all_analyses.append(analysis)

        if not all_analyses:
            return jsonify({"error": "Insufficient lap data for degradation analysis"}), 404

        # Average degradation metrics across sessions
        avg_deg_rate = sum(a["degradation_rate_s_per_lap"] for a in all_analyses) / len(all_analyses)
        avg_clean_laps = sum(a.get("clean_laps_before_degradation", 0) for a in all_analyses) / len(all_analyses)

        # Compute optimal stint and tire life from the combined data
        all_lap_times = []
        for row in rows:
            sid = row["session_id"]
            lap_rows = conn.execute(
                "SELECT lap_time_s FROM laps WHERE session_id = :sid ORDER BY lap_number",
                {"sid": sid},
            ).fetchall()
            all_lap_times.extend([r["lap_time_s"] for r in lap_rows if r["lap_time_s"] is not None])

        optimal_stint = compute_optimal_stint_length(all_lap_times) if len(all_lap_times) >= 5 else {}
        tire_life = estimate_tire_life(all_lap_times, threshold_pct=3.0) if len(all_lap_times) >= 5 else {}

        return jsonify({
            "n_sessions": len(all_analyses),
            "avg_degradation_rate_s_per_lap": round(avg_deg_rate, 4),
            "avg_clean_laps_before_degradation": round(avg_clean_laps, 1),
            "optimal_stint": optimal_stint,
            "tire_life": tire_life,
            "sessions": [
                {
                    "session_id": a["session_id"],
                    "n_laps": a["n_laps"],
                    "degradation_rate": round(a["degradation_rate_s_per_lap"], 4),
                }
                for a in all_analyses
            ],
        })
    except ImportError:
        return jsonify({"error": "tire_degradation module not available"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/race-strategy/simulate", methods=["POST"])
def api_race_simulate():
    """Lap-by-lap race simulation with tire and fuel models."""
    data = request.get_json(force=True) or {}
    try:
        from race_strategy import simulate_race
        result = simulate_race(data)
        return jsonify(result)
    except ImportError:
        return jsonify({"error": "race_strategy module not available"}), 500


@bp.route("/race-strategy/plan", methods=["POST"])
def api_race_plan():
    """Generate optimal race strategy with multi-stop comparison."""
    data = request.get_json(force=True) or {}
    try:
        from race_strategy import plan_race_strategy
        result = plan_race_strategy(data)
        return jsonify(result)
    except ImportError:
        return jsonify({"error": "race_strategy module not available"}), 500


# ------------------------------------------------------------------
# Meteo / Weather API
# ------------------------------------------------------------------


def _resolve_track_coords(request_args, conn):
    """Resolve lat/lon from request — by direct params or track ID."""
    lat = request_args.get("lat", type=float)
    lon = request_args.get("lon", type=float)
    track_id = request_args.get("track")

    if lat is not None and lon is not None:
        return lat, lon

    if track_id and track_id.startswith("db:"):
        real_id = track_id[3:]
        row = conn.execute(
            "SELECT start_lat, start_lon FROM tracks WHERE track_id = :tid",
            {"tid": real_id},
        ).fetchone()
        if row and row["start_lat"] is not None:
            return row["start_lat"], row["start_lon"]
    elif track_id and track_id.startswith("csv:"):
        name = track_id[4:]
        row = conn.execute(
            "SELECT latitude, longitude FROM predefined_track_coords WHERE track_name = :n",
            {"n": name},
        ).fetchone()
        if row and row["latitude"] is not None:
            return row["latitude"], row["longitude"]

    return None, None


@bp.route("/meteo/current")
def api_meteo_current():
    """Get current weather at coordinates or known track."""
    conn = get_db_connection()
    lat, lon = _resolve_track_coords(request.args, conn)
    if lat is None or lon is None:
        return jsonify({"error": "Provide track ID or lat/lon"}), 400
    try:
        from meteo_service import fetch_current_weather, estimate_track_conditions
        weather = fetch_current_weather(lat, lon)
        conditions = estimate_track_conditions(weather)
        weather["track_conditions"] = conditions
        return jsonify(weather)
    except ImportError:
        return jsonify({"error": "meteo_service module not available"}), 500


@bp.route("/meteo/historical")
def api_meteo_historical():
    """Get historical weather for a date at coordinates."""
    conn = get_db_connection()
    lat, lon = _resolve_track_coords(request.args, conn)
    date_str = request.args.get("date", "")
    if not date_str:
        return jsonify({"error": "date parameter required (YYYY-MM-DD)"}), 400
    if lat is None or lon is None:
        return jsonify({"error": "Provide track ID or lat/lon"}), 400
    try:
        from meteo_service import fetch_historical_weather
        result = fetch_historical_weather(lat, lon, date_str)
        return jsonify(result)
    except ImportError:
        return jsonify({"error": "meteo_service module not available"}), 500


@bp.route("/meteo/forecast")
def api_meteo_forecast():
    """Get weather forecast for upcoming hours."""
    conn = get_db_connection()
    lat, lon = _resolve_track_coords(request.args, conn)
    hours = request.args.get("hours", 12, type=int)
    if lat is None or lon is None:
        return jsonify({"error": "Provide track ID or lat/lon"}), 400
    try:
        from meteo_service import get_weather_forecast
        result = get_weather_forecast(lat, lon, hours)
        return jsonify(result)
    except ImportError:
        return jsonify({"error": "meteo_service module not available"}), 500


@bp.route("/meteo/tracks")
def api_meteo_tracks():
    """Get list of known track locations for weather (grouped format)."""
    conn = get_db_connection()
    try:
        from meteo_service import get_all_track_locations
        return jsonify(get_all_track_locations(conn))
    except ImportError:
        return jsonify({"error": "meteo_service module not available"}), 500


@bp.route("/meteo/pace-estimate")
def api_meteo_pace_estimate():
    """Estimate pace impact of current weather conditions."""
    conn = get_db_connection()
    track_id = request.args.get("track_id")
    driver_id = request.args.get("driver_id", type=int)
    if not track_id:
        return jsonify({"error": "track_id required"}), 400
    actual_track_id = track_id
    if track_id.startswith("db:"):
        actual_track_id = track_id[3:]
    try:
        from pace_estimator import estimate_pace
        weather = {}
        resolved_lat, resolved_lon = _resolve_track_coords(request.args, conn)
        if resolved_lat is not None:
            from meteo_service import fetch_current_weather
            weather = fetch_current_weather(resolved_lat, resolved_lon)
        result = estimate_pace(conn, actual_track_id, driver_id or 0, weather)
        return jsonify(result)
    except ImportError as e:
        return jsonify({"error": f"Module not available: {e}"}), 500
