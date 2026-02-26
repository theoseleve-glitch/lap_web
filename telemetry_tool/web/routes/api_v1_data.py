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

from flask import Blueprint, current_app, request

from web.api_utils import ErrorCode, api_error, api_response
from web.db import get_db_connection
from web.models import (
    get_gps_trace,
    get_gps_lap_numbers,
    get_laps_for_session,
    get_reference_line,
    get_session_by_id,
    get_theoretical_data,
    get_track_records,
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
    return api_response({
        "theoretical_time_s": data.get("theoretical_time_s"),
        "actual_best_time_s": data.get("actual_best_time_s"),
        "gap_pct": data.get("gap_pct"),
        "simulation_method": data.get("simulation_method"),
        "speeds": data.get("speeds"),
        "distances": data.get("distances"),
        "metrics": data.get("metrics"),
    })


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
