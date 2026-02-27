"""V1 data API endpoints — REST-style wrappers over legacy data-fetching logic.

Blueprint: ``/api/v1/`` — provides 15 hardened endpoints that call the same
data-fetching functions used by ``api_data.py``, but return responses in the
standard ``api_response`` envelope with rate limiting.

Usage::

    from web.routes.api_v1_data import bp as api_v1_data_bp
    app.register_blueprint(api_v1_data_bp)
"""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime
from pathlib import Path

from flask import Blueprint, current_app, g, request

from web.api_utils import ErrorCode, api_error, api_response
from web.db import get_db_connection, validate_karts_schema
from web.models import (
    get_all_drivers,
    get_all_karts,
    get_all_tracks,
    get_all_weekends,
    get_dashboard_stats,
    get_driver_profile,
    get_driver_progression,
    get_driving_style,
    get_gps_trace,
    get_gps_lap_numbers,
    get_kart_by_id,
    get_laps_for_session,
    get_reference_line,
    get_score_details,
    get_session_by_id,
    get_session_sectors,
    get_sessions,
    get_stint_analysis,
    get_theoretical_data,
    get_track_by_id,
    get_track_records,
    get_weekend_by_id,
    get_weekend_sessions,
)

logger = logging.getLogger(__name__)

bp = Blueprint("api_v1_data", __name__, url_prefix="/api/v1")


# ---- Rate limit import (graceful fallback for dev/test) ----
try:
    from web.rate_limit import rate_limit
except ImportError:
    def rate_limit(**kwargs):
        """No-op fallback when rate_limit module is not available."""
        def decorator(fn):
            return fn
        return decorator


# ---- Validate params import (graceful fallback for dev/test) ----
try:
    from web.validation import validate_params
except ImportError:
    def validate_params(schema):
        """No-op fallback when validation module is not available."""
        def decorator(fn):
            return fn
        return decorator


# ---------------------------------------------------------------------------
# 1. GET /sessions/<id>/laps/gps — list lap numbers with GPS data
# ---------------------------------------------------------------------------

@bp.route("/sessions/<session_id>/laps/gps", methods=["GET"])
@rate_limit(tier="read")
def v1_laps_gps(session_id: str):
    """Return list of lap numbers that have GPS data.

    Returns:
        200 with ``{"laps": [1, 2, 3]}``
    """
    conn = get_db_connection()
    laps = get_gps_lap_numbers(conn, session_id)
    return api_response({"laps": laps})


# ---------------------------------------------------------------------------
# 2. GET /sessions/<id>/speed-trace — speed vs distance data
# ---------------------------------------------------------------------------

@bp.route("/sessions/<session_id>/speed-trace", methods=["GET"])
@rate_limit(tier="read")
def v1_speed_trace(session_id: str):
    """Return speed vs distance data for charting.

    Returns:
        200 with ``{"laps": {...}, "best_lap_number": N, "session_id": "..."}``
        404 if session not found.
    """
    conn = get_db_connection()
    session = get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    laps = get_laps_for_session(conn, session_id)
    gps_lap_nums = get_gps_lap_numbers(conn, session_id)

    best_lap = None
    for lap in laps:
        if lap.get("is_best"):
            best_lap = lap["lap_number"]
            break

    traces = {}
    for lap_num in gps_lap_nums:
        gps = get_gps_trace(conn, session_id, lap_num)
        if gps:
            traces[lap_num] = {
                "distances": gps["distances"],
                "speeds": gps["speeds"],
            }

    return api_response({
        "laps": traces,
        "best_lap_number": best_lap,
        "session_id": session_id,
    })


# ---------------------------------------------------------------------------
# 3. GET /sessions/<id>/lap-times — lap times for charting
# ---------------------------------------------------------------------------

@bp.route("/sessions/<session_id>/lap-times", methods=["GET"])
@rate_limit(tier="read")
def v1_lap_times(session_id: str):
    """Return lap times as JSON for charting.

    Returns:
        200 with ``{"laps": [...]}``
    """
    conn = get_db_connection()
    laps = get_laps_for_session(conn, session_id)
    return api_response({
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
    })


# ---------------------------------------------------------------------------
# 4. GET /sessions/<id>/gg-data — G-G scatter data
# ---------------------------------------------------------------------------

def _clean_accel(arr):
    """Replace NaN/Inf with None; values are already in G from RaceChrono."""
    out = []
    for v in arr:
        if v is None:
            out.append(None)
        else:
            fv = float(v)
            out.append(None if (math.isnan(fv) or math.isinf(fv)) else round(fv, 4))
    return out


@bp.route("/sessions/<session_id>/gg-data", methods=["GET"])
@rate_limit(tier="read")
def v1_gg_data(session_id: str):
    """Return aggregated G-G scatter data from all laps with accel data.

    Returns:
        200 with ``{"accel_lat": [...], "accel_long": [...], "per_lap": {...}, "n_points": N}``
    """
    conn = get_db_connection()
    gps_lap_nums = get_gps_lap_numbers(conn, session_id)

    accel_lat_all = []
    accel_long_all = []
    per_lap = {}

    for lap_num in gps_lap_nums:
        gps = get_gps_trace(conn, session_id, lap_num)
        if gps and gps.get("accel_lat") and gps.get("accel_long"):
            lat_clean = _clean_accel(gps["accel_lat"])
            long_clean = _clean_accel(gps["accel_long"])
            accel_lat_all.extend(lat_clean)
            accel_long_all.extend(long_clean)
            per_lap[str(lap_num)] = {
                "accel_lat": lat_clean,
                "accel_long": long_clean,
            }

    return api_response({
        "accel_lat": accel_lat_all,
        "accel_long": accel_long_all,
        "per_lap": per_lap,
        "n_points": len(accel_lat_all),
    })


# ---------------------------------------------------------------------------
# 5. GET /sessions/<id>/theoretical — theoretical lap data
# ---------------------------------------------------------------------------

@bp.route("/sessions/<session_id>/theoretical", methods=["GET"])
@rate_limit(tier="read")
def v1_theoretical(session_id: str):
    """Return theoretical lap speed profile and metrics.

    Returns:
        200 with theoretical data.
        404 if no theoretical data exists.
    """
    conn = get_db_connection()
    data = get_theoretical_data(conn, session_id)
    if data is None:
        return api_error(ErrorCode.NOT_FOUND, "No theoretical data", status=404)
    response = {
        "theoretical_time_s": data.get("theoretical_time_s"),
        "actual_best_time_s": data.get("actual_best_time_s"),
        "gap_pct": data.get("gap_pct"),
        "simulation_method": data.get("simulation_method"),
        "speeds": data.get("speeds"),
        "distances": data.get("distances"),
        "metrics": data.get("metrics"),
    }
    # New kart_envelope fields (optional — None if old engine was used)
    if data.get("corner_coaching"):
        response["corner_coaching"] = data["corner_coaching"]
    if data.get("session_scalars"):
        response["session_scalars"] = data["session_scalars"]
    if data.get("delta_map_summary"):
        response["delta_map_summary"] = data["delta_map_summary"]
    return api_response(response)


# ---------------------------------------------------------------------------
# 6. GET /sessions/<id>/fingerprint — performance fingerprint
# ---------------------------------------------------------------------------

@bp.route("/sessions/<session_id>/fingerprint", methods=["GET"])
@rate_limit(tier="read")
def v1_fingerprint(session_id: str):
    """Return a 6-dimension performance fingerprint for a session.

    Delegates to the legacy ``api_fingerprint`` logic in ``api_data.py``.

    Returns:
        200 with fingerprint data.
        404 if session not found.
    """
    conn = get_db_connection()
    row = conn.execute(
        "SELECT * FROM sessions WHERE session_id = :sid",
        {"sid": session_id},
    ).fetchone()
    if not row:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)
    sess = dict(row)

    # Build input data from scoring sub-scores and analysis results
    session_data = {"session_id": session_id, "driver_name": ""}

    if sess.get("driver_id"):
        dr = conn.execute(
            "SELECT driver_name FROM drivers WHERE driver_id = :did",
            {"did": sess["driver_id"]},
        ).fetchone()
        if dr:
            session_data["driver_name"] = dr["driver_name"]

    scoring_row = conn.execute(
        "SELECT * FROM score_details WHERE session_id = :sid",
        {"sid": session_id},
    ).fetchone()
    if scoring_row:
        sd = dict(scoring_row)
        if sd.get("pace_score") is not None and sd.get("pace_max") and sd["pace_max"] > 0:
            session_data["pace_pct"] = sd["pace_score"] / sd["pace_max"] * 100
        if sd.get("consistency_score") is not None and sd.get("consistency_max") and sd["consistency_max"] > 0:
            session_data["consistency_pct"] = sd["consistency_score"] / sd["consistency_max"] * 100
        if sd.get("robustness_score") is not None and sd.get("robustness_max") and sd["robustness_max"] > 0:
            session_data["robustness_pct"] = sd["robustness_score"] / sd["robustness_max"] * 100
        if sd.get("execution_score") is not None and sd.get("execution_max") and sd["execution_max"] > 0:
            session_data["execution_pct"] = sd["execution_score"] / sd["execution_max"] * 100

    if not session_data.get("pace_pct") and sess.get("total_score"):
        session_data["pace_pct"] = sess["total_score"]

    try:
        from performance_fingerprint import compute_fingerprint
        fp = compute_fingerprint(session_data)
        return api_response(fp.to_dict())
    except ImportError:
        return api_error(
            ErrorCode.SERVICE_UNAVAILABLE,
            "performance_fingerprint module not available",
            status=503,
        )


# ---------------------------------------------------------------------------
# 7. GET /sessions/<id>/reference-line — reference (median racing) line
# ---------------------------------------------------------------------------

@bp.route("/sessions/<session_id>/reference-line", methods=["GET"])
@rate_limit(tier="read")
def v1_reference_line(session_id: str):
    """Return the reference (median racing) line GPS coordinates.

    Returns:
        200 with reference line data.
        404 if no reference line exists.
    """
    conn = get_db_connection()
    data = get_reference_line(conn, session_id)
    if data is None:
        return api_error(ErrorCode.NOT_FOUND, "No reference line", status=404)
    return api_response(data)


# ---------------------------------------------------------------------------
# 8. GET /sessions/<id>/best-lap-gps — GPS trace for the best lap
# ---------------------------------------------------------------------------

@bp.route("/sessions/<session_id>/best-lap-gps", methods=["GET"])
@rate_limit(tier="read")
def v1_best_lap_gps(session_id: str):
    """Return the GPS trace for the best lap.

    Returns:
        200 with GPS trace data (includes ``lap_number``).
        404 if no best lap or no GPS data.
    """
    conn = get_db_connection()
    laps = get_laps_for_session(conn, session_id)
    best_lap = None
    for lap in laps:
        if lap.get("is_best"):
            best_lap = lap["lap_number"]
            break

    if best_lap is None:
        return api_error(ErrorCode.NOT_FOUND, "No best lap", status=404)

    gps = get_gps_trace(conn, session_id, best_lap)
    if gps is None:
        return api_error(ErrorCode.NOT_FOUND, "No GPS data for best lap", status=404)

    gps["lap_number"] = best_lap
    return api_response(gps)


# ---------------------------------------------------------------------------
# 9. GET /sessions/<id>/fatigue — fatigue and concentration analysis
# ---------------------------------------------------------------------------

@bp.route("/sessions/<session_id>/fatigue", methods=["GET"])
@rate_limit(tier="read")
def v1_fatigue(session_id: str):
    """Return driver fatigue and concentration analysis.

    Returns:
        200 with fatigue analysis data.
        404 if session not found or no lap data.
        503 if fatigue_detection module unavailable.
    """
    conn = get_db_connection()
    session = get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    laps = conn.execute(
        """SELECT lap_number, lap_time_s, speed_mean_mps, braking_max_mps2,
                  accel_max_mps2
           FROM laps WHERE session_id = :sid AND is_valid = 1
           ORDER BY lap_number""",
        {"sid": session_id},
    ).fetchall()

    if not laps:
        return api_error(ErrorCode.NOT_FOUND, "No lap data", status=404)

    lap_metrics = []
    lap_times = []
    lap_numbers = []
    for r in laps:
        rd = dict(r)
        lap_numbers.append(int(rd["lap_number"]))
        lap_times.append(float(rd["lap_time_s"]) if rd["lap_time_s"] else float("nan"))
        lap_metrics.append({
            "braking_max_mps2": rd.get("braking_max_mps2"),
            "jerk_rms_mps3": None,
            "speed_mean_mps": rd.get("speed_mean_mps"),
        })

    try:
        from fatigue_detection import analyze_fatigue
        result = analyze_fatigue(lap_metrics, lap_times, lap_numbers)
        return api_response(result.to_dict())
    except ImportError:
        return api_error(
            ErrorCode.SERVICE_UNAVAILABLE,
            "fatigue_detection module not available",
            status=503,
        )


# ---------------------------------------------------------------------------
# 10. GET /sessions/<id>/speed-profile — track segment speed profile
# ---------------------------------------------------------------------------

@bp.route("/sessions/<session_id>/speed-profile", methods=["GET"])
@rate_limit(tier="read")
def v1_speed_profile(session_id: str):
    """Return track segment speed profile for a session.

    Returns:
        200 with speed profile data.
        404 if session not found.
        503 if speed_profile module unavailable.
    """
    conn = get_db_connection()
    row = conn.execute(
        "SELECT * FROM sessions WHERE session_id = :sid",
        {"sid": session_id},
    ).fetchone()
    if not row:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

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
        return api_response(d)
    except ImportError:
        return api_error(
            ErrorCode.SERVICE_UNAVAILABLE,
            "speed_profile module not available",
            status=503,
        )


# ---------------------------------------------------------------------------
# 11. GET /tracks/<id>/records — track records
# ---------------------------------------------------------------------------

@bp.route("/tracks/<track_id>/records", methods=["GET"])
@rate_limit(tier="read")
def v1_track_records(track_id: str):
    """Return track records as JSON.

    Returns:
        200 with ``{"records": [...]}``
    """
    conn = get_db_connection()
    records = get_track_records(conn, track_id)
    return api_response({"records": records})


# ---------------------------------------------------------------------------
# 12. GET /tracks/<id>/evolution — best lap progression over time
# ---------------------------------------------------------------------------

@bp.route("/tracks/<track_id>/evolution", methods=["GET"])
@rate_limit(tier="read")
def v1_track_evolution(track_id: str):
    """Return best lap time progression over time for a track.

    Returns:
        200 with ``{"track_id": "...", "sessions": [...]}``
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

    return api_response({"track_id": track_id, "sessions": sessions})


# ---------------------------------------------------------------------------
# 13. GET /tracks/<id>/geometry — track reference line geometry
# ---------------------------------------------------------------------------

@bp.route("/tracks/<track_id>/geometry", methods=["GET"])
@rate_limit(tier="read")
def v1_track_geometry(track_id: str):
    """Return track reference line geometry for static track outline.

    Returns:
        200 with ``{"track_name": "...", "latitudes": [...], "longitudes": [...]}``
        404 if no geometry available.
    """
    conn = get_db_connection()
    row = conn.execute(
        "SELECT track_name, reference_line FROM tracks WHERE track_id = :track_id",
        {"track_id": track_id},
    ).fetchone()
    if not row or not row["reference_line"]:
        return api_error(ErrorCode.NOT_FOUND, "No geometry available", status=404)
    try:
        geo = json.loads(row["reference_line"])
    except (json.JSONDecodeError, TypeError):
        return api_error(ErrorCode.INTERNAL_ERROR, "Invalid geometry data", status=500)
    return api_response({
        "track_name": row["track_name"],
        "latitudes": geo.get("latitudes", []),
        "longitudes": geo.get("longitudes", []),
    })


# ---------------------------------------------------------------------------
# 14. GET /files — list CSV files
# ---------------------------------------------------------------------------

def _human_size(nbytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if nbytes < 1024:
            return f"{nbytes:.1f} {unit}" if unit != "B" else f"{nbytes} {unit}"
        nbytes /= 1024
    return f"{nbytes:.1f} TB"


@bp.route("/files", methods=["GET"])
@rate_limit(tier="read")
def v1_files():
    """List CSV files in data/raw/ directory.

    Returns:
        200 with ``{"files": [...]}``
    """
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
    return api_response({"files": files})


# ---------------------------------------------------------------------------
# 15. DELETE /sessions/<id> — delete a session
# ---------------------------------------------------------------------------

@bp.route("/sessions/<session_id>", methods=["DELETE"])
@rate_limit(tier="write")
def v1_delete_session(session_id: str):
    """Delete a session and all its associated data.

    Returns:
        200 with ``{"session_id": "..."}``
        404 if session not found.
    """
    conn = get_db_connection()
    row = conn.execute(
        "SELECT session_id FROM sessions WHERE session_id = :sid",
        {"sid": session_id},
    ).fetchone()
    if row is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    try:
        related_tables = [
            "gps_traces", "laps", "score_details", "condition_phases",
            "corner_metrics", "driving_style_features",
            "theoretical_data", "reference_lines", "data_health",
            "session_tags", "session_weather", "session_sectors",
            "session_annotations", "stint_analysis", "condition_markers",
            "driver_progression", "vehicle_setups", "weekend_sessions",
            "what_if_scenarios",
        ]
        assert all(t.isidentifier() for t in related_tables), "Invalid table name"
        for table in related_tables:
            try:
                conn.execute(
                    f"DELETE FROM {table} WHERE session_id = :sid",
                    {"sid": session_id},
                )
            except Exception:
                pass

        conn.execute(
            "DELETE FROM sessions WHERE session_id = :sid",
            {"sid": session_id},
        )
        conn.commit()
        logger.info("Deleted session: %s", session_id)
        return api_response({"session_id": session_id})
    except Exception as exc:
        logger.error("Failed to delete session %s: %s", session_id, exc)
        return api_error(ErrorCode.INTERNAL_ERROR, str(exc), status=500)


# ===================================================================
# Batch 2: Session Analysis Endpoints (16–30)
# ===================================================================


# ---------------------------------------------------------------------------
# 16. GET /sessions/<id>/cross-session — cross-session comparison
# ---------------------------------------------------------------------------

@bp.route("/sessions/<session_id>/cross-session", methods=["GET"])
@rate_limit(tier="read")
def v1_cross_session(session_id: str):
    """Return cross-session comparison data for the same driver+track.

    Returns:
        200 with ``{"session_id": "...", "comparisons": [...]}``
        404 if session not found.
    """
    conn = get_db_connection()
    session = get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    rows = conn.execute(
        """SELECT s.session_id, s.session_date, s.best_lap_time_s,
                  s.total_score, s.grade, s.n_laps, s.session_type
           FROM sessions s
           WHERE s.driver_id = :driver_id
             AND s.track_id = :track_id
           ORDER BY s.session_date DESC""",
        {"driver_id": session["driver_id"], "track_id": session["track_id"]},
    ).fetchall()

    comparisons = []
    for r in rows:
        comparisons.append({
            "session_id": r["session_id"],
            "date": r["session_date"],
            "best_time_s": r["best_lap_time_s"],
            "score": r["total_score"],
            "grade": r["grade"],
            "n_laps": r["n_laps"],
            "session_type": r["session_type"],
        })

    return api_response({
        "session_id": session_id,
        "driver_name": session.get("driver_name"),
        "track_name": session.get("track_name"),
        "comparisons": comparisons,
    })


# ---------------------------------------------------------------------------
# 17. GET /sessions/<id>/sectors — sector definitions
# ---------------------------------------------------------------------------

@bp.route("/sessions/<session_id>/sectors", methods=["GET"])
@rate_limit(tier="read")
def v1_session_sectors(session_id: str):
    """Return sector split point definitions for a session.

    Returns:
        200 with ``{"session_id": "...", "sectors": [...]}``
    """
    conn = get_db_connection()
    sectors = get_session_sectors(conn, session_id)
    return api_response({"session_id": session_id, "sectors": sectors})


# ---------------------------------------------------------------------------
# 18. GET /sessions/<id>/sector-times — sector times per lap
# ---------------------------------------------------------------------------

@bp.route("/sessions/<session_id>/sector-times", methods=["GET"])
@rate_limit(tier="read")
def v1_sector_times(session_id: str):
    """Return sector times per lap from the sector_times view.

    Falls back to computing from sector split distances and GPS data
    if no dedicated sector_times table exists.

    Returns:
        200 with ``{"session_id": "...", "sector_times": [...]}``
    """
    conn = get_db_connection()
    try:
        rows = conn.execute(
            """SELECT * FROM sector_times
               WHERE session_id = :sid
               ORDER BY lap_number, sector_index""",
            {"sid": session_id},
        ).fetchall()
        data = [dict(r) for r in rows]
    except Exception:
        data = []

    return api_response({"session_id": session_id, "sector_times": data})


# ---------------------------------------------------------------------------
# 19. GET /sessions/<id>/delta — delta time between laps
# ---------------------------------------------------------------------------

@bp.route("/sessions/<session_id>/delta", methods=["GET"])
@rate_limit(tier="read")
def v1_delta(session_id: str):
    """Return delta times between consecutive laps.

    Returns:
        200 with ``{"session_id": "...", "deltas": [...], "reference_lap": N}``
        404 if no lap data.
    """
    conn = get_db_connection()
    laps = get_laps_for_session(conn, session_id)
    valid_laps = [l for l in laps if l.get("lap_time_s") is not None]

    if not valid_laps:
        return api_error(ErrorCode.NOT_FOUND, "No lap data", status=404)

    # Find the best lap as reference
    best_lap = None
    best_time = None
    for l in valid_laps:
        if l.get("is_best"):
            best_lap = l["lap_number"]
            best_time = l["lap_time_s"]
            break
    if best_time is None and valid_laps:
        best_lap = valid_laps[0]["lap_number"]
        best_time = valid_laps[0]["lap_time_s"]
        for l in valid_laps:
            if l["lap_time_s"] < best_time:
                best_time = l["lap_time_s"]
                best_lap = l["lap_number"]

    deltas = []
    for l in valid_laps:
        delta_s = round(l["lap_time_s"] - best_time, 4) if best_time else None
        deltas.append({
            "lap_number": l["lap_number"],
            "lap_time_s": l["lap_time_s"],
            "delta_s": delta_s,
            "is_best": bool(l.get("is_best")),
        })

    return api_response({
        "session_id": session_id,
        "reference_lap": best_lap,
        "reference_time_s": best_time,
        "deltas": deltas,
    })


# ---------------------------------------------------------------------------
# 20. GET /sessions/<id>/corner-metrics — corner-by-corner metrics
# ---------------------------------------------------------------------------

@bp.route("/sessions/<session_id>/corner-metrics", methods=["GET"])
@rate_limit(tier="read")
def v1_corner_metrics(session_id: str):
    """Return corner-by-corner metrics for all laps in a session.

    Returns:
        200 with ``{"session_id": "...", "metrics": [...]}``
    """
    conn = get_db_connection()
    rows = conn.execute(
        """SELECT * FROM corner_metrics
           WHERE session_id = :sid
           ORDER BY lap_number, corner_id""",
        {"sid": session_id},
    ).fetchall()
    data = [dict(r) for r in rows]
    return api_response({"session_id": session_id, "metrics": data})


# ---------------------------------------------------------------------------
# 21. GET /sessions/<id>/corner-coaching — corner coaching tips
# ---------------------------------------------------------------------------

@bp.route("/sessions/<session_id>/corner-coaching", methods=["GET"])
@rate_limit(tier="read")
def v1_corner_coaching(session_id: str):
    """Return corner coaching tips aggregated from corner_metrics.

    Groups by corner_id and returns the coaching_hint from the best
    lap for each corner, plus best-practice data if available.

    Returns:
        200 with ``{"session_id": "...", "coaching": [...]}``
    """
    conn = get_db_connection()

    # Get session to find track_id
    session = get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    # Get distinct corners with coaching hints from best lap metrics
    rows = conn.execute(
        """SELECT corner_id, coaching_hint,
                  AVG(entry_speed_mps) as avg_entry_speed_mps,
                  AVG(apex_speed_mps)  as avg_apex_speed_mps,
                  AVG(exit_speed_mps)  as avg_exit_speed_mps,
                  AVG(time_loss_ms)    as avg_time_loss_ms
           FROM corner_metrics
           WHERE session_id = :sid
           GROUP BY corner_id
           ORDER BY corner_id""",
        {"sid": session_id},
    ).fetchall()

    coaching = []
    for r in rows:
        entry = dict(r)
        # Try to fetch best practice for this corner
        if session.get("track_id"):
            bp_row = conn.execute(
                """SELECT best_entry_mps, best_apex_mps, best_exit_mps,
                          best_brake_m, best_time_s
                   FROM corner_best_practices
                   WHERE track_id = :tid AND corner_id = :cid""",
                {"tid": session["track_id"], "cid": r["corner_id"]},
            ).fetchone()
            if bp_row:
                entry["best_practice"] = dict(bp_row)
        coaching.append(entry)

    return api_response({"session_id": session_id, "coaching": coaching})


# ---------------------------------------------------------------------------
# 22. GET /sessions/<id>/badges — session achievement badges
# ---------------------------------------------------------------------------

@bp.route("/sessions/<session_id>/badges", methods=["GET"])
@rate_limit(tier="read")
def v1_session_badges(session_id: str):
    """Return achievement badges earned in a session.

    Queries driver_badges table for badges linked to this session's driver,
    plus session_tags as lightweight badges.

    Returns:
        200 with ``{"session_id": "...", "badges": [...], "tags": [...]}``
    """
    conn = get_db_connection()
    session = get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    # Driver badges
    badge_rows = conn.execute(
        """SELECT badge_type, badge_name, badge_level, metadata_json, earned_at
           FROM driver_badges
           WHERE driver_id = :did
           ORDER BY earned_at DESC""",
        {"did": session["driver_id"]},
    ).fetchall()
    badges = []
    for r in badge_rows:
        b = dict(r)
        if b.get("metadata_json"):
            try:
                b["metadata"] = json.loads(b["metadata_json"])
            except (json.JSONDecodeError, TypeError):
                b["metadata"] = None
            del b["metadata_json"]
        badges.append(b)

    # Session tags as lightweight badges
    tag_rows = conn.execute(
        """SELECT tag, confidence, source, created_at
           FROM session_tags
           WHERE session_id = :sid
           ORDER BY created_at""",
        {"sid": session_id},
    ).fetchall()
    tags = [dict(r) for r in tag_rows]

    return api_response({
        "session_id": session_id,
        "badges": badges,
        "tags": tags,
    })


# ---------------------------------------------------------------------------
# 23. GET /sessions/<id>/style — driving style metrics
# ---------------------------------------------------------------------------

@bp.route("/sessions/<session_id>/style", methods=["GET"])
@rate_limit(tier="read")
def v1_session_style(session_id: str):
    """Return driving style metrics for a session.

    Returns:
        200 with style feature data.
        404 if session or style data not found.
    """
    conn = get_db_connection()
    session = get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    style = get_driving_style(conn, session["driver_id"], session_id)
    if style is None:
        # Fallback: try score_details for basic style info
        sd = get_score_details(conn, session_id)
        if sd:
            return api_response({
                "session_id": session_id,
                "source": "score_details",
                "pace_score": sd.get("pace_score"),
                "consistency_score": sd.get("consistency_score"),
                "execution_score": sd.get("execution_score"),
                "robustness_score": sd.get("robustness_score"),
                "strengths": sd.get("strengths", []),
                "weaknesses": sd.get("weaknesses", []),
            })
        return api_error(ErrorCode.NOT_FOUND, "No style data", status=404)

    return api_response({
        "session_id": session_id,
        "source": "driving_style_features",
        "style_label": style.get("style_label"),
        "style_confidence": style.get("style_confidence"),
        "trail_braking_depth": style.get("trail_braking_depth"),
        "brake_point_consistency": style.get("brake_point_consistency"),
        "brake_pressure_buildup_rate": style.get("brake_pressure_buildup_rate"),
        "apex_speed_ratio": style.get("apex_speed_ratio"),
        "turn_in_aggressiveness": style.get("turn_in_aggressiveness"),
        "throttle_onset_delay_m": style.get("throttle_onset_delay_m"),
        "exit_acceleration_efficiency": style.get("exit_acceleration_efficiency"),
        "line_variation_index": style.get("line_variation_index"),
        "early_vs_late_stint_pace": style.get("early_vs_late_stint_pace"),
        "smoothness_composite": style.get("smoothness_composite"),
        "strengths": style.get("strengths", []),
        "weaknesses": style.get("weaknesses", []),
    })


# ---------------------------------------------------------------------------
# 24. GET /sessions/<id>/brake-points — brake point locations
# ---------------------------------------------------------------------------

@bp.route("/sessions/<session_id>/brake-points", methods=["GET"])
@rate_limit(tier="read")
def v1_brake_points(session_id: str):
    """Return brake point locations derived from corner_metrics.

    Returns:
        200 with ``{"session_id": "...", "brake_points": [...]}``
    """
    conn = get_db_connection()
    rows = conn.execute(
        """SELECT lap_number, corner_id, brake_point_m, brake_intensity,
                  entry_speed_mps
           FROM corner_metrics
           WHERE session_id = :sid AND brake_point_m IS NOT NULL
           ORDER BY lap_number, corner_id""",
        {"sid": session_id},
    ).fetchall()

    brake_points = [dict(r) for r in rows]

    # Compute per-corner averages
    corner_avgs = {}
    for bp in brake_points:
        cid = bp["corner_id"]
        if cid not in corner_avgs:
            corner_avgs[cid] = {"distances": [], "intensities": []}
        corner_avgs[cid]["distances"].append(bp["brake_point_m"])
        if bp.get("brake_intensity") is not None:
            corner_avgs[cid]["intensities"].append(bp["brake_intensity"])

    summary = []
    for cid, vals in sorted(corner_avgs.items()):
        avg_dist = sum(vals["distances"]) / len(vals["distances"])
        avg_int = (
            sum(vals["intensities"]) / len(vals["intensities"])
            if vals["intensities"] else None
        )
        summary.append({
            "corner_id": cid,
            "avg_brake_point_m": round(avg_dist, 2),
            "avg_brake_intensity": round(avg_int, 3) if avg_int is not None else None,
            "sample_count": len(vals["distances"]),
        })

    return api_response({
        "session_id": session_id,
        "brake_points": brake_points,
        "corner_summary": summary,
    })


# ---------------------------------------------------------------------------
# 25. GET /sessions/<id>/energy — energy balance data
# ---------------------------------------------------------------------------

@bp.route("/sessions/<session_id>/energy", methods=["GET"])
@rate_limit(tier="read")
def v1_energy(session_id: str):
    """Return energy balance data derived from lap speed statistics.

    Returns:
        200 with ``{"session_id": "...", "laps": [...]}``
    """
    conn = get_db_connection()
    rows = conn.execute(
        """SELECT lap_number, lap_time_s, speed_mean_mps, speed_max_mps,
                  braking_max_mps2, accel_max_mps2, line_length_m
           FROM laps
           WHERE session_id = :sid AND is_valid = 1
           ORDER BY lap_number""",
        {"sid": session_id},
    ).fetchall()

    laps = []
    for r in rows:
        d = dict(r)
        # Approximate kinetic energy metrics from speed data
        if d.get("speed_mean_mps") and d.get("speed_max_mps"):
            d["speed_range_mps"] = round(d["speed_max_mps"] - d["speed_mean_mps"], 3)
        laps.append(d)

    return api_response({"session_id": session_id, "laps": laps})


# ---------------------------------------------------------------------------
# 26. GET /sessions/<id>/consistency — lap consistency heatmap data
# ---------------------------------------------------------------------------

@bp.route("/sessions/<session_id>/consistency", methods=["GET"])
@rate_limit(tier="read")
def v1_consistency(session_id: str):
    """Return lap consistency analysis data.

    Includes per-lap times, deviations from mean/best, and stint analysis.

    Returns:
        200 with consistency data.
        404 if no lap data.
    """
    conn = get_db_connection()
    laps = get_laps_for_session(conn, session_id)
    valid_laps = [l for l in laps if l.get("lap_time_s") is not None and l.get("is_valid", True)]

    if not valid_laps:
        return api_error(ErrorCode.NOT_FOUND, "No valid lap data", status=404)

    times = [l["lap_time_s"] for l in valid_laps]
    mean_time = sum(times) / len(times)
    best_time = min(times)

    consistency_data = []
    for l in valid_laps:
        t = l["lap_time_s"]
        consistency_data.append({
            "lap_number": l["lap_number"],
            "lap_time_s": t,
            "delta_from_mean_s": round(t - mean_time, 4),
            "delta_from_best_s": round(t - best_time, 4),
            "pct_from_best": round((t - best_time) / best_time * 100, 3) if best_time > 0 else 0,
        })

    # Coefficient of variation
    if len(times) > 1 and mean_time > 0:
        variance = sum((t - mean_time) ** 2 for t in times) / (len(times) - 1)
        std_dev = variance ** 0.5
        cv_pct = round(std_dev / mean_time * 100, 3)
    else:
        std_dev = 0.0
        cv_pct = 0.0

    # Stint analysis if available
    stints = get_stint_analysis(conn, session_id)

    return api_response({
        "session_id": session_id,
        "mean_time_s": round(mean_time, 4),
        "best_time_s": round(best_time, 4),
        "std_dev_s": round(std_dev, 4),
        "cv_pct": cv_pct,
        "n_valid_laps": len(valid_laps),
        "laps": consistency_data,
        "stints": stints,
    })


# ---------------------------------------------------------------------------
# 27. GET /sessions/<id>/comparison-matrix — multi-metric lap comparison
# ---------------------------------------------------------------------------

@bp.route("/sessions/<session_id>/comparison-matrix", methods=["GET"])
@rate_limit(tier="read")
def v1_comparison_matrix(session_id: str):
    """Return multi-metric comparison matrix between laps.

    Returns:
        200 with ``{"session_id": "...", "laps": [...]}``
    """
    conn = get_db_connection()
    rows = conn.execute(
        """SELECT lap_number, lap_time_s, speed_mean_mps, speed_max_mps,
                  braking_max_mps2, accel_max_mps2, line_length_m,
                  is_valid, is_best, phase_id
           FROM laps
           WHERE session_id = :sid
           ORDER BY lap_number""",
        {"sid": session_id},
    ).fetchall()

    laps = [dict(r) for r in rows]
    return api_response({"session_id": session_id, "laps": laps})


# ---------------------------------------------------------------------------
# 28. GET /sessions/<id>/corner-mastery — corner mastery scores
# ---------------------------------------------------------------------------

@bp.route("/sessions/<session_id>/corner-mastery", methods=["GET"])
@rate_limit(tier="read")
def v1_corner_mastery(session_id: str):
    """Return corner-by-corner mastery scores.

    Computes a mastery rating per corner based on consistency of entry/apex/exit
    speeds and time loss across laps.

    Returns:
        200 with ``{"session_id": "...", "corners": [...]}``
    """
    conn = get_db_connection()
    rows = conn.execute(
        """SELECT corner_id,
                  COUNT(*) as lap_count,
                  AVG(entry_speed_mps) as avg_entry_mps,
                  AVG(apex_speed_mps)  as avg_apex_mps,
                  AVG(exit_speed_mps)  as avg_exit_mps,
                  AVG(time_loss_ms)    as avg_time_loss_ms,
                  MIN(time_loss_ms)    as min_time_loss_ms,
                  MAX(time_loss_ms)    as max_time_loss_ms,
                  AVG(grip_utilization) as avg_grip_util
           FROM corner_metrics
           WHERE session_id = :sid
           GROUP BY corner_id
           ORDER BY corner_id""",
        {"sid": session_id},
    ).fetchall()

    corners = []
    for r in rows:
        d = dict(r)
        # Mastery score: higher grip utilization + lower time loss = better
        mastery = 50.0  # base
        if d.get("avg_grip_util") is not None:
            mastery += d["avg_grip_util"] * 30
        if d.get("avg_time_loss_ms") is not None and d["avg_time_loss_ms"] >= 0:
            # Less time loss = higher mastery, cap deduction at 30
            mastery -= min(d["avg_time_loss_ms"] / 100, 30)
        d["mastery_score"] = round(max(0, min(100, mastery)), 1)
        corners.append(d)

    return api_response({"session_id": session_id, "corners": corners})


# ---------------------------------------------------------------------------
# 29. GET /sessions/<id>/details — full session details
# ---------------------------------------------------------------------------

@bp.route("/sessions/<session_id>/details", methods=["GET"])
@rate_limit(tier="read")
def v1_session_details(session_id: str):
    """Return full session details including scores and metadata.

    Returns:
        200 with comprehensive session data.
        404 if session not found.
    """
    conn = get_db_connection()
    session = get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    # Score details
    scores = get_score_details(conn, session_id)

    # Condition phases
    phase_rows = conn.execute(
        """SELECT phase_id, lap_start, lap_end, label, confidence, median_pace_s
           FROM condition_phases
           WHERE session_id = :sid
           ORDER BY phase_id""",
        {"sid": session_id},
    ).fetchall()
    phases = [dict(r) for r in phase_rows]

    # Data health
    dh_row = conn.execute(
        "SELECT * FROM data_health WHERE session_id = :sid",
        {"sid": session_id},
    ).fetchone()
    data_health = dict(dh_row) if dh_row else None

    # Weather
    weather_row = conn.execute(
        "SELECT * FROM session_weather WHERE session_id = :sid",
        {"sid": session_id},
    ).fetchone()
    weather = dict(weather_row) if weather_row else None

    return api_response({
        "session": session,
        "scores": scores,
        "condition_phases": phases,
        "data_health": data_health,
        "weather": weather,
    })


# ---------------------------------------------------------------------------
# 30. GET /sessions/<id>/laps — lap list with times, speeds, validity
# ---------------------------------------------------------------------------

@bp.route("/sessions/<session_id>/laps", methods=["GET"])
@rate_limit(tier="read")
def v1_session_laps(session_id: str):
    """Return full lap list with times, speeds, and validity.

    Returns:
        200 with ``{"session_id": "...", "laps": [...]}``
    """
    conn = get_db_connection()
    laps = get_laps_for_session(conn, session_id)
    return api_response({"session_id": session_id, "laps": laps})


# ===================================================================
# Batch 3: Browse/Search/Entity Endpoints (31–46)
# ===================================================================


# ---------------------------------------------------------------------------
# 31. GET /sessions/browse — paginated session list with search
# ---------------------------------------------------------------------------

@bp.route("/sessions/browse", methods=["GET"])
@rate_limit(tier="read")
def v1_sessions_browse():
    """Return paginated session list with optional search filtering.

    Query params:
        page (int): Page number (default 1).
        per_page (int): Items per page (default 25, max 100).
        driver (str): Filter by driver name (partial match).
        track (str): Filter by track name (partial match).
        sort (str): Sort field (date, score, best_time). Default: date.

    Returns:
        200 with ``{"sessions": [...], "total": N, "page": N, "per_page": N}``
    """
    conn = get_db_connection()

    page = max(1, request.args.get("page", 1, type=int))
    per_page = min(100, max(1, request.args.get("per_page", 25, type=int)))
    driver_filter = request.args.get("driver", "").strip()
    track_filter = request.args.get("track", "").strip()
    sort = request.args.get("sort", "date").strip()

    offset = (page - 1) * per_page

    # Build query with optional filters
    where_clauses = []
    params = {}
    if driver_filter:
        where_clauses.append("d.driver_name LIKE :driver")
        params["driver"] = f"%{driver_filter}%"
    if track_filter:
        where_clauses.append("t.track_name LIKE :track")
        params["track"] = f"%{track_filter}%"

    where_sql = ""
    if where_clauses:
        where_sql = "WHERE " + " AND ".join(where_clauses)

    sort_map = {
        "date": "s.session_date DESC",
        "score": "s.total_score DESC",
        "best_time": "s.best_lap_time_s ASC",
    }
    order_sql = sort_map.get(sort, "s.session_date DESC")

    # Count total
    count_row = conn.execute(
        f"""SELECT COUNT(*) as total
            FROM sessions s
            JOIN drivers d ON s.driver_id = d.driver_id
            LEFT JOIN tracks t ON s.track_id = t.track_id
            {where_sql}""",
        params,
    ).fetchone()
    total = count_row["total"] if count_row else 0

    # Fetch page
    params["limit"] = per_page
    params["offset"] = offset
    rows = conn.execute(
        f"""SELECT s.*, d.driver_name, t.track_name
            FROM sessions s
            JOIN drivers d ON s.driver_id = d.driver_id
            LEFT JOIN tracks t ON s.track_id = t.track_id
            {where_sql}
            ORDER BY {order_sql}
            LIMIT :limit OFFSET :offset""",
        params,
    ).fetchall()

    sessions = [dict(r) for r in rows]

    return api_response({
        "sessions": sessions,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": math.ceil(total / per_page) if per_page > 0 else 0,
    })


# ---------------------------------------------------------------------------
# 32. GET /sessions/recent — last 10 sessions
# ---------------------------------------------------------------------------

@bp.route("/sessions/recent", methods=["GET"])
@rate_limit(tier="read")
def v1_sessions_recent():
    """Return the most recent sessions.

    Query params:
        limit (int): Number of sessions (default 10, max 50).

    Returns:
        200 with ``{"sessions": [...]}``
    """
    conn = get_db_connection()
    limit = min(50, max(1, request.args.get("limit", 10, type=int)))
    sessions = get_sessions(conn, limit=limit, offset=0)
    return api_response({"sessions": sessions})


# ---------------------------------------------------------------------------
# 33. GET /dashboard/stats — dashboard statistics
# ---------------------------------------------------------------------------

@bp.route("/dashboard/stats", methods=["GET"])
@rate_limit(tier="read")
def v1_dashboard_stats():
    """Return dashboard overview statistics.

    Returns:
        200 with {total_sessions, total_drivers, avg_score, pb_time,
        recent_scores: number[], recent_times: number[],
        recent_sessions: SessionRow[]}
    """
    conn = get_db_connection()
    raw = get_dashboard_stats(conn)

    # Map DB column names to frontend-expected names
    stats = {
        "total_sessions": raw.get("total_sessions", 0) or 0,
        "total_drivers": raw.get("total_drivers", 0) or 0,
        "avg_score": raw.get("avg_score"),
        "pb_time": raw.get("overall_best_time_s"),
    }

    # Recent sessions — map to frontend SessionRow shape
    sessions = get_sessions(conn, limit=5, offset=0)
    stats["recent_sessions"] = [
        {
            "id": s.get("session_id", ""),
            "date": s.get("session_date", ""),
            "track_name": s.get("track_name", ""),
            "driver_name": s.get("driver_name", ""),
            "laps": s.get("n_laps", 0) or 0,
            "best_time": s.get("best_lap_time_s"),
            "score": s.get("total_score"),
        }
        for s in sessions
    ]

    # Recent scores — flat number array for sparkline
    score_rows = conn.execute(
        """SELECT s.total_score
           FROM sessions s
           WHERE s.total_score IS NOT NULL
           ORDER BY s.session_date DESC
           LIMIT 20""",
    ).fetchall()
    stats["recent_scores"] = [r["total_score"] for r in score_rows]

    # Recent best times — flat number array for sparkline
    time_rows = conn.execute(
        """SELECT s.best_lap_time_s
           FROM sessions s
           WHERE s.best_lap_time_s IS NOT NULL
           ORDER BY s.session_date DESC
           LIMIT 20""",
    ).fetchall()
    stats["recent_times"] = [r["best_lap_time_s"] for r in time_rows]

    return api_response(stats)


# ---------------------------------------------------------------------------
# 34. GET /drivers — list all drivers
# ---------------------------------------------------------------------------

@bp.route("/drivers", methods=["GET"])
@rate_limit(tier="read")
def v1_drivers_list():
    """Return all drivers with session counts and stats.

    Returns:
        200 with ``{"drivers": [...]}``
    """
    conn = get_db_connection()
    drivers = get_all_drivers(conn)
    return api_response({"drivers": drivers})


# ---------------------------------------------------------------------------
# 35. GET /drivers/<id> — driver detail
# ---------------------------------------------------------------------------

@bp.route("/drivers/<int:driver_id>", methods=["GET"])
@rate_limit(tier="read")
def v1_driver_detail(driver_id: int):
    """Return driver detail with profile and stats.

    Returns:
        200 with driver data.
        404 if driver not found.
    """
    conn = get_db_connection()
    row = conn.execute(
        """SELECT d.driver_id, d.driver_name, d.created_at, d.notes,
                  COUNT(s.session_id) AS session_count,
                  MIN(s.best_lap_time_s) AS personal_best_s,
                  AVG(s.total_score) AS mean_score
           FROM drivers d
           LEFT JOIN sessions s ON d.driver_id = s.driver_id
           WHERE d.driver_id = :did
           GROUP BY d.driver_id""",
        {"did": driver_id},
    ).fetchone()
    if row is None:
        return api_error(ErrorCode.NOT_FOUND, "Driver not found", status=404)

    driver = dict(row)
    profile = get_driver_profile(conn, driver_id)
    if profile:
        driver["profile"] = profile

    progression = get_driver_progression(conn, driver_id)
    if progression:
        driver["progression"] = progression

    return api_response(driver)


# ---------------------------------------------------------------------------
# 36. GET /drivers/<id>/sessions — sessions for a driver
# ---------------------------------------------------------------------------

@bp.route("/drivers/<int:driver_id>/sessions", methods=["GET"])
@rate_limit(tier="read")
def v1_driver_sessions(driver_id: int):
    """Return sessions for a specific driver.

    Query params:
        limit (int): Max results (default 50, max 200).
        offset (int): Pagination offset (default 0).

    Returns:
        200 with ``{"driver_id": N, "sessions": [...]}``
        404 if driver not found.
    """
    conn = get_db_connection()
    dr = conn.execute(
        "SELECT driver_id, driver_name FROM drivers WHERE driver_id = :did",
        {"did": driver_id},
    ).fetchone()
    if dr is None:
        return api_error(ErrorCode.NOT_FOUND, "Driver not found", status=404)

    limit = min(200, max(1, request.args.get("limit", 50, type=int)))
    offset = max(0, request.args.get("offset", 0, type=int))

    rows = conn.execute(
        """SELECT s.*, t.track_name
           FROM sessions s
           LEFT JOIN tracks t ON s.track_id = t.track_id
           WHERE s.driver_id = :did
           ORDER BY s.session_date DESC
           LIMIT :limit OFFSET :offset""",
        {"did": driver_id, "limit": limit, "offset": offset},
    ).fetchall()

    sessions = [dict(r) for r in rows]
    return api_response({
        "driver_id": driver_id,
        "driver_name": dr["driver_name"],
        "sessions": sessions,
    })


# ---------------------------------------------------------------------------
# 37. GET /tracks — list all tracks
# ---------------------------------------------------------------------------

@bp.route("/tracks", methods=["GET"])
@rate_limit(tier="read")
def v1_tracks_list():
    """Return all tracks with session counts.

    Returns:
        200 with ``{"tracks": [...]}``
    """
    conn = get_db_connection()
    tracks = get_all_tracks(conn)
    return api_response({"tracks": tracks})


# ---------------------------------------------------------------------------
# 38. GET /tracks/<id> — track detail
# ---------------------------------------------------------------------------

@bp.route("/tracks/<track_id>", methods=["GET"])
@rate_limit(tier="read")
def v1_track_detail(track_id: str):
    """Return track detail with session and lap stats.

    Returns:
        200 with track data.
        404 if track not found.
    """
    conn = get_db_connection()
    track = get_track_by_id(conn, track_id)
    if track is None:
        return api_error(ErrorCode.NOT_FOUND, "Track not found", status=404)

    # Add session count and best time
    stats_row = conn.execute(
        """SELECT COUNT(s.session_id) AS session_count,
                  MIN(s.best_lap_time_s) AS best_time_s,
                  COUNT(DISTINCT s.driver_id) AS driver_count
           FROM sessions s
           WHERE s.track_id = :tid""",
        {"tid": track_id},
    ).fetchone()
    if stats_row:
        track["session_count"] = stats_row["session_count"]
        track["best_time_s"] = stats_row["best_time_s"]
        track["driver_count"] = stats_row["driver_count"]

    return api_response(track)


# ---------------------------------------------------------------------------
# 39. GET /tracks/<id>/leaderboard — fastest times at a track
# ---------------------------------------------------------------------------

@bp.route("/tracks/<track_id>/leaderboard", methods=["GET"])
@rate_limit(tier="read")
def v1_track_leaderboard(track_id: str):
    """Return fastest lap times at a track (leaderboard).

    Query params:
        limit (int): Max entries (default 20, max 100).

    Returns:
        200 with ``{"track_id": "...", "leaderboard": [...]}``
    """
    conn = get_db_connection()
    limit = min(100, max(1, request.args.get("limit", 20, type=int)))

    rows = conn.execute(
        """SELECT s.session_id, s.session_date, s.best_lap_time_s,
                  s.total_score, s.grade, s.session_type, s.track_state,
                  d.driver_name
           FROM sessions s
           JOIN drivers d ON s.driver_id = d.driver_id
           WHERE s.track_id = :tid AND s.best_lap_time_s IS NOT NULL
           ORDER BY s.best_lap_time_s ASC
           LIMIT :limit""",
        {"tid": track_id, "limit": limit},
    ).fetchall()

    leaderboard = []
    for i, r in enumerate(rows, 1):
        entry = dict(r)
        entry["rank"] = i
        leaderboard.append(entry)

    return api_response({"track_id": track_id, "leaderboard": leaderboard})


# ---------------------------------------------------------------------------
# 40. GET /karts — list all karts
# ---------------------------------------------------------------------------

@bp.route("/karts", methods=["GET"])
@rate_limit(tier="read")
def v1_karts_list():
    """Return all user karts with session counts.

    Returns:
        200 with ``{"karts": [...]}``
    """
    conn = get_db_connection()
    try:
        karts = get_all_karts(conn)
    except Exception:
        request_id = getattr(g, "request_id", None)
        workspace_id = getattr(g, "workspace_id", None)
        user_id = getattr(g, "current_user_id", None) or getattr(g, "user_id", None)
        logger.exception(
            "Failed to load karts list "
            "(request_id=%s workspace_id=%s user_id=%s)",
            request_id,
            workspace_id,
            user_id,
        )

        # Surface migration/schema drift in logs when operational errors occur.
        if current_app.config.get("USE_PG"):
            logger.warning("Karts schema validation check skipped for PostgreSQL backend.")
        else:
            try:
                validate_karts_schema(conn)
            except Exception:
                logger.warning("Unable to validate karts schema state after failure.", exc_info=True)

        return api_error(
            ErrorCode.INTERNAL_ERROR,
            "Internal server error",
            status=500,
        )
    return api_response({"karts": karts})


# ---------------------------------------------------------------------------
# 41. GET /karts/<id> — kart detail
# ---------------------------------------------------------------------------

@bp.route("/karts/<int:kart_id>", methods=["GET"])
@rate_limit(tier="read")
def v1_kart_detail(kart_id: int):
    """Return kart detail.

    Returns:
        200 with kart data.
        404 if kart not found.
    """
    conn = get_db_connection()
    kart = get_kart_by_id(conn, kart_id)
    if kart is None:
        return api_error(ErrorCode.NOT_FOUND, "Kart not found", status=404)

    # Add session count
    count_row = conn.execute(
        "SELECT COUNT(*) as session_count FROM sessions WHERE kart_id = :kid",
        {"kid": kart_id},
    ).fetchone()
    kart["session_count"] = count_row["session_count"] if count_row else 0

    return api_response(kart)


# ---------------------------------------------------------------------------
# 42. GET /weekends — list all weekends
# ---------------------------------------------------------------------------

@bp.route("/weekends", methods=["GET"])
@rate_limit(tier="read")
def v1_weekends_list():
    """Return all weekends with session counts.

    Returns:
        200 with ``{"weekends": [...]}``
    """
    conn = get_db_connection()
    weekends = get_all_weekends(conn)
    return api_response({"weekends": weekends})


# ---------------------------------------------------------------------------
# 43. GET /weekends/<id> — weekend detail
# ---------------------------------------------------------------------------

@bp.route("/weekends/<int:weekend_id>", methods=["GET"])
@rate_limit(tier="read")
def v1_weekend_detail(weekend_id: int):
    """Return weekend detail with sessions.

    Returns:
        200 with weekend data and sessions.
        404 if weekend not found.
    """
    conn = get_db_connection()
    weekend = get_weekend_by_id(conn, weekend_id)
    if weekend is None:
        return api_error(ErrorCode.NOT_FOUND, "Weekend not found", status=404)

    sessions = get_weekend_sessions(conn, weekend_id)
    weekend["sessions"] = sessions

    return api_response(weekend)


# ---------------------------------------------------------------------------
# 44. GET /annotations — list annotations with optional search
# ---------------------------------------------------------------------------

@bp.route("/annotations", methods=["GET"])
@rate_limit(tier="read")
def v1_annotations_list():
    """Return session annotations with optional filtering.

    Query params:
        session_id (str): Filter by session ID.
        type (str): Filter by annotation_type.
        q (str): Full-text search in title and body.
        limit (int): Max results (default 50, max 200).
        offset (int): Pagination offset.

    Returns:
        200 with ``{"annotations": [...], "total": N}``
    """
    conn = get_db_connection()

    where_clauses = []
    params = {}

    session_filter = request.args.get("session_id", "").strip()
    if session_filter:
        where_clauses.append("a.session_id = :session_id")
        params["session_id"] = session_filter

    type_filter = request.args.get("type", "").strip()
    if type_filter:
        where_clauses.append("a.annotation_type = :atype")
        params["atype"] = type_filter

    q = request.args.get("q", "").strip()
    if q:
        where_clauses.append("(a.title LIKE :q OR a.body LIKE :q)")
        params["q"] = f"%{q}%"

    where_sql = ""
    if where_clauses:
        where_sql = "WHERE " + " AND ".join(where_clauses)

    limit = min(200, max(1, request.args.get("limit", 50, type=int)))
    offset = max(0, request.args.get("offset", 0, type=int))

    count_row = conn.execute(
        f"SELECT COUNT(*) as total FROM session_annotations a {where_sql}",
        params,
    ).fetchone()
    total = count_row["total"] if count_row else 0

    params["limit"] = limit
    params["offset"] = offset
    rows = conn.execute(
        f"""SELECT a.*, s.session_date, d.driver_name, t.track_name
            FROM session_annotations a
            JOIN sessions s ON a.session_id = s.session_id
            JOIN drivers d ON s.driver_id = d.driver_id
            LEFT JOIN tracks t ON s.track_id = t.track_id
            {where_sql}
            ORDER BY a.created_at DESC
            LIMIT :limit OFFSET :offset""",
        params,
    ).fetchall()

    annotations = []
    for r in rows:
        d = dict(r)
        if d.get("tags_json"):
            try:
                d["tags"] = json.loads(d["tags_json"])
            except (json.JSONDecodeError, TypeError):
                d["tags"] = []
            del d["tags_json"]
        annotations.append(d)

    return api_response({"annotations": annotations, "total": total})


# ---------------------------------------------------------------------------
# 45. GET /data-health/stats — ingest job statistics
# ---------------------------------------------------------------------------

@bp.route("/data-health/stats", methods=["GET"])
@rate_limit(tier="read")
def v1_data_health_stats():
    """Return aggregate ingest job statistics.

    Returns:
        200 with ``{"total_jobs": N, "completed": N, "failed": N, ...}``
    """
    conn = get_db_connection()
    try:
        row = conn.execute(
            """SELECT
                   COUNT(*)                                    AS total_jobs,
                   SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed,
                   SUM(CASE WHEN status = 'failed'    THEN 1 ELSE 0 END) AS failed,
                   SUM(CASE WHEN status = 'pending'   THEN 1 ELSE 0 END) AS pending,
                   SUM(CASE WHEN status = 'running'   THEN 1 ELSE 0 END) AS running,
                   AVG(elapsed_s)                              AS avg_elapsed_s,
                   AVG(peak_rss_mb)                            AS avg_peak_rss_mb,
                   AVG(throughput_mb_s)                         AS avg_throughput_mb_s,
                   SUM(n_rows_loaded)                          AS total_rows_loaded,
                   SUM(file_size)                               AS total_bytes_processed
               FROM ingestion_jobs"""
        ).fetchone()
        stats = dict(row) if row else {}
    except Exception:
        stats = {}

    return api_response(stats)


# ---------------------------------------------------------------------------
# 46. GET /data-health/jobs — recent ingest jobs list
# ---------------------------------------------------------------------------

@bp.route("/data-health/jobs", methods=["GET"])
@rate_limit(tier="read")
def v1_data_health_jobs():
    """Return recent ingest jobs.

    Query params:
        limit (int): Max results (default 25, max 100).
        status (str): Filter by status (completed, failed, pending, running).

    Returns:
        200 with ``{"jobs": [...]}``
    """
    conn = get_db_connection()
    limit = min(100, max(1, request.args.get("limit", 25, type=int)))
    status_filter = request.args.get("status", "").strip()

    params = {"limit": limit}
    where_sql = ""
    if status_filter:
        where_sql = "WHERE status = :status"
        params["status"] = status_filter

    try:
        rows = conn.execute(
            f"""SELECT job_id, file_path, file_size, sha256_partial,
                       status, n_rows_total, n_rows_loaded, n_chunks,
                       error_message, elapsed_s, peak_rss_mb,
                       throughput_mb_s, started_at, completed_at
                FROM ingestion_jobs
                {where_sql}
                ORDER BY started_at DESC
                LIMIT :limit""",
            params,
        ).fetchall()
        jobs = []
        for r in rows:
            d = dict(r)
            # Expose file_name only, never full file_path
            if d.get("file_path"):
                d["file_name"] = Path(d["file_path"]).name
                del d["file_path"]
            jobs.append(d)
    except Exception:
        jobs = []

    return api_response({"jobs": jobs})
