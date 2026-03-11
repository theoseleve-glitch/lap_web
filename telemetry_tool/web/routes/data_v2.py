"""
routes/data_v2.py
-----------------
Data-serving API endpoints for the Phase 1 re-port.

These endpoints read from the SQLite database and return data
the Next.js frontend needs to display session details, charts,
scores, and coaching information.

Endpoints:
    GET    /api/v1/dashboard/stats                  - Dashboard aggregate stats
    GET    /api/v1/sessions                        - List sessions
    GET    /api/v1/sessions/<id>                    - Session detail
    GET    /api/v1/sessions/<id>/laps               - Lap list
    GET    /api/v1/sessions/<id>/speed-trace        - Speed vs distance
    GET    /api/v1/sessions/<id>/gps-trace          - GPS coordinates
    GET    /api/v1/sessions/<id>/gg-data            - GG diagram data
    GET    /api/v1/sessions/<id>/scores             - Score breakdown
    GET    /api/v1/sessions/<id>/corners            - Corner coaching
    DELETE /api/v1/sessions/<id>                    - Delete session
    GET    /api/v1/compare/sessions?a=X&b=Y         - Session comparison
    GET    /api/v1/compare/drivers?a=X&b=Y          - Driver comparison
    GET    /api/v1/sessions/<id>/compare/sectors     - Sector/corner compare
    GET    /api/v1/sessions/<id>/report?format=html  - Report download
    GET    /api/v1/export/scores                    - Scoring history CSV export
    PATCH  /api/v1/sessions/<id>                    - Update session fields
    GET    /api/v1/sessions/<id>/grip-map           - Distance-binned grip map
    GET    /api/v1/sessions/<id>/friction-envelope   - Speed-binned friction envelope
"""
from __future__ import annotations

import csv
import io
import json
import logging
import math
from functools import wraps
from pathlib import Path
from typing import Any, Callable

from flask import Blueprint, Response, g, request, send_file

from web import models
from web.api_utils import ErrorCode, api_error, api_response
from web.db import get_db_connection
from web.middleware.audit import audit_log

logger = logging.getLogger(__name__)


def _safe_api(f: Callable) -> Callable:
    """Catch unhandled exceptions in API routes — log + return structured error."""
    @wraps(f)
    def wrapper(*args: Any, **kwargs: Any) -> tuple:
        try:
            return f(*args, **kwargs)
        except Exception:
            req_id = getattr(g, "request_id", "?")
            logger.exception(
                "Unhandled error in %s [%s %s] request_id=%s",
                f.__name__, request.method, request.path, req_id,
            )
            return api_error(ErrorCode.INTERNAL_ERROR,
                             "Internal server error", status=500)
    return wrapper

bp = Blueprint("data_v2", __name__, url_prefix="/api/v1")


# ── Blueprint-level rate limiting ─────────────────────────────────
# Apply rate limits to all data endpoints without decorating each one.
# GET → "read" tier (300/min), mutating methods → "write" tier (60/min).

@bp.before_request
def _apply_rate_limit() -> tuple | None:
    from web.rate_limit import rate_limit as _rl_decorator
    tier = "write" if request.method in ("DELETE", "PATCH", "POST", "PUT") else "read"
    # Build a no-op function, wrap it with the decorator, and call it.
    # If rate-limited, the wrapper returns a 429 response tuple.
    @_rl_decorator(tier=tier)
    def _check() -> None:
        return None
    result = _check()
    if result is not None:
        return result


# ── Helpers ───────────────────────────────────────────────────────


def _resolve_lap_number(conn: Any, session_id: str) -> int | None:
    """Determine the lap number to use when ?lap= is not provided.

    Strategy: find the first lap with is_best=True; otherwise fall back
    to the first lap in the list.
    """
    laps = models.get_laps_for_session(conn, session_id)
    if not laps:
        return None
    for lap in laps:
        if lap.get("is_best"):
            return lap["lap_number"]
    return laps[0]["lap_number"]


def _get_lap_param(conn: Any, session_id: str) -> int | None:
    """Read the ?lap= query parameter or fall back to best/first lap."""
    raw = request.args.get("lap")
    if raw is not None:
        try:
            return int(raw)
        except (ValueError, TypeError):
            return None
    return _resolve_lap_number(conn, session_id)


# ── Tables to clean on session delete ─────────────────────────────

_DELETE_RELATED_TABLES = [
    "gps_traces",
    "laps",
    "score_details",
    "condition_phases",
    "theoretical_data",
    "reference_lines",
    "session_sectors",
    "session_tags",
    "corner_metrics",
    "session_weather",
    "data_health",
    "driver_progression",
    "driving_style_features",
    "condition_markers",
    "vehicle_setups",
    "what_if_scenarios",
    "session_annotations",
    "stint_analysis",
]

_ALLOWED_DELETE_TABLES = frozenset(_DELETE_RELATED_TABLES)


# ══════════════════════════════════════════════════════════════════
# 0. GET /api/v1/dashboard/stats — Dashboard aggregate stats
# ══════════════════════════════════════════════════════════════════


@bp.route("/dashboard/stats", methods=["GET"])
@_safe_api
def dashboard_stats() -> tuple[dict, int]:
    """Return aggregate dashboard statistics.

    Returns total_sessions, total_drivers, total_tracks, total_laps,
    pb_time, avg_score, best_score, plus recent_scores, recent_times,
    and recent_sessions for sparkline and table display.
    """
    # Check cache first (keyed by workspace for multi-tenant)
    ws_id = getattr(g, "workspace_id", "default")
    cache_key = f"dashboard:stats:{ws_id}"
    try:
        from web.cache import api_cache
        cached = api_cache.get(cache_key)
        if cached is not None:
            return api_response(cached)
    except ImportError:
        pass

    conn = get_db_connection()
    stats = models.get_dashboard_stats(conn)

    # Fetch recent sessions for sparklines and table (last 20).
    recent = models.get_sessions(conn, limit=20, offset=0)

    recent_scores = [
        s["total_score"] for s in recent
        if s.get("total_score") is not None
    ]
    recent_times = [
        s["best_lap_time_s"] for s in recent
        if s.get("best_lap_time_s") is not None
    ]

    # Map to frontend-expected session shape.
    recent_sessions = [
        {
            "id": s.get("session_id"),
            "date": s.get("session_date"),
            "track_name": s.get("track_name", "Unknown"),
            "driver_name": s.get("driver_name", "Unknown"),
            "laps": s.get("n_laps", 0),
            "best_time": s.get("best_lap_time_s"),
            "score": s.get("total_score"),
            "grade": s.get("grade"),
            "session_type": s.get("session_type"),
            "track_state": s.get("track_state"),
        }
        for s in recent[:10]  # Table shows 10 most recent
    ]

    # Identify which session holds the personal best
    pb_session_id = None
    if stats.get("overall_best_time_s") is not None:
        for s in recent:
            if s.get("best_lap_time_s") == stats["overall_best_time_s"]:
                pb_session_id = s.get("session_id")
                break

    result = {
        "total_sessions": stats.get("total_sessions", 0),
        "total_drivers": stats.get("total_drivers", 0),
        "total_tracks": stats.get("total_tracks", 0),
        "total_laps": stats.get("total_laps", 0) or 0,
        "pb_time": stats.get("overall_best_time_s"),
        "pb_session_id": pb_session_id,
        "avg_score": stats.get("avg_score"),
        "best_score": stats.get("best_score"),
        "recent_scores": recent_scores,
        "recent_times": recent_times,
        "recent_sessions": recent_sessions,
    }

    # Cache for 60s, tagged by workspace for targeted invalidation
    try:
        from web.cache import api_cache
        api_cache.set(cache_key, result, ttl=60, tags=[f"ws:{ws_id}", "dashboard"])
    except ImportError:
        pass

    return api_response(result)


# ══════════════════════════════════════════════════════════════════
# 1. GET /api/v1/sessions — List sessions
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions", methods=["GET"])
@_safe_api
def list_sessions() -> tuple[dict, int]:
    """List sessions with pagination, filtering, and sorting.

    Query params:
        limit        (int, default 25)
        offset       (int, default 0)
        driver       (str) — exact driver name
        track        (str) — exact track name
        session_type (str) — practice/qualifying/race/test/endurance
        track_state  (str) — dry/wet/damp/mixed/greasy
        date_from    (str) — YYYY-MM-DD
        date_to      (str) — YYYY-MM-DD
        min_score    (float)
        max_score    (float)
        search       (str) — free-text search across driver, track, filename
        sort_by      (str) — column key
        sort_dir     (str) — asc or desc
    """
    try:
        limit = int(request.args.get("limit", 25))
    except (ValueError, TypeError):
        limit = 25
    try:
        offset = int(request.args.get("offset", 0))
    except (ValueError, TypeError):
        offset = 0

    # Clamp to reasonable bounds
    limit = max(1, min(limit, 100))
    offset = max(0, offset)

    # Build filters dict from query params
    filters = {}
    for key in ("driver", "track", "session_type", "track_state",
                "date_from", "date_to", "search"):
        val = request.args.get(key)
        if val:
            filters[key] = val
    for key in ("min_score", "max_score"):
        val = request.args.get(key)
        if val is not None:
            try:
                filters[key] = float(val)
            except (ValueError, TypeError):
                pass
    if request.args.get("favorite", "").lower() in ("true", "1"):
        filters["favorite"] = True
    # Archive filter: by default hide archived sessions unless explicitly requested
    archived_param = request.args.get("archived", "").lower()
    if archived_param in ("true", "1"):
        filters["archived"] = True
    elif archived_param in ("all",):
        pass  # show all — don't filter on archived
    else:
        filters["archived"] = False  # default: hide archived

    sort_by = request.args.get("sort_by")
    sort_dir = request.args.get("sort_dir", "desc")

    conn = get_db_connection()
    sessions = models.get_sessions(
        conn, limit=limit, offset=offset,
        filters=filters or None,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )
    total = models.count_sessions_filtered(conn, filters=filters or None)

    # Strip internal fields from each session
    clean = []
    for s in sessions:
        s = dict(s)
        s.pop("source_path", None)
        s.pop("html_report_path", None)
        if s.get("csv_filename"):
            s["csv_filename"] = Path(s["csv_filename"]).name
        # Ensure display_name is always set and clean
        if not s.get("display_name"):
            fn = s.get("csv_filename", "")
            s["display_name"] = Path(fn).stem if fn else s.get("session_id", "")
        clean.append(s)

    return api_response({
        "sessions": clean,
        "total": total,
        "limit": limit,
        "offset": offset,
    })


@bp.route("/sessions/filter-options", methods=["GET"])
@_safe_api
def session_filter_options() -> tuple[dict, int]:
    """Return distinct values for filter dropdowns."""
    conn = get_db_connection()
    drivers = [r["driver_name"] for r in conn.execute(
        "SELECT DISTINCT driver_name FROM drivers ORDER BY driver_name"
    ).fetchall()]
    tracks = [r["track_name"] for r in conn.execute(
        "SELECT DISTINCT track_name FROM tracks WHERE track_name IS NOT NULL ORDER BY track_name"
    ).fetchall()]
    return api_response({
        "drivers": drivers,
        "tracks": tracks,
        "session_types": ["practice", "qualifying", "race", "test", "endurance"],
        "track_states": ["dry", "wet", "damp", "mixed", "greasy"],
    })


# ══════════════════════════════════════════════════════════════════
# 2. GET /api/v1/sessions/<id> — Session detail
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>", methods=["GET"])
@_safe_api
def get_session(session_id: str) -> tuple[dict, int]:
    """Return a single session by ID."""
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)
    # Strip internal fields -- never expose server paths
    result = dict(session)
    result.pop("source_path", None)
    result.pop("html_report_path", None)
    # Ensure csv_filename is just the filename, not a path
    if result.get("csv_filename"):
        result["csv_filename"] = Path(result["csv_filename"]).name
    # Ensure display_name is always set and clean
    if not result.get("display_name"):
        fn = result.get("csv_filename", "")
        result["display_name"] = Path(fn).stem if fn else result.get("session_id", "")
    # Flag unnamed tracks (track_name == track_id means auto-generated UUID name)
    tid = result.get("track_id") or ""
    tname = (result.get("track_name") or "").strip()
    result["track_unnamed"] = bool(tid and (not tname or tname == tid))

    # Surface pipeline status from analysis_json if available
    analysis = models.get_analysis_json(conn, session_id)
    if analysis and isinstance(analysis, dict):
        pipeline = analysis.get("pipeline")
        if pipeline:
            result["pipeline"] = pipeline
        dq = analysis.get("distance_quality")
        if dq:
            result["distance_quality"] = dq
    return api_response(result)


# ══════════════════════════════════════════════════════════════════
# 3. GET /api/v1/sessions/<id>/laps — Lap list
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/laps", methods=["GET"])
@_safe_api
def get_laps(session_id: str) -> tuple[dict, int]:
    """Return all laps for a session."""
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    laps = models.get_laps_for_session(conn, session_id)
    return api_response({"laps": laps})


# ══════════════════════════════════════════════════════════════════
# 4. GET /api/v1/sessions/<id>/speed-trace?lap=N
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/speed-trace", methods=["GET"])
@_safe_api
def get_speed_trace(session_id: str) -> tuple[dict, int]:
    """Return speed vs distance arrays for a lap.

    Query params:
        lap (int, optional) — lap number; defaults to best lap
        ref (int, optional) — reference lap for overlay; interpolated to same distance axis
    """
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    lap_num = _get_lap_param(conn, session_id)
    if lap_num is None:
        return api_response({
            "available": False,
            "reason_code": "no_laps",
            "message": "No laps available for this session",
        })

    trace = models.get_gps_trace(conn, session_id, lap_num)
    if trace is None:
        return api_response({
            "available": False,
            "reason_code": "no_speed_trace",
            "message": f"No speed trace data for lap {lap_num}",
        })

    # Check for v2 version parameter
    version = request.args.get("version", "v1")
    if version == "v2":
        analysis = models.get_analysis_json(conn, session_id)
        if analysis and isinstance(analysis, dict):
            opt = analysis.get("optimal_v2")
            if opt and "v_opt_mps" in opt:
                return api_response({
                    "available": True,
                    "distances": opt.get("distance_m", []),
                    "speeds": opt["v_opt_mps"],
                    "speeds_low": opt.get("v_opt_low_mps", []),
                    "speeds_high": opt.get("v_opt_high_mps", []),
                    "lap_number": lap_num,
                    "lap_time_s": opt.get("lap_time_s"),
                    "lap_time_low_s": opt.get("lap_time_low_s"),
                    "lap_time_high_s": opt.get("lap_time_high_s"),
                    "solver_version": opt.get("solver_version"),
                    "version": "v2",
                })

    distances = trace.get("distances", [])
    # Detect row-index distances (0,1,2,...N-1) from legacy bug and
    # reconstruct real distances from GPS coordinates via haversine.
    if (
        distances
        and len(distances) > 2
        and distances[0] == 0
        and abs(distances[-1] - (len(distances) - 1)) < 1.0
    ):
        lats = trace.get("latitudes", [])
        lons = trace.get("longitudes", [])
        if lats and lons and len(lats) == len(distances):
            import math
            _R = 6_371_000  # Earth radius in metres
            cum = [0.0]
            for i in range(1, len(lats)):
                lat1, lat2 = math.radians(lats[i - 1]), math.radians(lats[i])
                dlat = lat2 - lat1
                dlon = math.radians(lons[i] - lons[i - 1])
                a = (math.sin(dlat / 2) ** 2
                     + math.cos(lat1) * math.cos(lat2)
                     * math.sin(dlon / 2) ** 2)
                cum.append(cum[-1] + _R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))
            distances = cum

    result = {
        "distances": distances,
        "speeds": trace.get("speeds", []),
        "lap_number": lap_num,
    }
    result["available"] = True

    # Optional reference lap overlay
    ref_raw = request.args.get("ref")
    if ref_raw is not None:
        try:
            ref_lap = int(ref_raw)
        except (ValueError, TypeError):
            ref_lap = None
        if ref_lap is not None:
            ref_trace = models.get_gps_trace(conn, session_id, ref_lap)
            if ref_trace:
                import numpy as np
                ref_dists = ref_trace.get("distances", [])
                ref_speeds = ref_trace.get("speeds", [])
                if ref_dists and ref_speeds:
                    primary_dists = trace.get("distances", [])
                    interp = np.interp(primary_dists, ref_dists, ref_speeds)
                    result["ref_speeds"] = interp.tolist()
                    result["ref_lap_number"] = ref_lap

    # Optional average pace line across all valid laps
    if request.args.get("avg") == "1":
        try:
            import numpy as np

            all_laps = models.get_laps(conn, session_id)
            primary_dists = trace.get("distances", [])
            if all_laps and primary_dists:
                speed_arrays = []
                for lap_row in all_laps:
                    ln = lap_row.get("lap_number")
                    if ln == lap_num:
                        speed_arrays.append(np.array(trace.get("speeds", [])))
                        continue
                    lt = models.get_gps_trace(conn, session_id, ln)
                    if lt and lt.get("distances") and lt.get("speeds"):
                        interp_s = np.interp(
                            primary_dists, lt["distances"], lt["speeds"]
                        )
                        speed_arrays.append(interp_s)
                if len(speed_arrays) >= 2:
                    avg_arr = np.mean(speed_arrays, axis=0)
                    result["avg_speeds"] = avg_arr.tolist()
                    result["avg_lap_count"] = len(speed_arrays)
        except Exception:
            pass  # non-critical — graceful degradation

    return api_response(result)


# ══════════════════════════════════════════════════════════════════
# 5. GET /api/v1/sessions/<id>/gps-trace?lap=N
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/gps-trace", methods=["GET"])
@_safe_api
def get_gps_trace(session_id: str) -> tuple[dict, int]:
    """Return GPS coordinates and speed arrays for a lap.

    Query params:
        lap (int, optional) — lap number; defaults to best lap
    """
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    lap_num = _get_lap_param(conn, session_id)
    if lap_num is None:
        return api_response({
            "available": False,
            "reason_code": "no_laps",
            "message": "No laps available for this session",
        })

    trace = models.get_gps_trace(conn, session_id, lap_num)
    if trace is None:
        return api_response({
            "available": False,
            "reason_code": "no_gps_data",
            "message": f"No GPS trace for lap {lap_num}",
        })

    distances = trace.get("distances", [])
    lats = trace.get("latitudes", [])
    lons = trace.get("longitudes", [])

    # Reconstruct real distances from GPS if stored values are row indices
    if (
        distances
        and len(distances) > 2
        and distances[0] == 0
        and abs(distances[-1] - (len(distances) - 1)) < 1.0
        and lats and lons and len(lats) == len(distances)
    ):
        import math
        _R = 6_371_000
        cum = [0.0]
        for i in range(1, len(lats)):
            lat1, lat2 = math.radians(lats[i - 1]), math.radians(lats[i])
            dlat = lat2 - lat1
            dlon = math.radians(lons[i] - lons[i - 1])
            a = (math.sin(dlat / 2) ** 2
                 + math.cos(lat1) * math.cos(lat2)
                 * math.sin(dlon / 2) ** 2)
            cum.append(cum[-1] + _R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))
        distances = cum

    return api_response({
        "latitudes": lats,
        "longitudes": lons,
        "distances": distances,
        "speeds": trace.get("speeds", []),
        "lap_number": lap_num,
        "available": True,
    })


# ══════════════════════════════════════════════════════════════════
# 6. GET /api/v1/sessions/<id>/gg-data?lap=N
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/gg-data", methods=["GET"])
@_safe_api
def get_gg_data(session_id: str) -> tuple[dict, int]:
    """Return lateral and longitudinal acceleration arrays for GG diagram.

    Query params:
        lap (int, optional) — lap number; defaults to best lap
    """
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    lap_num = _get_lap_param(conn, session_id)
    if lap_num is None:
        return api_response({
            "accel_lat": [],
            "accel_long": [],
            "distances": [],
            "available": False,
            "reason_code": "no_laps",
            "message": "No laps available for this session",
        })

    trace = models.get_gps_trace(conn, session_id, lap_num)
    if trace is None:
        return api_response({
            "accel_lat": [],
            "accel_long": [],
            "distances": [],
            "lap_number": lap_num,
            "available": False,
            "reason_code": "NO_GG_DATA",
            "message": "No trace data available for this lap",
        })

    lat_g = trace.get("accel_lat") or []
    lon_g = trace.get("accel_long") or []
    distances = trace.get("distances") or []
    has_accel = bool(lat_g and lon_g)

    # Reconstruct real distances from GPS if stored values are row indices
    lats = trace.get("latitudes") or []
    lons = trace.get("longitudes") or []
    if (
        distances
        and len(distances) > 2
        and distances[0] == 0
        and abs(distances[-1] - (len(distances) - 1)) < 1.0
        and lats and lons and len(lats) == len(distances)
    ):
        import math
        _R = 6_371_000
        cum = [0.0]
        for i in range(1, len(lats)):
            lat1, lat2 = math.radians(lats[i - 1]), math.radians(lats[i])
            dlat = lat2 - lat1
            dlon = math.radians(lons[i] - lons[i - 1])
            a = (math.sin(dlat / 2) ** 2
                 + math.cos(lat1) * math.cos(lat2)
                 * math.sin(dlon / 2) ** 2)
            cum.append(cum[-1] + _R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))
        distances = cum

    result = {
        "accel_lat": lat_g if has_accel else [],
        "accel_long": lon_g if has_accel else [],
        "distances": distances if has_accel else [],
        "lap_number": lap_num,
        "available": has_accel,
    }
    if not has_accel:
        result["reason_code"] = "NO_GG_DATA"
        result["message"] = (
            "No accelerometer data available for this session. "
            "G-G diagrams require lateral and longitudinal acceleration columns "
            "in your CSV (e.g., 'Acceleration X/Y' or 'Lateral/Longitudinal G')."
        )

    return api_response(result)


# ══════════════════════════════════════════════════════════════════
# 7. GET /api/v1/sessions/<id>/scores
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/scores", methods=["GET"])
@_safe_api
def get_scores(session_id: str) -> tuple[dict, int]:
    """Return score breakdown for a session."""
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    scores = models.get_score_details(conn, session_id)
    if scores is None:
        return api_response({
            "available": False,
            "reason_code": "NO_SCORE_DATA",
            "message": "Scoring data not available for this session",
        })

    scores["available"] = True

    # ── display_scores: integer-rounded values for clean UI display ──
    display = {}
    for cat in ("pace", "consistency", "execution", "robustness", "adaptation"):
        raw = scores.get(f"{cat}_score")
        mx = scores.get(f"{cat}_max")
        display[cat] = {
            "score": round(raw) if raw is not None else None,
            "max": round(mx) if mx is not None else None,
        }
    scores["display_scores"] = display

    # ── badges: earned achievement badges ──
    try:
        from scoring import evaluate_badges
        sub_scores = {}
        for cat in ("pace", "consistency", "execution", "robustness", "adaptation"):
            sub_scores[cat] = {
                "score": scores.get(f"{cat}_score", 0) or 0,
                "max": scores.get(f"{cat}_max", 1) or 1,
            }
        total = sum(s["score"] for s in sub_scores.values())
        badges_input = {"total_score": total, "sub_scores": sub_scores}
        scores["badges"] = evaluate_badges(badges_input)
    except Exception:
        logger.warning("Badge evaluation failed for session %s", session_id, exc_info=True)
        scores["badges"] = []

    # ── confidence: from theoretical_metrics ──
    try:
        theo_data = models.get_theoretical_data(conn, session_id)
        if theo_data and isinstance(theo_data, dict):
            metrics = theo_data.get("theoretical_metrics", {})
            if metrics and "confidence" in metrics:
                conf = metrics["confidence"]
                scores["confidence_score"] = conf.get("confidence_score")
                scores["confidence_level"] = conf.get("confidence_level")
                scores["confidence_reasons"] = conf.get(
                    "confidence_reasons", []
                )
                scores["recommended_next_action"] = conf.get(
                    "recommended_next_action", ""
                )
    except Exception:
        logger.warning(
            "Confidence data unavailable for session %s",
            session_id,
            exc_info=True,
        )

    # ── grip / friction / optimal_v2 availability ──
    try:
        analysis = models.get_analysis_json(conn, session_id)
        if analysis and isinstance(analysis, dict):
            scores["grip_map_available"] = analysis.get("grip_map") is not None
            scores["friction_envelope_available"] = (
                analysis.get("friction_envelope") is not None
            )
            scores["optimal_v2_available"] = (
                analysis.get("optimal_v2") is not None
            )
        else:
            scores["grip_map_available"] = False
            scores["friction_envelope_available"] = False
            scores["optimal_v2_available"] = False
    except Exception:
        scores["grip_map_available"] = False
        scores["friction_envelope_available"] = False
        scores["optimal_v2_available"] = False

    return api_response(scores)


# ══════════════════════════════════════════════════════════════════
# 8. GET /api/v1/sessions/<id>/corners
# ══════════════════════════════════════════════════════════════════


def _merge_coaching_labels(conn: Any, session_id: str, corners: list[dict]) -> None:
    """Merge corner coaching labels from optimal_v2 into corner dicts (in-place)."""
    analysis = models.get_analysis_json(conn, session_id)
    if not analysis or not isinstance(analysis, dict):
        return
    opt = analysis.get("optimal_v2")
    if not opt or not isinstance(opt, dict):
        return
    coaching_labels: dict = {}
    for label in opt.get("corner_coaching_labels", []):
        cid = label.get("corner_id")
        if cid is not None:
            coaching_labels[cid] = label
    if not coaching_labels:
        return
    for corner in corners:
        cid = corner.get("corner_id")
        if cid in coaching_labels:
            cl = coaching_labels[cid]
            corner["limiting_factor"] = cl.get("limiting_factor", "")
            corner["corner_priority"] = cl.get("corner_priority", "")
            corner["coaching_text"] = cl.get("coaching_text", "")


@bp.route("/sessions/<session_id>/corners", methods=["GET"])
@_safe_api
def get_corners(session_id: str) -> tuple[dict, int]:
    """Return corner boundaries merged with coaching metrics.

    Corner boundaries come from corner_metrics_summary (aggregated
    per-corner data across all laps).  Coaching metrics come from
    theoretical_data.corner_coaching_json (physics-based theoretical
    vs actual comparison).

    If boundaries exist but coaching is missing for a corner, the
    corner is still returned with ``available: false`` and metric
    fields set to ``null``.  If no boundaries exist but coaching
    does, the coaching list is returned directly as a fallback.
    """
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    # -- 0. Coaching V2 from analysis_json (if available) ----------------
    _analysis = models.get_analysis_json(conn, session_id)
    _coaching_v2 = _analysis.get("coaching_v2") if _analysis else None

    # -- 1. Corner boundaries from corner_metrics_summary ----------------
    boundary_rows = models.get_corner_metrics_summary(conn, session_id)

    # -- 2. Coaching metrics from theoretical_data -----------------------
    theo = models.get_theoretical_data(conn, session_id)
    coaching_list = theo.get("corner_coaching") if theo else None

    # -- 3. Build coaching lookup by corner_id ---------------------------
    coaching_map: dict = {}
    if coaching_list:
        for cc in coaching_list:
            cid = cc.get("corner_id")
            if cid is not None:
                coaching_map[cid] = cc

    _METRIC_FIELDS = (
        "entry_speed_actual", "entry_speed_theory",
        "apex_speed_actual", "apex_speed_theory",
        "exit_speed_actual", "exit_speed_theory",
        "time_loss_total_s", "grip_utilisation_pct",
        "primary_cause", "coaching_hint",
    )

    # Map from CornerPerformance.to_dict() keys to our API field names.
    _COACHING_KEY_MAP = {
        "entry_speed_actual":    "actual_entry_speed_mps",
        "entry_speed_theory":    "theoretical_entry_speed_mps",
        "apex_speed_actual":     "actual_apex_speed_mps",
        "apex_speed_theory":     "theoretical_apex_speed_mps",
        "exit_speed_actual":     "actual_exit_speed_mps",
        "exit_speed_theory":     "theoretical_exit_speed_mps",
        "time_loss_total_s":     "time_loss_s",
        "grip_utilisation_pct":  "grip_utilisation_pct",
        "primary_cause":         "primary_cause",
        "coaching_hint":         "coaching_hint",
    }

    def _extract_coaching(cc: dict) -> dict:
        """Extract metric fields from a coaching dict, mapping keys."""
        out = {}
        for api_key, src_key in _COACHING_KEY_MAP.items():
            out[api_key] = cc.get(src_key) if cc.get(src_key) is not None else cc.get(api_key)
        return out

    # -- 4. Merge boundaries + coaching ----------------------------------
    if boundary_rows:
        corners = []
        for row in boundary_rows:
            cid = row["corner_id"]
            cc = coaching_map.get(cid)
            corner: dict = {
                "corner_id": cid,
                "s_start":   cc.get("s_start") if cc else None,
                "s_end":     cc.get("s_end") if cc else None,
                "s_apex":    cc.get("s_apex") if cc else None,
                "direction": cc.get("direction") if cc else None,
            }
            if cc:
                corner["available"] = True
                corner.update(_extract_coaching(cc))
            else:
                corner["available"] = False
                corner["reason_code"] = "no_theoretical"
                corner["coaching_hint"] = "Theoretical data unavailable for this corner"
                for field in _METRIC_FIELDS:
                    if field not in corner:
                        corner[field] = None
            corners.append(corner)

        # -- Merge coaching labels from optimal_v2 ---
        _merge_coaching_labels(conn, session_id, corners)

        # -- 4b. Merge timeline data if available --
        if theo:
            timeline_list = theo.get("corner_timelines", [])
            tl_map = {}
            for tl in (timeline_list or []):
                tid = tl.get("corner_id")
                if tid is not None:
                    tl_map[tid] = tl

            if corners and tl_map:
                for corner in corners:
                    cid = corner.get("corner_id")
                    if cid in tl_map:
                        corner["timeline"] = tl_map[cid]

        # -- 4c. Merge advanced corner intelligence --
        if theo:
            aci = theo.get("advanced_corner_intelligence", {})
            if aci and corners:
                br_map = {br["corner_id"]: br for br in aci.get("brake_release", [])}
                coup_map = {c["corner_id"]: c for c in aci.get("brake_yaw_coupling", [])}
                tgt_map = {t["corner_id"]: t for t in aci.get("corner_targets", [])}
                risk_map = {r["corner_id"]: r for r in aci.get("corner_risk_scores", [])}
                for corner in corners:
                    cid = corner.get("corner_id")
                    if cid in br_map:
                        corner["brake_release"] = br_map[cid]
                    if cid in coup_map:
                        corner["brake_yaw_coupling"] = coup_map[cid]
                    if cid in tgt_map:
                        corner["targets"] = tgt_map[cid]
                    if cid in risk_map:
                        corner["risk_index"] = risk_map[cid].get("risk_index", 0)

        # -- Merge v2 corner coaching fields --
        try:
            for corner in corners:
                cid = corner.get("corner_id")
                if cid is not None:
                    v2_row = conn.execute(
                        """SELECT corner_type, section_type, mrp_distance_m,
                                  mrp_speed_mps, geometric_apex_m, exit_importance,
                                  handling_events_json, is_user_defined
                           FROM corner_metrics
                           WHERE session_id = ? AND corner_id = ?
                           LIMIT 1""",
                        (session_id, cid),
                    ).fetchone()
                    if v2_row:
                        v2 = dict(v2_row) if hasattr(v2_row, 'keys') else {}
                        corner["corner_type"] = v2.get("corner_type")
                        corner["section_type"] = v2.get("section_type")
                        corner["mrp_distance_m"] = v2.get("mrp_distance_m")
                        corner["mrp_speed_mps"] = v2.get("mrp_speed_mps")
                        corner["geometric_apex_m"] = v2.get("geometric_apex_m")
                        corner["exit_importance"] = v2.get("exit_importance")
                        corner["is_user_defined"] = bool(v2.get("is_user_defined"))
                        he_json = v2.get("handling_events_json")
                        if he_json:
                            try:
                                corner["handling_events"] = json.loads(he_json)
                            except (json.JSONDecodeError, TypeError):
                                pass
        except Exception:
            logger.debug("v2 corner field merge failed", exc_info=True)

        resp = {
            "corners": corners,
            "available": True,
        }
        if _coaching_v2:
            resp["coaching_v2"] = _coaching_v2
        # Include per-section v2 coaching from analysis_json
        _ccv2 = _analysis.get("corner_coaching_v2") if _analysis else None
        if _ccv2:
            resp["corner_coaching_v2"] = _ccv2
        return api_response(resp)

    # -- 5. Fallback: no boundaries but coaching exists ------------------
    if coaching_list:
        corners = []
        for cc in coaching_list:
            corner = {
                "corner_id": cc.get("corner_id"),
                "s_start":   cc.get("s_start"),
                "s_end":     cc.get("s_end"),
                "s_apex":    cc.get("s_apex"),
                "direction": cc.get("direction"),
                "available": True,
            }
            corner.update(_extract_coaching(cc))
            corners.append(corner)

        # -- Merge coaching labels from optimal_v2 ---
        _merge_coaching_labels(conn, session_id, corners)

        # -- 5b. Merge timeline data if available --
        if theo:
            timeline_list = theo.get("corner_timelines", [])
            tl_map = {}
            for tl in (timeline_list or []):
                tid = tl.get("corner_id")
                if tid is not None:
                    tl_map[tid] = tl

            if corners and tl_map:
                for corner in corners:
                    cid = corner.get("corner_id")
                    if cid in tl_map:
                        corner["timeline"] = tl_map[cid]

        # -- 5c. Merge advanced corner intelligence --
        if theo:
            aci = theo.get("advanced_corner_intelligence", {})
            if aci and corners:
                br_map = {br["corner_id"]: br for br in aci.get("brake_release", [])}
                coup_map = {c["corner_id"]: c for c in aci.get("brake_yaw_coupling", [])}
                tgt_map = {t["corner_id"]: t for t in aci.get("corner_targets", [])}
                risk_map = {r["corner_id"]: r for r in aci.get("corner_risk_scores", [])}
                for corner in corners:
                    cid = corner.get("corner_id")
                    if cid in br_map:
                        corner["brake_release"] = br_map[cid]
                    if cid in coup_map:
                        corner["brake_yaw_coupling"] = coup_map[cid]
                    if cid in tgt_map:
                        corner["targets"] = tgt_map[cid]
                    if cid in risk_map:
                        corner["risk_index"] = risk_map[cid].get("risk_index", 0)

        # -- Merge v2 corner coaching fields --
        try:
            for corner in corners:
                cid = corner.get("corner_id")
                if cid is not None:
                    v2_row = conn.execute(
                        """SELECT corner_type, section_type, mrp_distance_m,
                                  mrp_speed_mps, geometric_apex_m, exit_importance,
                                  handling_events_json, is_user_defined
                           FROM corner_metrics
                           WHERE session_id = ? AND corner_id = ?
                           LIMIT 1""",
                        (session_id, cid),
                    ).fetchone()
                    if v2_row:
                        v2 = dict(v2_row) if hasattr(v2_row, 'keys') else {}
                        corner["corner_type"] = v2.get("corner_type")
                        corner["section_type"] = v2.get("section_type")
                        corner["mrp_distance_m"] = v2.get("mrp_distance_m")
                        corner["mrp_speed_mps"] = v2.get("mrp_speed_mps")
                        corner["geometric_apex_m"] = v2.get("geometric_apex_m")
                        corner["exit_importance"] = v2.get("exit_importance")
                        corner["is_user_defined"] = bool(v2.get("is_user_defined"))
                        he_json = v2.get("handling_events_json")
                        if he_json:
                            try:
                                corner["handling_events"] = json.loads(he_json)
                            except (json.JSONDecodeError, TypeError):
                                pass
        except Exception:
            logger.debug("v2 corner field merge failed", exc_info=True)

        resp = {
            "corners": corners,
            "available": True,
        }
        if _coaching_v2:
            resp["coaching_v2"] = _coaching_v2
        _ccv2 = _analysis.get("corner_coaching_v2") if _analysis else None
        if _ccv2:
            resp["corner_coaching_v2"] = _ccv2
        return api_response(resp)

    # -- 6. No data at all -----------------------------------------------
    return api_response({
        "corners": [],
        "available": False,
        "reason_code": "NO_CORNER_DATA",
        "message": "Corner detection did not produce results for this session",
    })


# ══════════════════════════════════════════════════════════════════
# 8b. GET /api/v1/sessions/<id>/corners/per-lap
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/corners/per-lap", methods=["GET"])
@_safe_api
def get_corners_per_lap(session_id: str) -> tuple[dict, int]:
    """Return per-lap corner metrics (apex speed, entry speed, etc.).

    Used for corner speed trend analysis across laps.
    Returns a flat list of rows with lap_number + corner_id + metrics.
    """
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    rows = models.get_corner_metrics_for_session(conn, session_id)
    if not rows:
        return api_response({
            "metrics": [],
            "available": False,
            "reason_code": "NO_PER_LAP_CORNER_DATA",
            "message": "No per-lap corner metrics available",
        })

    return api_response({
        "metrics": rows,
        "available": True,
    })


# ══════════════════════════════════════════════════════════════════
# 9. DELETE /api/v1/sessions/<id>
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>", methods=["DELETE"])
@_safe_api
def delete_session(session_id: str) -> tuple[dict, int]:
    """Soft-delete a session (recoverable for 30 days).

    Requires at least 'member' role in the workspace (viewers cannot delete).
    Pass ``?permanent=true`` to hard-delete immediately (admin only).
    """
    # RBAC: viewers should not be able to delete sessions.
    workspace_role = getattr(g, "workspace_role", None)
    if workspace_role == "viewer":
        return api_error(ErrorCode.FORBIDDEN, "Insufficient permissions to delete sessions", status=403)

    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    permanent = request.args.get("permanent", "").lower() in ("true", "1")

    if permanent:
        # Only admins/owners can permanently delete
        if workspace_role not in ("admin", "owner", None):
            return api_error(ErrorCode.FORBIDDEN, "Only admins can permanently delete", status=403)

        for table in _DELETE_RELATED_TABLES:
            assert table in _ALLOWED_DELETE_TABLES, f"Unexpected table: {table}"
            try:
                conn.execute(
                    f"DELETE FROM {table} WHERE session_id = :session_id",
                    {"session_id": session_id},
                )
            except Exception as exc:
                logger.debug("Skipping delete from %s: %s", table, exc)

        conn.execute(
            "DELETE FROM sessions WHERE session_id = :session_id",
            {"session_id": session_id},
        )
        audit_log(conn, "session.hard_delete", {"session_id": session_id})
    else:
        # Soft delete — mark deleted_at, data preserved
        models.soft_delete_session(conn, session_id)
        audit_log(conn, "session.soft_delete", {"session_id": session_id})

    conn.commit()

    try:
        from telemetry_tool.web.rollups import refresh_rollups
        refresh_rollups(conn, int(g.workspace_id))
    except Exception:
        logger.warning("Rollup refresh failed after delete", exc_info=True)

    mode = "permanently deleted" if permanent else "soft-deleted"
    logger.info("%s session %s", mode.capitalize(), session_id)
    return api_response({"deleted": session_id, "permanent": permanent})


@bp.route("/sessions/<session_id>/restore", methods=["POST"])
@_safe_api
def restore_session(session_id: str) -> tuple[dict, int]:
    """Restore a soft-deleted session."""
    workspace_role = getattr(g, "workspace_role", None)
    if workspace_role == "viewer":
        return api_error(ErrorCode.FORBIDDEN, "Insufficient permissions", status=403)

    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    if not session.get("deleted_at"):
        return api_error(ErrorCode.CONFLICT, "Session is not deleted", status=409)

    models.restore_session(conn, session_id)
    audit_log(conn, "session.restore", {"session_id": session_id})
    conn.commit()

    logger.info("Restored session %s", session_id)
    return api_response({"restored": session_id})


# ══════════════════════════════════════════════════════════════════
# 9b. POST /api/v1/sessions/<id>/favorite — Toggle favorite
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/favorite", methods=["POST"])
@_safe_api
def toggle_favorite(session_id: str) -> tuple[dict, int]:
    """Toggle the favorite/bookmark status of a session."""
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    current = session.get("is_favorite", 0)
    new_val = 0 if current else 1
    models.update_session_field(conn, session_id, "is_favorite", new_val)
    conn.commit()
    return api_response({"session_id": session_id, "is_favorite": bool(new_val)})


# ══════════════════════════════════════════════════════════════════
# 9c. POST /api/v1/sessions/bulk — Bulk operations
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/bulk", methods=["POST"])
@_safe_api
def bulk_session_action() -> tuple[dict, int]:
    """Perform a bulk action on multiple sessions.

    Body::

        {
            "action": "delete" | "restore" | "favorite" | "unfavorite",
            "session_ids": ["id1", "id2", ...]
        }

    Returns the count of successfully processed sessions.
    Max 100 session_ids per request.
    """
    workspace_role = getattr(g, "workspace_role", None)
    if workspace_role == "viewer":
        return api_error(ErrorCode.FORBIDDEN, "Insufficient permissions", status=403)

    body = request.get_json(silent=True) or {}
    action = body.get("action")
    session_ids = body.get("session_ids", [])

    if action not in ("delete", "restore", "favorite", "unfavorite"):
        return api_error(ErrorCode.VALIDATION_ERROR, "Invalid action", status=422)
    if not session_ids or not isinstance(session_ids, list):
        return api_error(ErrorCode.VALIDATION_ERROR, "session_ids must be a non-empty list", status=422)
    if len(session_ids) > 100:
        return api_error(ErrorCode.VALIDATION_ERROR, "Max 100 sessions per bulk operation", status=422)

    conn = get_db_connection()
    processed = 0

    for sid in session_ids:
        session = models.get_session_by_id(conn, sid)
        if session is None:
            continue

        if action == "delete":
            if models.soft_delete_session(conn, sid):
                processed += 1
        elif action == "restore":
            if models.restore_session(conn, sid):
                processed += 1
        elif action == "favorite":
            models.update_session_field(conn, sid, "is_favorite", 1)
            processed += 1
        elif action == "unfavorite":
            models.update_session_field(conn, sid, "is_favorite", 0)
            processed += 1

    audit_log(conn, f"session.bulk_{action}", {
        "session_ids": session_ids,
        "processed": processed,
    })
    conn.commit()

    return api_response({
        "action": action,
        "requested": len(session_ids),
        "processed": processed,
    })


# ══════════════════════════════════════════════════════════════════
# 9d. GET/POST/DELETE /api/v1/sessions/<id>/tags — Session tagging
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/tags", methods=["GET"])
@_safe_api
def get_session_tags(session_id: str) -> tuple[dict, int]:
    """List all tags for a session."""
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    rows = conn.execute(
        "SELECT tag, confidence, source, created_at "
        "FROM session_tags WHERE session_id = :sid ORDER BY created_at",
        {"sid": session_id},
    ).fetchall()
    tags = [dict(r) for r in rows]
    return api_response({"session_id": session_id, "tags": tags})


@bp.route("/sessions/<session_id>/tags", methods=["POST"])
@_safe_api
def add_session_tag(session_id: str) -> tuple[dict, int]:
    """Add a tag to a session.

    Body::

        {"tag": "race-day", "confidence": 1.0}
    """
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    body = request.get_json(silent=True) or {}
    tag = (body.get("tag") or "").strip().lower()
    if not tag or len(tag) > 50:
        return api_error(ErrorCode.VALIDATION_ERROR,
                         "Tag must be 1-50 characters", status=422)

    confidence = body.get("confidence", 1.0)
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = 1.0

    try:
        conn.execute(
            "INSERT INTO session_tags (session_id, tag, confidence, source) "
            "VALUES (:sid, :tag, :conf, 'user')",
            {"sid": session_id, "tag": tag, "conf": confidence},
        )
        conn.commit()
    except Exception:
        # Duplicate tag — ignore
        return api_response({"session_id": session_id, "tag": tag, "created": False})

    return api_response({"session_id": session_id, "tag": tag, "created": True}, status=201)


@bp.route("/sessions/<session_id>/tags/<tag>", methods=["DELETE"])
@_safe_api
def delete_session_tag(session_id: str, tag: str) -> tuple[dict, int]:
    """Remove a tag from a session."""
    conn = get_db_connection()
    result = conn.execute(
        "DELETE FROM session_tags WHERE session_id = :sid AND tag = :tag",
        {"sid": session_id, "tag": tag.lower()},
    )
    conn.commit()
    if result.rowcount == 0:
        return api_error(ErrorCode.NOT_FOUND, "Tag not found on session", status=404)
    return api_response({"session_id": session_id, "tag": tag, "deleted": True})


# ══════════════════════════════════════════════════════════════════
# 10. GET /api/v1/compare/sessions?a=X&b=Y — Session comparison
# ══════════════════════════════════════════════════════════════════


@bp.route("/compare/sessions", methods=["GET"])
@_safe_api
def compare_sessions() -> tuple[dict, int]:
    """Return two sessions side-by-side with scores and laps.

    Query params:
        a (str, required) — first session ID
        b (str, required) — second session ID
    """
    session_a_id = request.args.get("a")
    session_b_id = request.args.get("b")

    if not session_a_id or not session_b_id:
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            "Both 'a' and 'b' query parameters are required",
            status=400,
        )

    conn = get_db_connection()

    session_a = models.get_session_by_id(conn, session_a_id)
    if session_a is None:
        return api_error(
            ErrorCode.NOT_FOUND,
            f"Session {session_a_id} not found",
            status=404,
        )

    session_b = models.get_session_by_id(conn, session_b_id)
    if session_b is None:
        return api_error(
            ErrorCode.NOT_FOUND,
            f"Session {session_b_id} not found",
            status=404,
        )

    scores_a = models.get_score_details(conn, session_a_id)
    scores_b = models.get_score_details(conn, session_b_id)
    laps_a = models.get_laps_for_session(conn, session_a_id)
    laps_b = models.get_laps_for_session(conn, session_b_id)

    return api_response({
        "session_a": {
            "session": session_a,
            "scores": scores_a,
            "laps": laps_a,
        },
        "session_b": {
            "session": session_b,
            "scores": scores_b,
            "laps": laps_b,
        },
    })


# ══════════════════════════════════════════════════════════════════
# 10a2. GET /api/v1/compare/multi?ids=X,Y,Z — Multi-session comparison (3+)
# ══════════════════════════════════════════════════════════════════


@bp.route("/compare/multi", methods=["GET"])
@_safe_api
def compare_multi_sessions() -> tuple[dict, int]:
    """Compare up to 8 sessions side-by-side with scores, laps, and deltas.

    Query params:
        ids (str, required) — comma-separated session IDs (2-8)
    """
    ids_param = request.args.get("ids", "")
    if not ids_param:
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            "The 'ids' query parameter is required (comma-separated session IDs)",
            status=400,
        )

    session_ids = [sid.strip() for sid in ids_param.split(",") if sid.strip()]
    if len(session_ids) < 2:
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            "At least 2 session IDs are required for comparison",
            status=400,
        )
    if len(session_ids) > 8:
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            "Maximum 8 sessions can be compared at once",
            status=400,
        )

    conn = get_db_connection()
    sessions_data = []

    for sid in session_ids:
        session = models.get_session_by_id(conn, sid)
        if session is None:
            return api_error(ErrorCode.NOT_FOUND, f"Session {sid} not found", status=404)
        session = dict(session) if not isinstance(session, dict) else session

        scores = models.get_score_details(conn, sid)
        laps = models.get_laps_for_session(conn, sid)

        # Best lap time for delta computation
        best_time = None
        if laps:
            valid_times = [
                float(l.get("lap_time_s", 0) if isinstance(l, dict) else l["lap_time_s"])
                for l in laps
                if (l.get("lap_time_s") if isinstance(l, dict) else l["lap_time_s"])
                and float(l.get("lap_time_s") if isinstance(l, dict) else l["lap_time_s"]) > 0
            ]
            if valid_times:
                best_time = min(valid_times)

        sessions_data.append({
            "session_id": sid,
            "session": session,
            "scores": scores,
            "laps": laps,
            "best_lap_time_s": best_time,
            "n_laps": len(laps) if laps else 0,
        })

    # Find the overall best for delta computation
    best_times = [s["best_lap_time_s"] for s in sessions_data if s["best_lap_time_s"]]
    overall_best = min(best_times) if best_times else None
    best_session_id = None
    if overall_best is not None:
        best_session_id = next(
            s["session_id"] for s in sessions_data
            if s["best_lap_time_s"] == overall_best
        )

    # Add deltas relative to best
    for s in sessions_data:
        if s["best_lap_time_s"] and overall_best:
            s["delta_to_best_s"] = round(s["best_lap_time_s"] - overall_best, 3)
        else:
            s["delta_to_best_s"] = None

    # Build pairwise delta matrix
    n = len(sessions_data)
    delta_matrix: list[list[float | None]] = []
    for i in range(n):
        row: list[float | None] = []
        for j in range(n):
            t_i = sessions_data[i]["best_lap_time_s"]
            t_j = sessions_data[j]["best_lap_time_s"]
            if t_i is not None and t_j is not None:
                row.append(round(t_i - t_j, 3))
            else:
                row.append(None)
        delta_matrix.append(row)

    return api_response({
        "sessions": sessions_data,
        "session_count": len(sessions_data),
        "best_session_id": best_session_id,
        "overall_best_time_s": overall_best,
        "delta_matrix": delta_matrix,
        "session_ids": session_ids,
    })


# ══════════════════════════════════════════════════════════════════
# 10b. GET /api/v1/compare/drivers?a=X&b=Y — Driver comparison
# ══════════════════════════════════════════════════════════════════


def _driver_data(conn: Any, driver_id: int) -> dict | None:
    """Aggregate scores, trend, and stats for a single driver.

    Returns None if the driver does not exist.
    Returns zeroed/empty data if the driver exists but has no sessions.
    """
    # --- driver record ---
    row = conn.execute(
        "SELECT driver_id, driver_name, created_at, notes "
        "FROM drivers WHERE driver_id = :driver_id",
        {"driver_id": driver_id},
    ).fetchone()
    if row is None:
        return None
    driver = {"id": row["driver_id"], "name": row["driver_name"]}

    # --- all sessions for this driver (with track name) ---
    sessions = [
        dict(r)
        for r in conn.execute(
            "SELECT s.session_id, s.session_date, s.total_score, s.track_id "
            "FROM sessions s "
            "WHERE s.driver_id = :driver_id "
            "ORDER BY s.session_date ASC",
            {"driver_id": driver_id},
        ).fetchall()
    ]

    if not sessions:
        return {
            "driver": driver,
            "avg_scores": {
                "pace": 0, "consistency": 0,
                "execution": 0, "robustness": 0,
            },
            "trend": [],
            "stats": {
                "sessions": 0, "avg_score": 0,
                "best_score": 0, "tracks": 0,
            },
        }

    # --- score aggregation ---
    pace_vals: list[float] = []
    consistency_vals: list[float] = []
    execution_vals: list[float] = []
    robustness_vals: list[float] = []

    for sess in sessions:
        scores = models.get_score_details(conn, sess["session_id"])
        if scores is None:
            continue
        if scores.get("pace_score") is not None:
            pace_vals.append(scores["pace_score"])
        if scores.get("consistency_score") is not None:
            consistency_vals.append(scores["consistency_score"])
        if scores.get("execution_score") is not None:
            execution_vals.append(scores["execution_score"])
        if scores.get("robustness_score") is not None:
            robustness_vals.append(scores["robustness_score"])

    def _avg(vals: list[float]) -> float:
        return round(sum(vals) / len(vals), 1) if vals else 0

    avg_scores = {
        "pace": _avg(pace_vals),
        "consistency": _avg(consistency_vals),
        "execution": _avg(execution_vals),
        "robustness": _avg(robustness_vals),
    }

    # --- trend (session_date + total_score, chronological) ---
    trend = [
        {
            "session_date": s["session_date"],
            "total_score": s["total_score"],
        }
        for s in sessions
        if s.get("total_score") is not None
    ]

    # --- stats ---
    total_scores = [
        s["total_score"] for s in sessions if s.get("total_score") is not None
    ]
    unique_tracks = {s["track_id"] for s in sessions if s.get("track_id")}

    stats = {
        "sessions": len(sessions),
        "avg_score": round(sum(total_scores) / len(total_scores), 1) if total_scores else 0,
        "best_score": max(total_scores) if total_scores else 0,
        "tracks": len(unique_tracks),
    }

    return {
        "driver": driver,
        "avg_scores": avg_scores,
        "trend": trend,
        "stats": stats,
    }


@bp.route("/compare/drivers", methods=["GET"])
@_safe_api
def compare_drivers() -> tuple[dict, int]:
    """Return two drivers side-by-side with aggregated scores, trend, and stats.

    Query params:
        a (int, required) — first driver ID
        b (int, required) — second driver ID
    """
    raw_a = request.args.get("a")
    raw_b = request.args.get("b")

    if not raw_a or not raw_b:
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            "Both 'a' and 'b' query parameters are required",
            status=400,
        )

    try:
        driver_a_id = int(raw_a)
        driver_b_id = int(raw_b)
    except (ValueError, TypeError):
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            "Driver IDs must be integers",
            status=400,
        )

    conn = get_db_connection()

    data_a = _driver_data(conn, driver_a_id)
    if data_a is None:
        return api_error(
            ErrorCode.NOT_FOUND,
            f"Driver {driver_a_id} not found",
            status=404,
        )

    data_b = _driver_data(conn, driver_b_id)
    if data_b is None:
        return api_error(
            ErrorCode.NOT_FOUND,
            f"Driver {driver_b_id} not found",
            status=404,
        )

    return api_response({"driver_a": data_a, "driver_b": data_b})


# ══════════════════════════════════════════════════════════════════
# 11. GET /api/v1/sessions/<id>/report?format=html — Report download
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/report", methods=["GET"])
@_safe_api
def get_report(session_id: str) -> tuple | Response:
    """Download a pre-generated HTML report for a session.

    Query params:
        format (str) — currently only 'html' is supported
    """
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    fmt = request.args.get("format", "html")
    if fmt != "html":
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            f"Unsupported report format: {fmt!r}. Only 'html' is supported.",
            status=400,
        )

    report_path = session.get("html_report_path")
    if not report_path:
        return api_error(
            ErrorCode.NOT_FOUND,
            "Report not available",
            status=404,
        )

    path = Path(report_path).resolve()

    # Prevent path traversal: report must be under the results directory
    # or the temp upload directory. Reject absolute paths pointing elsewhere.
    from flask import current_app
    allowed_dirs = [Path("results").resolve()]
    custom_results = current_app.config.get("RESULTS_DIR")
    if custom_results:
        allowed_dirs.append(Path(custom_results).resolve())

    if not any(str(path).startswith(str(d)) for d in allowed_dirs):
        logger.warning("Report path traversal attempt: %s", report_path)
        return api_error(
            ErrorCode.NOT_FOUND,
            "Report not available",
            status=404,
        )

    if not path.is_file():
        return api_error(
            ErrorCode.NOT_FOUND,
            "Report not available",
            status=404,
        )

    return send_file(
        path,
        mimetype="text/html",
        as_attachment=True,
        download_name=f"report_{session_id}.html",
    )


# ══════════════════════════════════════════════════════════════════
# 12. GET /api/v1/export/scores — Scoring history CSV
# ══════════════════════════════════════════════════════════════════


@bp.route("/export/scores", methods=["GET"])
@_safe_api
def export_scores_csv() -> tuple:
    """Export scoring history as CSV with session metadata."""
    conn = get_db_connection()
    limit = min(int(request.args.get("limit", 500)), 2000)

    sessions = models.get_sessions(conn, limit=limit, offset=0)
    if not sessions:
        return api_error(ErrorCode.NOT_FOUND, "No sessions found", status=404)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "session_id", "session_date", "track_name", "driver_name",
        "best_lap_s", "total_score", "grade",
        "pace_score", "pace_max",
        "consistency_score", "consistency_max",
        "execution_score", "execution_max",
        "robustness_score", "robustness_max",
        "adaptation_score",
    ])

    for sess in sessions:
        sid = sess.get("session_id", "")
        scores = models.get_score_details(conn, sid)
        if scores is None:
            continue

        writer.writerow([
            sid,
            sess.get("session_date", ""),
            sess.get("track_name", ""),
            sess.get("driver_name", ""),
            sess.get("best_lap_time_s", ""),
            sess.get("total_score", ""),
            sess.get("grade", ""),
            scores.get("pace_score", ""),
            scores.get("pace_max", ""),
            scores.get("consistency_score", ""),
            scores.get("consistency_max", ""),
            scores.get("execution_score", ""),
            scores.get("execution_max", ""),
            scores.get("robustness_score", ""),
            scores.get("robustness_max", ""),
            scores.get("adaptation_score", ""),
        ])

    output = buf.getvalue()
    buf.close()

    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=scoring_history.csv"},
    )


# ══════════════════════════════════════════════════════════════════
# 12c. GET /api/v1/sessions/<id>/export?format=aim|motec
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/export", methods=["GET"])
@_safe_api
def export_session_telemetry(session_id: str) -> tuple:
    """Export session telemetry in AiM RaceStudio or MoTeC i2 CSV format.

    Query params:
        format — aim (default) or motec
        lap    — specific lap number (optional, all laps if omitted)
    """
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    fmt = request.args.get("format", "aim").lower()
    lap_filter = request.args.get("lap")

    # Get GPS trace data (has distance, lat, lon, speed)
    laps = models.get_laps(conn, session_id)
    if not laps:
        return api_error(ErrorCode.NOT_FOUND, "No lap data available", status=404)

    buf = io.StringIO()
    writer = csv.writer(buf)

    if fmt == "motec":
        # MoTeC i2 CSV format: Time, Distance, Speed, Lat Accel, Long Accel, GPS Lat, GPS Lon
        writer.writerow([
            "Time [s]", "Distance [m]", "Speed [m/s]",
            "G Force Lat [m/s2]", "G Force Long [m/s2]",
            "GPS Latitude [deg]", "GPS Longitude [deg]",
            "Lap Number",
        ])
    else:
        # AiM RaceStudio CSV format
        writer.writerow([
            "Time(s)", "Distance(m)", "Speed(m/s)",
            "LateralAcceleration(m/s2)", "LongitudinalAcceleration(m/s2)",
            "GPSLatitude(deg)", "GPSLongitude(deg)",
            "LapNumber",
        ])

    for lap_row in laps:
        lap_num = lap_row.get("lap_number", 0)
        if lap_filter and str(lap_num) != str(lap_filter):
            continue

        gps_data = models.get_gps_trace(conn, session_id, lap_num)
        if not gps_data:
            continue

        for pt in gps_data:
            writer.writerow([
                pt.get("elapsed_s", ""),
                pt.get("distance_m", ""),
                pt.get("speed_mps", ""),
                pt.get("a_lat", ""),
                pt.get("a_long", ""),
                pt.get("latitude", ""),
                pt.get("longitude", ""),
                lap_num,
            ])

    output = buf.getvalue()
    buf.close()

    track = session.get("track_name", "unknown") or "unknown"
    ext_name = "motec" if fmt == "motec" else "aim"
    filename = f"{track}_{session_id}_{ext_name}.csv"

    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ══════════════════════════════════════════════════════════════════
# 13. PATCH /api/v1/sessions/<id> — Update session fields
# ══════════════════════════════════════════════════════════════════


import re

# Fields the PATCH endpoint accepts directly (via the for-loop).
_UPDATABLE_FIELDS = {
    "display_name", "session_date", "driver_id", "track_id",
    "session_type", "track_state", "kart_id", "notes",
}

_VALID_SESSION_TYPES = {"practice", "qualifying", "race", "test"}
_VALID_TRACK_STATES = {"dry", "wet", "damp", "mixed"}
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _validate_patch_fields(conn: Any, body: dict) -> tuple[list[dict], dict]:
    """Validate PATCH body fields and return (errors, cleaned_body).

    Returns a tuple of (errors_list, cleaned_body_dict).  ``errors`` is a
    list of ``{"field": ..., "message": ...}`` dicts.  ``cleaned_body``
    contains only the recognised updatable keys from ``body`` (unknown
    keys are silently dropped).
    """
    errors: list[dict] = []
    cleaned: dict = {}

    for field, value in body.items():
        if field == "driver_name":
            # driver_name is handled separately (upsert); just pass through.
            if value is not None and not isinstance(value, str):
                errors.append({"field": "driver_name", "message": "Must be a string."})
            else:
                cleaned["driver_name"] = value
            continue

        if field not in _UPDATABLE_FIELDS:
            continue  # silently ignore unknown fields

        # -- session_type enum --
        if field == "session_type":
            if value not in _VALID_SESSION_TYPES:
                errors.append({
                    "field": "session_type",
                    "message": f"Must be one of: {', '.join(sorted(_VALID_SESSION_TYPES))}.",
                })
            else:
                cleaned[field] = value

        # -- track_state enum --
        elif field == "track_state":
            if value not in _VALID_TRACK_STATES:
                errors.append({
                    "field": "track_state",
                    "message": f"Must be one of: {', '.join(sorted(_VALID_TRACK_STATES))}.",
                })
            else:
                cleaned[field] = value

        # -- driver_id FK check --
        elif field == "driver_id":
            if value is None:
                errors.append({"field": "driver_id", "message": "Cannot be null."})
            else:
                try:
                    did = int(value)
                except (TypeError, ValueError):
                    errors.append({"field": "driver_id", "message": "Must be an integer."})
                    continue
                row = conn.execute(
                    "SELECT 1 FROM drivers WHERE driver_id = ?", (did,)
                ).fetchone()
                if row is None:
                    errors.append({"field": "driver_id", "message": f"Driver {did} not found."})
                else:
                    cleaned[field] = did

        # -- track_id FK check --
        elif field == "track_id":
            if value is None:
                cleaned[field] = None  # unlink track is OK
            else:
                row = conn.execute(
                    "SELECT 1 FROM tracks WHERE track_id = ?", (str(value),)
                ).fetchone()
                if row is None:
                    errors.append({"field": "track_id", "message": f"Track {value!r} not found."})
                else:
                    cleaned[field] = str(value)

        # -- kart_id FK check --
        elif field == "kart_id":
            if value is None:
                cleaned[field] = None  # unlink kart is OK
            else:
                try:
                    kid = int(value)
                except (TypeError, ValueError):
                    errors.append({"field": "kart_id", "message": "Must be an integer."})
                    continue
                row = conn.execute(
                    "SELECT 1 FROM karts WHERE kart_id = ?", (kid,)
                ).fetchone()
                if row is None:
                    errors.append({"field": "kart_id", "message": f"Kart {kid} not found."})
                else:
                    cleaned[field] = kid

        # -- session_date format --
        elif field == "session_date":
            if value is None or not isinstance(value, str) or not _DATE_RE.match(value):
                errors.append({
                    "field": "session_date",
                    "message": "Must be a date string in YYYY-MM-DD format.",
                })
            else:
                cleaned[field] = value

        # -- display_name length --
        elif field == "display_name":
            if value is not None and not isinstance(value, str):
                errors.append({"field": "display_name", "message": "Must be a string."})
            elif isinstance(value, str) and len(value) > 200:
                errors.append({
                    "field": "display_name",
                    "message": "Must be at most 200 characters.",
                })
            else:
                cleaned[field] = value

        # -- notes length --
        elif field == "notes":
            if value is not None and not isinstance(value, str):
                errors.append({"field": "notes", "message": "Must be a string."})
            elif isinstance(value, str) and len(value) > 2000:
                errors.append({
                    "field": "notes",
                    "message": "Must be at most 2000 characters.",
                })
            else:
                cleaned[field] = value

    return errors, cleaned


@bp.route("/sessions/<session_id>", methods=["PATCH"])
@_safe_api
def update_session(session_id: str) -> tuple[dict, int]:
    """Update editable fields on a session.

    Accepts JSON body with any of: session_type, track_state,
    driver_name, driver_id, track_id, kart_id, session_date,
    display_name, notes.  Unknown fields are silently ignored.
    Validation is performed before any writes.

    Requires at least 'member' role (viewers cannot edit sessions).
    """
    workspace_role = getattr(g, "workspace_role", None)
    if workspace_role == "viewer":
        return api_error(ErrorCode.FORBIDDEN, "Insufficient permissions to update sessions", status=403)

    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    body = request.get_json(silent=True)
    if not body or not isinstance(body, dict):
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            "Request body must be a JSON object",
            status=400,
        )

    # Validate all fields up front — collect all errors before writing.
    errors, cleaned = _validate_patch_fields(conn, body)
    if errors:
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            "Validation failed",
            details=errors,
            status=400,
        )

    updated_count = 0

    # Handle driver_name specially — upsert driver, then update driver_id.
    driver_name = cleaned.get("driver_name")
    if driver_name and isinstance(driver_name, str):
        driver_id = models.upsert_driver(conn, driver_name)
        models.update_session_field(conn, session_id, "driver_id", driver_id)
        updated_count += 1

    # Handle the validated fields.
    for field in _UPDATABLE_FIELDS:
        if field in cleaned:
            models.update_session_field(conn, session_id, field, cleaned[field])
            updated_count += 1

    if updated_count == 0:
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            "No updatable fields provided. "
            "Allowed: session_type, track_state, driver_name, driver_id, "
            "track_id, kart_id, session_date, display_name, notes",
            status=400,
        )

    conn.commit()

    # Re-fetch and return the updated session (strip internal fields).
    updated = dict(models.get_session_by_id(conn, session_id))
    updated.pop("source_path", None)
    updated.pop("html_report_path", None)
    if updated.get("csv_filename"):
        updated["csv_filename"] = Path(updated["csv_filename"]).name
    return api_response(updated)


# ══════════════════════════════════════════════════════════════════
# 12b. POST /api/v1/sessions/<id>/archive
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/archive", methods=["POST"])
@_safe_api
def archive_session(session_id: str) -> tuple[dict, int]:
    """Toggle archive status on a session.

    JSON body: { "archived": true } or { "archived": false }
    Requires at least 'member' role.
    """
    workspace_role = getattr(g, "workspace_role", None)
    if workspace_role == "viewer":
        return api_error(ErrorCode.FORBIDDEN, "Insufficient permissions", status=403)

    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    body = request.get_json(silent=True) or {}
    archived = body.get("archived", True)
    if not isinstance(archived, bool):
        archived = str(archived).lower() in ("true", "1")

    models.update_session_field(conn, session_id, "archived", 1 if archived else 0)
    conn.commit()

    return api_response({"session_id": session_id, "archived": archived})


# ══════════════════════════════════════════════════════════════════
# 13. GET /api/v1/sessions/<id>/theoretical
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/theoretical", methods=["GET"])
@_safe_api
def get_theoretical(session_id: str) -> tuple[dict, int]:
    """Return theoretical lap data (simulation result)."""
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    theo = models.get_theoretical_data(conn, session_id)
    if theo is None:
        return api_response({
            "available": False,
            "reason_code": "no_theoretical_data",
            "message": "Theoretical lap not computed for this session",
        })

    return api_response({
        "theoretical_time_s": theo.get("theoretical_time_s"),
        "actual_best_time_s": theo.get("actual_best_time_s"),
        "gap_pct": theo.get("gap_pct"),
        "simulation_method": theo.get("simulation_method"),
        "speeds": theo.get("speeds", []),
        "distances": theo.get("distances", []),
        "metrics": theo.get("metrics", {}),
        "corner_coaching": theo.get("corner_coaching", []),
        "delta_map_summary": theo.get("delta_map_summary", []),
        "session_scalars": theo.get("session_scalars", {}),
    })


# ══════════════════════════════════════════════════════════════════
# 14. GET /api/v1/sessions/<id>/reference_line
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/reference_line", methods=["GET"])
@_safe_api
def get_reference_line(session_id: str) -> tuple[dict, int]:
    """Return the median reference racing line GPS coordinates."""
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    ref = models.get_reference_line(conn, session_id)
    if ref is None:
        return api_response({
            "available": False,
            "reason_code": "no_reference_line",
            "message": "Reference line not computed for this session",
        })

    return api_response(ref)


# ══════════════════════════════════════════════════════════════════
# 15. GET /api/v1/sessions/<id>/best_lap_gps
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/best_lap_gps", methods=["GET"])
@_safe_api
def get_best_lap_gps(session_id: str) -> tuple[dict, int]:
    """Return GPS trace for the best lap."""
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    lap_num = _resolve_lap_number(conn, session_id)
    if lap_num is None:
        return api_response({
            "available": False, "reason_code": "no_laps",
            "message": "No laps available for this session",
        })

    trace = models.get_gps_trace(conn, session_id, lap_num)
    if trace is None:
        return api_response({
            "available": False, "reason_code": "no_gps_trace",
            "message": f"No GPS trace for best lap {lap_num}",
        })

    return api_response({
        "latitudes": trace.get("latitudes", []),
        "longitudes": trace.get("longitudes", []),
        "distances": trace.get("distances", []),
        "speeds": trace.get("speeds", []),
        "lap_number": lap_num,
    })


# ══════════════════════════════════════════════════════════════════
# 16. GET /api/v1/sessions/<id>/corner-positions
# ══════════════════════════════════════════════════════════════════


def _closest_index(distances: list[float], target: float) -> int:
    """Binary search for closest distance index."""
    if not distances:
        return 0
    lo, hi = 0, len(distances) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if distances[mid] < target:
            lo = mid + 1
        else:
            hi = mid
    return lo


@bp.route("/sessions/<session_id>/corner-positions", methods=["GET"])
@_safe_api
def get_corner_positions(session_id: str) -> tuple[dict, int]:
    """Return corner GPS positions with brake point data."""
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    # Build corners from theoretical data
    theo = models.get_theoretical_data(conn, session_id)
    corners = []
    if theo and theo.get("corner_coaching"):
        seen = set()
        for cc in theo["corner_coaching"]:
            cid = cc.get("corner_id") or cc.get("corner_index")
            if cid is not None and cid not in seen:
                seen.add(cid)
                corners.append({
                    "corner_id": cid,
                    "s_start": cc.get("s_start") or cc.get("distance_start"),
                    "s_end": cc.get("s_end") or cc.get("distance_end"),
                    "s_apex": cc.get("s_apex") or cc.get("distance_apex"),
                    "direction": cc.get("direction"),
                    "label": cc.get("label") or cc.get("name"),
                    "lat": cc.get("lat"),
                    "lon": cc.get("lon"),
                    "brake_point_m": None,
                })

    if not corners:
        # Fall back to corner_metrics summary (unique corner_ids)
        summary = models.get_corner_metrics_summary(conn, session_id)
        for row in summary:
            corners.append({
                "corner_id": row["corner_id"],
                "s_start": None, "s_end": None, "s_apex": None,
                "direction": None, "label": None,
                "lat": None, "lon": None,
                "brake_point_m": row.get("avg_brake_point_m"),
            })

    if not corners:
        return api_error(ErrorCode.NOT_FOUND,
                         "No corner position data for this session", status=404)

    # Enrich with GPS coordinates from best lap trace
    best_lap = _resolve_lap_number(conn, session_id)
    best_gps = models.get_gps_trace(conn, session_id, best_lap) if best_lap else None

    if best_gps:
        dists = best_gps.get("distances", [])
        lats = best_gps.get("latitudes", [])
        lons = best_gps.get("longitudes", [])
        if dists and lats and lons:
            for corner in corners:
                apex_d = corner.get("s_apex")
                if apex_d is not None and corner.get("lat") is None:
                    idx = _closest_index(dists, apex_d)
                    if idx < len(lats):
                        corner["lat"] = lats[idx]
                        corner["lon"] = lons[idx]

    # Merge brake_point_m from corner_metrics summary
    cm_summary = models.get_corner_metrics_summary(conn, session_id)
    bp_map = {row["corner_id"]: row.get("avg_brake_point_m") for row in cm_summary}
    for corner in corners:
        if corner.get("brake_point_m") is None:
            corner["brake_point_m"] = bp_map.get(corner["corner_id"])

    return api_response({"corners": corners})


# ══════════════════════════════════════════════════════════════════
# 17. GET /api/v1/sessions/<id>/corner-metrics
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/corner-metrics", methods=["GET"])
@_safe_api
def get_corner_metrics(session_id: str) -> tuple[dict, int]:
    """Return per-lap, per-corner metrics from the corner_metrics table."""
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    metrics = models.get_corner_metrics_for_session(conn, session_id)

    return api_response({
        "corners": metrics or [],
        "available": bool(metrics),
    })


# ══════════════════════════════════════════════════════════════════
# 18. GET /api/v1/sessions/<id>/corner-metrics/summary
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/corner-metrics/summary", methods=["GET"])
@_safe_api
def get_corner_metrics_summary(session_id: str) -> tuple[dict, int]:
    """Return per-corner aggregate metrics."""
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    summary = models.get_corner_metrics_summary(conn, session_id)

    return api_response({
        "corners": summary or [],
        "available": bool(summary),
    })


# ══════════════════════════════════════════════════════════════════
# 19. GET /api/v1/sessions/<id>/delta?lap_a=X&lap_b=Y
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/delta", methods=["GET"])
@_safe_api
def get_delta(session_id: str) -> tuple[dict, int]:
    """Compute time delta between two laps on the fly."""
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    try:
        lap_a = int(request.args.get("lap_a", 0))
        lap_b = int(request.args.get("lap_b", 0))
    except (ValueError, TypeError):
        return api_error(ErrorCode.VALIDATION_ERROR,
                         "lap_a and lap_b must be integers", status=400)

    if lap_a == 0 or lap_b == 0:
        return api_error(ErrorCode.VALIDATION_ERROR,
                         "Both lap_a and lap_b are required", status=400)

    trace_a = models.get_gps_trace(conn, session_id, lap_a)
    trace_b = models.get_gps_trace(conn, session_id, lap_b)

    if trace_a is None or trace_b is None:
        return api_response({
            "available": False, "reason_code": "no_gps_trace",
            "message": "GPS trace not found for one or both laps",
        })

    # Compute cumulative time from distance and speed for each lap
    def _cumulative_time(distances: list[float], speeds: list[float]) -> list[float]:
        """Build cumulative time array from distance/speed arrays."""
        t = [0.0]
        for i in range(1, len(distances)):
            ds = distances[i] - distances[i - 1]
            v = speeds[i] if speeds[i] and speeds[i] > 0 else speeds[i - 1]
            if v and v > 0:
                t.append(t[-1] + ds / v)
            else:
                t.append(t[-1])
        return t

    dist_a = trace_a.get("distances", [])
    spd_a = trace_a.get("speeds", [])
    dist_b = trace_b.get("distances", [])
    spd_b = trace_b.get("speeds", [])

    if not dist_a or not spd_a or not dist_b or not spd_b:
        return api_response({
            "available": False, "reason_code": "insufficient_trace_data",
            "message": "Insufficient trace data for delta computation",
        })

    time_a = _cumulative_time(dist_a, spd_a)
    time_b = _cumulative_time(dist_b, spd_b)

    # Interpolate to common distance axis (use shorter lap)
    import numpy as np
    max_dist = min(dist_a[-1] if dist_a else 0, dist_b[-1] if dist_b else 0)
    if max_dist <= 0:
        return api_response({
            "available": False, "reason_code": "no_valid_distance",
            "message": "No valid distance range for delta",
        })

    common_dist = np.linspace(0, max_dist, min(500, len(dist_a)))
    interp_a = np.interp(common_dist, dist_a, time_a)
    interp_b = np.interp(common_dist, dist_b, time_b)
    delta = (interp_b - interp_a).tolist()

    return api_response({
        "distances": common_dist.tolist(),
        "delta_s": delta,
        "lap_a": lap_a,
        "lap_b": lap_b,
    })


# ══════════════════════════════════════════════════════════════════
# 20. GET /api/v1/sessions/<id>/fingerprint
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/fingerprint", methods=["GET"])
@_safe_api
def get_fingerprint(session_id: str) -> tuple[dict, int]:
    """Build a 6-dimension performance radar from scores + driving style."""
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    scores = models.get_score_details(conn, session_id)
    if scores is None:
        return api_response({
            "available": False,
            "reason_code": "no_score_data",
            "message": "No score data for fingerprint",
        })

    # Normalize each score to percentage of its max
    def _pct(val: float | None, mx: float | None) -> float:
        if val is None or mx is None or mx == 0:
            return 0
        return round(min(val / mx * 100, 100), 1)

    pace = _pct(scores.get("pace_score"), scores.get("pace_max"))
    consistency = _pct(scores.get("consistency_score"),
                       scores.get("consistency_max"))
    execution = _pct(scores.get("execution_score"),
                     scores.get("execution_max"))
    robustness = _pct(scores.get("robustness_score"),
                      scores.get("robustness_max"))

    # Try to get smoothness/aggression from driving style
    smoothness = 50.0
    aggression = 50.0
    style_label = None
    driver_id = session.get("driver_id")
    if driver_id:
        style = models.get_driving_style(conn, driver_id, session_id)
        if style:
            style_label = style.get("style_label")
            sm = style.get("smoothness_composite")
            ag = style.get("turn_in_aggressiveness")
            if sm is not None:
                smoothness = round(min(max(sm * 100, 0), 100), 1)
            if ag is not None:
                aggression = round(min(max(ag * 100, 0), 100), 1)

    dimensions = ["Pace", "Consistency", "Execution",
                   "Robustness", "Smoothness", "Aggression"]
    values = [pace, consistency, execution, robustness, smoothness, aggression]

    return api_response({
        "dimensions": dimensions,
        "values": values,
        "style_label": style_label,
    })


# ══════════════════════════════════════════════════════════════════
# 21. GET /api/v1/sessions/<id>/driving-style
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/driving-style", methods=["GET"])
@_safe_api
def get_driving_style(session_id: str) -> tuple[dict, int]:
    """Return driving style features for this session."""
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    driver_id = session.get("driver_id")
    if not driver_id:
        return api_response({
            "available": False,
            "reason_code": "no_driver_linked",
            "message": "No driver linked to this session",
        })

    style = models.get_driving_style(conn, driver_id, session_id)
    if style is None:
        return api_response({
            "available": False,
            "reason_code": "no_driving_style",
            "message": "Driving style not computed for this session",
        })

    # Build features list for frontend
    feature_keys = [
        "trail_braking_depth", "brake_point_consistency",
        "brake_pressure_buildup_rate", "apex_speed_ratio",
        "turn_in_aggressiveness", "throttle_onset_delay_m",
        "exit_acceleration_efficiency", "line_variation_index",
        "early_vs_late_stint_pace", "smoothness_composite",
    ]
    features = []
    for key in feature_keys:
        val = style.get(key)
        if val is not None:
            features.append({"name": key, "value": val})

    return api_response({
        "style_label": style.get("style_label"),
        "style_confidence": style.get("style_confidence"),
        "features": features,
        "strengths": style.get("strengths", []),
        "weaknesses": style.get("weaknesses", []),
    })


# ══════════════════════════════════════════════════════════════════
# 22. GET /api/v1/sessions/<id>/lap-distribution
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/lap-distribution", methods=["GET"])
@_safe_api
def get_lap_distribution(session_id: str) -> tuple[dict, int]:
    """Compute lap time distribution histogram on the fly."""
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    laps = models.get_laps_for_session(conn, session_id)
    valid_times = [
        lp["lap_time_s"] for lp in laps
        if lp.get("lap_time_s") and lp["lap_time_s"] > 0
        and lp.get("is_valid", 1)
    ]

    if not valid_times:
        return api_response({
            "available": False,
            "reason_code": "no_valid_lap_times",
            "message": "No valid lap times for distribution",
        })

    import numpy as np
    arr = np.array(valid_times)
    n_bins = min(10, len(valid_times))
    counts, bin_edges = np.histogram(arr, bins=n_bins)

    return api_response({
        "bins": bin_edges.tolist(),
        "counts": counts.tolist(),
        "mean": round(float(np.mean(arr)), 3),
        "median": round(float(np.median(arr)), 3),
        "std": round(float(np.std(arr)), 3),
        "q1": round(float(np.percentile(arr, 25)), 3),
        "q3": round(float(np.percentile(arr, 75)), 3),
        "n_valid": len(valid_times),
    })


# ══════════════════════════════════════════════════════════════════
# 23. GET /api/v1/sessions/<id>/lap-progress
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/lap-progress", methods=["GET"])
@_safe_api
def get_lap_progress(session_id: str) -> tuple[dict, int]:
    """Lap times in order with rolling average and trend."""
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    laps = models.get_laps_for_session(conn, session_id)
    # Only include valid laps with times
    valid = [
        lp for lp in laps
        if lp.get("lap_time_s") and lp["lap_time_s"] > 0
        and lp.get("is_valid", 1)
    ]

    if not valid:
        return api_response({
            "available": False,
            "reason_code": "no_valid_lap_times",
            "message": "No valid lap times for progress",
        })

    import numpy as np
    lap_numbers = [lp["lap_number"] for lp in valid]
    times = [lp["lap_time_s"] for lp in valid]

    # Rolling average (window=3 or fewer)
    window = min(3, len(times))
    rolling = []
    for i in range(len(times)):
        start = max(0, i - window + 1)
        rolling.append(round(sum(times[start:i + 1]) / (i - start + 1), 3))

    # Linear trend
    trend_slope = 0.0
    is_improving = False
    if len(times) >= 2:
        coeffs = np.polyfit(range(len(times)), times, 1)
        trend_slope = round(float(coeffs[0]), 4)
        is_improving = trend_slope < 0

    return api_response({
        "lap_numbers": lap_numbers,
        "times": times,
        "rolling_avg": rolling,
        "trend_slope": trend_slope,
        "is_improving": is_improving,
    })


# ══════════════════════════════════════════════════════════════════
# 24. GET /api/v1/sessions/<id>/speed-profile
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/speed-profile", methods=["GET"])
@_safe_api
def get_speed_profile(session_id: str) -> tuple[dict, int]:
    """Best-lap actual speed vs theoretical speed over distance."""
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    # Get best lap GPS trace
    lap_num = _resolve_lap_number(conn, session_id)
    if lap_num is None:
        return api_response({
            "available": False,
            "reason_code": "no_laps",
            "message": "No laps available",
        })

    trace = models.get_gps_trace(conn, session_id, lap_num)
    if trace is None:
        return api_response({
            "available": False,
            "reason_code": "no_gps_trace",
            "message": f"No trace for lap {lap_num}",
        })

    distances = trace.get("distances", [])
    # Convert m/s to km/h for frontend
    speeds_mps = trace.get("speeds", [])
    actual_kmh = [round(s * 3.6, 1) if s else 0 for s in speeds_mps]

    # Get theoretical speeds
    theo = models.get_theoretical_data(conn, session_id)
    theo_kmh = []
    speed_delta_kmh = []
    if theo and theo.get("speeds"):
        import numpy as np
        theo_speeds = theo["speeds"]
        theo_dists = theo.get("distances", [])
        if theo_dists and len(theo_speeds) == len(theo_dists):
            # Interpolate theoretical onto actual distance axis
            interp_theo = np.interp(distances, theo_dists, theo_speeds)
            theo_kmh = [round(s * 3.6, 1) for s in interp_theo]
            speed_delta_kmh = [
                round(a - t, 1) for a, t in zip(actual_kmh, theo_kmh)
            ]
        else:
            theo_kmh = [round(s * 3.6, 1) if s else 0 for s in theo_speeds]

    return api_response({
        "distances": distances,
        "actual_speeds_kmh": actual_kmh,
        "theoretical_speeds_kmh": theo_kmh,
        "speed_delta_kmh": speed_delta_kmh,
        "lap_number": lap_num,
    })


# ══════════════════════════════════════════════════════════════════
# 25. GET /api/v1/sessions/<id>/brake-precision
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/brake-precision", methods=["GET"])
@_safe_api
def get_brake_precision(session_id: str) -> tuple[dict, int]:
    """Per-corner brake point consistency from corner_metrics."""
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    metrics = models.get_corner_metrics_for_session(conn, session_id)
    if not metrics:
        return api_response({
            "corners": [],
            "available": False,
            "reason_code": "no_corner_metrics",
        })

    # Group by corner_id, collect brake points
    from collections import defaultdict

    import numpy as np
    by_corner = defaultdict(list)
    for m in metrics:
        bp_m = m.get("brake_point_m")
        if bp_m is not None:
            by_corner[m["corner_id"]].append(bp_m)

    corners = []
    for cid in sorted(by_corner):
        pts = by_corner[cid]
        arr = np.array(pts)
        mean_m = round(float(np.mean(arr)), 2)
        std_m = round(float(np.std(arr)), 2)
        cv_pct = round(std_m / mean_m * 100, 1) if mean_m > 0 else 0
        corners.append({
            "corner_id": cid,
            "brake_points": pts,
            "mean_m": mean_m,
            "std_m": std_m,
            "cv_pct": cv_pct,
        })

    return api_response({"corners": corners})


# ══════════════════════════════════════════════════════════════════
# 26. GET /api/v1/sessions/<id>/stint-analysis
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/stint-analysis", methods=["GET"])
@_safe_api
def get_stint_analysis(session_id: str) -> tuple[dict, int]:
    """Return stint breakdown from the stint_analysis table."""
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    stints = models.get_stint_analysis(conn, session_id)
    if stints:
        return api_response({"stints": stints})

    # Fall back to analysis_json robustness_metrics
    analysis = models.get_analysis_json(conn, session_id)
    if analysis and analysis.get("robustness_metrics"):
        return api_response({
            "stints": [],
            "robustness_metrics": analysis["robustness_metrics"],
        })

    return api_response({
        "available": False, "reason_code": "no_stint_analysis",
        "message": "No stint analysis for this session",
        "stints": [],
    })


# ══════════════════════════════════════════════════════════════════
# 27. GET /api/v1/sessions/<id>/sector_times
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/sector_times", methods=["GET"])
@_safe_api
def get_sector_times(session_id: str) -> tuple[dict, int]:
    """Return sector analysis from analysis_json."""
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    analysis = models.get_analysis_json(conn, session_id)
    if analysis and analysis.get("sector_analysis"):
        result = analysis["sector_analysis"]
        if isinstance(result, dict):
            result["available"] = True
        return api_response(result)

    # If no pre-computed sector analysis, try computing on the fly
    laps = models.get_laps_for_session(conn, session_id)
    valid_times = [
        lp["lap_time_s"] for lp in laps
        if lp.get("lap_time_s") and lp["lap_time_s"] > 0
        and lp.get("is_valid", 1)
    ]

    if len(valid_times) >= 3:
        try:
            from sector_analysis import analyze_sector_performance
            result = analyze_sector_performance(valid_times)
            return api_response(result.to_dict())
        except Exception:
            pass

    return api_response({
        "available": False,
        "reason_code": "NO_SECTOR_DATA",
        "message": "Sector analysis not available for this session",
    })


# ══════════════════════════════════════════════════════════════════
# 28. GET /api/v1/sessions/<id>/track-map?lap=best|all
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/track-map", methods=["GET"])
@_safe_api
def get_track_map(session_id: str) -> tuple[dict, int]:
    """Return bundled GPS data for track map rendering.

    Query params:
        lap: "best" (default) or "all"
    """
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    best_lap = _resolve_lap_number(conn, session_id)
    if best_lap is None:
        return api_response({
            "available": False,
            "reason_code": "no_laps",
            "message": "No laps available",
        })

    lap_mode = request.args.get("lap", "best")

    # Determine which laps to include
    if lap_mode == "all":
        lap_numbers = models.get_gps_lap_numbers(conn, session_id)
    else:
        lap_numbers = [best_lap]

    # Fetch GPS data for each lap
    laps_data = {}
    for ln in lap_numbers:
        trace = models.get_gps_trace(conn, session_id, ln)
        if trace:
            laps_data[str(ln)] = {
                "latitudes": trace.get("latitudes", []),
                "longitudes": trace.get("longitudes", []),
                "distances": trace.get("distances", []),
                "speeds": trace.get("speeds", []),
            }

    if not laps_data:
        return api_response({
            "available": False,
            "reason_code": "no_gps_data",
            "message": "No GPS data available for any laps",
        })

    # Build corners with GPS coords
    corners = []
    theo = models.get_theoretical_data(conn, session_id)
    if theo and theo.get("corner_coaching"):
        best_gps = models.get_gps_trace(conn, session_id, best_lap)
        dists = best_gps.get("distances", []) if best_gps else []
        lats = best_gps.get("latitudes", []) if best_gps else []
        lons = best_gps.get("longitudes", []) if best_gps else []

        seen = set()
        for cc in theo["corner_coaching"]:
            cid = cc.get("corner_id") or cc.get("corner_index")
            if cid is not None and cid not in seen:
                seen.add(cid)
                apex_d = cc.get("s_apex") or cc.get("distance_apex")
                lat = cc.get("lat")
                lon = cc.get("lon")
                if lat is None and apex_d is not None and dists:
                    idx = _closest_index(dists, apex_d)
                    if idx < len(lats):
                        lat = lats[idx]
                        lon = lons[idx]
                corners.append({
                    "corner_id": cid,
                    "lat": lat,
                    "lon": lon,
                    "label": cc.get("label") or cc.get("name"),
                    "distance_m": apex_d,
                })

    return api_response({
        "laps": laps_data,
        "best_lap": best_lap,
        "corners": corners,
    })


# ══════════════════════════════════════════════════════════════════
# 29. GET /api/v1/sessions/<id>/sectors (alias)
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/sectors", methods=["GET"])
@_safe_api
def get_sectors(session_id: str) -> tuple[dict, int]:
    """Alias for sector_times — returns sector analysis."""
    return get_sector_times(session_id)


# ══════════════════════════════════════════════════════════════════
# 30. GET /api/v1/sessions/<id>/compare?sessionKeyB=...
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/compare", methods=["GET"])
@_safe_api
def get_session_compare_overlay(session_id: str) -> tuple[dict, int]:
    """Cross-session overlay with distance-aligned speed traces."""
    conn = get_db_connection()
    session_a = models.get_session_by_id(conn, session_id)
    if session_a is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    session_b_id = request.args.get("sessionKeyB")
    if not session_b_id:
        return api_error(ErrorCode.VALIDATION_ERROR,
                         "sessionKeyB parameter is required", status=400)

    session_b = models.get_session_by_id(conn, session_b_id)
    if session_b is None:
        return api_error(ErrorCode.NOT_FOUND,
                         f"Session {session_b_id} not found", status=404)

    # Get best lap traces for both sessions
    best_a = _resolve_lap_number(conn, session_id)
    best_b = _resolve_lap_number(conn, session_b_id)

    if best_a is None or best_b is None:
        return api_error(ErrorCode.NOT_FOUND, "No laps in one or both sessions",
                         status=404)

    trace_a = models.get_gps_trace(conn, session_id, best_a)
    trace_b = models.get_gps_trace(conn, session_b_id, best_b)

    if trace_a is None or trace_b is None:
        return api_error(ErrorCode.NOT_FOUND,
                         "No GPS trace for one or both sessions", status=404)

    import numpy as np

    dist_a = trace_a.get("distances", [])
    spd_a = trace_a.get("speeds", [])
    dist_b = trace_b.get("distances", [])
    spd_b = trace_b.get("speeds", [])

    if not dist_a or not spd_a or not dist_b or not spd_b:
        return api_error(ErrorCode.NOT_FOUND,
                         "Insufficient trace data for comparison", status=404)

    # Common distance axis (shorter lap's range, up to 500 points)
    max_dist = min(dist_a[-1], dist_b[-1])
    if max_dist <= 0:
        return api_error(ErrorCode.NOT_FOUND,
                         "No valid distance range for comparison", status=404)

    n_points = min(500, min(len(dist_a), len(dist_b)))
    common_dist = np.linspace(0, max_dist, n_points)
    interp_a = np.interp(common_dist, dist_a, spd_a)
    interp_b = np.interp(common_dist, dist_b, spd_b)

    # Cumulative time delta
    def _cum_time(dists: list[float], speeds: list[float]) -> list[float]:
        t = [0.0]
        for i in range(1, len(dists)):
            ds = dists[i] - dists[i - 1]
            v = speeds[i] if speeds[i] > 0 else speeds[i - 1]
            t.append(t[-1] + (ds / v if v > 0 else 0))
        return t

    time_a = _cum_time(common_dist.tolist(), interp_a.tolist())
    time_b = _cum_time(common_dist.tolist(), interp_b.tolist())
    delta = [round(b - a, 4) for a, b in zip(time_a, time_b)]

    return api_response({
        "distances": common_dist.tolist(),
        "speeds_a": interp_a.tolist(),
        "speeds_b": interp_b.tolist(),
        "delta_s": delta,
        "session_a": {
            "session_id": session_id,
            "best_time_s": session_a.get("best_lap_time_s"),
            "lap_number": best_a,
        },
        "session_b": {
            "session_id": session_b_id,
            "best_time_s": session_b.get("best_lap_time_s"),
            "lap_number": best_b,
        },
        "gps_a": {
            "latitudes": trace_a.get("latitudes", []),
            "longitudes": trace_a.get("longitudes", []),
        },
        "gps_b": {
            "latitudes": trace_b.get("latitudes", []),
            "longitudes": trace_b.get("longitudes", []),
        },
    })


# ══════════════════════════════════════════════════════════════════
# 31. GET /api/v1/sessions/<id>/compare/sectors?sessionKeyB=...
# ══════════════════════════════════════════════════════════════════


def _safe_float(val: Any, default: float | None = None) -> float | None:
    """Return float(val) rounded to 4 decimal places, or *default* if val is None/NaN."""
    if val is None:
        return default
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return default
        return round(f, 4)
    except (TypeError, ValueError):
        return default


def _build_corner_comparison(summary_a: list[dict], summary_b: list[dict]) -> list[dict]:
    """Align two corner-metrics-summary lists by corner_id and compute deltas.

    Corners are matched by index position (both lists are ORDER BY corner_id).
    If one session has more corners than the other, extra corners are dropped.
    """
    n = min(len(summary_a), len(summary_b))
    corners = []
    for i in range(n):
        ca = summary_a[i]
        cb = summary_b[i]

        time_a = _safe_float(ca.get("avg_time_loss_ms"))
        time_b = _safe_float(cb.get("avg_time_loss_ms"))
        # Delta: positive means B is slower (lost more time)
        delta = None
        if time_a is not None and time_b is not None:
            delta = round(time_b - time_a, 4)

        min_speed_a = _safe_float(ca.get("avg_apex_speed"))
        min_speed_b = _safe_float(cb.get("avg_apex_speed"))
        entry_speed_a = _safe_float(ca.get("avg_entry_speed"))
        entry_speed_b = _safe_float(cb.get("avg_entry_speed"))
        exit_speed_a = _safe_float(ca.get("avg_exit_speed"))
        exit_speed_b = _safe_float(cb.get("avg_exit_speed"))

        corners.append({
            "corner_id": ca.get("corner_id", i + 1),
            "name": f"Corner {ca.get('corner_id', i + 1)}",
            "time_a": time_a,
            "time_b": time_b,
            "delta": delta,
            "min_speed_a": min_speed_a,
            "min_speed_b": min_speed_b,
            "entry_speed_a": entry_speed_a,
            "entry_speed_b": entry_speed_b,
            "exit_speed_a": exit_speed_a,
            "exit_speed_b": exit_speed_b,
        })
    return corners


def _build_sector_comparison(corner_list: list[dict], corners_per_sector: int = 3) -> list[dict]:
    """Group consecutive corners into sectors and aggregate timing deltas.

    Each sector spans *corners_per_sector* corners (the last sector may have
    fewer).  Sector times are the sum of per-corner ``time_a`` / ``time_b``
    values.  If any corner in a sector has a ``None`` time, that sector's
    aggregate is also ``None``.
    """
    if not corner_list:
        return []

    sectors = []
    for start in range(0, len(corner_list), corners_per_sector):
        chunk = corner_list[start:start + corners_per_sector]
        sector_id = (start // corners_per_sector) + 1

        sum_a = 0.0
        sum_b = 0.0
        all_valid = True
        for c in chunk:
            if c.get("time_a") is None or c.get("time_b") is None:
                all_valid = False
                break
            sum_a += c["time_a"]
            sum_b += c["time_b"]

        if all_valid:
            sectors.append({
                "sector_id": sector_id,
                "name": f"Sector {sector_id}",
                "time_a": round(sum_a, 4),
                "time_b": round(sum_b, 4),
                "delta": round(sum_b - sum_a, 4),
            })
        else:
            sectors.append({
                "sector_id": sector_id,
                "name": f"Sector {sector_id}",
                "time_a": None,
                "time_b": None,
                "delta": None,
            })

    return sectors


@bp.route("/sessions/<session_id>/compare/sectors", methods=["GET"])
@_safe_api
def get_session_compare_sectors(session_id: str) -> tuple[dict, int]:
    """Compare sector and corner timing between two sessions.

    Query params:
        sessionKeyB  (required) — session_id of the second session.

    Corner data comes from ``corner_metrics_summary`` (aggregated per-corner
    averages across all laps for each session).  Sectors are synthesised by
    grouping consecutive corners (3 per sector by default).
    """
    conn = get_db_connection()

    # -- Validate session A ---------------------------------------------------
    session_a = models.get_session_by_id(conn, session_id)
    if session_a is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    # -- Validate session B ---------------------------------------------------
    session_b_id = request.args.get("sessionKeyB")
    if not session_b_id:
        return api_error(ErrorCode.VALIDATION_ERROR,
                         "sessionKeyB parameter is required", status=400)

    session_b = models.get_session_by_id(conn, session_b_id)
    if session_b is None:
        return api_error(ErrorCode.NOT_FOUND,
                         f"Session {session_b_id} not found", status=404)

    # -- Fetch corner summaries for both sessions -----------------------------
    summary_a = models.get_corner_metrics_summary(conn, session_id)
    summary_b = models.get_corner_metrics_summary(conn, session_b_id)

    # If either session has no corner data, return empty (not an error)
    if not summary_a or not summary_b:
        return api_response({
            "sectors": [],
            "corners": [],
            "session_a": {"session_id": session_id},
            "session_b": {"session_id": session_b_id},
            "available": not summary_a and not summary_b,
            "reason_code": "NO_CORNER_DATA",
            "message": "Corner metrics not available for one or both sessions",
        })

    # -- Build corner comparison ----------------------------------------------
    corners = _build_corner_comparison(summary_a, summary_b)

    # -- Build sector comparison (group by 3 corners) -------------------------
    sectors = _build_sector_comparison(corners, corners_per_sector=3)

    return api_response({
        "sectors": sectors,
        "corners": corners,
        "session_a": {
            "session_id": session_id,
            "best_time_s": session_a.get("best_lap_time_s"),
        },
        "session_b": {
            "session_id": session_b_id,
            "best_time_s": session_b.get("best_lap_time_s"),
        },
    })


# ══════════════════════════════════════════════════════════════════
# 25. GET /api/v1/sessions/<id>/corner-replay-data
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/corner-replay-data", methods=["GET"])
@_safe_api
def get_corner_replay_data(session_id: str) -> tuple[dict, int]:
    """Batch endpoint for corner replay — traces, positions, metrics, lap times."""
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    # Parse requested laps (comma-separated)
    laps_param = request.args.get("laps", "")
    requested_laps = []
    if laps_param:
        try:
            requested_laps = [int(x.strip()) for x in laps_param.split(",") if x.strip()]
        except ValueError:
            return api_error(ErrorCode.VALIDATION_ERROR,
                             "laps must be comma-separated integers", status=400)

    # If no laps specified, use all available (up to 5)
    if not requested_laps:
        all_laps = models.get_laps_for_session(conn, session_id) or []
        requested_laps = [lap["lap_number"] for lap in all_laps[:5]]

    # Fetch GPS traces for each requested lap
    traces = {}
    lap_times = {}
    has_pedal_data = False
    has_steering_data = False

    all_laps_data = models.get_laps_for_session(conn, session_id) or []
    for lap_info in all_laps_data:
        ln = lap_info.get("lap_number")
        if ln is not None:
            lt = lap_info.get("lap_time_s")
            if lt is not None:
                lap_times[str(ln)] = lt

    for lap_num in requested_laps:
        trace = models.get_gps_trace(conn, session_id, lap_num)
        if trace is None:
            continue

        lats = trace.get("latitudes", [])
        lons = trace.get("longitudes", [])
        speeds = trace.get("speeds", [])
        distances = trace.get("distances", [])
        accel_lat = trace.get("accel_lat", [])
        accel_long = trace.get("accel_long", [])
        brake = trace.get("brake", [])
        throttle = trace.get("throttle", [])
        steering = trace.get("steering", [])

        n = len(lats)
        points = []
        for i in range(n):
            pt = {
                "lat": lats[i] if i < len(lats) else None,
                "lon": lons[i] if i < len(lons) else None,
                "speed": speeds[i] if i < len(speeds) else 0,
                "distance": distances[i] if i < len(distances) else 0,
            }
            if i < len(accel_lat):
                pt["accel_lat"] = accel_lat[i]
            if i < len(accel_long):
                pt["accel_long"] = accel_long[i]
            if brake and i < len(brake):
                pt["brake"] = brake[i]
                has_pedal_data = True
            if throttle and i < len(throttle):
                pt["throttle"] = throttle[i]
                has_pedal_data = True
            if steering and i < len(steering):
                pt["steering"] = steering[i]
                has_steering_data = True
            points.append(pt)

        traces[str(lap_num)] = points

    if not traces:
        return api_response({
            "available": False,
            "reason_code": "NO_REPLAY_DATA",
            "message": "No GPS trace data available for replay",
        })

    # Corner positions
    corner_positions = []
    try:
        cp_data = models.get_corner_positions(conn, session_id)
        if cp_data:
            corner_positions = cp_data
    except Exception:
        logger.warning("Failed to get corner positions for %s", session_id, exc_info=True)

    # Corner metrics summary
    corner_metrics = {}
    try:
        cm_data = models.get_corner_metrics_for_session(conn, session_id)
        if cm_data:
            corner_metrics = cm_data
    except Exception:
        logger.warning("Failed to get corner metrics for %s", session_id, exc_info=True)

    # Best lap
    best_lap_num = None
    best_time = float("inf")
    for ln_str, lt in lap_times.items():
        if lt < best_time:
            best_time = lt
            best_lap_num = int(ln_str)

    return api_response({
        "traces": traces,
        "corner_positions": corner_positions,
        "corner_metrics": corner_metrics,
        "lap_times": lap_times,
        "best_lap_number": best_lap_num,
        "has_pedal_data": has_pedal_data,
        "has_steering_data": has_steering_data,
        "available": True,
    })


# ══════════════════════════════════════════════════════════════════
# 26. GET /api/v1/sessions/<id>/corner-mastery
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/corner-mastery", methods=["GET"])
@_safe_api
def get_corner_mastery(session_id: str) -> tuple[dict, int]:
    """Return corner mastery report card with per-corner scoring."""
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    # Get per-corner metrics grouped by corner_id
    metrics = models.get_corner_metrics_for_session(conn, session_id)
    if not metrics:
        return api_response({
            "available": False,
            "reason_code": "NO_CORNER_METRICS",
            "message": "Corner metrics not available for mastery scoring",
        })

    try:
        from corner_mastery import compute_corner_mastery, generate_corner_report_card

        # Group metrics by corner_id
        metrics_by_corner: dict[int, list[dict]] = {}
        if isinstance(metrics, list):
            for m in metrics:
                cid = m.get("corner_id")
                if cid is not None:
                    metrics_by_corner.setdefault(cid, []).append(m)
        elif isinstance(metrics, dict):
            metrics_by_corner = metrics

        mastery_results = compute_corner_mastery(metrics_by_corner)
        report = generate_corner_report_card(mastery_results)
        report["available"] = True
        return api_response(report)
    except Exception:
        logger.warning("Corner mastery scoring failed for %s", session_id, exc_info=True)
        return api_response({
            "available": False,
            "reason_code": "MASTERY_FAILED",
            "message": "Corner mastery analysis could not be computed",
        })


# ══════════════════════════════════════════════════════════════════
# 34. GET /api/v1/sessions/<id>/condition-phases
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/condition-phases", methods=["GET"])
@_safe_api
def get_condition_phases(session_id: str) -> tuple[dict, int]:
    """Return condition phase breakdown for a session."""
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    phases = models.get_condition_phases(conn, session_id)
    if not phases:
        return api_response({
            "available": False,
            "reason_code": "no_condition_phases",
            "message": "No condition phase data for this session",
            "phases": [],
        })

    return api_response({"phases": phases})


# ══════════════════════════════════════════════════════════════════
# 38. GET /api/v1/sessions/<id>/throttle-onset
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/throttle-onset", methods=["GET"])
@_safe_api
def get_throttle_onset(session_id: str) -> tuple[dict, int]:
    """Per-corner throttle onset distance from corner_metrics."""
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    metrics = models.get_corner_metrics_for_session(conn, session_id)
    if not metrics:
        return api_response({
            "corners": [],
            "available": False,
            "reason_code": "no_corner_metrics",
        })

    from collections import defaultdict

    import numpy as np
    by_corner: dict = defaultdict(list)
    for m in metrics:
        onset = m.get("throttle_onset_m")
        if onset is not None:
            by_corner[m["corner_id"]].append(float(onset))

    if not by_corner:
        return api_response({
            "corners": [],
            "available": False,
            "reason_code": "no_throttle_data",
        })

    corners = []
    for cid in sorted(by_corner):
        pts = by_corner[cid]
        arr = np.array(pts)
        mean_m = round(float(np.mean(arr)), 2)
        std_m = round(float(np.std(arr)), 2)
        corners.append({
            "corner_id": cid,
            "onset_points": [round(p, 2) for p in pts],
            "mean_m": mean_m,
            "std_m": std_m,
            "n_laps": len(pts),
        })

    return api_response({"corners": corners, "available": True})


# ══════════════════════════════════════════════════════════════════
# 39. GET /api/v1/sessions/<id>/consistency-heatmap
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/consistency-heatmap", methods=["GET"])
@_safe_api
def get_consistency_heatmap(session_id: str) -> tuple[dict, int]:
    """Laps x corners consistency heatmap from corner_metrics."""
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    metrics = models.get_corner_metrics_for_session(conn, session_id)
    if not metrics:
        return api_response({
            "available": False,
            "reason_code": "no_corner_metrics",
            "laps": [],
            "corners": [],
            "values": [],
        })

    # Build lap -> corner -> time_loss_ms mapping
    from collections import defaultdict
    lap_corners: dict = defaultdict(dict)
    all_corners: set = set()
    all_laps: set = set()
    for m in metrics:
        lap = m.get("lap_number")
        cid = m.get("corner_id")
        loss = m.get("time_loss_ms")
        if lap is not None and cid is not None:
            all_laps.add(lap)
            all_corners.add(cid)
            if loss is not None:
                lap_corners[lap][cid] = round(float(loss), 1)

    if not all_corners or not all_laps:
        return api_response({
            "available": False,
            "reason_code": "no_corner_metrics",
            "laps": [],
            "corners": [],
            "values": [],
        })

    laps_sorted = sorted(all_laps)
    corners_sorted = sorted(all_corners)

    # Build 2D array: values[lap_idx][corner_idx] = time_loss_ms or None
    values = []
    for lap in laps_sorted:
        row = []
        for cid in corners_sorted:
            row.append(lap_corners.get(lap, {}).get(cid))
        values.append(row)

    # Per-corner stats
    import numpy as np
    corner_stats = []
    for ci, cid in enumerate(corners_sorted):
        col_vals = [values[li][ci] for li in range(len(laps_sorted))
                    if values[li][ci] is not None]
        if col_vals:
            arr = np.array(col_vals)
            corner_stats.append({
                "corner_id": cid,
                "mean_ms": round(float(np.mean(arr)), 1),
                "std_ms": round(float(np.std(arr)), 1),
                "max_ms": round(float(np.max(arr)), 1),
            })
        else:
            corner_stats.append({
                "corner_id": cid,
                "mean_ms": None,
                "std_ms": None,
                "max_ms": None,
            })

    return api_response({
        "available": True,
        "laps": laps_sorted,
        "corners": corners_sorted,
        "values": values,
        "corner_stats": corner_stats,
    })


# ══════════════════════════════════════════════════════════════════
# 40. GET /api/v1/sessions/<id>/timeline — Session event timeline
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/timeline", methods=["GET"])
@_safe_api
def get_session_timeline(session_id: str) -> tuple[dict, int]:
    """Return the session replay timeline — a narrative event feed."""
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    laps = models.get_laps_for_session(conn, session_id)

    from session_replay import build_session_timeline
    tl = build_session_timeline(
        laps,
        session_info={
            "session_id": session_id,
            "driver_name": session.get("driver_name", ""),
        },
    )
    return api_response(tl.to_dict())


# ══════════════════════════════════════════════════════════════════
# 40. GET /api/v1/sessions/<id>/sector-analysis  (alias)
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/sector-analysis", methods=["GET"])
@_safe_api
def get_sector_analysis(session_id: str) -> tuple[dict, int]:
    """Alias for sector_times — desktop tool vanilla JS uses this path."""
    return get_sector_times(session_id)


# ══════════════════════════════════════════════════════════════════
# 41. GET /api/v1/sessions/<id>/comparison-matrix
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/comparison-matrix", methods=["GET"])
@_safe_api
def get_comparison_matrix(session_id: str) -> tuple[dict, int]:
    """Return a multi-session comparison matrix for the same track.

    Finds recent sessions on the same track, computes pairwise deltas
    for key metrics (best lap, mean lap, consistency), and returns
    structured data for the comparison_matrix.js visualisation.
    """
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    track_id = session.get("track_id")
    if not track_id:
        return api_response({
            "sessions": [],
            "pairwise": [],
            "best_per_metric": {},
            "metric_labels": {},
            "lower_is_better": [],
            "focus_session_id": session_id,
        })

    # Fetch other sessions on the same track (limit 10 most recent)
    all_sessions = models.get_sessions(conn, limit=50, offset=0)
    same_track = [
        s for s in all_sessions
        if s.get("track_id") == track_id and s.get("session_id")
    ]
    # Sort by date descending, take top 10
    same_track.sort(key=lambda s: s.get("session_date", ""), reverse=True)
    same_track = same_track[:10]

    if len(same_track) < 2:
        return api_response({
            "sessions": [],
            "pairwise": [],
            "best_per_metric": {},
            "metric_labels": {},
            "lower_is_better": [],
            "focus_session_id": session_id,
        })

    # Build session summaries with lap stats
    summaries = []
    for s in same_track:
        sid = s["session_id"]
        laps = models.get_laps_for_session(conn, sid)
        valid = [
            lp["lap_time_s"] for lp in laps
            if lp.get("lap_time_s") and lp["lap_time_s"] > 0
            and lp.get("is_valid", 1)
        ]
        best_t = min(valid) if valid else 0
        mean_t = sum(valid) / len(valid) if valid else 0
        consist = 0
        if len(valid) >= 2 and mean_t > 0:
            import statistics
            std = statistics.stdev(valid)
            consist = round(max(0, 100 - (std / mean_t * 100)), 1)

        summaries.append({
            "session_id": sid,
            "session_date": s.get("session_date", ""),
            "session_type": s.get("session_type", ""),
            "best_lap_time_s": round(best_t, 3) if best_t else 0,
            "mean_lap_time_s": round(mean_t, 3) if mean_t else 0,
            "total_laps": len(valid),
            "consistency_pct": consist,
        })

    # Best-per-metric
    metrics = ["best_lap_time_s", "mean_lap_time_s", "consistency_pct"]
    labels = {
        "best_lap_time_s": "Best Lap",
        "mean_lap_time_s": "Mean Lap",
        "consistency_pct": "Consistency",
    }
    lower_better = ["best_lap_time_s", "mean_lap_time_s"]
    best_per = {}
    for m in metrics:
        valid_s = [s for s in summaries if s[m] and s[m] > 0]
        if valid_s:
            if m in lower_better:
                best_per[m] = min(valid_s, key=lambda s: s[m])["session_id"]
            else:
                best_per[m] = max(valid_s, key=lambda s: s[m])["session_id"]

    # Pairwise deltas (focus session vs each other)
    pairwise = []
    focus = next((s for s in summaries if s["session_id"] == session_id), None)
    if focus:
        for other in summaries:
            if other["session_id"] == session_id:
                continue
            deltas = {}
            for m in metrics:
                if focus[m] and other[m]:
                    deltas[m] = round(other[m] - focus[m], 3)
                else:
                    deltas[m] = None

            # Assessment
            improvements = sum(
                1 for m in metrics
                if deltas.get(m) is not None and (
                    (m in lower_better and deltas[m] > 0) or
                    (m not in lower_better and deltas[m] < 0)
                )
            )
            regressions = sum(
                1 for m in metrics
                if deltas.get(m) is not None and (
                    (m in lower_better and deltas[m] < 0) or
                    (m not in lower_better and deltas[m] > 0)
                )
            )
            if improvements > 0 and regressions == 0:
                assess = "improved"
            elif regressions > 0 and improvements == 0:
                assess = "regressed"
            elif improvements > 0 and regressions > 0:
                assess = "mixed"
            else:
                assess = "unchanged"

            pairwise.append({
                "session_a": session_id,
                "session_b": other["session_id"],
                "metrics": deltas,
                "assessment": assess,
            })

    return api_response({
        "sessions": summaries,
        "pairwise": pairwise,
        "best_per_metric": best_per,
        "metric_labels": labels,
        "lower_is_better": lower_better,
        "focus_session_id": session_id,
    })


# ══════════════════════════════════════════════════════════════════
# 42. GET /api/v1/sessions/<id>/cross_session
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/cross_session", methods=["GET"])
@_safe_api
def get_cross_session(session_id: str) -> tuple[dict, int]:
    """Return cross-session speed overlay data.

    Finds comparable sessions on the same track and returns
    best-lap speed traces for overlay comparison.
    """
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    track_id = session.get("track_id")
    if not track_id:
        return api_response({"sessions": [], "available": False})

    # Find sessions on same track
    all_sessions = models.get_sessions(conn, limit=50, offset=0)
    same_track = [
        s for s in all_sessions
        if s.get("track_id") == track_id and s.get("session_id")
    ]
    same_track.sort(key=lambda s: s.get("session_date", ""), reverse=True)
    same_track = same_track[:6]

    traces = []
    for s in same_track:
        sid = s["session_id"]
        best = _resolve_lap_number(conn, sid)
        if best is None:
            continue
        trace = models.get_gps_trace(conn, sid, best)
        if trace and trace.get("distances") and trace.get("speeds"):
            traces.append({
                "session_id": sid,
                "session_date": s.get("session_date", ""),
                "lap_number": best,
                "distances": trace["distances"],
                "speeds": trace["speeds"],
            })

    # Compute cross-session metrics for the initMetrics panel
    comparable_count = len(traces)
    historical_percentile = None
    improvement = None
    track_best_time_s = None

    if comparable_count >= 1:
        # Get best lap times for all comparable sessions
        lap_times = []
        focus_time = None
        prev_time = None
        for t in traces:
            laps = models.get_laps_for_session(conn, t["session_id"])
            best = None
            for lap in (laps or []):
                lt = lap.get("lap_time_s")
                if lt and lt > 0:
                    if best is None or lt < best:
                        best = lt
            if best is not None:
                lap_times.append(best)
                if t["session_id"] == session_id:
                    focus_time = best

        if lap_times:
            track_best_time_s = min(lap_times)

        if focus_time is not None and len(lap_times) >= 2:
            faster = sum(1 for t in lap_times if t < focus_time)
            historical_percentile = (faster / len(lap_times)) * 100

            # Find previous session's best time (second most recent on same track)
            other_traces = [
                t for t in traces if t["session_id"] != session_id
            ]
            if other_traces:
                prev_laps = models.get_laps_for_session(
                    conn, other_traces[0]["session_id"]
                )
                for lap in (prev_laps or []):
                    lt = lap.get("lap_time_s")
                    if lt and lt > 0:
                        if prev_time is None or lt < prev_time:
                            prev_time = lt

            if prev_time is not None:
                delta_s = focus_time - prev_time
                improvement = {
                    "delta_s": round(delta_s, 3),
                    "delta_pct": round((delta_s / prev_time) * 100, 2),
                    "improved": delta_s < 0,
                }

    return api_response({
        "sessions": traces,
        "available": len(traces) >= 1,
        "focus_session_id": session_id,
        "comparable_count": comparable_count,
        "historical_percentile": historical_percentile,
        "improvement": improvement,
        "track_best_time_s": track_best_time_s,
    })


# ══════════════════════════════════════════════════════════════════
# 43. GET /api/v1/sessions/<id>/speed_overlay
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/speed_overlay", methods=["GET"])
@_safe_api
def get_speed_overlay(session_id: str) -> tuple[dict, int]:
    """Return speed overlay traces keyed by session ID.

    Used by the vanilla JS cross_session.js module (initOverlay).
    Returns traces as an object keyed by session_id so the JS can
    iterate and toggle individual traces.

    Response shape (after envelope unwrap)::

        {
            "traces": {
                "sid-1": {"distances": [...], "speeds": [...], "label": "...", "is_current": true},
                "sid-2": {"distances": [...], "speeds": [...], "label": "...", "is_current": false}
            }
        }
    """
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    track_id = session.get("track_id")
    if not track_id:
        return api_response({
            "traces": {},
            "available": False,
            "reason_code": "no_track",
            "message": "Session has no associated track for comparison",
        })

    # Find sessions on same track
    all_sessions = models.get_sessions(conn, limit=50, offset=0)
    same_track = [
        s for s in all_sessions
        if s.get("track_id") == track_id and s.get("session_id")
    ]
    same_track.sort(key=lambda s: s.get("session_date", ""), reverse=True)
    same_track = same_track[:6]

    traces_dict = {}
    for s in same_track:
        sid = s["session_id"]
        best = _resolve_lap_number(conn, sid)
        if best is None:
            continue
        trace = models.get_gps_trace(conn, sid, best)
        if trace and trace.get("distances") and trace.get("speeds"):
            date_str = s.get("session_date", "")
            driver = s.get("driver_name", "")
            label = f"{driver} {date_str}".strip() if driver else date_str
            traces_dict[sid] = {
                "distances": trace["distances"],
                "speeds": trace["speeds"],
                "label": label or sid[:8],
                "is_current": sid == session_id,
                "lap_number": best,
            }

    if not traces_dict:
        return api_response({
            "traces": {},
            "available": False,
            "reason_code": "no_comparable_traces",
            "message": "No comparable speed traces found on this track",
        })

    # Observability
    try:
        from web.metrics import incr_counter
        incr_counter("speed_overlay_served")
    except Exception:
        pass

    return api_response({
        "traces": traces_dict,
        "available": True,
    })


# ══════════════════════════════════════════════════════════════════
# GET /api/v1/sessions/<id>/channels — Channel inventory
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/channels", methods=["GET"])
@_safe_api
def get_session_channels(session_id: str) -> tuple[dict, int]:
    """Return the channel inventory discovered during CSV ingestion."""
    conn = get_db_connection()
    row = conn.execute(
        "SELECT channel_inventory FROM sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    if row is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    inventory = None
    if row["channel_inventory"]:
        try:
            inventory = json.loads(row["channel_inventory"])
        except (json.JSONDecodeError, TypeError):
            inventory = None

    return api_response(inventory)


# ══════════════════════════════════════════════════════════════════
# 43. GET /api/v1/sessions/<id>/corner-replay
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/corner-replay", methods=["GET"])
@_safe_api
def get_corner_replay(session_id: str) -> tuple[dict, int]:
    """Batch endpoint for modular corner replay — columnar traces,
    replay windows, typed corners, structured laps, and per-corner metrics.

    Query params:
        corners   (str)  Comma-separated corner IDs to include (default: all)
        laps      (str)  Comma-separated lap numbers (default: all, max 10)
    """
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    track_id = session.get("track_id") or ""

    # ── Parse optional corner filter ───────────────────────────
    corners_param = request.args.get("corners", "")
    requested_corner_ids = set()
    if corners_param:
        try:
            requested_corner_ids = {
                int(x.strip()) for x in corners_param.split(",") if x.strip()
            }
        except ValueError:
            return api_error(ErrorCode.VALIDATION_ERROR,
                             "corners must be comma-separated integers", status=400)

    # ── Build corners list from theoretical data ───────────────
    theo = models.get_theoretical_data(conn, session_id)
    corners = []
    if theo and theo.get("corner_coaching"):
        seen = set()
        for cc in theo["corner_coaching"]:
            cid = cc.get("corner_id") or cc.get("corner_index")
            if cid is None or cid in seen:
                continue
            if requested_corner_ids and cid not in requested_corner_ids:
                continue
            seen.add(cid)

            s_start = cc.get("s_start") or cc.get("distance_start") or 0
            s_end = cc.get("s_end") or cc.get("distance_end") or 0
            s_apex = cc.get("s_apex") or cc.get("distance_apex")
            dist_m = s_apex if s_apex is not None else (s_start + s_end) / 2

            corners.append({
                "corner_id": str(cid),
                "label": cc.get("label") or cc.get("name") or f"C{cid}",
                "lat": cc.get("lat"),
                "lon": cc.get("lon"),
                "dist_m": dist_m,
                "direction": cc.get("direction"),
                "_s_start": s_start,
                "_s_end": s_end,
            })

    if not corners:
        # Fall back to corner_metrics summary
        summary = models.get_corner_metrics_summary(conn, session_id)
        for row in summary:
            cid = row["corner_id"]
            if requested_corner_ids and cid not in requested_corner_ids:
                continue
            corners.append({
                "corner_id": str(cid),
                "label": f"C{cid}",
                "lat": None,
                "lon": None,
                "dist_m": 0,
                "direction": None,
                "_s_start": None,
                "_s_end": None,
            })

    if not corners:
        return api_error(ErrorCode.VALIDATION_ERROR,
                         "No key corners found for this session", status=409)

    # ── Laps ───────────────────────────────────────────────────
    all_laps = models.get_laps_for_session(conn, session_id) or []
    if len(all_laps) < 2:
        return api_error(ErrorCode.VALIDATION_ERROR,
                         "Insufficient laps for replay (need >= 2)", status=422)

    laps_param = request.args.get("laps", "")
    requested_laps = []
    if laps_param:
        try:
            requested_laps = [int(x.strip()) for x in laps_param.split(",") if x.strip()]
        except ValueError:
            return api_error(ErrorCode.VALIDATION_ERROR,
                             "laps must be comma-separated integers", status=400)

    if not requested_laps:
        requested_laps = [lap["lap_number"] for lap in all_laps[:10]]

    laps_out = []
    for lap_info in all_laps:
        ln = lap_info.get("lap_number")
        if ln in requested_laps:
            laps_out.append({
                "lap_number": ln,
                "lap_time_s": lap_info.get("lap_time_s"),
            })

    # ── Columnar traces per lap ────────────────────────────────
    traces = {}
    has_pedal_data = False
    has_steering_data = False

    for lap_num in requested_laps:
        trace = models.get_gps_trace(conn, session_id, lap_num)
        if trace is None:
            continue

        lats = trace.get("latitudes", [])
        lons = trace.get("longitudes", [])
        dists = trace.get("distances", [])
        speeds = trace.get("speeds", [])
        accel_lat = trace.get("accel_lat", [])
        accel_long = trace.get("accel_long", [])

        col_trace = {
            "lat": lats,
            "lon": lons,
            "dist_m": dists,
            "speed_mps": speeds,
            "accel_lat": accel_lat or [0.0] * len(lats),
            "accel_lon": accel_long or [0.0] * len(lats),
        }

        # Brake/throttle/steering not in gps_traces table yet,
        # but include empty arrays for forward compatibility
        col_trace["brake"] = []
        col_trace["throttle"] = []
        col_trace["steering"] = []

        traces[str(lap_num)] = col_trace

    if not traces:
        return api_error(ErrorCode.VALIDATION_ERROR,
                         "No GPS trace data available for replay", status=422)

    # ── Enrich corner GPS from best-lap trace ──────────────────
    best_lap = _resolve_lap_number(conn, session_id)
    best_key = str(best_lap) if best_lap else None
    if best_key and best_key in traces:
        best_dists = traces[best_key]["dist_m"]
        best_lats = traces[best_key]["lat"]
        best_lons = traces[best_key]["lon"]
        if best_dists and best_lats and best_lons:
            for corner in corners:
                if corner["lat"] is None:
                    apex_d = corner["dist_m"]
                    idx = _closest_index(best_dists, apex_d)
                    if idx < len(best_lats):
                        corner["lat"] = best_lats[idx]
                        corner["lon"] = best_lons[idx]

    # ── Replay windows per corner ──────────────────────────────
    BUFFER_M = 50.0
    replay_windows = {}
    for corner in corners:
        cid = corner["corner_id"]
        s_start = corner.get("_s_start")
        s_end = corner.get("_s_end")
        if s_start is None or s_end is None:
            replay_windows[cid] = []
            continue

        win_start = max(0, s_start - BUFFER_M)
        win_end = s_end + BUFFER_M
        windows = []

        for lap_key, col_trace in traces.items():
            dists = col_trace["dist_m"]
            speeds = col_trace["speed_mps"]
            if not dists:
                continue

            start_idx = _closest_index(dists, win_start)
            end_idx = _closest_index(dists, win_end)
            end_idx = min(end_idx, len(dists) - 1)

            if end_idx <= start_idx:
                continue

            # Estimate duration: sum of dt = ds / speed for each segment
            duration = 0.0
            for i in range(start_idx, end_idx):
                ds = abs(dists[i + 1] - dists[i]) if i + 1 < len(dists) else 0
                spd = speeds[i] if i < len(speeds) and speeds[i] > 0.5 else 0.5
                duration += ds / spd

            windows.append({
                "lap_number": int(lap_key),
                "start_idx": start_idx,
                "end_idx": end_idx,
                "estimated_duration_s": round(duration, 2),
            })

        replay_windows[cid] = windows

    # ── Corner metrics keyed by corner_id ──────────────────────
    all_metrics = models.get_corner_metrics_for_session(conn, session_id) or []
    corner_metrics = {}
    corner_id_set = {c["corner_id"] for c in corners}
    for m in all_metrics:
        cid_int = m.get("corner_id")
        cid_str = str(cid_int)
        if cid_str not in corner_id_set:
            continue
        corner_metrics.setdefault(cid_str, []).append({
            "lap_number": m.get("lap_number"),
            "brake_point_m": m.get("brake_point_m"),
            "entry_speed_mps": m.get("entry_speed_mps"),
            "apex_speed_mps": m.get("apex_speed_mps"),
            "exit_speed_mps": m.get("exit_speed_mps"),
            "time_loss_ms": m.get("time_loss_ms"),
            "coaching_hint": m.get("coaching_hint"),
        })

    # ── Strip internal fields from corners ─────────────────────
    for corner in corners:
        corner.pop("_s_start", None)
        corner.pop("_s_end", None)
        corner.pop("direction", None)

    return api_response({
        "session_id": session_id,
        "track_id": track_id,
        "has_pedal_data": has_pedal_data,
        "has_steering_data": has_steering_data,
        "corners": corners,
        "laps": laps_out,
        "traces": traces,
        "replay_windows": replay_windows,
        "corner_metrics": corner_metrics,
    })


# ══════════════════════════════════════════════════════════════════
# 44. GET /api/v1/sessions/<id>/provenance — Provenance record
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/provenance", methods=["GET"])
@_safe_api
def get_provenance(session_id: str) -> tuple[dict, int]:
    """Return the provenance record for a session.

    Read path: check analysis_provenance table first (fast indexed lookup),
    fall back to extracting from analysis_json for pre-migration sessions.
    """
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    # Try provenance table first
    try:
        from provenance.persistence import get_provenance_by_session
        prov = get_provenance_by_session(conn, session_id)
        if prov is not None:
            prov.pop("id", None)
            prov.pop("created_at", None)
            return api_response(prov)
    except Exception:
        pass

    # Fall back to analysis_json
    analysis = models.get_analysis_json(conn, session_id)
    if analysis and isinstance(analysis, dict):
        prov = analysis.get("provenance")
        if prov:
            return api_response(prov)

    return api_error(
        ErrorCode.NOT_FOUND,
        "No provenance available for this session",
        status=404,
    )


# ══════════════════════════════════════════════════════════════════
# 45. GET /api/v1/sessions/<id>/distance-quality — Distance quality
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/distance-quality", methods=["GET"])
@_safe_api
def get_distance_quality(session_id: str) -> tuple[dict, int]:
    """Return the distance quality assessment for a session.

    Read from analysis_json['distance_quality'].
    """
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    analysis = models.get_analysis_json(conn, session_id)
    if analysis and isinstance(analysis, dict):
        dq = analysis.get("distance_quality")
        if dq:
            return api_response(dq)

    return api_error(
        ErrorCode.NOT_FOUND,
        "No distance quality data available for this session",
        status=404,
    )



# ══════════════════════════════════════════════════════════════════
# GET /api/v1/sessions/<id>/grip-map
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/grip-map", methods=["GET"])
@_safe_api
def get_grip_map(session_id: str) -> tuple[dict, int]:
    """Return distance-binned grip map for a session.

    Read from analysis_json['grip_map'].
    """
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    analysis = models.get_analysis_json(conn, session_id)
    if analysis and isinstance(analysis, dict):
        gm = analysis.get("grip_map")
        if gm:
            return api_response(gm)

    return api_error(
        ErrorCode.NOT_FOUND,
        "Grip map not available for this session",
        status=404,
    )


# ══════════════════════════════════════════════════════════════════
# GET /api/v1/sessions/<id>/friction-envelope
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/friction-envelope", methods=["GET"])
@_safe_api
def get_friction_envelope(session_id: str) -> tuple[dict, int]:
    """Return speed-binned friction envelope for a session.

    Read from analysis_json['friction_envelope'].
    """
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    analysis = models.get_analysis_json(conn, session_id)
    if analysis and isinstance(analysis, dict):
        fe = analysis.get("friction_envelope")
        if fe:
            return api_response(fe)

    return api_error(
        ErrorCode.NOT_FOUND,
        "Friction envelope not available for this session",
        status=404,
    )


# ══════════════════════════════════════════════════════════════════
# GET /api/v1/sessions/<id>/optimal-v2
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/optimal-v2", methods=["GET"])
@_safe_api
def get_optimal_v2(session_id: str) -> tuple[dict, int]:
    """Return unified optimal speed trace (v2 solver).

    Read from analysis_json['optimal_v2'].
    """
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    analysis = models.get_analysis_json(conn, session_id)
    if analysis and isinstance(analysis, dict):
        opt = analysis.get("optimal_v2")
        if opt:
            return api_response(opt)

    return api_error(
        ErrorCode.NOT_FOUND,
        "Optimal V2 not available — enable OPTIMAL_V2 flag and re-process",
        status=404,
    )


@bp.route("/sessions/<session_id>/boundaries", methods=["GET"])
@_safe_api
def get_boundaries(session_id: str) -> tuple[dict, int]:
    """Return estimated track boundaries for a session."""
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    analysis = models.get_analysis_json(conn, session_id)
    if analysis and isinstance(analysis, dict):
        boundaries = analysis.get("track_boundaries")
        if boundaries:
            return api_response(boundaries)

    return api_error(
        ErrorCode.NOT_FOUND,
        "Boundary data not available — session may lack XY position data",
        status=404,
    )


@bp.route("/sessions/<session_id>/practice-plan", methods=["GET"])
@_safe_api
def get_practice_plan(session_id: str) -> tuple[dict, int]:
    """Return generated practice plan for a session."""
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    analysis = models.get_analysis_json(conn, session_id)
    if analysis and isinstance(analysis, dict):
        plan = analysis.get("practice_plan")
        if plan:
            return api_response(plan)

    return api_error(
        ErrorCode.NOT_FOUND,
        "Practice plan not available — requires coaching_v2 data",
        status=404,
    )


@bp.route("/sessions/<session_id>/endurance", methods=["GET"])
@_safe_api
def get_endurance(session_id: str) -> tuple[dict, int]:
    """Return endurance analytics for a session."""
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    analysis = models.get_analysis_json(conn, session_id)
    if analysis and isinstance(analysis, dict):
        endurance = analysis.get("endurance")
        if endurance:
            return api_response(endurance)

    return api_error(
        ErrorCode.NOT_FOUND,
        "Endurance data not available",
        status=404,
    )


# ══════════════════════════════════════════════════════════════════
# Driver achievements
# ══════════════════════════════════════════════════════════════════


@bp.route("/driver/achievements", methods=["GET"])
@_safe_api
def get_driver_achievements() -> tuple[dict, int]:
    """Return career milestone badges for the current user's sessions.

    Evaluates cumulative metrics (total laps, scores, tracks visited, etc.)
    and returns both earned and in-progress achievements.
    """
    conn = get_db_connection()

    # Fetch all sessions for the current workspace
    rows = conn.execute(
        "SELECT s.session_id, s.session_date, t.track_name, d.driver_name, "
        "       s.n_laps, s.best_lap_time_s, s.total_score, s.grade "
        "FROM sessions s "
        "JOIN drivers d ON s.driver_id = d.driver_id "
        "LEFT JOIN tracks t ON s.track_id = t.track_id "
        "WHERE s.deleted_at IS NULL "
        "ORDER BY s.session_date DESC"
    ).fetchall()

    sessions = [dict(r) if not isinstance(r, dict) else r for r in rows]

    from scoring.driver_achievements import evaluate_driver_achievements

    achievements = evaluate_driver_achievements(sessions)

    earned = [a for a in achievements if a["earned"]]
    in_progress = [a for a in achievements if not a["earned"]]

    return api_response({
        "achievements": achievements,
        "earned_count": len(earned),
        "total_count": len(achievements),
        "in_progress": in_progress[:5],  # Top 5 closest to earning
    })


# ── Coaching debrief endpoint ─────────────────────────────────────


@bp.route("/sessions/<session_id>/coaching", methods=["GET"])
@_safe_api
def get_coaching(session_id: str) -> tuple[dict, int]:
    """Return AI coaching debrief with narrative, drills, and goals.

    Synthesizes corner data, CoachingV2, scores, lap metrics, and
    driving style into a structured session debrief.
    """
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    # Gather all available coaching inputs
    _analysis = models.get_analysis_json(conn, session_id)
    coaching_v2 = _analysis.get("coaching_v2") if _analysis else None

    # Corner data
    theo = models.get_theoretical_data(conn, session_id)
    corner_list = theo.get("corner_coaching", []) if theo else []

    # Scores
    score_rows = models.get_scores(conn, session_id)
    scores: dict = {}
    if score_rows:
        row = score_rows[0] if isinstance(score_rows, list) else score_rows
        scores = dict(row) if not isinstance(row, dict) else row

    # Lap metrics
    laps = models.get_laps(conn, session_id)
    lap_metrics = [dict(lap) if not isinstance(lap, dict) else lap for lap in (laps or [])]

    # Driving style
    driving_style = None
    if _analysis:
        driving_style = _analysis.get("driving_style")

    from coaching_engine import generate_session_coaching

    result = generate_session_coaching(
        corners=corner_list,
        coaching_v2=coaching_v2,
        scores=scores,
        lap_metrics=lap_metrics,
        driving_style=driving_style,
    )

    return api_response(result.to_dict())


# ── Predictive lap time endpoint ──────────────────────────────────


@bp.route("/sessions/<session_id>/predict", methods=["GET"])
@_safe_api
def predict_lap_time_endpoint(session_id: str) -> tuple[dict, int]:
    """Predict expected lap time based on session conditions and history.

    Uses the session's conditions and historical data from the same
    driver/track to estimate expected performance. If the session has
    completed laps, blends observed data with historical prediction.
    """
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    session = dict(session) if not isinstance(session, dict) else session
    driver_id = session.get("driver_id", 0)
    track_id = session.get("track_id", 0)

    # Build current conditions from session data
    from lap_time_predictor import (
        SessionConditions,
        HistoricalSession,
        predict_lap_time as _predict,
        predict_from_partial_session,
        estimate_improvement_potential,
    )

    # Extract conditions from theoretical data
    theo = models.get_theoretical_data(conn, session_id)
    scalars = {}
    if theo:
        scalars = theo.get("session_scalars") or {}
        if isinstance(scalars, str):
            try:
                scalars = json.loads(scalars)
            except Exception:
                scalars = {}

    conditions = SessionConditions(
        grip_mu=float(scalars.get("mu", 1.0)),
        air_temp_c=float(session.get("air_temp_c", 20.0) or 20.0),
        session_type=str(session.get("session_type", "practice") or "practice"),
    )

    # Gather historical sessions for this driver+track
    rows = conn.execute(
        "SELECT s.session_id, s.driver_id, s.track_id, s.best_lap_time_s, "
        "s.mean_lap_time_s, s.n_laps, s.session_type, s.air_temp_c "
        "FROM sessions s "
        "WHERE s.track_id = :tid AND s.deleted_at IS NULL AND s.n_laps >= 3 "
        "AND s.session_id != :sid "
        "ORDER BY s.session_date DESC LIMIT 50",
        {"tid": track_id, "sid": session_id},
    ).fetchall()

    history = []
    for r in rows:
        r = dict(r) if not isinstance(r, dict) else r
        # Try to get grip from theoretical data
        h_grip = 1.0
        h_theo = models.get_theoretical_data(conn, r["session_id"])
        if h_theo:
            h_scalars = h_theo.get("session_scalars") or {}
            if isinstance(h_scalars, str):
                try:
                    h_scalars = json.loads(h_scalars)
                except Exception:
                    h_scalars = {}
            h_grip = float(h_scalars.get("mu", 1.0))

        history.append(HistoricalSession(
            session_id=str(r["session_id"]),
            driver_id=int(r.get("driver_id", 0)),
            track_id=int(r.get("track_id", 0)),
            best_lap_time_s=float(r.get("best_lap_time_s", 0) or 0),
            mean_lap_time_s=float(r.get("mean_lap_time_s", 0) or 0),
            n_laps=int(r.get("n_laps", 0)),
            grip_mu=h_grip,
            air_temp_c=float(r.get("air_temp_c", 20.0) or 20.0),
            session_type=str(r.get("session_type", "practice") or "practice"),
        ))

    # Get completed laps for partial-session prediction
    laps = models.get_laps(conn, session_id)
    completed_times = []
    if laps:
        for lap in laps:
            lap = dict(lap) if not isinstance(lap, dict) else lap
            t = lap.get("lap_time_s")
            if t and float(t) > 0:
                completed_times.append(float(t))

    # Predict
    if completed_times:
        prediction = predict_from_partial_session(
            completed_times, conditions, history,
            driver_id=driver_id, track_id=track_id,
        )
    else:
        prediction = _predict(driver_id, track_id, conditions, history)

    result = prediction.to_dict()

    # Add improvement potential if theoretical time is available
    if theo and theo.get("theoretical_time_s"):
        potential = estimate_improvement_potential(
            prediction, float(theo["theoretical_time_s"]),
        )
        result["improvement_potential"] = potential.to_dict()

    return api_response(result)


# ══════════════════════════════════════════════════════════════════
# User-defined corner endpoints (corner coaching v2)
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/user-corners", methods=["POST"])
@_safe_api
def save_user_corners(session_id: str) -> tuple[dict, int]:
    """Save user-defined corner definitions for a session.

    Body: {"corners": [{"corner_index": 1, "lat_entry": ..., "lon_entry": ...,
           "lat_apex": ..., "lon_apex": ..., "lat_exit": ..., "lon_exit": ...,
           "s_entry": ..., "s_apex": ..., "s_exit": ...}, ...]}
    """
    conn = get_db_connection()
    data = request.get_json(silent=True) or {}
    corners = data.get("corners", [])

    if not corners:
        return api_error(ErrorCode.VALIDATION_ERROR,
                         "No corners provided", status=400)

    # Validate and insert
    count = 0
    for c in corners:
        idx = c.get("corner_index")
        if idx is None:
            continue

        try:
            conn.execute(
                """INSERT OR REPLACE INTO user_corners
                   (session_id, corner_index, lat_entry, lon_entry,
                    lat_apex, lon_apex, lat_exit, lon_exit,
                    s_entry, s_apex, s_exit)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (session_id, idx,
                 c.get("lat_entry"), c.get("lon_entry"),
                 c.get("lat_apex"), c.get("lon_apex"),
                 c.get("lat_exit"), c.get("lon_exit"),
                 c.get("s_entry"), c.get("s_apex"), c.get("s_exit")),
            )
            count += 1
        except Exception:
            logger.debug("Failed to save user corner %s", idx, exc_info=True)

    conn.commit()
    logger.info("Saved %d user-defined corners for session %s", count, session_id)
    return api_response({"saved": count}), 200


@bp.route("/sessions/<session_id>/user-corners", methods=["GET"])
@_safe_api
def get_user_corners(session_id: str) -> tuple[dict, int]:
    """Retrieve user-defined corners for a session."""
    conn = get_db_connection()

    try:
        rows = conn.execute(
            "SELECT * FROM user_corners WHERE session_id = ? ORDER BY corner_index",
            (session_id,),
        ).fetchall()
    except Exception:
        # Table might not exist yet
        return api_response({"corners": [], "count": 0})

    corners = []
    for row in rows:
        row_dict = dict(row) if hasattr(row, 'keys') else {}
        corners.append({
            "corner_index": row_dict.get("corner_index"),
            "lat_entry": row_dict.get("lat_entry"),
            "lon_entry": row_dict.get("lon_entry"),
            "lat_apex": row_dict.get("lat_apex"),
            "lon_apex": row_dict.get("lon_apex"),
            "lat_exit": row_dict.get("lat_exit"),
            "lon_exit": row_dict.get("lon_exit"),
            "s_entry": row_dict.get("s_entry"),
            "s_apex": row_dict.get("s_apex"),
            "s_exit": row_dict.get("s_exit"),
        })

    return api_response({"corners": corners, "count": len(corners)})


@bp.route("/sessions/<session_id>/recoach", methods=["POST"])
@_safe_api
def recoach_session(session_id: str) -> tuple[dict, int]:
    """Re-run v2 coaching with current corner definitions.

    Loads the best lap GPS trace, runs the v2 corner coaching pipeline
    (which checks user_corners table first), and persists results.
    """
    conn = get_db_connection()

    # Check session exists
    session = conn.execute(
        "SELECT session_id FROM sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    if not session:
        return api_error(ErrorCode.NOT_FOUND,
                         "Session not found", status=404)

    # 1. Resolve best lap and load GPS trace
    best_lap = _resolve_lap_number(conn, session_id)
    if best_lap is None:
        return api_error(ErrorCode.VALIDATION, "No laps for session", status=400)

    trace = models.get_gps_trace(conn, session_id, best_lap)
    if trace is None:
        return api_error(ErrorCode.VALIDATION, "No GPS trace for best lap", status=400)

    # 2. Reconstruct a best_lap DataFrame from stored trace data
    import numpy as np
    import pandas as pd

    distances = trace.get("distances", [])
    speeds = trace.get("speeds", [])
    lats = trace.get("latitudes", [])
    lons = trace.get("longitudes", [])

    if not distances or not speeds:
        return api_error(ErrorCode.VALIDATION, "Insufficient trace data", status=400)

    best_lap_df = pd.DataFrame({
        "Distance (m)": distances,
        "Speed (m/s)": speeds,
        "Latitude": lats,
        "Longitude": lons,
    })
    if trace.get("accel_lat"):
        best_lap_df["Lateral acceleration (G) *calc"] = trace["accel_lat"]
    if trace.get("accel_long"):
        best_lap_df["Longitudinal acceleration (G) *calc"] = trace["accel_long"]

    # 3. Run v2 corner coaching pipeline stages
    from pipeline.stages import s10b_corners

    # Load existing corners as fallback for when decompose_track returns 0
    fallback_corners = None
    theo = models.get_theoretical_data(conn, session_id)
    if theo and theo.get("corner_coaching"):
        fallback_corners = theo["corner_coaching"]

    v2_sections = s10b_corners.run_track_decomposition_v2(
        best_lap_df, conn=conn, session_id=session_id,
        fallback_corners=fallback_corners,
    )
    if not v2_sections:
        return api_response({
            "status": "completed",
            "message": "No corner sections found (define corners or check data)",
            "corner_coaching_v2": [],
        })

    v2_mrp = s10b_corners.run_mrp_detection_v2(v2_sections, best_lap_df)
    avail_cols = set(best_lap_df.columns)
    v2_handling = s10b_corners.run_handling_analysis_v2(
        v2_sections, best_lap_df, available_columns=avail_cols,
    )
    v2_coaching = s10b_corners.run_coaching_v2(
        v2_sections, v2_mrp, v2_handling, best_lap_df,
        available_columns=avail_cols,
    )

    # 4. Persist to analysis_json
    analysis = models.get_analysis_json(conn, session_id) or {}
    analysis["track_sections_v2"] = v2_sections
    if v2_mrp:
        analysis["mrp_events_v2"] = v2_mrp
    if v2_coaching:
        analysis["corner_coaching_v2"] = v2_coaching
    models.insert_analysis_json(conn, session_id, analysis)
    conn.commit()

    logger.info(
        "Recoach session %s: %d sections, %d coached (%d user-defined)",
        session_id, len(v2_sections),
        len(v2_coaching) if v2_coaching else 0,
        sum(1 for s in v2_sections if s.get("corner_type") == "user_defined"),
    )

    return api_response({
        "status": "completed",
        "session_id": session_id,
        "sections_count": len(v2_sections),
        "corner_coaching_v2": v2_coaching or [],
    })


# Dev-plans endpoints moved to api_v1_entities.py (Task 5).
