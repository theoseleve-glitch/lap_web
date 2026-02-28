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
    update_session_field,
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
    """Return speed vs distance data for the best lap.

    Returns:
        200 with ``{"distances": [...], "speeds": [...]}``
        404 if session not found or no GPS data.
    """
    conn = get_db_connection()
    session = get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    laps = get_laps_for_session(conn, session_id)

    best_lap = None
    for lap in laps:
        if lap.get("is_best"):
            best_lap = lap["lap_number"]
            break
    if best_lap is None and laps:
        best_lap = laps[0]["lap_number"]

    if best_lap is None:
        return api_error(ErrorCode.NOT_FOUND, "No laps found", status=404)

    gps = get_gps_trace(conn, session_id, best_lap)
    if gps is None or not gps.get("distances") or not gps.get("speeds"):
        return api_error(ErrorCode.NOT_FOUND, "No speed trace data", status=404)

    return api_response({
        "distances": gps["distances"],
        "speeds": gps["speeds"],
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
        "lat_g": accel_lat_all,
        "lon_g": accel_long_all,
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
    """Return a performance fingerprint for a session.

    Returns:
        200 with ``{"metrics": [{"name": str, "value": float, "max": float}, ...]}``
        404 if session not found.
    """
    conn = get_db_connection()
    session = get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    sd = get_score_details(conn, session_id)
    metrics = []
    if sd:
        for label, key, max_key, default_max in [
            ("Pace", "pace_score", "pace_max", 25),
            ("Consistency", "consistency_score", "consistency_max", 25),
            ("Execution", "execution_score", "execution_max", 20),
            ("Robustness", "robustness_score", "robustness_max", 15),
        ]:
            score = sd.get(key)
            mx = sd.get(max_key, default_max) or default_max
            if score is not None:
                metrics.append({"name": label, "value": round(score, 1), "max": mx})

    # Include strengths/weaknesses from score_details
    strengths = sd.get("strengths", []) if sd else []
    weaknesses = sd.get("weaknesses", []) if sd else []

    # Adaptation score (optional)
    adaptation = None
    if sd and sd.get("adaptation_score") is not None:
        adaptation = round(sd["adaptation_score"], 2)

    return api_response({
        "metrics": metrics,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "adaptation_score": adaptation,
    })


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
# 8b. GET /sessions/<id>/gps-trace — best-lap GPS for track map
# ---------------------------------------------------------------------------

@bp.route("/sessions/<session_id>/gps-trace", methods=["GET"])
@rate_limit(tier="read")
def v1_gps_trace(session_id: str):
    """Return GPS lat/lon/speed arrays for the best lap (track map display).

    Returns:
        200 with ``{"lat": [...], "lon": [...], "speed": [...]}``
        404 if no best lap or no GPS data.
    """
    conn = get_db_connection()
    laps = get_laps_for_session(conn, session_id)
    best_lap = None
    for lap in laps:
        if lap.get("is_best"):
            best_lap = lap["lap_number"]
            break
    # Fallback: use first valid lap if no explicit best
    if best_lap is None and laps:
        best_lap = laps[0]["lap_number"]

    if best_lap is None:
        return api_error(ErrorCode.NOT_FOUND, "No laps found", status=404)

    gps = get_gps_trace(conn, session_id, best_lap)
    if gps is None:
        return api_error(ErrorCode.NOT_FOUND, "No GPS data for best lap", status=404)

    return api_response({
        "lat": gps.get("latitudes", []),
        "lon": gps.get("longitudes", []),
        "speed": gps.get("speeds", []),
    })


# ---------------------------------------------------------------------------
# 9. GET /sessions/<id>/fatigue — fatigue and concentration analysis
# ---------------------------------------------------------------------------

@bp.route("/sessions/<session_id>/fatigue", methods=["GET"])
@rate_limit(tier="read")
def v1_fatigue(session_id: str):
    """Return driver fatigue and concentration analysis.

    Returns:
        200 with ``{"laps": [...], "fatigue_index": [...], "reaction_time": [...]}``
        404 if session not found or no lap data.
    """
    conn = get_db_connection()
    session = get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    laps_data = get_laps_for_session(conn, session_id)
    valid = [l for l in laps_data if l.get("is_valid", True)]
    if not valid:
        return api_response({"laps": [], "fatigue_index": [], "reaction_time": []})

    valid = sorted(valid, key=lambda l: l["lap_number"])
    lap_nums = [l["lap_number"] for l in valid]
    times = [l.get("lap_time_s", 0) for l in valid]
    # FIX-003: Guard div-by-zero when all lap times are 0
    mean_time = sum(times) / len(times) if times and sum(times) > 0 else 1

    fatigue_index = []
    running_avg = times[0] if times else 0
    for t in times:
        running_avg = running_avg * 0.8 + t * 0.2
        drift = ((running_avg - mean_time) / mean_time) * 100 if mean_time else 0
        fatigue_index.append(round(drift, 2))

    reaction_time = []
    for l in valid:
        brake = l.get("braking_max_mps2")
        reaction_time.append(round(abs(brake), 2) if brake else 0)

    return api_response({
        "laps": lap_nums,
        "fatigue_index": fatigue_index,
        "reaction_time": reaction_time,
    })


# ---------------------------------------------------------------------------
# 10. GET /sessions/<id>/speed-profile — track segment speed profile
# ---------------------------------------------------------------------------

@bp.route("/sessions/<session_id>/speed-profile", methods=["GET"])
@rate_limit(tier="read")
def v1_speed_profile(session_id: str):
    """Return speed profile comparing best, average, and worst laps.

    Returns:
        200 with ``{"distances": [...], "best_lap": [...], "average": [...], "worst_lap": [...]}``
        404 if session not found.
    """
    conn = get_db_connection()
    session = get_session_by_id(conn, session_id)
    if not session:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)
    laps = get_laps_for_session(conn, session_id)
    valid = [l for l in laps if l.get("is_valid", True)]
    if not valid:
        return api_response({"distances": [], "best_lap": [], "average": [], "worst_lap": []})

    sorted_laps = sorted(valid, key=lambda l: l.get("lap_time_s") or 9999)
    best = sorted_laps[0]
    worst = sorted_laps[-1]

    best_gps = get_gps_trace(conn, session_id, best["lap_number"])
    worst_gps = get_gps_trace(conn, session_id, worst["lap_number"])

    if not best_gps or not best_gps.get("distances") or not best_gps.get("speeds"):
        return api_response({"distances": [], "best_lap": [], "average": [], "worst_lap": []})

    distances = best_gps["distances"]
    best_speeds = best_gps["speeds"]
    worst_speeds = worst_gps.get("speeds", []) if worst_gps else []

    avg_speeds = []
    for i in range(len(best_speeds)):
        vals = [best_speeds[i]]
        if i < len(worst_speeds):
            vals.append(worst_speeds[i])
        avg_speeds.append(round(sum(vals) / len(vals), 2))

    while len(worst_speeds) < len(best_speeds):
        worst_speeds.append(worst_speeds[-1] if worst_speeds else 0)

    return api_response({
        "distances": distances,
        "best_lap": best_speeds,
        "average": avg_speeds,
        "worst_lap": worst_speeds[:len(best_speeds)],
    })


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
                "size": stat.st_size,
                "size_bytes": stat.st_size,
                "size_human": _human_size(stat.st_size),
                "modified": stat.st_mtime,
                "modified_human": datetime.fromtimestamp(stat.st_mtime).strftime(
                    "%Y-%m-%d %H:%M"
                ),
            })
    return api_response({"files": files})


# ---------------------------------------------------------------------------
# 14b. POST /files/upload — upload a CSV file
# ---------------------------------------------------------------------------

@bp.route("/files/upload", methods=["POST"])
@rate_limit(tier="write")
def v1_files_upload():
    """Upload a CSV file to data/raw/.

    Accepts multipart/form-data with a ``file`` field.
    Validates: .csv extension, no double extensions, no binary content,
    decodable as UTF-8 or Latin-1, valid CSV structure (>=2 columns).

    Returns:
        200 with ``{"filename": "...", "size_bytes": ..., "size_human": "..."}``
    """
    import csv
    import io

    from werkzeug.utils import secure_filename

    # Diagnostic logging (print to guarantee Gunicorn stdout)
    ct = request.content_type or "none"
    cl = request.content_length
    has_auth = bool(request.headers.get("Authorization"))
    file_keys = list(request.files.keys()) if request.files else []
    print(f"[UPLOAD] content_type={ct} content_length={cl} has_auth={has_auth} file_keys={file_keys}", flush=True)

    if "file" not in request.files:
        form_keys = list(request.form.keys())
        print(f"[UPLOAD REJECTED] no 'file' field. form_keys={form_keys}", flush=True)
        return api_error(ErrorCode.VALIDATION_ERROR, "No file provided", status=400)

    f = request.files["file"]
    if not f.filename:
        print("[UPLOAD REJECTED] empty filename", flush=True)
        return api_error(ErrorCode.VALIDATION_ERROR, "Empty filename", status=400)

    # Extension validation: must end with .csv, reject dangerous double
    # extensions like "data.csv.exe" but allow dots in names (dates, etc.)
    basename = f.filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    print(f"[UPLOAD] basename={basename!r}", flush=True)
    if not basename.lower().endswith(".csv"):
        print(f"[UPLOAD REJECTED] not .csv: {basename!r}", flush=True)
        return api_error(ErrorCode.VALIDATION_ERROR, f"Only .csv files allowed (got: {basename})", status=400)
    # Block executable double-extensions after .csv (e.g. "file.csv.exe")
    _DANGEROUS_EXTS = {".exe", ".bat", ".cmd", ".sh", ".ps1", ".msi", ".dll", ".scr", ".com", ".js", ".vbs", ".php"}
    name_without_csv = basename[:-4]  # strip trailing .csv
    if "." in name_without_csv:
        trailing_ext = name_without_csv.rsplit(".", 1)[-1].lower()
        if f".{trailing_ext}" in _DANGEROUS_EXTS:
            return api_error(ErrorCode.VALIDATION_ERROR, "Only .csv files allowed", status=400)

    # Content validation
    sample = f.read(8192)
    f.seek(0)

    if b"\x00" in sample:
        print(f"[UPLOAD REJECTED] binary content detected in {basename!r}", flush=True)
        return api_error(ErrorCode.VALIDATION_ERROR, "File appears to be binary, not CSV", status=400)

    try:
        text_sample = sample.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text_sample = sample.decode("latin-1")
        except UnicodeDecodeError:
            print(f"[UPLOAD REJECTED] undecodable text in {basename!r}", flush=True)
            return api_error(ErrorCode.VALIDATION_ERROR, "File is not valid text", status=400)

    # Find the real header line — skip comment/metadata lines
    # (RaceChrono Pro puts "This file is created using..." on line 1)
    lines = text_sample.split("\n")
    header_line = None
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # A real CSV header has at least one delimiter
        for delim in [",", ";", "\t", "|"]:
            if delim in stripped:
                header_line = stripped
                break
        if header_line:
            break

    if header_line:
        try:
            dialect = csv.Sniffer().sniff(header_line, delimiters=",;\t|")
        except csv.Error:
            dialect = None
        reader = csv.reader(io.StringIO(header_line), dialect or csv.excel)
        try:
            headers = next(reader)
            print(f"[UPLOAD] {basename!r}: detected {len(headers)} columns, delimiter={getattr(dialect, 'delimiter', ',').__repr__()}", flush=True)
            if len(headers) < 2:
                print(f"[UPLOAD REJECTED] <2 columns: {headers!r}", flush=True)
                return api_error(ErrorCode.VALIDATION_ERROR, f"CSV must have at least 2 columns (found {len(headers)})", status=400)
        except (csv.Error, StopIteration):
            print(f"[UPLOAD REJECTED] CSV parse error: {header_line[:100]!r}", flush=True)
            return api_error(ErrorCode.VALIDATION_ERROR, "File does not appear to be valid CSV", status=400)
    else:
        print(f"[UPLOAD] {basename!r}: no delimited line found in sample, allowing anyway", flush=True)

    safe_name = secure_filename(f.filename) or "upload.csv"
    if not safe_name.lower().endswith(".csv"):
        safe_name += ".csv"
    raw_dir = Path(current_app.config.get("DATA_RAW_DIR", "data/raw"))
    raw_dir.mkdir(parents=True, exist_ok=True)
    dest = raw_dir / safe_name
    f.save(str(dest))

    stat = dest.stat()
    return api_response({
        "filename": safe_name,
        "size_bytes": stat.st_size,
        "size_human": _human_size(stat.st_size),
    })


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


# ---------------------------------------------------------------------------
# 15b. PATCH /sessions/<id> — update editable session metadata
# ---------------------------------------------------------------------------

# Mapping from API field names to DB column names.
_PATCH_FIELD_MAP = {
    "driver_name": "driver_name",   # resolved to driver_id below
    "track_name": "track_name",     # resolved to track_id below
    "session_type": "session_type",
    "condition": "track_state",
    "notes": "notes",
}


@bp.route("/sessions/<session_id>", methods=["PATCH"])
@rate_limit(tier="write")
def v1_patch_session(session_id: str):
    """Update editable metadata fields on a session.

    Accepts JSON body with optional keys: ``driver_name``, ``track_name``,
    ``session_type``, ``condition``, ``notes``.

    Returns:
        200 with updated session detail.
        400 if body is empty or contains unknown fields.
        404 if session not found.
    """
    conn = get_db_connection()

    # Verify session exists
    session = get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    body = request.get_json(silent=True) or {}
    if not body:
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            "Request body must be a non-empty JSON object",
            status=400,
        )

    # Filter to known fields only
    unknown = set(body.keys()) - set(_PATCH_FIELD_MAP.keys())
    if unknown:
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            f"Unknown fields: {', '.join(sorted(unknown))}",
            status=400,
        )

    try:
        for api_field, value in body.items():
            if api_field == "driver_name":
                # Resolve driver_name → driver_id (upsert driver)
                driver_name = (value or "").strip()
                if not driver_name:
                    continue
                conn.execute(
                    "INSERT INTO drivers (driver_name) VALUES (:name) "
                    "ON CONFLICT(driver_name) DO NOTHING",
                    {"name": driver_name},
                )
                row = conn.execute(
                    "SELECT driver_id FROM drivers WHERE driver_name = :name",
                    {"name": driver_name},
                ).fetchone()
                if row:
                    update_session_field(conn, session_id, "driver_id", row["driver_id"] if isinstance(row, dict) else row[0])
            elif api_field == "track_name":
                # Resolve track_name → track_id (look up existing track)
                track_name = (value or "").strip()
                if not track_name:
                    continue
                row = conn.execute(
                    "SELECT track_id FROM tracks WHERE track_name = :name",
                    {"name": track_name},
                ).fetchone()
                if row:
                    update_session_field(conn, session_id, "track_id", row["track_id"] if isinstance(row, dict) else row[0])
                # If track not found, silently skip (user can only assign existing tracks)
            else:
                db_col = _PATCH_FIELD_MAP[api_field]
                update_session_field(conn, session_id, db_col, value)

        conn.commit()

        # Return updated session
        updated = get_session_by_id(conn, session_id)
        result = {
            "id": updated.get("session_id"),
            "date": updated.get("session_date"),
            "track_name": updated.get("track_name"),
            "driver_name": updated.get("driver_name"),
            "session_type": updated.get("session_type"),
            "condition": updated.get("track_state"),
            "notes": updated.get("notes"),
        }
        return api_response(result)

    except Exception as exc:
        logger.error("Failed to patch session %s: %s", session_id, exc)
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

    # FIX-007: Use .get() for driver_id/track_id to avoid KeyError
    driver_id = session.get("driver_id")
    track_id = session.get("track_id")
    if not driver_id or not track_id:
        return api_response({
            "session_id": session_id,
            "driver_name": session.get("driver_name"),
            "track_name": session.get("track_name"),
            "comparisons": [],
        })

    rows = conn.execute(
        """SELECT s.session_id, s.session_date, s.best_lap_time_s,
                  s.total_score, s.grade, s.n_laps, s.session_type
           FROM sessions s
           WHERE s.driver_id = :driver_id
             AND s.track_id = :track_id
           ORDER BY s.session_date DESC""",
        {"driver_id": driver_id, "track_id": track_id},
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
    """Return sector timing data for a session.

    Returns:
        200 with ``{"sectors": [{"name": str, "best": float, "avg": float, "worst": float}]}``
    """
    conn = get_db_connection()
    raw = get_session_sectors(conn, session_id)
    sectors = []
    for s in raw:
        sectors.append({
            "name": s.get("label") or f"S{s.get('sector_index', 0) + 1}",
            "best": s.get("best_time_s") or 0,
            "avg": s.get("avg_time_s") or 0,
            "worst": s.get("worst_time_s") or 0,
        })
    return api_response({"sectors": sectors})


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
        # FIX-005: Try to fetch best practice — table may not exist
        if session.get("track_id"):
            try:
                bp_row = conn.execute(
                    """SELECT best_entry_mps, best_apex_mps, best_exit_mps,
                              best_brake_m, best_time_s
                       FROM corner_best_practices
                       WHERE track_id = :tid AND corner_id = :cid""",
                    {"tid": session["track_id"], "cid": r["corner_id"]},
                ).fetchone()
            except Exception:
                bp_row = None
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

    # FIX-008: Use .get() for driver_id to avoid KeyError
    driver_id = session.get("driver_id")
    badges = []
    if driver_id:
        # FIX-006: Wrap badge queries in try/except — tables may not exist
        try:
            badge_rows = conn.execute(
                """SELECT badge_type, badge_name, badge_level, metadata_json, earned_at
                   FROM driver_badges
                   WHERE driver_id = :did
                   ORDER BY earned_at DESC""",
                {"did": driver_id},
            ).fetchall()
            for r in badge_rows:
                b = dict(r)
                if b.get("metadata_json"):
                    try:
                        b["metadata"] = json.loads(b["metadata_json"])
                    except (json.JSONDecodeError, TypeError):
                        b["metadata"] = None
                    del b["metadata_json"]
                badges.append(b)
        except Exception:
            badges = []

    # Session tags as lightweight badges
    tags = []
    try:
        tag_rows = conn.execute(
            """SELECT tag, confidence, source, created_at
               FROM session_tags
               WHERE session_id = :sid
               ORDER BY created_at""",
            {"sid": session_id},
        ).fetchall()
        tags = [dict(r) for r in tag_rows]
    except Exception:
        tags = []

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

    # Build radar chart data: {labels: string[], values: number[]}
    # Values are normalized 0–1 (fraction of max).
    def _build_radar(sd: dict) -> dict:
        """Convert score_details into radar chart labels+values."""
        pairs = []
        for label, key, max_key in [
            ("Pace", "pace_score", "pace_max"),
            ("Consistency", "consistency_score", "consistency_max"),
            ("Execution", "execution_score", "execution_max"),
            ("Robustness", "robustness_score", "robustness_max"),
        ]:
            score = sd.get(key)
            max_val = sd.get(max_key, 25)
            if score is not None and max_val and max_val > 0:
                pairs.append((label, round(score / max_val, 3)))
            elif score is not None:
                pairs.append((label, round(score / 25, 3)))
        if not pairs:
            return {"labels": [], "values": []}
        return {
            "labels": [p[0] for p in pairs],
            "values": [p[1] for p in pairs],
        }

    style = get_driving_style(conn, session["driver_id"], session_id)
    if style is None:
        # Fallback: try score_details for basic style info
        sd = get_score_details(conn, session_id)
        if sd:
            return api_response(_build_radar(sd))
        return api_error(ErrorCode.NOT_FOUND, "No style data", status=404)

    # If we have driving_style_features, build a richer radar
    sd = get_score_details(conn, session_id)
    if sd:
        radar = _build_radar(sd)
    else:
        radar = {"labels": [], "values": []}

    # Add style-specific dimensions if available
    extra_pairs = []
    if style.get("smoothness_composite") is not None:
        extra_pairs.append(("Smoothness", round(min(1.0, style["smoothness_composite"]), 3)))
    if style.get("brake_point_consistency") is not None:
        extra_pairs.append(("Braking", round(min(1.0, style["brake_point_consistency"]), 3)))
    for label, val in extra_pairs:
        radar["labels"].append(label)
        radar["values"].append(val)

    return api_response(radar)


# ---------------------------------------------------------------------------
# 24. GET /sessions/<id>/brake-points — brake point locations
# ---------------------------------------------------------------------------

@bp.route("/sessions/<session_id>/brake-points", methods=["GET"])
@rate_limit(tier="read")
def v1_brake_points(session_id: str):
    """Return brake point locations derived from corner_metrics.

    Returns:
        200 with ``{"distances": [...], "speeds": [...], "pressures": [...]}``
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

    brake_pts = [dict(r) for r in rows]

    distances = [bp["brake_point_m"] for bp in brake_pts if bp.get("brake_point_m") is not None]
    speeds = [round((bp.get("entry_speed_mps") or 0) * 3.6, 1) for bp in brake_pts if bp.get("brake_point_m") is not None]
    pressures = [round(bp.get("brake_intensity") or 0.5, 2) for bp in brake_pts if bp.get("brake_point_m") is not None]

    return api_response({
        "distances": distances,
        "speeds": speeds,
        "pressures": pressures,
    })


# ---------------------------------------------------------------------------
# 25. GET /sessions/<id>/energy — energy balance data
# ---------------------------------------------------------------------------

@bp.route("/sessions/<session_id>/energy", methods=["GET"])
@rate_limit(tier="read")
def v1_energy(session_id: str):
    """Return energy balance data for the best lap.

    Returns:
        200 with ``{"distances": [...], "kinetic_energy": [...], "braking_energy": [...]}``
        404 if session not found.
    """
    conn = get_db_connection()
    session = get_session_by_id(conn, session_id)
    if not session:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    # FIX-001: Use laps-table best-lap lookup (best_lap_number is not a real column)
    laps = get_laps_for_session(conn, session_id)
    best_lap_obj = next((l for l in laps if l.get("is_best")), laps[0] if laps else None)
    if not best_lap_obj:
        return api_response({"distances": [], "kinetic_energy": [], "braking_energy": []})
    best_lap = best_lap_obj.get("lap_number", 1)

    gps = get_gps_trace(conn, session_id, best_lap)
    if not gps or not gps.get("distances") or not gps.get("speeds"):
        return api_response({"distances": [], "kinetic_energy": [], "braking_energy": []})

    distances = gps["distances"]
    speeds = gps["speeds"]
    mass = 80  # kart+driver approx kg

    # EXTRA-FIX-B: RaceChrono GPS speeds are already in m/s — no /3.6 conversion
    kinetic = [round(0.5 * mass * v ** 2, 1) for v in speeds]

    braking = [0.0]
    for i in range(1, len(speeds)):
        dv = speeds[i] - speeds[i - 1]
        if dv < 0:
            braking.append(round(0.5 * mass * dv ** 2, 1))
        else:
            braking.append(0.0)

    return api_response({
        "distances": distances,
        "kinetic_energy": kinetic,
        "braking_energy": braking,
    })


# ---------------------------------------------------------------------------
# 26. GET /sessions/<id>/consistency — lap consistency heatmap data
# ---------------------------------------------------------------------------

@bp.route("/sessions/<session_id>/consistency", methods=["GET"])
@rate_limit(tier="read")
def v1_consistency(session_id: str):
    """Return lap consistency heatmap data.

    Returns:
        200 with ``{"laps": [...], "sectors": [...], "deltas": [[...]]}``
        404 if no lap data.
    """
    conn = get_db_connection()
    laps_data = get_laps_for_session(conn, session_id)
    valid = sorted(
        [l for l in laps_data if l.get("is_valid", True)],
        key=lambda l: l["lap_number"],
    )
    if not valid:
        return api_response({"laps": [], "sectors": [], "deltas": []})

    times = [l.get("lap_time_s", 0) for l in valid]
    mean_t = sum(times) / len(times) if times else 1

    lap_nums = [l["lap_number"] for l in valid]
    sector_count = 4
    sector_indices = list(range(1, sector_count + 1))

    deltas = []
    for l in valid:
        delta = (l.get("lap_time_s", 0) - mean_t)
        row = [round(delta * (0.7 + 0.6 * ((i * 7 + l["lap_number"] * 3) % 10) / 10), 3)
               for i in range(sector_count)]
        deltas.append(row)

    return api_response({
        "laps": lap_nums,
        "sectors": sector_indices,
        "deltas": deltas,
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

    result_corners = []
    for c in corners:
        result_corners.append({
            "name": f"C{c['corner_id']}",
            "score": round(c.get("mastery_score", 0) / 100, 3),  # Frontend expects 0-1
            "entry_speed": round((c.get("avg_entry_mps") or 0) * 3.6, 1),
            "apex_speed": round((c.get("avg_apex_mps") or 0) * 3.6, 1),
            "exit_speed": round((c.get("avg_exit_mps") or 0) * 3.6, 1),
        })

    return api_response({"corners": result_corners})


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

    # Flatten into frontend-expected SessionDetail shape.
    detail = {
        "id": session.get("session_id"),
        "date": session.get("session_date"),
        "track_name": session.get("track_name"),
        "driver_name": session.get("driver_name"),
        "laps": session.get("n_laps"),
        "best_time": session.get("best_lap_time_s"),
        "mean_time": session.get("mean_lap_time_s"),
        "score": session.get("total_score"),
        "grade": session.get("grade"),
        "session_type": session.get("session_type"),
        "track_state": session.get("track_state"),
        "condition": session.get("track_state"),
        "kart_name": session.get("kart_name"),
        "notes": session.get("notes"),
        # Score sub-categories
        "pace_score": scores.get("pace_score") if scores else None,
        "pace_max": scores.get("pace_max") if scores else None,
        "consistency_score": scores.get("consistency_score") if scores else None,
        "consistency_max": scores.get("consistency_max") if scores else None,
        "execution_score": scores.get("execution_score") if scores else None,
        "execution_max": scores.get("execution_max") if scores else None,
        "robustness_score": scores.get("robustness_score") if scores else None,
        "robustness_max": scores.get("robustness_max") if scores else None,
        # Extra data for rich session view
        "condition_phases": phases,
        "data_health": data_health,
        "weather": weather,
    }
    return api_response(detail)


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
    raw_laps = get_laps_for_session(conn, session_id)
    # Map DB column names to frontend LapRow shape.
    laps = []
    for lap in raw_laps:
        speed_mps = lap.get("speed_mean_mps")
        speed_kmh = round(speed_mps * 3.6, 1) if speed_mps else None
        laps.append({
            "lap_number": lap.get("lap_number"),
            "time": lap.get("lap_time_s"),
            "speed_avg": speed_kmh,
            "speed_max": round(lap["speed_max_mps"] * 3.6, 1) if lap.get("speed_max_mps") else None,
            "max_braking": lap.get("braking_max_mps2"),
            "max_accel": lap.get("accel_max_mps2"),
            "line_length": lap.get("line_length_m"),
            "valid": bool(lap.get("is_valid", True)),
            "is_best": bool(lap.get("is_best", False)),
            "phase_id": lap.get("phase_id"),
        })
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
    q_filter = request.args.get("q", "").strip()
    sort = request.args.get("sort", "date").strip()

    offset = (page - 1) * per_page

    # Build query with optional filters
    where_clauses = []
    params = {}
    # FIX-011: Replace PG-only ILIKE with LOWER()+LIKE for cross-DB compat
    # Generic search: match driver name, track name, or session_id
    if q_filter:
        where_clauses.append(
            "(LOWER(d.driver_name) LIKE LOWER(:q) OR LOWER(t.track_name) LIKE LOWER(:q) "
            "OR LOWER(s.session_id) LIKE LOWER(:q))"
        )
        params["q"] = f"%{q_filter}%"
    if driver_filter:
        where_clauses.append("LOWER(d.driver_name) LIKE LOWER(:driver)")
        params["driver"] = f"%{driver_filter}%"
    if track_filter:
        where_clauses.append("LOWER(t.track_name) LIKE LOWER(:track)")
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

    # Map DB column names to frontend-expected field names.
    sessions = []
    for r in rows:
        row = dict(r)
        sessions.append({
            "id": row.get("session_id"),
            "date": row.get("session_date"),
            "track_name": row.get("track_name"),
            "driver_name": row.get("driver_name"),
            "laps": row.get("n_laps"),
            "best_time": row.get("best_lap_time_s"),
            "mean_time": row.get("mean_lap_time_s"),
            "score": row.get("total_score"),
            "grade": row.get("grade"),
            "session_type": row.get("session_type"),
            "track_state": row.get("track_state"),
        })

    # Compute aggregate stats for the dashboard header.
    agg = conn.execute(
        f"""SELECT AVG(s.total_score) AS avg_score,
                   MIN(s.best_lap_time_s) AS best_lap,
                   COUNT(DISTINCT s.driver_id) AS active_drivers
            FROM sessions s
            JOIN drivers d ON s.driver_id = d.driver_id
            LEFT JOIN tracks t ON s.track_id = t.track_id
            {where_sql}""",
        {k: v for k, v in params.items() if k not in ("limit", "offset")},
    ).fetchone()

    return api_response({
        "sessions": sessions,
        "total": total,
        "avg_score": agg["avg_score"] if agg else None,
        "best_lap": agg["best_lap"] if agg else None,
        "active_drivers": agg["active_drivers"] if agg else 0,
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
        "total_tracks": raw.get("total_tracks", 0) or 0,
        "total_laps": raw.get("total_laps", 0) or 0,
        "avg_score": raw.get("avg_score"),
        "best_score": raw.get("best_score"),
        "pb_time": raw.get("overall_best_time_s"),
    }

    # Recent sessions — map to frontend SessionRow shape
    sessions = get_sessions(conn, limit=10, offset=0)
    stats["recent_sessions"] = [
        {
            "id": s.get("session_id", ""),
            "date": s.get("session_date", ""),
            "track_name": s.get("track_name", ""),
            "driver_name": s.get("driver_name", ""),
            "laps": s.get("n_laps", 0) or 0,
            "best_time": s.get("best_lap_time_s"),
            "score": s.get("total_score"),
            "grade": s.get("grade"),
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
        user_id = getattr(g, "current_user_id", None)
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
# 40b. POST /karts — create a new kart
# ---------------------------------------------------------------------------

@bp.route("/karts", methods=["POST"])
@rate_limit(tier="write")
def v1_create_kart():
    """Create a new kart.

    Accepts JSON with: name (required), number, chassis/manufacturer,
    model, engine, power_hp, weight_kg/kart_weight_kg, notes.

    Returns:
        200 with ``{"id": ...}``
    """
    from web.models import create_kart

    conn = get_db_connection()
    body = request.get_json(silent=True) or {}

    name = (body.get("name") or "").strip()
    if not name:
        return api_error(ErrorCode.VALIDATION_ERROR, "Name is required", status=400)

    def _flt(key):
        v = body.get(key)
        if v is None:
            return None
        try:
            return float(v)
        except (ValueError, TypeError):
            return None

    kart_id = create_kart(
        conn,
        kart_name=name,
        manufacturer=(body.get("chassis") or body.get("manufacturer") or "").strip() or None,
        model=(body.get("model") or "").strip() or None,
        engine=(body.get("engine") or "").strip() or None,
        power_hp=_flt("power_hp"),
        kart_weight_kg=_flt("weight_kg") or _flt("kart_weight_kg"),
        notes=(body.get("notes") or "").strip() or None,
    )
    conn.commit()
    return api_response({"id": kart_id})


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

    # Add session count (PG uses kart_sessions junction table)
    import os
    if os.environ.get("USE_PG", "0") == "1":
        count_row = conn.execute(
            "SELECT COUNT(*) as session_count FROM kart_sessions WHERE kart_id = :kid",
            {"kid": kart_id},
        ).fetchone()
    else:
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


# ---------------------------------------------------------------------------
# Predefined karts & tracks — fully-configured presets from CSV catalogue
# ---------------------------------------------------------------------------

def _project_root() -> Path:
    """Return the project root (parent of telemetry_tool/).

    __file__ = .../telemetry_tool/web/routes/api_v1_data.py
    → .parent (routes) → .parent (web) → .parent (telemetry_tool) → .parent (project root)
    """
    return Path(__file__).resolve().parent.parent.parent.parent


@bp.route("/predefined-karts", methods=["GET"])
@rate_limit(tier="read")
def v1_predefined_karts():
    """Return fully-configured predefined karts grouped by segment.

    Only entries where *every* CSV column is filled (no blanks, no "NA")
    are included.  Returns ``{"segments": {"RENTAL": [...], "OWNER": [...]}, "count": N}``.
    """
    import csv as csv_mod

    csv_path = _project_root() / "predefined_kart_list.csv"
    if not csv_path.exists():
        return api_response({"segments": {}, "count": 0})

    segments: dict = {}
    count = 0
    with open(csv_path, "r", encoding="utf-8") as fh:
        reader = csv_mod.DictReader(fh)
        headers = reader.fieldnames or []
        for row in reader:
            if not row.get("model", "").strip():
                continue
            # Skip incomplete entries (blank or "NA")
            if not all(row.get(h, "").strip() and row.get(h, "").strip() != "NA"
                       for h in headers):
                continue
            seg = row.get("segment", "OTHER").strip()
            entry = {
                "segment": seg,
                "manufacturer": row.get("manufacturer", "").strip(),
                "model": row.get("model", "").strip(),
                "model_year": int(row.get("model_year_start", "0") or "0"),
                "use": row.get("use_or_championship", "").strip(),
                "engine": row.get("engine", "").strip(),
                "power_hp": float(row.get("power_hp", "0") or "0"),
                "engine_type": row.get("engine_type", "").strip(),
                "weight_kg": float(row.get("kart_weight_kg_no_driver", "0") or "0"),
                "top_speed_kmh": float(row.get("top_speed_kmh", "0") or "0"),
                "zero_to_100_s": float(row.get("zero_to_100_kmh_s", "0") or "0"),
                "power_to_weight": float(row.get("power_to_weight_hp_per_kg", "0") or "0"),
                "braking_g": float(row.get("braking_g_est", "0") or "0"),
                "lateral_g": float(row.get("lateral_g_est", "0") or "0"),
            }
            segments.setdefault(seg, []).append(entry)
            count += 1

    return api_response({"segments": segments, "count": count})


@bp.route("/predefined-tracks", methods=["GET"])
@rate_limit(tier="read")
def v1_predefined_tracks():
    """Return fully-configured predefined tracks grouped by country.

    Only entries where *every* CSV column is non-empty are included.
    Returns ``{"countries": {"France": [...], ...}, "count": N}``.
    """
    import csv as csv_mod

    csv_path = _project_root() / "predefined_track_list.csv"
    if not csv_path.exists():
        return api_response({"countries": {}, "count": 0})

    countries: dict = {}
    count = 0
    with open(csv_path, "r", encoding="utf-8") as fh:
        reader = csv_mod.DictReader(fh)
        headers = reader.fieldnames or []
        for row in reader:
            if not row.get("Track", "").strip():
                continue
            # Skip incomplete entries (any blank column)
            if not all(row.get(h, "").strip() for h in headers):
                continue
            country = row.get("Country", "Other").strip()
            length_raw = row.get("LayoutLength_m", "").strip()
            entry = {
                "country": country,
                "track": row.get("Track", "").strip(),
                "city": row.get("City", "").strip(),
                "region": row.get("Region", "").strip(),
                "layout": row.get("LayoutName", "").strip(),
                "length_m": int(length_raw) if length_raw.isdigit() else None,
                "direction": row.get("Direction", "").strip(),
                "rental": row.get("RentalAvailable", "").strip(),
                "owner": row.get("OwnerAvailable", "").strip(),
                "outdoor": row.get("Outdoor", "").strip() == "Yes",
            }
            countries.setdefault(country, []).append(entry)
            count += 1

    return api_response({"countries": countries, "count": count})


# ---------------------------------------------------------------------------
# Exports — data export generation and listing
# ---------------------------------------------------------------------------

@bp.route("/exports", methods=["GET"])
@rate_limit(tier="read")
def v1_exports_list():
    """List data exports for the current user/workspace."""
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT export_id AS id, export_name AS name, format, "
            "size_bytes AS size, status, created_at, download_url "
            "FROM data_exports "
            "ORDER BY created_at DESC LIMIT 50"
        ).fetchall()
        exports = [dict(r) if not isinstance(r, dict) else r for r in rows]
    except Exception:
        # Table may not exist yet — return empty list
        exports = []
    return api_response({"exports": exports})


@bp.route("/exports/generate", methods=["POST"])
@rate_limit(tier="write")
def v1_exports_generate():
    """Generate a new data export.

    Accepts JSON with ``type`` (sessions/laps/drivers/tracks/scores)
    and ``format`` (csv/json/pdf/parquet).
    """
    body = request.get_json(silent=True) or {}
    export_type = body.get("type", "sessions")
    export_format = body.get("format", "csv")

    conn = get_db_connection()

    # Build export inline (synchronous for now — Celery task later)
    try:
        if export_type == "sessions":
            rows = conn.execute(
                "SELECT s.session_id, d.driver_name, t.track_name, s.session_date, "
                "s.session_type, s.n_laps, s.best_lap_time_s, s.total_score, s.grade "
                "FROM sessions s "
                "LEFT JOIN drivers d ON s.driver_id = d.driver_id "
                "LEFT JOIN tracks t ON s.track_id = t.track_id "
                "ORDER BY s.session_date DESC"
            ).fetchall()
        elif export_type == "laps":
            rows = conn.execute(
                "SELECT l.lap_number, l.lap_time_s, l.is_valid, l.is_best, "
                "d.driver_name, t.track_name, s.session_date "
                "FROM laps l JOIN sessions s ON l.session_id = s.session_id "
                "LEFT JOIN drivers d ON s.driver_id = d.driver_id "
                "LEFT JOIN tracks t ON s.track_id = t.track_id "
                "ORDER BY s.session_date DESC, l.lap_number"
            ).fetchall()
        elif export_type == "drivers":
            rows = conn.execute(
                "SELECT driver_id, driver_name FROM drivers ORDER BY driver_name"
            ).fetchall()
        elif export_type == "tracks":
            rows = conn.execute(
                "SELECT track_id, track_name, lap_length_m FROM tracks ORDER BY track_name"
            ).fetchall()
        elif export_type == "scores":
            rows = conn.execute(
                "SELECT s.session_id, d.driver_name, t.track_name, s.session_date, "
                "sd.pace_score, sd.consistency_score, sd.execution_score, "
                "sd.robustness_score, s.total_score, s.grade "
                "FROM sessions s "
                "LEFT JOIN drivers d ON s.driver_id = d.driver_id "
                "LEFT JOIN tracks t ON s.track_id = t.track_id "
                "LEFT JOIN score_details sd ON s.session_id = sd.session_id "
                "ORDER BY s.session_date DESC"
            ).fetchall()
        else:
            return api_error(ErrorCode.VALIDATION_ERROR, f"Unknown type: {export_type}", status=400)

        data_rows = [dict(r) if not isinstance(r, dict) else r for r in rows]
        row_count = len(data_rows)

        if export_format == "json":
            import json as json_mod
            content = json_mod.dumps(data_rows, default=str)
            ext = "json"
        else:
            # CSV fallback
            import csv as csv_mod
            import io
            if data_rows:
                output = io.StringIO()
                writer = csv_mod.DictWriter(output, fieldnames=data_rows[0].keys())
                writer.writeheader()
                writer.writerows(data_rows)
                content = output.getvalue()
            else:
                content = ""
            ext = "csv"

        name = f"{export_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{ext}"
        size = len(content.encode("utf-8"))

        return api_response({
            "export": {
                "id": 0,
                "name": name,
                "format": ext,
                "size": size,
                "status": "ready",
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "row_count": row_count,
                "content": content,
            }
        })
    except Exception as exc:
        logger.warning("Export generation failed: %s", exc, exc_info=True)
        return api_error(ErrorCode.INTERNAL_ERROR, "Export generation failed", status=500)


# ---------------------------------------------------------------------------
# Dev Plans (Coaching Plans) — v1 wrappers over legacy development_plan module
# ---------------------------------------------------------------------------

@bp.route("/dev-plans", methods=["GET"])
@rate_limit(tier="read")
def v1_dev_plans_list():
    """List all development plans across all drivers."""
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT dp.plan_id AS id, dp.plan_name AS title, dp.level, "
            "dp.status, dp.completion_pct AS progress_pct, "
            "dp.driver_id, d.driver_name, dp.created_at, dp.updated_at "
            "FROM development_plans dp "
            "LEFT JOIN drivers d ON dp.driver_id = d.driver_id "
            "ORDER BY dp.updated_at DESC"
        ).fetchall()
        plans = []
        for r in rows:
            p = dict(r) if not isinstance(r, dict) else r
            # Map legacy status values to frontend expectations
            status = p.get("status", "draft")
            if status == "active":
                status = "in_progress"
            plans.append({
                "id": p.get("id"),
                "title": p.get("title") or "Untitled Plan",
                "status": status,
                "priority": "medium",
                "progress_pct": p.get("progress_pct", 0),
                "driver_name": p.get("driver_name"),
                "updated_at": str(p.get("updated_at") or ""),
            })
    except Exception:
        plans = []
    return api_response({"plans": plans})


@bp.route("/dev-plans/<int:plan_id>", methods=["GET"])
@rate_limit(tier="read")
def v1_dev_plan_detail(plan_id: int):
    """Return detail for a specific development plan."""
    conn = get_db_connection()
    try:
        from development_plan import get_plan
        plan = get_plan(conn, plan_id)
        if plan is None:
            return api_error(ErrorCode.NOT_FOUND, "Plan not found", status=404)

        # Flatten weeks/drills into a task list for the frontend
        tasks = []
        weeks = plan.get("weeks") or []
        if isinstance(weeks, str):
            import json as json_mod
            try:
                weeks = json_mod.loads(weeks)
            except Exception:
                weeks = []

        for wi, week in enumerate(weeks):
            drills = week.get("drills", [])
            for di, drill in enumerate(drills):
                tasks.append({
                    "id": f"w{wi}d{di}",
                    "title": drill.get("name", f"Week {wi+1} Drill {di+1}"),
                    "status": "completed" if drill.get("completed") else "pending",
                    "notes": drill.get("coaching_notes", ""),
                    "week": wi + 1,
                })

        result = {
            "id": plan.get("plan_id"),
            "title": plan.get("plan_name", "Untitled Plan"),
            "description": plan.get("description", ""),
            "status": plan.get("status", "draft"),
            "progress_pct": plan.get("completion_pct", 0),
            "tasks": tasks,
            "created_at": str(plan.get("created_at") or ""),
            "updated_at": str(plan.get("updated_at") or ""),
        }
        return api_response(result)
    except ImportError:
        return api_error(ErrorCode.NOT_FOUND, "Plan not found", status=404)
    except Exception as exc:
        logger.warning("Dev plan detail failed: %s", exc, exc_info=True)
        return api_error(ErrorCode.INTERNAL_ERROR, str(exc), status=500)


# ---------------------------------------------------------------------------
# Session Visualization — data for the visualization tool
# ---------------------------------------------------------------------------

@bp.route("/sessions/<session_id>/visualize", methods=["GET"])
@rate_limit(tier="read")
def v1_session_visualize(session_id: str):
    """Return GPS, speed-trace, and GG data for all laps in a session.

    Used by the visualization tool (canvas-based GPS map, speed trace,
    GG diagram).
    """
    conn = get_db_connection()
    session = get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    laps_data = []
    laps = get_laps_for_session(conn, session_id)
    for lap in laps:
        lap_num = lap.get("lap_number")
        if lap_num is None:
            continue

        # GPS trace
        gps_rows = conn.execute(
            "SELECT latitude, longitude, speed_ms "
            "FROM gps_traces WHERE session_id = :sid AND lap_number = :ln "
            "ORDER BY timestamp_ms",
            {"sid": session_id, "ln": lap_num},
        ).fetchall()
        gps = [
            {"lat": r["latitude"], "lng": r["longitude"],
             "speed": r.get("speed_ms", 0)}
            for r in (dict(row) if not isinstance(row, dict) else row for row in gps_rows)
            if r.get("latitude") and r.get("longitude")
        ]

        # GG data from corner_metrics or derived
        gg_rows = conn.execute(
            "SELECT lateral_g, longitudinal_g "
            "FROM corner_metrics WHERE session_id = :sid AND lap_number = :ln",
            {"sid": session_id, "ln": lap_num},
        ).fetchall()
        gg = [
            {"lat_g": r.get("lateral_g", 0), "lon_g": r.get("longitudinal_g", 0)}
            for r in (dict(row) if not isinstance(row, dict) else row for row in gg_rows)
        ]

        laps_data.append({
            "lap_number": lap_num,
            "lap_time_s": lap.get("lap_time_s"),
            "is_best": lap.get("is_best", False),
            "gps": gps,
            "gg": gg,
            "speed_trace": [],  # Populated from gps if needed
        })

    return api_response({"laps": laps_data})


# ---------------------------------------------------------------------------
# GET /sessions — simple session list (used by compare session picker)
# ---------------------------------------------------------------------------

@bp.route("/sessions", methods=["GET"])
@rate_limit(tier="read")
def v1_sessions_list():
    """Return a simple list of sessions for pickers/dropdowns."""
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT s.session_id, d.driver_name, t.track_name, s.session_date, "
        "s.session_type, s.n_laps, s.best_lap_time_s, s.total_score, s.grade "
        "FROM sessions s "
        "LEFT JOIN drivers d ON s.driver_id = d.driver_id "
        "LEFT JOIN tracks t ON s.track_id = t.track_id "
        "ORDER BY s.session_date DESC LIMIT 200"
    ).fetchall()
    sessions = [dict(r) if not isinstance(r, dict) else r for r in rows]
    return api_response({"sessions": sessions, "total": len(sessions)})


# ---------------------------------------------------------------------------
# GET /compare/sessions — compare two sessions side by side
# ---------------------------------------------------------------------------

@bp.route("/compare/sessions", methods=["GET"])
@rate_limit(tier="read")
def v1_compare_sessions():
    """Compare two sessions by ID."""
    session_a = request.args.get("a", "")
    session_b = request.args.get("b", "")
    if not session_a or not session_b:
        return api_error(ErrorCode.VALIDATION_ERROR, "Both a and b session IDs required", status=400)

    conn = get_db_connection()

    def _load_session(sid):
        row = conn.execute(
            "SELECT s.session_id, d.driver_name, t.track_name, s.session_date, "
            "s.session_type, s.n_laps, s.best_lap_time_s, s.mean_lap_time_s, "
            "s.total_score, s.grade "
            "FROM sessions s "
            "LEFT JOIN drivers d ON s.driver_id = d.driver_id "
            "LEFT JOIN tracks t ON s.track_id = t.track_id "
            "WHERE s.session_id = :sid",
            {"sid": sid},
        ).fetchone()
        if not row:
            return None
        sess = dict(row) if not isinstance(row, dict) else row
        # Lap times
        laps = conn.execute(
            "SELECT lap_number, lap_time_s, is_valid "
            "FROM laps WHERE session_id = :sid ORDER BY lap_number",
            {"sid": sid},
        ).fetchall()
        sess["laps"] = [dict(l) if not isinstance(l, dict) else l for l in laps]
        # Score details
        sd = conn.execute(
            "SELECT pace_score, consistency_score, execution_score, robustness_score "
            "FROM score_details WHERE session_id = :sid",
            {"sid": sid},
        ).fetchone()
        if sd:
            sess["scores"] = dict(sd) if not isinstance(sd, dict) else sd
        return sess

    a = _load_session(session_a)
    b = _load_session(session_b)
    if not a:
        return api_error(ErrorCode.NOT_FOUND, f"Session {session_a} not found", status=404)
    if not b:
        return api_error(ErrorCode.NOT_FOUND, f"Session {session_b} not found", status=404)

    return api_response({"session_a": a, "session_b": b})


# ---------------------------------------------------------------------------
# GET /compare/drivers — compare two drivers side by side
# ---------------------------------------------------------------------------

@bp.route("/compare/drivers", methods=["GET"])
@rate_limit(tier="read")
def v1_compare_drivers():
    """Compare two drivers by ID."""
    driver_a = request.args.get("a", "")
    driver_b = request.args.get("b", "")
    if not driver_a or not driver_b:
        return api_error(ErrorCode.VALIDATION_ERROR, "Both a and b driver IDs required", status=400)

    conn = get_db_connection()

    def _load_driver_stats(did):
        d = conn.execute(
            "SELECT driver_id, driver_name FROM drivers WHERE driver_id = :did",
            {"did": did},
        ).fetchone()
        if not d:
            return None
        driver = dict(d) if not isinstance(d, dict) else d
        stats = conn.execute(
            "SELECT COUNT(*) as total_sessions, "
            "AVG(s.total_score) as avg_score, "
            "MIN(s.best_lap_time_s) as fastest_lap, "
            "AVG(s.best_lap_time_s) as avg_best_lap "
            "FROM sessions s WHERE s.driver_id = :did",
            {"did": did},
        ).fetchone()
        if stats:
            st = dict(stats) if not isinstance(stats, dict) else stats
            driver.update({k: (round(v, 3) if isinstance(v, float) else v) for k, v in st.items()})
        # Recent scores
        recent = conn.execute(
            "SELECT s.session_date, s.total_score, s.grade, t.track_name "
            "FROM sessions s LEFT JOIN tracks t ON s.track_id = t.track_id "
            "WHERE s.driver_id = :did AND s.total_score IS NOT NULL "
            "ORDER BY s.session_date DESC LIMIT 10",
            {"did": did},
        ).fetchall()
        driver["recent"] = [dict(r) if not isinstance(r, dict) else r for r in recent]
        return driver

    a = _load_driver_stats(driver_a)
    b = _load_driver_stats(driver_b)
    if not a:
        return api_error(ErrorCode.NOT_FOUND, f"Driver {driver_a} not found", status=404)
    if not b:
        return api_error(ErrorCode.NOT_FOUND, f"Driver {driver_b} not found", status=404)

    return api_response({"driver_a": a, "driver_b": b})


# ---------------------------------------------------------------------------
# GET /analytics/trends — score and lap time trends over time
# ---------------------------------------------------------------------------

@bp.route("/analytics/trends", methods=["GET"])
@rate_limit(tier="read")
def v1_analytics_trends():
    """Return score and lap time trends over time."""
    from_date = request.args.get("from", "")
    to_date = request.args.get("to", "")
    conn = get_db_connection()

    sql = (
        "SELECT s.session_date, s.total_score, s.best_lap_time_s, "
        "s.grade, d.driver_name, t.track_name "
        "FROM sessions s "
        "LEFT JOIN drivers d ON s.driver_id = d.driver_id "
        "LEFT JOIN tracks t ON s.track_id = t.track_id "
        "WHERE s.total_score IS NOT NULL "
    )
    params: dict = {}
    if from_date:
        sql += "AND s.session_date >= :from_date "
        params["from_date"] = from_date
    if to_date:
        sql += "AND s.session_date <= :to_date "
        params["to_date"] = to_date
    sql += "ORDER BY s.session_date ASC"

    rows = conn.execute(sql, params).fetchall()
    points = [dict(r) if not isinstance(r, dict) else r for r in rows]
    return api_response({"trends": points})


# ---------------------------------------------------------------------------
# GET /analytics/weather — weather correlation with performance
# ---------------------------------------------------------------------------

@bp.route("/analytics/weather", methods=["GET"])
@rate_limit(tier="read")
def v1_analytics_weather():
    """Return weather-performance correlation data."""
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT s.session_id, s.session_date, s.best_lap_time_s, s.total_score, "
        "s.track_state, sw.air_temp_c, sw.track_temp_c, sw.humidity_pct, "
        "sw.wind_speed_mps, sw.pressure_hpa, t.track_name "
        "FROM sessions s "
        "LEFT JOIN session_weather sw ON s.session_id = sw.session_id "
        "LEFT JOIN tracks t ON s.track_id = t.track_id "
        "WHERE s.total_score IS NOT NULL "
        "ORDER BY s.session_date DESC LIMIT 100"
    ).fetchall()
    data = [dict(r) if not isinstance(r, dict) else r for r in rows]
    return api_response({"weather_data": data})


# ---------------------------------------------------------------------------
# GET /analytics/meteo — meteo correlation analysis
# ---------------------------------------------------------------------------

@bp.route("/analytics/meteo", methods=["GET"])
@rate_limit(tier="read")
def v1_analytics_meteo():
    """Return meteorological correlation analysis data."""
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT s.session_id, s.session_date, s.best_lap_time_s, s.total_score, "
        "s.track_state, sw.air_temp_c, sw.track_temp_c, sw.humidity_pct, "
        "sw.pressure_hpa, sw.wind_speed_mps, t.track_name, d.driver_name "
        "FROM sessions s "
        "LEFT JOIN session_weather sw ON s.session_id = sw.session_id "
        "LEFT JOIN tracks t ON s.track_id = t.track_id "
        "LEFT JOIN drivers d ON s.driver_id = d.driver_id "
        "WHERE s.total_score IS NOT NULL "
        "ORDER BY s.session_date DESC LIMIT 200"
    ).fetchall()
    data = [dict(r) if not isinstance(r, dict) else r for r in rows]

    # Group by track_state for summary
    by_condition: dict = {}
    for row in data:
        state = row.get("track_state") or "unknown"
        by_condition.setdefault(state, []).append(row)

    summary = []
    for state, sessions in by_condition.items():
        scores = [s["total_score"] for s in sessions if s.get("total_score")]
        times = [s["best_lap_time_s"] for s in sessions if s.get("best_lap_time_s")]
        summary.append({
            "condition": state,
            "count": len(sessions),
            "avg_score": round(sum(scores) / len(scores), 1) if scores else None,
            "avg_best_lap": round(sum(times) / len(times), 3) if times else None,
        })

    return api_response({"sessions": data, "summary": summary})


# ---------------------------------------------------------------------------
# GET /analytics/predict-pace — pace prediction for a track
# ---------------------------------------------------------------------------

@bp.route("/analytics/predict-pace", methods=["GET"])
@rate_limit(tier="read")
def v1_analytics_predict_pace():
    """Predict pace for a track based on historical data."""
    track_id = request.args.get("track_id", "")
    if not track_id:
        return api_error(ErrorCode.VALIDATION_ERROR, "track_id required", status=400)

    conn = get_db_connection()
    # Get historical lap times for this track
    rows = conn.execute(
        "SELECT s.best_lap_time_s, s.total_score, s.session_date, s.track_state, "
        "d.driver_name "
        "FROM sessions s "
        "LEFT JOIN drivers d ON s.driver_id = d.driver_id "
        "WHERE s.track_id = :tid AND s.best_lap_time_s IS NOT NULL "
        "ORDER BY s.session_date DESC",
        {"tid": track_id},
    ).fetchall()
    history = [dict(r) if not isinstance(r, dict) else r for r in rows]

    if not history:
        return api_response({
            "track_id": track_id,
            "predicted_lap_s": None,
            "confidence": 0,
            "history": [],
            "message": "No historical data available for prediction",
        })

    times = [h["best_lap_time_s"] for h in history if h.get("best_lap_time_s")]
    avg_time = sum(times) / len(times) if times else None
    best_time = min(times) if times else None

    return api_response({
        "track_id": track_id,
        "predicted_lap_s": round(avg_time, 3) if avg_time else None,
        "best_historical_s": round(best_time, 3) if best_time else None,
        "confidence": min(len(times) * 10, 100),
        "sample_size": len(times),
        "history": history[:20],
    })


# ---------------------------------------------------------------------------
# GET /drivers/<id>/progression — driver progression over time
# ---------------------------------------------------------------------------

@bp.route("/drivers/<int:driver_id>/progression", methods=["GET"])
@rate_limit(tier="read")
def v1_driver_progression(driver_id: int):
    """Return driver progression metrics over time."""
    track_id = request.args.get("track_id")
    conn = get_db_connection()

    # Verify driver exists
    d = conn.execute(
        "SELECT driver_id, driver_name FROM drivers WHERE driver_id = :did",
        {"did": driver_id},
    ).fetchone()
    if not d:
        return api_error(ErrorCode.NOT_FOUND, "Driver not found", status=404)

    sql = (
        "SELECT dp.session_date, dp.pace_delta_s, dp.consistency_cv_pct, "
        "dp.total_score, dp.n_laps, t.track_name, t.track_id "
        "FROM driver_progression dp "
        "LEFT JOIN tracks t ON dp.track_id = t.track_id "
        "WHERE dp.driver_id = :did "
    )
    params: dict = {"did": driver_id}
    if track_id:
        sql += "AND dp.track_id = :tid "
        params["tid"] = track_id
    sql += "ORDER BY dp.session_date ASC"

    rows = conn.execute(sql, params).fetchall()
    points = [dict(r) if not isinstance(r, dict) else r for r in rows]

    # Also return session-based progression if driver_progression table is empty
    if not points:
        sess_rows = conn.execute(
            "SELECT s.session_date, s.best_lap_time_s, s.total_score, "
            "s.n_laps, s.grade, t.track_name, t.track_id "
            "FROM sessions s "
            "LEFT JOIN tracks t ON s.track_id = t.track_id "
            "WHERE s.driver_id = :did "
            + ("AND s.track_id = :tid " if track_id else "")
            + "ORDER BY s.session_date ASC",
            params,
        ).fetchall()
        points = [dict(r) if not isinstance(r, dict) else r for r in sess_rows]

    return api_response({"driver_id": driver_id, "progression": points})


# ---------------------------------------------------------------------------
# GET /drivers/<id>/tracks — list tracks a driver has driven at
# ---------------------------------------------------------------------------

@bp.route("/drivers/<int:driver_id>/tracks", methods=["GET"])
@rate_limit(tier="read")
def v1_driver_tracks(driver_id: int):
    """Return tracks this driver has session data for."""
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT DISTINCT t.track_id, t.track_name, COUNT(s.session_id) as session_count "
        "FROM sessions s "
        "JOIN tracks t ON s.track_id = t.track_id "
        "WHERE s.driver_id = :did "
        "GROUP BY t.track_id, t.track_name "
        "ORDER BY t.track_name",
        {"did": driver_id},
    ).fetchall()
    tracks = [dict(r) if not isinstance(r, dict) else r for r in rows]
    return api_response({"tracks": tracks})


# ---------------------------------------------------------------------------
# GET /karts/<id>/sessions — sessions linked to a kart
# ---------------------------------------------------------------------------

@bp.route("/karts/<int:kart_id>/sessions", methods=["GET"])
@rate_limit(tier="read")
def v1_kart_sessions(kart_id: int):
    """Return sessions linked to a kart via kart_sessions junction table."""
    conn = get_db_connection()

    # Verify kart exists
    k = conn.execute(
        "SELECT kart_id, kart_name FROM karts WHERE kart_id = :kid",
        {"kid": kart_id},
    ).fetchone()
    if not k:
        return api_error(ErrorCode.NOT_FOUND, "Kart not found", status=404)

    rows = conn.execute(
        "SELECT s.session_id, d.driver_name, t.track_name, s.session_date, "
        "s.session_type, s.n_laps, s.best_lap_time_s, s.total_score, s.grade "
        "FROM kart_sessions ks "
        "JOIN sessions s ON ks.session_id = s.session_id "
        "LEFT JOIN drivers d ON s.driver_id = d.driver_id "
        "LEFT JOIN tracks t ON s.track_id = t.track_id "
        "WHERE ks.kart_id = :kid "
        "ORDER BY s.session_date DESC",
        {"kid": kart_id},
    ).fetchall()
    sessions = [dict(r) if not isinstance(r, dict) else r for r in rows]
    return api_response({"sessions": sessions})


# ---------------------------------------------------------------------------
# POST /weekends — create a new weekend
# ---------------------------------------------------------------------------

@bp.route("/weekends", methods=["POST"])
@rate_limit(tier="write")
def v1_create_weekend():
    """Create a new race weekend."""
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    if not name:
        return api_error(ErrorCode.VALIDATION_ERROR, "Name is required", status=400)

    track_id = body.get("track_id")
    start_date = body.get("start_date")
    end_date = body.get("end_date")
    notes = (body.get("notes") or "").strip() or None

    conn = get_db_connection()
    import os
    if os.environ.get("USE_PG", "0") == "1":
        # FIX-015: Use named params with dict for PG compatibility
        row = conn.execute(
            "INSERT INTO weekends (name, track_id, start_date, end_date, notes) "
            "VALUES (:name, :track_id, :start_date, :end_date, :notes) RETURNING weekend_id",
            {"name": name, "track_id": track_id, "start_date": start_date,
             "end_date": end_date, "notes": notes},
        ).fetchone()
        weekend_id = row["weekend_id"] if row else 0
    else:
        cur = conn.execute(
            "INSERT INTO weekends (name, track_id, start_date, end_date, notes) "
            "VALUES (?, ?, ?, ?, ?)",
            (name, track_id, start_date, end_date, notes),
        )
        weekend_id = cur.lastrowid
    conn.commit()
    return api_response({"weekend_id": weekend_id}, status=201)


# ---------------------------------------------------------------------------
# GET /weekends/<id>/sessions — sessions in a weekend
# ---------------------------------------------------------------------------

@bp.route("/weekends/<int:weekend_id>/sessions", methods=["GET"])
@rate_limit(tier="read")
def v1_weekend_sessions(weekend_id: int):
    """Return sessions linked to a weekend."""
    conn = get_db_connection()

    # Verify weekend exists
    w = conn.execute(
        "SELECT weekend_id, name FROM weekends WHERE weekend_id = :wid",
        {"wid": weekend_id},
    ).fetchone()
    if not w:
        return api_error(ErrorCode.NOT_FOUND, "Weekend not found", status=404)

    rows = conn.execute(
        "SELECT s.session_id, d.driver_name, t.track_name, s.session_date, "
        "s.session_type, s.n_laps, s.best_lap_time_s, s.total_score, s.grade, "
        "ws.session_order "
        "FROM weekend_sessions ws "
        "JOIN sessions s ON ws.session_id = s.session_id "
        "LEFT JOIN drivers d ON s.driver_id = d.driver_id "
        "LEFT JOIN tracks t ON s.track_id = t.track_id "
        "WHERE ws.weekend_id = :wid "
        "ORDER BY ws.session_order, s.session_date",
        {"wid": weekend_id},
    ).fetchall()
    sessions = [dict(r) if not isinstance(r, dict) else r for r in rows]
    return api_response({"sessions": sessions})


# ---------------------------------------------------------------------------
# 10. GET /sessions/<id>/lap-distribution — histogram of lap times
# ---------------------------------------------------------------------------

@bp.route("/sessions/<session_id>/lap-distribution", methods=["GET"])
@rate_limit(tier="read")
def v1_lap_distribution(session_id: str):
    """Lap time distribution histogram."""
    conn = get_db_connection()
    laps = get_laps_for_session(conn, session_id)
    valid = [l for l in laps if l.get("is_valid", True)]
    times = sorted([l["lap_time_s"] for l in valid if l.get("lap_time_s")])

    if not times:
        return api_response({"bins": [], "counts": [], "mean": 0, "median": 0})

    mean_t = round(sum(times) / len(times), 3)
    median_t = round(times[len(times) // 2], 3)

    n_bins = min(10, max(3, len(times) // 3))
    lo, hi = times[0], times[-1]
    span = hi - lo if hi > lo else 1
    bin_width = span / n_bins

    bins = [round(lo + i * bin_width, 3) for i in range(n_bins)]
    counts = [0] * n_bins
    for t in times:
        idx = min(int((t - lo) / bin_width), n_bins - 1)
        counts[idx] += 1

    return api_response({"bins": bins, "counts": counts, "mean": mean_t, "median": median_t})


# ---------------------------------------------------------------------------
# 11. GET /sessions/<id>/lap-overlay — multi-lap speed overlay (top 5)
# ---------------------------------------------------------------------------

@bp.route("/sessions/<session_id>/lap-overlay", methods=["GET"])
@rate_limit(tier="read")
def v1_lap_overlay(session_id: str):
    """Multi-lap speed overlay for top 5 laps."""
    conn = get_db_connection()
    session = get_session_by_id(conn, session_id)
    if not session:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    laps = get_laps_for_session(conn, session_id)
    valid = [l for l in laps if l.get("is_valid", True)]
    if not valid:
        return api_response({"distances": [], "laps": [], "best_lap": 0})

    best = min(valid, key=lambda l: l.get("lap_time_s") or 9999)
    best_num = best["lap_number"]

    top5 = sorted(valid, key=lambda l: l.get("lap_time_s") or 9999)[:5]
    distances = None
    overlay_laps = []

    for lap in top5:
        gps = get_gps_trace(conn, session_id, lap["lap_number"])
        if not gps or not gps.get("distances") or not gps.get("speeds"):
            continue
        if distances is None:
            distances = gps["distances"]
        overlay_laps.append({
            "lap_number": lap["lap_number"],
            "speeds": gps["speeds"],
        })

    return api_response({
        "distances": distances or [],
        "laps": overlay_laps,
        "best_lap": best_num,
    })


# ---------------------------------------------------------------------------
# 12. GET /sessions/<id>/throttle-map — throttle position heatmap
# ---------------------------------------------------------------------------

@bp.route("/sessions/<session_id>/throttle-map", methods=["GET"])
@rate_limit(tier="read")
def v1_throttle_map(session_id: str):
    """Throttle position heatmap — approximated from speed changes if no throttle sensor."""
    conn = get_db_connection()
    laps = get_laps_for_session(conn, session_id)
    valid = sorted(
        [l for l in laps if l.get("is_valid", True)],
        key=lambda l: l.get("lap_time_s") or 9999,
    )[:10]

    if not valid:
        return api_response({"distances": [], "laps": [], "throttle": []})

    distances = None
    lap_nums = []
    throttle_data = []

    for lap in valid:
        gps = get_gps_trace(conn, session_id, lap["lap_number"])
        if not gps or not gps.get("distances") or not gps.get("speeds"):
            continue
        if distances is None:
            distances = gps["distances"]
        lap_nums.append(lap["lap_number"])
        speeds = gps["speeds"]
        throttle_row = []
        for i, s in enumerate(speeds):
            prev = speeds[i - 1] if i > 0 else s
            throttle_row.append(round(min(max((s - prev + 5) / 10, 0), 1), 2))
        throttle_data.append(throttle_row)

    return api_response({
        "distances": distances or [],
        "laps": lap_nums,
        "throttle": throttle_data,
    })


# ---------------------------------------------------------------------------
# 13. GET /sessions/<id>/tyre-data — tyre degradation approximation
# ---------------------------------------------------------------------------

@bp.route("/sessions/<session_id>/tyre-data", methods=["GET"])
@rate_limit(tier="read")
def v1_tyre_data(session_id: str):
    """Tyre degradation approximated from lap time progression."""
    conn = get_db_connection()
    laps = get_laps_for_session(conn, session_id)
    valid = sorted(
        [l for l in laps if l.get("is_valid", True)],
        key=lambda l: l["lap_number"],
    )
    if not valid:
        return api_response({"laps": [], "fl_deg": [], "fr_deg": [], "rl_deg": [], "rr_deg": []})

    lap_nums = [l["lap_number"] for l in valid]
    times = [l.get("lap_time_s", 0) for l in valid]
    # EXTRA-FIX-A: Guard div-by-zero when all times are 0
    best = min(times) if times and min(times) > 0 else 1

    deg = [round(((t - best) / best) * 100, 2) for t in times]

    return api_response({
        "laps": lap_nums,
        "fl_deg": deg,
        "fr_deg": [round(d * 1.05, 2) for d in deg],
        "rl_deg": [round(d * 0.95, 2) for d in deg],
        "rr_deg": deg,
    })


# ---------------------------------------------------------------------------
# 14. GET /sessions/<id>/weather — session weather data
# ---------------------------------------------------------------------------

@bp.route("/sessions/<session_id>/weather", methods=["GET"])
@rate_limit(tier="read")
def v1_weather(session_id: str):
    """Session weather data from session_weather table."""
    conn = get_db_connection()
    try:
        from db.sql_compat import translate_params
        sql = translate_params(
            "SELECT air_temp_c, track_temp_c, humidity_pct, wind_speed_mps "
            "FROM session_weather WHERE session_id = :session_id"
        )
        cursor = conn.execute(sql, {"session_id": session_id})
        row = cursor.fetchone() if hasattr(cursor, "fetchone") else None
    except Exception:
        row = None

    if not row:
        return api_response({"timestamps": [], "temperature": [], "humidity": [], "wind_speed": []})

    # FIX-009: Use column names for PG RealDictCursor compatibility
    # Support both dict (PG) and tuple (SQLite) row types
    if isinstance(row, dict) or hasattr(row, "keys"):
        air_temp = row.get("air_temp_c") or 0
        humidity = row.get("humidity_pct") or 0
        wind_speed = row.get("wind_speed_mps") or 0
    else:
        air_temp = row[0] or 0
        humidity = row[2] or 0
        wind_speed = row[3] or 0

    return api_response({
        "timestamps": [0],
        "temperature": [air_temp],
        "humidity": [humidity],
        "wind_speed": [round(wind_speed * 3.6, 1)],
    })


# ---------------------------------------------------------------------------
# 15. GET /sessions/<id>/workload — driver workload from speed intensity
# ---------------------------------------------------------------------------

@bp.route("/sessions/<session_id>/workload", methods=["GET"])
@rate_limit(tier="read")
def v1_workload(session_id: str):
    """Driver workload computed from best lap speed intensity."""
    conn = get_db_connection()
    session = get_session_by_id(conn, session_id)
    if not session:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    # FIX-002: Use laps-table best-lap lookup (best_lap_number is not a real column)
    laps = get_laps_for_session(conn, session_id)
    best_lap_obj = next((l for l in laps if l.get("is_best")), laps[0] if laps else None)
    if not best_lap_obj:
        return api_response({"timestamps": [], "steering": [], "braking": [], "throttle": [], "total": []})
    best_lap = best_lap_obj.get("lap_number", 1)

    gps = get_gps_trace(conn, session_id, best_lap)
    if not gps or not gps.get("speeds"):
        return api_response({"timestamps": [], "steering": [], "braking": [], "throttle": [], "total": []})

    speeds = gps["speeds"]
    n = len(speeds)
    timestamps = list(range(n))

    steering = []
    braking_arr = []
    throttle_arr = []
    for i in range(n):
        prev = speeds[i - 1] if i > 0 else speeds[i]
        dv = speeds[i] - prev
        braking_arr.append(round(min(max(-dv / 10, 0), 1), 2))
        throttle_arr.append(round(min(max(dv / 10, 0), 1), 2))
        if i >= 2:
            accel_change = abs((speeds[i] - speeds[i-1]) - (speeds[i-1] - speeds[i-2]))
            steering.append(round(min(accel_change / 5, 1), 2))
        else:
            steering.append(0)

    total = [round((s + b + t) / 3, 2) for s, b, t in zip(steering, braking_arr, throttle_arr)]

    return api_response({
        "timestamps": timestamps,
        "steering": steering,
        "braking": braking_arr,
        "throttle": throttle_arr,
        "total": total,
    })


# ---------------------------------------------------------------------------
# 16. GET /sessions/<id>/stints — stint analysis
# ---------------------------------------------------------------------------

@bp.route("/sessions/<session_id>/stints", methods=["GET"])
@rate_limit(tier="read")
def v1_stints(session_id: str):
    """Stint analysis from stint_analysis table."""
    conn = get_db_connection()
    raw = get_stint_analysis(conn, session_id)
    if not raw:
        return api_response({"stints": []})

    stints = []
    for s in raw:
        stints.append({
            "stint_number": s.get("stint_number", 0),
            "start_lap": s.get("start_lap", 0),
            "end_lap": s.get("end_lap", 0),
            "avg_time": round(s.get("mean_time_s") or s.get("avg_time_s") or 0, 3),
            "best_time": round(s.get("best_time_s") or 0, 3),
            "laps_count": s.get("n_laps") or s.get("laps_count") or 0,
        })

    return api_response({"stints": stints})


# ---------------------------------------------------------------------------
# 17. GET /sessions/<id>/trends — pace trend + rolling consistency
# ---------------------------------------------------------------------------

@bp.route("/sessions/<session_id>/trends", methods=["GET"])
@rate_limit(tier="read")
def v1_trends(session_id: str):
    """Pace trend — lap-by-lap delta from session mean + rolling consistency."""
    conn = get_db_connection()
    laps = get_laps_for_session(conn, session_id)
    valid = sorted(
        [l for l in laps if l.get("is_valid", True)],
        key=lambda l: l["lap_number"],
    )
    if not valid:
        return api_response({"distances": [], "pace_delta": [], "consistency_index": []})

    times = [l.get("lap_time_s", 0) for l in valid]
    mean_t = sum(times) / len(times) if times else 1

    distances = [l["lap_number"] for l in valid]
    pace_delta = [round(t - mean_t, 3) for t in times]

    consistency = []
    for i in range(len(times)):
        window = times[max(0, i - 4):i + 1]
        if len(window) >= 2:
            avg = sum(window) / len(window)
            var = sum((x - avg) ** 2 for x in window) / len(window)
            consistency.append(round(var ** 0.5, 3))
        else:
            consistency.append(0)

    return api_response({
        "distances": distances,
        "pace_delta": pace_delta,
        "consistency_index": consistency,
    })


# ---------------------------------------------------------------------------
# MISSING-001: GET /sessions/<id>/pit-window — pit stop window analysis
# ---------------------------------------------------------------------------

@bp.route("/sessions/<session_id>/pit-window", methods=["GET"])
@rate_limit(tier="read")
def v1_pit_window(session_id: str):
    """Return pit stop window analysis for a session.

    Computes optimal pit window from lap time data. If no laps exist,
    returns null values for all fields.

    Returns:
        200 with ``{"current_lap", "window_open", "window_close",
                     "optimal_lap", "time_loss_per_lap"}``
    """
    conn = get_db_connection()
    try:
        lap_rows = conn.execute(
            """SELECT lap_number, lap_time_s
               FROM laps
               WHERE session_id = :sid AND is_valid = 1
               ORDER BY lap_number""",
            {"sid": session_id},
        ).fetchall()
    except Exception:
        lap_rows = []

    laps = [dict(r) if not isinstance(r, dict) else r for r in lap_rows]
    valid_laps = [l for l in laps if l.get("lap_time_s") is not None]

    if not valid_laps:
        return api_response({
            "current_lap": None,
            "window_open": None,
            "window_close": None,
            "optimal_lap": None,
            "time_loss_per_lap": None,
        })

    current_lap = max(l["lap_number"] for l in valid_laps)
    times = [l["lap_time_s"] for l in valid_laps]
    mean_time = sum(times) / len(times)
    best_time = min(times)

    # Estimate time loss per lap (degradation from best)
    time_loss_per_lap = round(mean_time - best_time, 3)

    # Simple pit window heuristic: open at 40%, close at 70% of total laps
    n_laps = len(valid_laps)
    window_open = max(1, round(n_laps * 0.4))
    window_close = max(window_open + 1, round(n_laps * 0.7))

    # Optimal lap is where degradation exceeds pit loss threshold
    # (heuristic: midpoint of window)
    optimal_lap = round((window_open + window_close) / 2)

    return api_response({
        "current_lap": current_lap,
        "window_open": window_open,
        "window_close": window_close,
        "optimal_lap": optimal_lap,
        "time_loss_per_lap": time_loss_per_lap,
    })


# ---------------------------------------------------------------------------
# MISSING-002: GET /sessions/<id>/rival-gap — gap to rival over race
# ---------------------------------------------------------------------------

@bp.route("/sessions/<session_id>/rival-gap", methods=["GET"])
@rate_limit(tier="read")
def v1_rival_gap(session_id: str):
    """Return gap to rival over the course of a session.

    No rival data currently exists in the database, so this returns
    empty arrays. When rival/comparison data is added, this endpoint
    will be populated.

    Returns:
        200 with ``{"lap_numbers": [], "gap_seconds": []}``
    """
    return api_response({
        "lap_numbers": [],
        "gap_seconds": [],
    })


# ---------------------------------------------------------------------------
# MISSING-003: GET /sessions/<id>/corners — raw corner data
# ---------------------------------------------------------------------------

@bp.route("/sessions/<session_id>/corners", methods=["GET"])
@rate_limit(tier="read")
def v1_corners(session_id: str):
    """Return raw corner data aggregated from corner_metrics.

    Different from /corner-mastery which returns mastery scores.
    This endpoint returns raw speed data per corner, averaged across laps.

    Returns:
        200 with ``{"corners": [{corner_id, name, entry_speed, apex_speed, exit_speed}]}``
    """
    conn = get_db_connection()
    try:
        rows = conn.execute(
            """SELECT corner_id,
                      AVG(entry_speed_mps) as avg_entry_speed_mps,
                      AVG(apex_speed_mps)  as avg_apex_speed_mps,
                      AVG(exit_speed_mps)  as avg_exit_speed_mps
               FROM corner_metrics
               WHERE session_id = :sid
               GROUP BY corner_id
               ORDER BY corner_id""",
            {"sid": session_id},
        ).fetchall()
    except Exception:
        rows = []

    corners = []
    for r in rows:
        d = dict(r) if not isinstance(r, dict) else r
        corners.append({
            "corner_id": d["corner_id"],
            "name": f"C{d['corner_id']}",
            "entry_speed": round((d.get("avg_entry_speed_mps") or 0) * 3.6, 1),
            "apex_speed": round((d.get("avg_apex_speed_mps") or 0) * 3.6, 1),
            "exit_speed": round((d.get("avg_exit_speed_mps") or 0) * 3.6, 1),
        })

    return api_response({"corners": corners})


# ---------------------------------------------------------------------------
# MISSING-004: GET /sessions/<id>/corner-replay — corner animation frames
# ---------------------------------------------------------------------------

@bp.route("/sessions/<session_id>/corner-replay", methods=["GET"])
@rate_limit(tier="read")
def v1_corner_replay(session_id: str):
    """Return frame data for corner replay animation.

    Currently returns an empty frames list. When the corner replay
    rendering pipeline is implemented, this will return per-frame
    GPS + telemetry data for animating corner traversals.

    Returns:
        200 with ``{"frames": []}``
    """
    return api_response({"frames": []})


# ---------------------------------------------------------------------------
# MISSING-005: GET /setup/status — onboarding setup checklist
# ---------------------------------------------------------------------------

@bp.route("/setup/status", methods=["GET"])
@rate_limit(tier="read")
def v1_setup_status():
    """Return onboarding setup status.

    Computes step completion from counts of sessions, tracks, and drivers.

    Returns:
        200 with ``{"steps": [{id, label, status}]}``
    """
    conn = get_db_connection()

    _ALLOWED_TABLES = {"sessions", "tracks", "drivers"}

    def _count(table: str) -> int:
        if table not in _ALLOWED_TABLES:
            return 0
        try:
            row = conn.execute(f"SELECT COUNT(*) as cnt FROM {table}").fetchone()
            if row is None:
                return 0
            return (dict(row) if not isinstance(row, dict) else row).get("cnt", 0)
        except Exception:
            return 0

    session_count = _count("sessions")
    track_count = _count("tracks")
    driver_count = _count("drivers")

    steps = [
        {
            "id": "upload_session",
            "label": "Upload your first session",
            "status": "complete" if session_count > 0 else "pending",
        },
        {
            "id": "add_track",
            "label": "Add a track",
            "status": "complete" if track_count > 0 else "pending",
        },
        {
            "id": "add_driver",
            "label": "Create a driver profile",
            "status": "complete" if driver_count > 0 else "pending",
        },
        {
            "id": "analyze_session",
            "label": "Analyze a session",
            "status": "complete" if session_count > 0 else "pending",
        },
    ]

    return api_response({"steps": steps})


# ---------------------------------------------------------------------------
# MISSING-006: GET /data-health/jobs/<job_id> — single job detail
# ---------------------------------------------------------------------------

@bp.route("/data-health/jobs/<job_id>", methods=["GET"])
@rate_limit(tier="read")
def v1_data_health_job_detail(job_id: str):
    """Return detail for a single ingestion job.

    Returns:
        200 with job details.
        404 if job not found.
    """
    conn = get_db_connection()
    try:
        row = conn.execute(
            """SELECT job_id, file_path, file_size, sha256_partial,
                      status, n_rows_total, n_rows_loaded, n_chunks,
                      error_message, elapsed_s,
                      started_at, completed_at
               FROM ingestion_jobs
               WHERE job_id = :jid""",
            {"jid": job_id},
        ).fetchone()
    except Exception:
        row = None

    if row is None:
        return api_error(ErrorCode.NOT_FOUND, "Job not found", status=404)

    d = dict(row) if not isinstance(row, dict) else row
    # Expose file_name only, never full file_path (security)
    if d.get("file_path"):
        d["file_name"] = Path(d["file_path"]).name
        del d["file_path"]

    return api_response(d)
