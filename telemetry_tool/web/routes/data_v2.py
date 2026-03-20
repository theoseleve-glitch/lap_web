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
from web.repos.delete_cascade import delete_entity_cascade, get_delete_impact

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
    # Exclude endurance stint child sessions (same filter as sessions list).
    recent = models.get_sessions(conn, limit=20, offset=0,
                                 filters={"exclude_endurance_stints": True, "archived": False})

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

    # Identify which session holds the personal best — query directly
    # instead of scanning recent (which is limited to 20 sessions).
    pb_session_id = None
    if stats.get("overall_best_time_s") is not None:
        try:
            pb_row = conn.execute(
                "SELECT session_id FROM sessions "
                "WHERE best_lap_time_s = :best AND deleted_at IS NULL "
                "ORDER BY session_date DESC LIMIT 1",
                {"best": stats["overall_best_time_s"]},
            ).fetchone()
            if pb_row:
                sid = pb_row["session_id"] if isinstance(pb_row, dict) else pb_row[0]
                pb_session_id = str(sid) if sid and isinstance(sid, (str, int)) else None
        except Exception:
            pass

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

    # Hide endurance stint child sessions (accessible only from master report)
    if filters.get("session_type") != "endurance_stint":
        filters["exclude_endurance_stints"] = True

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
        # Check for OCP theoretical availability
        if "theoretical_ocp" in analysis:
            result["theoretical_ocp_available"] = True
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

    # OCP theoretical source — checked FIRST (takes priority over version)
    source = request.args.get("source", "")
    if source == "ocp":
        row = conn.execute(
            "SELECT analysis_json FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        aj = json.loads(row[0]) if row and row[0] else {}
        ocp_data = aj.get("theoretical_ocp")
        if ocp_data and "speed_profile" in ocp_data:
            return api_response({
                "available": True,
                "source": "ocp",
                "lap_time_s": ocp_data.get("lap_time_s"),
                "speed_profile": ocp_data["speed_profile"],
                "solver_meta": ocp_data.get("solver_meta", {}),
            })
        return api_response({
            "available": False,
            "reason_code": "ocp_not_available",
            "message": "OCP theoretical not yet computed for this session",
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

    # Normalize per-lap distances to start from 0 (stored as
    # session-cumulative, e.g. Lap 6 might be 5000–6200m).
    if distances and len(distances) > 1 and distances[0] != 0:
        _d_off = distances[0]
        distances = [d - _d_off for d in distances]

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
                    # Normalize ref lap distances to 0-based
                    if ref_dists[0] != 0:
                        ref_dists = [d - ref_dists[0] for d in ref_dists]
                    interp = np.interp(distances, ref_dists, ref_speeds)
                    result["ref_speeds"] = interp.tolist()
                    result["ref_lap_number"] = ref_lap

    # Optional average pace line across all valid laps
    if request.args.get("avg") == "1":
        try:
            import numpy as np

            all_laps = models.get_laps_for_session(conn, session_id)
            if all_laps and distances:
                speed_arrays = []
                for lap_row in all_laps:
                    ln = lap_row.get("lap_number")
                    if ln == lap_num:
                        speed_arrays.append(np.array(trace.get("speeds", [])))
                        continue
                    lt = models.get_gps_trace(conn, session_id, ln)
                    if lt and lt.get("distances") and lt.get("speeds"):
                        lt_dists = lt["distances"]
                        # Normalize other lap distances to 0-based
                        if lt_dists and lt_dists[0] != 0:
                            lt_dists = [d - lt_dists[0] for d in lt_dists]
                        interp_s = np.interp(
                            distances, lt_dists, lt["speeds"]
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

    # Normalize to per-lap 0-based distances (stored values are
    # session-cumulative).  Other chart endpoints do the same so
    # the cross-chart hover sync works on a shared distance axis.
    if distances and len(distances) > 1 and distances[0] != 0:
        d0 = distances[0]
        distances = [d - d0 for d in distances]

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

    # Convert m/s² to G if needed.  Kart/car lateral G peaks at ~3G;
    # values >5 almost certainly indicate m/s² (5G ≈ 49 m/s²).
    if has_accel:
        _max_mag = max(
            (abs(v) for v in (*lat_g, *lon_g) if v is not None and isinstance(v, (int, float))),
            default=0,
        )
        if _max_mag > 5:
            lat_g = [v / 9.81 if v is not None else None for v in lat_g]
            lon_g = [v / 9.81 if v is not None else None for v in lon_g]

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

    # Normalize per-lap distances to 0-based
    if distances and len(distances) > 1 and distances[0] != 0:
        _d_off = distances[0]
        distances = [d - _d_off for d in distances]

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
        from scoring.constants import MAX_ADAPTATION
        sub_scores = {}
        _default_max = {"adaptation": MAX_ADAPTATION}  # no adaptation_max column in DB
        for cat in ("pace", "consistency", "execution", "robustness", "adaptation"):
            sub_scores[cat] = {
                "score": scores.get(f"{cat}_score", 0) or 0,
                "max": scores.get(f"{cat}_max") or _default_max.get(cat, 25),
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
            # Gamification data (XP gained, achievements, streak) from pipeline
            gam = analysis.get("gamification")
            if gam:
                scores["gamification"] = gam
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
            s_start = _first_not_none(cc, "s_start", "distance_start") if cc else None
            s_end = _first_not_none(cc, "s_end", "distance_end") if cc else None
            s_apex = _first_not_none(cc, "s_apex", "distance_apex", "apex_distance_m") if cc else None
            if s_apex is None and s_start is not None and s_end is not None:
                s_apex = round((s_start + s_end) / 2, 2)
            corner: dict = {
                "corner_id": cid,
                "s_start":   s_start,
                "s_end":     s_end,
                "s_apex":    s_apex,
                "direction": cc.get("direction") if cc else None,
            }
            if cc:
                corner["available"] = True
                corner.update(_extract_coaching(cc))
                # Per-corner OCP actionables (from s10a_corner_ocp)
                if "actionables" in cc:
                    corner["actionables"] = cc["actionables"]
                if "optimal_speeds" in cc:
                    corner["optimal_speeds"] = cc["optimal_speeds"]
                if "optimal_time_s" in cc:
                    corner["optimal_time_s"] = cc["optimal_time_s"]
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
            s_start = _first_not_none(cc, "s_start", "distance_start")
            s_end = _first_not_none(cc, "s_end", "distance_end")
            s_apex = _first_not_none(cc, "s_apex", "distance_apex", "apex_distance_m")
            if s_apex is None and s_start is not None and s_end is not None:
                s_apex = round((s_start + s_end) / 2, 2)
            corner = {
                "corner_id": cc.get("corner_id"),
                "s_start":   s_start,
                "s_end":     s_end,
                "s_apex":    s_apex,
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
    """Hard-delete a session and all related data.

    Requires at least 'member' role in the workspace (viewers cannot delete).
    """
    workspace_role = getattr(g, "workspace_role", None)
    if workspace_role == "viewer":
        return api_error(ErrorCode.FORBIDDEN, "Insufficient permissions to delete sessions", status=403)

    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    result = delete_entity_cascade(conn, "session", session_id)
    audit_log(conn, "session.delete", {"session_id": session_id, "impact": result["impact"]})
    conn.commit()

    try:
        from web.rollups import refresh_rollups
        refresh_rollups(conn, int(g.workspace_id))
    except Exception:
        logger.warning("Rollup refresh failed after delete", exc_info=True)

    logger.info("Deleted session %s, impact=%s", session_id, result["impact"])
    return api_response(result)


@bp.route("/sessions/<session_id>/delete-impact", methods=["GET"])
@_safe_api
def session_delete_impact(session_id: str) -> tuple[dict, int]:
    """Preview cascade impact of deleting a session."""
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)
    result = get_delete_impact(conn, "session", session_id)
    return api_response(result)


# ══════════════════════════════════════════════════════════════════
# 9a2. POST /api/v1/sessions/<id>/restore — Restore soft-deleted
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/restore", methods=["POST"])
@_safe_api
def restore_session(session_id: str) -> tuple[dict, int]:
    """Restore a soft-deleted session."""
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id, include_deleted=True)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)
    if not session.get("deleted_at"):
        return api_error(ErrorCode.CONFLICT, "Session is not deleted", status=409)
    models.restore_session(conn, session_id)
    conn.commit()
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
            "action": "delete" | "favorite" | "unfavorite",
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

    if action not in ("delete", "favorite", "unfavorite"):
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
            models.soft_delete_session(conn, sid)
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
            "WHERE s.driver_id = :driver_id AND s.deleted_at IS NULL "
            "ORDER BY s.session_date ASC",
            {"driver_id": driver_id},
        ).fetchall()
    ]

    if not sessions:
        return {
            "driver": driver,
            "avg_scores": {
                "pace": None, "consistency": None,
                "execution": None, "robustness": None,
            },
            "trend": [],
            "stats": {
                "sessions": 0, "avg_score": None,
                "best_score": None, "tracks": 0,
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

    def _avg(vals: list[float]) -> float | None:
        return round(sum(vals) / len(vals), 1) if vals else None

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
        "avg_score": round(sum(total_scores) / len(total_scores), 1) if total_scores else None,
        "best_score": max(total_scores) if total_scores else None,
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

    import os as _os
    if not any(str(path) == str(d) or str(path).startswith(str(d) + _os.sep) for d in allowed_dirs):
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
    try:
        limit = min(int(request.args.get("limit", 500)), 2000)
    except (ValueError, TypeError):
        limit = 500

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
    laps = models.get_laps_for_session(conn, session_id)
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
# 12b. GET /api/v1/sessions/<id>/track-match — GPS mismatch check
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/track-match", methods=["GET"])
@_safe_api
def check_track_match(session_id: str) -> tuple[dict, int]:
    """Check if a track's GPS fingerprint matches this session's GPS data.

    Query params:
        track_id (str) — the track to compare against
    """
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    track_id = request.args.get("track_id")
    if not track_id:
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            "track_id query parameter required",
            status=400,
        )

    result = models.check_track_gps_match(conn, session_id, track_id)
    return api_response(result)


# ══════════════════════════════════════════════════════════════════
# 13. PATCH /api/v1/sessions/<id> — Update session fields
# ══════════════════════════════════════════════════════════════════


import re

# Fields the PATCH endpoint accepts directly (via the for-loop).
_UPDATABLE_FIELDS = {
    "display_name", "session_date", "driver_id", "track_id",
    "session_type", "track_state", "kart_id", "notes",
}

_VALID_SESSION_TYPES = {"practice", "qualifying", "race", "test", "endurance", "heat", "final"}
_VALID_TRACK_STATES = {"dry", "wet", "damp", "mixed", "green", "rubbered", "dusty"}
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

        if field == "track_name":
            # track_name is handled separately (upsert); just pass through.
            if value is not None and not isinstance(value, str):
                errors.append({"field": "track_name", "message": "Must be a string."})
            else:
                cleaned["track_name"] = value
            continue

        if field == "kart_name":
            # kart_name is handled separately (upsert); just pass through.
            if value is not None and not isinstance(value, str):
                errors.append({"field": "kart_name", "message": "Must be a string."})
            else:
                cleaned["kart_name"] = value
            continue

        if field == "kart_details":
            # Optional details when creating a new kart (manufacturer, model, etc.)
            if value is not None and not isinstance(value, dict):
                errors.append({"field": "kart_details", "message": "Must be an object."})
            else:
                cleaned["kart_details"] = value
            continue

        if field == "track_details":
            if value is not None and not isinstance(value, dict):
                errors.append({"field": "track_details", "message": "Must be an object."})
            else:
                cleaned["track_details"] = value
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

    # Handle track_name — upsert track by name, then update track_id.
    # Also auto-populate the track's GPS fingerprint from this session
    # and save detected corners for cross-session analysis.
    track_name = cleaned.get("track_name")
    if track_name and isinstance(track_name, str):
        track_details = cleaned.get("track_details") or {}
        track_id = models.upsert_track_by_name(conn, track_name, details=track_details)
        models.update_session_field(conn, session_id, "track_id", track_id)
        models.populate_track_from_session_gps(conn, session_id, track_id)
        models.save_session_corners_to_track(conn, session_id, track_id)
        updated_count += 1

    # Handle kart_name — upsert kart by name, then update kart_id.
    # kart_details (manufacturer, model, engine, etc.) are passed through
    # to create_kart when the kart doesn't exist yet.
    kart_name = cleaned.get("kart_name")
    if kart_name and isinstance(kart_name, str):
        kart_details = cleaned.get("kart_details") or {}
        kart_id = models.upsert_kart_by_name(conn, kart_name, details=kart_details)
        models.update_session_field(conn, session_id, "kart_id", kart_id)
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
            "track_name, track_id, kart_name, kart_id, session_date, "
            "display_name, notes",
            status=400,
        )

    conn.commit()

    # Re-fetch and return the updated session (strip internal fields).
    refetched = models.get_session_by_id(conn, session_id)
    if refetched is None:
        return api_response({"session_id": session_id, "updated_fields": updated_count})
    updated = dict(refetched)
    updated.pop("source_path", None)
    updated.pop("html_report_path", None)
    if updated.get("csv_filename"):
        updated["csv_filename"] = Path(updated["csv_filename"]).name
    # Derive track_unnamed flag (same logic as GET detail endpoint)
    tid = updated.get("track_id") or ""
    tname = (updated.get("track_name") or "").strip()
    updated["track_unnamed"] = bool(tid and (not tname or tname == tid))
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
# 12c. POST /api/v1/sessions/<id>/revalidate
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/revalidate", methods=["POST"])
@_safe_api
def revalidate_session(session_id: str) -> tuple[dict, int]:
    """Re-run lap validity detection with the latest algorithm.

    Useful for sessions uploaded before seed-hardening or other
    validation improvements.  Returns a list of changed laps.
    """
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    result = models.revalidate_session_laps(conn, session_id)
    return api_response(result)


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
        "available": True,
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

    distances = trace.get("distances", [])
    if distances and len(distances) > 1 and distances[0] != 0:
        d0 = distances[0]
        distances = [d - d0 for d in distances]

    return api_response({
        "latitudes": trace.get("latitudes", []),
        "longitudes": trace.get("longitudes", []),
        "distances": distances,
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


def _first_not_none(d: dict, *keys):
    """Return the first non-None value for the given keys, or None."""
    for k in keys:
        v = d.get(k)
        if v is not None:
            return v
    return None


def _build_corner_positions(conn: Any, session_id: str) -> list[dict]:
    """Build corner GPS positions with brake point data (shared helper)."""
    theo = models.get_theoretical_data(conn, session_id)
    corners: list[dict] = []
    if theo and theo.get("corner_coaching"):
        seen: set = set()
        for cc in theo["corner_coaching"]:
            cid = _first_not_none(cc, "corner_id", "corner_index")
            if cid is not None and cid not in seen:
                seen.add(cid)
                corners.append({
                    "corner_id": cid,
                    "s_start": _first_not_none(cc, "s_start", "distance_start"),
                    "s_end": _first_not_none(cc, "s_end", "distance_end"),
                    "s_apex": _first_not_none(cc, "s_apex", "distance_apex", "apex_distance_m"),
                    "direction": cc.get("direction"),
                    "label": _first_not_none(cc, "label", "name"),
                    "lat": cc.get("lat"),
                    "lon": cc.get("lon"),
                    "brake_point_m": None,
                })

    # Compute s_apex midpoint fallback for corners missing apex distance
    for corner in corners:
        if corner["s_apex"] is None:
            s0, s1 = corner["s_start"], corner["s_end"]
            if s0 is not None and s1 is not None:
                corner["s_apex"] = round((s0 + s1) / 2, 2)

    if not corners:
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
        return []

    # Enrich with GPS coordinates from best lap trace
    best_lap = _resolve_lap_number(conn, session_id)
    best_gps = models.get_gps_trace(conn, session_id, best_lap) if best_lap else None

    if best_gps:
        raw_dists = best_gps.get("distances", [])
        if raw_dists and len(raw_dists) > 1 and raw_dists[0] != 0:
            d0 = raw_dists[0]
            dists = [d - d0 for d in raw_dists]
        else:
            dists = raw_dists
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

    return corners


@bp.route("/sessions/<session_id>/corner-positions", methods=["GET"])
@_safe_api
def get_corner_positions(session_id: str) -> tuple[dict, int]:
    """Return corner GPS positions with brake point data."""
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    corners = _build_corner_positions(conn, session_id)

    if not corners:
        return api_error(ErrorCode.NOT_FOUND,
                         "No corner position data for this session", status=404)

    return api_response({"corners": corners})


# ══════════════════════════════════════════════════════════════════
# 16b. POST /api/v1/sessions/<id>/ocp-corner — Per-corner OCP solve
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/ocp-corner", methods=["POST"])
@_safe_api
def solve_ocp_corner(session_id: str) -> tuple[dict, int]:
    """Run OCP segment solver for selected corners across all laps.

    Body: {"corner_ids": [1, 3, 5]}

    For each corner_id, builds a track mesh from s_start to s_end,
    extracts actual entry/exit speeds from each lap's GPS trace,
    and solves a boundary-value OCP to compute the optimal time
    through that corner segment.

    Also runs a full-lap OCP on the best lap to compute the optimal
    lap time (reuses existing result if available).

    Returns per-corner, per-lap optimal times + the full-lap optimal.
    """
    body = request.get_json(silent=True) or {}
    corner_ids = body.get("corner_ids", [])
    if not corner_ids or not isinstance(corner_ids, list):
        return api_error(ErrorCode.VALIDATION_ERROR,
                         "corner_ids is required (list of ints)", status=400)

    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    try:
        result = _run_corner_ocp(conn, session_id, corner_ids)
    except ImportError as e:
        logger.warning("OCP solver not available: %s", e)
        return api_error(ErrorCode.INTERNAL_ERROR,
                         "OCP solver dependencies not installed", status=503)
    except Exception:
        logger.exception("OCP corner solve failed for session %s", session_id)
        return api_error(ErrorCode.INTERNAL_ERROR,
                         "OCP corner solve failed", status=500)

    return api_response(result)


def _run_corner_ocp(conn, session_id: str, corner_ids: list[int]) -> dict:
    """Core logic for per-corner OCP across all laps + full-lap OCP for best lap."""
    import numpy as np
    import pandas as pd
    from web.repos import gps_repo, lap_repo, theoretical_repo

    # ── 1. Load session data ────────────────────────────────
    row = conn.execute(
        "SELECT analysis_json FROM sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    raw = row["analysis_json"] if isinstance(row, dict) else row[0]
    analysis_json = json.loads(raw) if raw else {}

    # ── 2. Load corners ─────────────────────────────────────
    corners = analysis_json.get("corners", [])
    corner_map = {}
    for c in corners:
        cid = c.get("corner_id")
        if cid is not None and cid in corner_ids:
            corner_map[cid] = c

    if not corner_map:
        # Try from theoretical_data coaching
        theo = models.get_theoretical_data(conn, session_id)
        if theo and theo.get("corner_coaching"):
            for cc in theo["corner_coaching"]:
                cid = cc.get("corner_id")
                if cid is not None and cid in corner_ids:
                    corner_map[cid] = cc

    if not corner_map:
        return {"corner_results": [], "full_lap_ocp": None, "error": "No matching corners found"}

    # ── 3. Load curvature from reference line ───────────────
    ref_line = theoretical_repo.get_reference_line(conn, session_id)
    if not ref_line:
        return {"corner_results": [], "full_lap_ocp": None, "error": "No reference line data"}

    ref_dists = ref_line.get("distances", [])
    ref_lats = ref_line.get("latitudes", [])
    ref_lons = ref_line.get("longitudes", [])
    if not ref_dists or len(ref_dists) < 20:
        return {"corner_results": [], "full_lap_ocp": None, "error": "Insufficient reference line data"}

    from tasks.ocp_tasks import _curvature_from_reference_line
    curvature_profile = _curvature_from_reference_line(
        np.array(ref_dists, dtype=float),
        np.array(ref_lats, dtype=float),
        np.array(ref_lons, dtype=float),
    )
    if curvature_profile is None:
        return {"corner_results": [], "full_lap_ocp": None, "error": "Could not compute curvature"}

    curv_dist = curvature_profile["distance_m"].to_numpy(dtype=float)
    curv_vals = curvature_profile["curvature_1pm"].to_numpy(dtype=float)

    # ── 4. Load vehicle params ──────────────────────────────
    from solver.vehicle_params import OCPVehicleParams, params_for_class
    from solver.tire_model import LoadSensitiveTire
    from solver.param_extractor import extract_session_params
    from solver.track_model import build_mesh
    from solver.ocp_solver import solve_ocp_segment

    vp_data = analysis_json.get("vehicle_params")
    if vp_data:
        try:
            from vehicle_model import VehicleParameters, VehicleClass
            vc = VehicleClass(vp_data.get("vehicle_class", "unknown"))
            vehicle_params = VehicleParameters(
                vehicle_class=vc,
                estimated_mass_kg=vp_data.get("estimated_mass_kg"),
                peak_lateral_g=vp_data.get("peak_lateral_g", 1.0),
                peak_braking_g=vp_data.get("peak_braking_g", 1.0),
            )
            base_params = OCPVehicleParams.from_vehicle_params(vehicle_params)
        except Exception:
            base_params = params_for_class("car")
    else:
        base_params = params_for_class("car")

    # ── 5. Load ALL laps ────────────────────────────────────
    laps = lap_repo.get_laps_for_session(conn, session_id)
    if not laps:
        return {"corner_results": [], "full_lap_ocp": None, "error": "No laps found"}

    best_lap_num = None
    for lap in laps:
        if lap.get("is_best"):
            best_lap_num = lap["lap_number"]
            break
    if best_lap_num is None and laps:
        best_lap_num = laps[0]["lap_number"]

    # ── 6. Per-corner, per-lap OCP ──────────────────────────
    corner_results = []
    for cid, cdata in corner_map.items():
        s_start = cdata.get("s_start") or cdata.get("distance_start") or cdata.get("entry_distance_m")
        s_end = cdata.get("s_end") or cdata.get("distance_end") or cdata.get("exit_distance_m")
        if s_start is None or s_end is None:
            continue

        s_start_f = float(s_start)
        s_end_f = float(s_end)
        segment_len = s_end_f - s_start_f
        if segment_len < 5:
            continue

        # Build mesh for this corner segment
        n_nodes = max(20, min(80, int(segment_len / 2)))
        mask = (curv_dist >= s_start_f) & (curv_dist <= s_end_f)
        seg_dists = curv_dist[mask]
        seg_curvs = curv_vals[mask]
        if len(seg_dists) < 5:
            # Interpolate from full curvature
            seg_dists = np.linspace(s_start_f, s_end_f, n_nodes)
            seg_curvs = np.interp(seg_dists, curv_dist, curv_vals)

        mesh = build_mesh(seg_dists, seg_curvs, n_nodes=n_nodes)

        lap_results = []
        for lap in laps:
            lap_num = lap["lap_number"]
            trace = gps_repo.get_gps_trace(conn, session_id, lap_num)
            if not trace:
                continue
            dists = trace.get("distances", [])
            speeds = trace.get("speeds", [])
            if not dists or not speeds or len(dists) != len(speeds) or len(dists) < 10:
                continue

            d_arr = np.array(dists, dtype=float)
            s_arr = np.array(speeds, dtype=float)

            # Get actual entry/exit speeds from this lap
            v_entry = float(np.interp(s_start_f, d_arr, s_arr))
            v_exit = float(np.interp(s_end_f, d_arr, s_arr))

            if v_entry < 1.0 or v_exit < 1.0:
                continue

            # Extract params from this lap's data
            lap_df = pd.DataFrame({"Distance (m)": d_arr, "Speed (m/s)": s_arr})
            try:
                params = extract_session_params(lap_df, base_params)
            except Exception:
                params = base_params

            tire = LoadSensitiveTire(
                mu_ref=params.mu_ref,
                Fz_ref=params.Fz_static_per_axle,
                sensitivity=params.load_sensitivity,
            )

            try:
                result = solve_ocp_segment(
                    mesh, params, tire,
                    v_entry=v_entry, v_exit=v_exit,
                    max_iter=200, tol=1e-3,
                )
                # Actual time through corner (from telemetry)
                seg_mask = (d_arr >= s_start_f) & (d_arr <= s_end_f)
                seg_d = d_arr[seg_mask]
                seg_s = s_arr[seg_mask]
                actual_time = 0.0
                if len(seg_d) > 1:
                    for j in range(len(seg_d) - 1):
                        v_avg = max((seg_s[j] + seg_s[j + 1]) / 2.0, 2.0)
                        actual_time += (seg_d[j + 1] - seg_d[j]) / v_avg

                # Apex speed (min speed in segment)
                actual_apex_mps = float(seg_s.min()) if len(seg_s) > 0 else None
                ocp_apex_mps = float(result.speed_profile.min())

                lap_results.append({
                    "lap_number": lap_num,
                    "is_best": lap.get("is_best", False),
                    "actual_time_s": round(actual_time, 4),
                    "optimal_time_s": round(result.lap_time_s, 4),
                    "delta_s": round(actual_time - result.lap_time_s, 4),
                    "delta_ms": round((actual_time - result.lap_time_s) * 1000, 1),
                    "actual_apex_mps": round(actual_apex_mps, 3) if actual_apex_mps else None,
                    "ocp_apex_mps": round(ocp_apex_mps, 3),
                    "converged": result.converged,
                    "v_entry": round(v_entry, 3),
                    "v_exit": round(v_exit, 3),
                })
            except Exception:
                logger.debug("OCP segment failed for corner %d lap %d", cid, lap_num, exc_info=True)
                continue

        corner_results.append({
            "corner_id": cid,
            "s_start": s_start_f,
            "s_end": s_end_f,
            "direction": cdata.get("direction"),
            "laps": lap_results,
        })

    # ── 7. Full-lap OCP for best lap (reuse if exists) ──────
    full_lap_ocp = None
    existing_ocp = analysis_json.get("theoretical_ocp")
    if existing_ocp and existing_ocp.get("converged"):
        full_lap_ocp = {
            "lap_time_s": existing_ocp.get("lap_time_s"),
            "converged": existing_ocp.get("converged"),
            "source": "cached",
        }
    else:
        # Queue or compute (don't block — return null and let Celery handle it)
        full_lap_ocp = {
            "lap_time_s": None,
            "converged": False,
            "source": "pending",
            "message": "Full-lap OCP not yet computed. Upload triggers background computation.",
        }

    return {
        "corner_results": corner_results,
        "full_lap_ocp": full_lap_ocp,
        "best_lap": best_lap_num,
    }


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
    """Compute time delta between two laps on the fly.

    Uses speed-trace shape to show WHERE time is gained/lost, but
    scales cumulative times to match the actual recorded lap times
    so the final delta equals the true lap-time difference.
    """
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

    # Fetch actual lap times from DB
    all_laps = models.get_laps_for_session(conn, session_id) or []
    lap_times = {l["lap_number"]: l.get("lap_time_s") for l in all_laps}
    real_time_a = lap_times.get(lap_a)
    real_time_b = lap_times.get(lap_b)

    trace_a = models.get_gps_trace(conn, session_id, lap_a)
    trace_b = models.get_gps_trace(conn, session_id, lap_b)

    if trace_a is None or trace_b is None:
        return api_response({
            "available": False, "reason_code": "no_gps_trace",
            "message": "GPS trace not found for one or both laps",
        })

    def _cumulative_time(distances: list[float], speeds: list[float]) -> list[float]:
        """Build cumulative time array using trapezoidal integration."""
        t = [0.0]
        for i in range(1, len(distances)):
            ds = distances[i] - distances[i - 1]
            v0 = speeds[i - 1] if speeds[i - 1] and speeds[i - 1] > 0 else 0
            v1 = speeds[i] if speeds[i] and speeds[i] > 0 else 0
            v_avg = (v0 + v1) / 2 if (v0 + v1) > 0 else 0
            if v_avg > 0:
                t.append(t[-1] + ds / v_avg)
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

    # Normalize per-lap distances to 0-based (stored as session-cumulative)
    if dist_a and dist_a[0] != 0:
        _off = dist_a[0]
        dist_a = [d - _off for d in dist_a]
    if dist_b and dist_b[0] != 0:
        _off = dist_b[0]
        dist_b = [d - _off for d in dist_b]

    time_a = _cumulative_time(dist_a, spd_a)
    time_b = _cumulative_time(dist_b, spd_b)

    # Scale cumulative times to match actual lap times so the final
    # delta equals the true lap-time difference.
    if real_time_a and time_a[-1] > 0:
        scale_a = real_time_a / time_a[-1]
        time_a = [t * scale_a for t in time_a]
    if real_time_b and time_b[-1] > 0:
        scale_b = real_time_b / time_b[-1]
        time_b = [t * scale_b for t in time_b]

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
            distances = trace.get("distances", [])
            if distances and len(distances) > 1 and distances[0] != 0:
                d0 = distances[0]
                distances = [d - d0 for d in distances]
            laps_data[str(ln)] = {
                "latitudes": trace.get("latitudes", []),
                "longitudes": trace.get("longitudes", []),
                "distances": distances,
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
        raw_dists = best_gps.get("distances", []) if best_gps else []
        if raw_dists and len(raw_dists) > 1 and raw_dists[0] != 0:
            d0 = raw_dists[0]
            dists = [d - d0 for d in raw_dists]
        else:
            dists = raw_dists
        lats = best_gps.get("latitudes", []) if best_gps else []
        lons = best_gps.get("longitudes", []) if best_gps else []

        seen = set()
        for cc in theo["corner_coaching"]:
            cid = _first_not_none(cc, "corner_id", "corner_index")
            if cid is not None and cid not in seen:
                seen.add(cid)
                apex_d = _first_not_none(cc, "s_apex", "distance_apex", "apex_distance_m")
                if apex_d is None:
                    s0 = _first_not_none(cc, "s_start", "distance_start")
                    s1 = _first_not_none(cc, "s_end", "distance_end")
                    if s0 is not None and s1 is not None:
                        apex_d = round((s0 + s1) / 2, 2)
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
                    "label": _first_not_none(cc, "label", "name"),
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

    # Normalize to per-lap 0-based distances
    if dist_a and len(dist_a) > 1 and dist_a[0] != 0:
        d0 = dist_a[0]
        dist_a = [d - d0 for d in dist_a]
    if dist_b and len(dist_b) > 1 and dist_b[0] != 0:
        d0 = dist_b[0]
        dist_b = [d - d0 for d in dist_b]

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
            "available": False,
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
        cp_data = _build_corner_positions(conn, session_id)
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

            if prev_time is not None and prev_time > 0:
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
            cid = _first_not_none(cc, "corner_id", "corner_index")
            if cid is None or cid in seen:
                continue
            if requested_corner_ids and cid not in requested_corner_ids:
                continue
            seen.add(cid)

            s_start = _first_not_none(cc, "s_start", "distance_start") or 0
            s_end = _first_not_none(cc, "s_end", "distance_end") or 0
            s_apex = _first_not_none(cc, "s_apex", "distance_apex", "apex_distance_m")
            dist_m = s_apex if s_apex is not None else (s_start + s_end) / 2

            corners.append({
                "corner_id": str(cid),
                "label": _first_not_none(cc, "label", "name") or f"C{cid}",
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
        "LEFT JOIN drivers d ON s.driver_id = d.driver_id "
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

    # Check for pre-computed V3 coaching first
    _analysis = models.get_analysis_json(conn, session_id)
    if _analysis and "coaching_v3" in _analysis:
        return api_response(_analysis["coaching_v3"])

    # Gather all available coaching inputs
    coaching_v2 = _analysis.get("coaching_v2") if _analysis else None

    # Corner data
    theo = models.get_theoretical_data(conn, session_id)
    corner_list = theo.get("corner_coaching", []) if theo else []

    # Scores
    score_rows = models.get_score_details(conn, session_id)
    scores: dict = {}
    if score_rows:
        row = score_rows[0] if isinstance(score_rows, list) else score_rows
        scores = dict(row) if not isinstance(row, dict) else row

    # Lap metrics
    laps = models.get_laps_for_session(conn, session_id)
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
    laps = models.get_laps_for_session(conn, session_id)
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
    return api_response({"saved": count})


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
        return api_error(ErrorCode.VALIDATION_ERROR, "No laps for session", status=400)

    trace = models.get_gps_trace(conn, session_id, best_lap)
    if trace is None:
        return api_error(ErrorCode.VALIDATION_ERROR, "No GPS trace for best lap", status=400)

    # 2. Reconstruct a best_lap DataFrame from stored trace data
    import numpy as np
    import pandas as pd

    distances = trace.get("distances", [])
    speeds = trace.get("speeds", [])
    lats = trace.get("latitudes", [])
    lons = trace.get("longitudes", [])

    if not distances or not speeds:
        return api_error(ErrorCode.VALIDATION_ERROR, "Insufficient trace data", status=400)

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
    try:
        from pipeline.stages import s10b_corners
    except ImportError:
        logger.error("Cannot import s10b_corners — pipeline module not available")
        return api_error(ErrorCode.INTERNAL_ERROR,
                         "Corner coaching module not available", status=500)

    # Load existing corners as fallback for when decompose_track returns 0
    fallback_corners = None
    theo = models.get_theoretical_data(conn, session_id)
    if theo and theo.get("corner_coaching"):
        fallback_corners = theo["corner_coaching"]

    try:
        v2_sections = s10b_corners.run_track_decomposition_v2(
            best_lap_df, conn=conn, session_id=session_id,
            fallback_corners=fallback_corners,
        )
    except Exception:
        logger.exception("Track decomposition failed for session %s", session_id)
        v2_sections = None

    if not v2_sections:
        return api_response({
            "status": "completed",
            "message": "No corner sections found (define corners or check data)",
            "corner_coaching_v2": [],
        })

    try:
        v2_mrp = s10b_corners.run_mrp_detection_v2(v2_sections, best_lap_df)
    except Exception:
        logger.exception("MRP detection failed for session %s", session_id)
        v2_mrp = None

    avail_cols = set(best_lap_df.columns)
    try:
        v2_handling = s10b_corners.run_handling_analysis_v2(
            v2_sections, best_lap_df, available_columns=avail_cols,
        )
    except Exception:
        logger.exception("Handling analysis failed for session %s", session_id)
        v2_handling = None

    try:
        v2_coaching = s10b_corners.run_coaching_v2(
            v2_sections, v2_mrp, v2_handling, best_lap_df,
            available_columns=avail_cols,
        )
    except Exception:
        logger.exception("Coaching v2 failed for session %s", session_id)
        v2_coaching = None

    # 4. Persist to analysis_json
    try:
        analysis = models.get_analysis_json(conn, session_id) or {}
        analysis["track_sections_v2"] = v2_sections
        if v2_mrp:
            analysis["mrp_events_v2"] = v2_mrp
        if v2_coaching:
            analysis["corner_coaching_v2"] = v2_coaching
        models.insert_analysis_json(conn, session_id, analysis)
        conn.commit()
    except Exception:
        logger.exception("Failed to persist recoach results for session %s", session_id)

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


# ══════════════════════════════════════════════════════════════════
# Annotations JSON API
# ══════════════════════════════════════════════════════════════════


@bp.route("/annotations", methods=["GET"])
@_safe_api
def list_annotations() -> tuple[dict, int]:
    """List all annotations across sessions, newest first.

    Query params:
        search (str)  — optional search filter
        limit  (int)  — max results (default 100, max 500)
    """
    conn = get_db_connection()
    search = request.args.get("search", "").strip()
    try:
        limit = min(int(request.args.get("limit", 100)), 500)
    except (ValueError, TypeError):
        limit = 100

    if search:
        from annotations import search_annotations
        rows = search_annotations(conn, search, limit=limit)
    else:
        raw = conn.execute(
            "SELECT sa.*, s.session_date, d.driver_name, t.track_name "
            "FROM session_annotations sa "
            "JOIN sessions s ON sa.session_id = s.session_id "
            "LEFT JOIN drivers d ON s.driver_id = d.driver_id "
            "LEFT JOIN tracks t ON s.track_id = t.track_id "
            "WHERE s.deleted_at IS NULL "
            "ORDER BY sa.created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        import json as _json
        rows = []
        for r in raw:
            d = dict(r)
            d["tags"] = _json.loads(d["tags_json"]) if d.get("tags_json") else []
            rows.append(d)

    # Map to the frontend's AnnotationRow interface
    annotations = []
    for row in rows:
        annotations.append({
            "id": row.get("id"),
            "session_id": row.get("session_id"),
            "session_label": (
                f"{row.get('driver_name', '')} — {row.get('track_name', 'Unknown')} "
                f"({row.get('session_date', '')})"
            ),
            "type": row.get("annotation_type", "note"),
            "text": row.get("body", ""),
            "timestamp_s": row.get("distance_m"),
            "created_at": row.get("created_at", ""),
        })

    return api_response({"annotations": annotations})


# ══════════════════════════════════════════════════════════════════
# Data Health JSON API
# ══════════════════════════════════════════════════════════════════


@bp.route("/data-health/stats", methods=["GET"])
@_safe_api
def data_health_stats() -> tuple[dict, int]:
    """Aggregate ingestion job statistics."""
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT "
            "  COUNT(*) AS total_files, "
            "  SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS success_count, "
            "  SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed_count "
            "FROM ingestion_jobs"
        ).fetchone()
    except Exception:
        # Table might not exist in SQLite mode
        return api_response({
            "total_files": 0, "success_count": 0,
            "failed_count": 0, "success_rate": 0, "avg_process_time_s": None,
        })

    d = dict(row) if row else {}
    total = d.get("total_files", 0) or 0
    success = d.get("success_count", 0) or 0
    return api_response({
        "total_files": total,
        "success_count": success,
        "failed_count": d.get("failed_count", 0) or 0,
        "success_rate": round(success / total * 100, 1) if total > 0 else 0,
        "avg_process_time_s": None,
    })


@bp.route("/data-health/jobs", methods=["GET"])
@_safe_api
def data_health_jobs() -> tuple[dict, int]:
    """List recent ingestion jobs."""
    conn = get_db_connection()
    try:
        limit = min(int(request.args.get("limit", 50)), 200)
    except (ValueError, TypeError):
        limit = 50

    try:
        rows = conn.execute(
            "SELECT * FROM ingestion_jobs "
            "ORDER BY COALESCE(started_at, '1970-01-01') DESC "
            "LIMIT ?",
            (limit,),
        ).fetchall()
    except Exception:
        return api_response({"jobs": []})

    jobs = []
    for r in rows:
        d = dict(r)
        # Handle SQLite (file_path/elapsed_s) vs PG (file_name/duration_s) columns
        fname = d.get("file_name") or ""
        if not fname and d.get("file_path"):
            import os as _os
            fname = _os.path.basename(d["file_path"])
        jobs.append({
            "id": d.get("job_id"),
            "file_name": fname,
            "status": d.get("status", "pending"),
            "started_at": d.get("started_at"),
            "completed_at": d.get("completed_at"),
            "duration_s": d.get("duration_s") or d.get("elapsed_s"),
            "peak_rss_mb": d.get("peak_rss_mb"),
            "throughput_mb_s": d.get("throughput_mb_s"),
            "error_message": d.get("error_message"),
        })

    return api_response({"jobs": jobs})


@bp.route("/data-health/jobs/<job_id>", methods=["GET"])
@_safe_api
def data_health_job_detail(job_id: str) -> tuple[dict, int]:
    """Get detail for a single ingestion job."""
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT * FROM ingestion_jobs WHERE job_id = ?",
            (job_id,),
        ).fetchone()
    except Exception:
        return api_error(ErrorCode.NOT_FOUND, "Job not found", status=404)

    if row is None:
        return api_error(ErrorCode.NOT_FOUND, "Job not found", status=404)

    d = dict(row)
    # Handle SQLite (file_path/file_size/elapsed_s/sha256) vs PG columns
    fname = d.get("file_name") or ""
    if not fname and d.get("file_path"):
        import os as _os
        fname = _os.path.basename(d["file_path"])
    file_size = d.get("file_size_bytes") or d.get("file_size")
    return api_response({
        "id": d.get("job_id"),
        "file_name": fname,
        "file_size_mb": round(file_size / (1024 * 1024), 2) if file_size else None,
        "status": d.get("status", "pending"),
        "started_at": d.get("started_at"),
        "completed_at": d.get("completed_at"),
        "duration_s": d.get("duration_s") or d.get("elapsed_s"),
        "peak_rss_mb": d.get("peak_rss_mb"),
        "throughput_mb_s": d.get("throughput_mb_s"),
        "rows_processed": d.get("rows_processed") or d.get("n_rows_loaded"),
        "chunks_written": d.get("chunks_written") or d.get("n_chunks"),
        "checksum": d.get("checksum_sha256") or d.get("sha256"),
        "error_message": d.get("error_message"),
        "session_id": d.get("session_id"),
    })


# ══════════════════════════════════════════════════════════════════
# Setup Status JSON API
# ══════════════════════════════════════════════════════════════════


@bp.route("/setup/status", methods=["GET"])
@_safe_api
def setup_status() -> tuple[dict, int]:
    """Return setup completion status based on actual data.

    Checks whether the user has: uploaded sessions, configured tracks,
    configured drivers, run analysis, compared sessions, etc.
    """
    conn = get_db_connection()

    steps = []

    # Always complete — they're on the app
    steps.append({"id": "create_account", "status": "complete"})

    # Check if any sessions exist
    session_row = conn.execute(
        "SELECT COUNT(*) AS n FROM sessions WHERE deleted_at IS NULL"
    ).fetchone()
    has_sessions = (dict(session_row).get("n", 0) or 0) > 0
    steps.append({"id": "upload_session", "status": "complete" if has_sessions else "pending"})

    # Check if tracks are configured (named, not "Unknown")
    track_row = conn.execute(
        "SELECT COUNT(*) AS n FROM tracks WHERE track_name NOT LIKE '%nknown%'"
    ).fetchone()
    has_tracks = (dict(track_row).get("n", 0) or 0) > 0
    steps.append({"id": "configure_tracks", "status": "complete" if has_tracks else "pending"})

    # Check if drivers exist
    driver_row = conn.execute("SELECT COUNT(*) AS n FROM drivers").fetchone()
    has_drivers = (dict(driver_row).get("n", 0) or 0) > 0
    steps.append({"id": "configure_drivers", "status": "complete" if has_drivers else "pending"})

    # Check if analysis has run (sessions with scores)
    score_row = conn.execute(
        "SELECT COUNT(*) AS n FROM sessions WHERE total_score IS NOT NULL AND deleted_at IS NULL"
    ).fetchone()
    has_analysis = (dict(score_row).get("n", 0) or 0) > 0
    steps.append({"id": "run_analysis", "status": "complete" if has_analysis else "pending"})

    # View dashboard — same as having sessions
    steps.append({"id": "view_dashboard", "status": "complete" if has_sessions else "pending"})

    # Compare sessions — need 2+ sessions
    multi_sessions = (dict(session_row).get("n", 0) or 0) >= 2
    steps.append({"id": "compare_sessions", "status": "complete" if multi_sessions else "pending"})

    # Kart setup
    try:
        kart_row = conn.execute("SELECT COUNT(*) AS n FROM karts").fetchone()
        has_karts = (dict(kart_row).get("n", 0) or 0) > 0
    except Exception:
        has_karts = False
    steps.append({"id": "setup_kart", "status": "complete" if has_karts else "pending"})

    # Race strategy
    try:
        strat_row = conn.execute("SELECT COUNT(*) AS n FROM race_configs").fetchone()
        has_strategy = (dict(strat_row).get("n", 0) or 0) > 0
    except Exception:
        has_strategy = False
    steps.append({"id": "create_strategy", "status": "complete" if has_strategy else "pending"})

    # Export data — check if any export templates exist or sessions have reports
    try:
        export_row = conn.execute(
            "SELECT COUNT(*) AS n FROM sessions WHERE html_report_path IS NOT NULL AND deleted_at IS NULL"
        ).fetchone()
        has_exports = (dict(export_row).get("n", 0) or 0) > 0
    except Exception:
        has_exports = False
    steps.append({"id": "export_data", "status": "complete" if has_exports else "pending"})

    return api_response({"steps": steps})


# ══════════════════════════════════════════════════════════════════
# ENDURANCE REPORT ENDPOINTS
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/stints", methods=["GET"])
@_safe_api
def get_session_stints(session_id: str) -> tuple[dict, int]:
    """Return detected stints for a session with per-stint stats."""
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    from web.repos.endurance_repo import get_stints, get_endurance_config

    stints = get_stints(conn, session_id)
    config = get_endurance_config(conn, session_id)

    # Enrich with per-stint stats from laps table
    laps = models.get_laps_for_session(conn, session_id)
    for stint in stints:
        stint_laps = [
            l for l in laps
            if stint["start_lap"] <= l["lap_number"] <= stint["end_lap"]
            and l.get("is_valid")
            and l.get("lap_time_s") and l["lap_time_s"] > 0
        ]
        if stint_laps:
            times = [l["lap_time_s"] for l in stint_laps]
            stint["best_lap_s"] = round(min(times), 3)
            stint["mean_lap_s"] = round(sum(times) / len(times), 3)

    return api_response({
        "stints": stints,
        "pit_threshold_s": config["pit_threshold_s"],
        "total_stints": len(stints),
    })


@bp.route("/sessions/<session_id>/stints/configure", methods=["POST"])
@_safe_api
def configure_stints(session_id: str) -> tuple[dict, int]:
    """Re-detect stints with a new pit threshold."""
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    body = request.get_json(silent=True) or {}
    threshold = body.get("pit_threshold_s")
    if threshold is None or not isinstance(threshold, (int, float)) or threshold <= 0:
        return api_error(ErrorCode.VALIDATION_ERROR, "pit_threshold_s must be a positive number", status=400)

    # Get lap times from DB
    laps = models.get_laps_for_session(conn, session_id)
    lap_times = {
        l["lap_number"]: l["lap_time_s"]
        for l in laps
        if l.get("lap_time_s") and l["lap_time_s"] > 0
    }

    from web.repos.endurance_repo import detect_and_store_stints
    stints = detect_and_store_stints(conn, session_id, lap_times, float(threshold))

    return api_response({
        "stints": stints,
        "pit_threshold_s": float(threshold),
        "total_stints": len(stints),
    })


@bp.route("/sessions/<session_id>/stints/assign", methods=["POST"])
@_safe_api
def assign_stint_drivers(session_id: str) -> tuple[dict, int]:
    """Assign drivers and conditions to stints."""
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    body = request.get_json(silent=True) or {}
    assignments = body.get("assignments")
    if not assignments or not isinstance(assignments, list):
        return api_error(ErrorCode.VALIDATION_ERROR, "assignments must be a non-empty list", status=400)

    from web.repos.endurance_repo import bulk_assign_drivers
    count = bulk_assign_drivers(conn, session_id, assignments)

    return api_response({"assigned": count})


@bp.route("/sessions/<session_id>/endurance-report", methods=["GET"])
@_safe_api
def get_endurance_report(session_id: str) -> tuple[dict, int]:
    """Return the 3-tier endurance report (team + per-driver + per-stint).

    Requires driver assignments to be set first.
    """
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    from web.repos.endurance_repo import get_stints
    from endurance_scoring import compute_stint_scores, compute_driver_report, compute_team_report

    stints = get_stints(conn, session_id)
    if not stints:
        return api_error(ErrorCode.VALIDATION_ERROR, "No stints detected. Upload or configure first.", status=400)

    # Check at least one driver assigned
    assigned = [s for s in stints if s.get("driver_name")]
    if not assigned:
        return api_error(ErrorCode.VALIDATION_ERROR, "No drivers assigned to stints. Use /stints/assign first.", status=400)

    # Get all laps
    laps = models.get_laps_for_session(conn, session_id)
    all_laps = [dict(l) for l in laps]

    # Score each stint
    stint_scores = {}
    for stint in stints:
        condition = stint.get("condition") or "dry"
        stint_scores[stint["stint_number"]] = compute_stint_scores(all_laps, stint, condition)

    # Group stints by driver
    driver_stints: dict[str, list] = {}
    for stint in stints:
        driver = stint.get("driver_name")
        if not driver:
            continue
        if driver not in driver_stints:
            driver_stints[driver] = []
        scored = stint_scores.get(stint["stint_number"], {})
        scored["driver_name"] = driver
        scored["condition"] = stint.get("condition")
        scored["start_lap"] = stint["start_lap"]
        scored["end_lap"] = stint["end_lap"]
        scored["pit_lap_time_s"] = stint.get("pit_lap_time_s")
        driver_stints[driver].append(scored)

    # Build per-driver reports
    driver_reports = {}
    for driver, scored_stints in driver_stints.items():
        driver_reports[driver] = compute_driver_report(driver, scored_stints)

    # Total race stats
    valid_laps = [l for l in all_laps if l.get("is_valid") and l.get("lap_time_s") and l["lap_time_s"] > 0]
    total_laps = len(valid_laps)
    total_time = sum(l["lap_time_s"] for l in valid_laps)

    team = compute_team_report(driver_reports, total_laps, len(stints), total_time)

    return api_response({
        "team": team,
        "drivers": driver_reports,
        "stints": stint_scores,
    })


# ══════════════════════════════════════════════════════════════════
# POST /api/v1/sessions/<id>/endurance-race — create race from session
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/endurance-race", methods=["POST"])
@_safe_api
def create_endurance_race(session_id: str) -> tuple[dict, int]:
    """Create a retrospective race config from endurance session stints."""
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    data = request.get_json(silent=True)
    if not data:
        return api_error(ErrorCode.VALIDATION_ERROR, "JSON body is required", status=400)

    race_meta = data.get("race", {})
    raw_driver_map = data.get("driver_map")
    if not raw_driver_map or not isinstance(raw_driver_map, dict):
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            "driver_map is required: {stint_number: driver_name}",
            status=400,
        )

    # Convert string keys to int (JSON keys are always strings)
    try:
        driver_map = {int(k): v for k, v in raw_driver_map.items()}
    except (ValueError, TypeError):
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            "driver_map keys must be stint numbers (integers)",
            status=400,
        )

    try:
        from services.race_strategy_bridge import create_race_from_session

        race_id = create_race_from_session(
            conn, session_id, race_meta, driver_map,
            max_duration_s=data.get("max_duration_s"),
        )
        return api_response({"race_id": race_id}, status=201)
    except ValueError as ve:
        return api_error(ErrorCode.VALIDATION_ERROR, str(ve), status=400)


# ══════════════════════════════════════════════════════════════════
# GET /api/v1/sessions/<id>/endurance-live — live endurance state
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/endurance-live", methods=["GET"])
@_safe_api
def get_endurance_live(session_id: str) -> tuple[dict, int]:
    """Compute live endurance state from stints + anchor."""
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    from datetime import datetime, timezone
    from web.repos.endurance_repo import get_race_anchor, get_stints

    stints = get_stints(conn, session_id)
    anchor = get_race_anchor(conn, session_id)

    # No anchor → 404 so frontend shows setup form
    if not anchor or not anchor.get("race_start_iso"):
        return api_error(ErrorCode.NOT_FOUND, "No race anchor set for this session", status=404)

    # Compute elapsed time from anchor
    elapsed_s = 0
    try:
        iso = anchor["race_start_iso"]
        start = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        elapsed_s = max(0, int((datetime.now(timezone.utc) - start).total_seconds()))
    except Exception:
        elapsed_s = 0

    # Compute per-stint lap stats
    all_laps = models.get_laps_for_session(conn, session_id)
    completed_stints = []
    current_stint = None
    total_laps = 0
    for stint in stints:
        stint_laps = [
            lap for lap in all_laps
            if stint["start_lap"] <= lap["lap_number"] <= stint["end_lap"]
            and lap.get("is_valid", True)
            and lap.get("lap_time_s") and lap["lap_time_s"] > 0
        ]
        times = [lap["lap_time_s"] for lap in stint_laps]
        total_laps += len(times)

        # Compute stint elapsed time from lap times
        stint_elapsed_s = int(sum(times)) if times else 0

        stint_info = {
            "stint_number": stint["stint_number"],
            "driver_name": stint.get("driver_name"),
            "start_lap": stint["start_lap"],
            "lap_count": len(times),
            "laps_completed": len(times),
            "best_lap_s": round(min(times), 3) if times else None,
            "stint_elapsed_s": stint_elapsed_s,
        }

        # Last stint without pit_lap is "current", others are "completed"
        if stint.get("pit_lap_number") is None and stint == stints[-1]:
            current_stint = stint_info
        else:
            completed_stints.append(stint_info)

    # Estimate next pit lap from pit threshold and current stint
    next_pit_lap = None
    if current_stint and stints:
        avg_lap = None
        if times:
            avg_lap = sum(times) / len(times)
        # No reliable prediction without average lap time

    return api_response({
        "race_start_iso": anchor["race_start_iso"],
        "elapsed_s": elapsed_s,
        "current_stint": current_stint,
        "completed_stints": completed_stints,
        "next_pit_lap": next_pit_lap,
    })


# ══════════════════════════════════════════════════════════════════
# POST /api/v1/sessions/<id>/endurance-anchor — store race start
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/endurance-anchor", methods=["POST"])
@_safe_api
def set_endurance_anchor(session_id: str) -> tuple[dict, int]:
    """Store or update the race start time anchor for live tracking."""
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    data = request.get_json(silent=True)
    if not data:
        return api_error(ErrorCode.VALIDATION_ERROR, "JSON body is required", status=400)

    race_start_iso = data.get("race_start_iso")
    if not race_start_iso:
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            "race_start_iso is required",
            status=400,
        )

    # Validate ISO-8601
    from datetime import datetime
    try:
        datetime.fromisoformat(race_start_iso.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            "race_start_iso must be a valid ISO-8601 datetime",
            status=400,
        )

    lap_duration_s = data.get("lap_duration_s")
    if lap_duration_s is not None:
        try:
            lap_duration_s = float(lap_duration_s)
        except (ValueError, TypeError):
            return api_error(
                ErrorCode.VALIDATION_ERROR,
                "lap_duration_s must be a number",
                status=400,
            )

    from web.repos.endurance_repo import upsert_race_anchor
    upsert_race_anchor(conn, session_id, race_start_iso, lap_duration_s)

    return api_response({"ok": True}, status=201)


# ── Reveal payload builder ────────────────────────────────────────


def _build_reveal_payload(
    session: dict,
    scores: dict | None,
    theo_data: dict | None,
    analysis: dict | None,
) -> dict:
    """Assemble the reveal payload from pre-fetched data.

    All inputs are dicts as returned by the repo functions.
    Returns a dict matching the reveal API contract.
    """
    result: dict = {
        "total_score": session.get("total_score"),
        "grade": session.get("grade"),
        "best_lap_s": session.get("best_lap_time_s"),
        "n_laps": session.get("n_laps"),
        "track_name": session.get("track_name"),
        "session_date": session.get("session_date"),
    }

    # ── Top corners (from theoretical_data.corner_coaching) ──
    corner_coaching = (theo_data or {}).get("corner_coaching", []) or []
    # Filter corners with positive time loss, sort desc
    lossy = [c for c in corner_coaching
             if (c.get("time_loss_total_s") or 0) > 0]
    lossy.sort(key=lambda c: c.get("time_loss_total_s", 0), reverse=True)

    result["top_corners"] = []
    for c in lossy[:3]:
        hints = c.get("coaching_hints") or []
        result["top_corners"].append({
            "corner_id": c.get("corner_id"),
            "direction": c.get("direction"),
            "time_loss_s": round(c.get("time_loss_total_s", 0), 3),
            "coaching_hint": hints[0] if hints else None,
        })

    result["recoverable_s"] = (
        round(sum(c.get("time_loss_total_s", 0) for c in lossy), 3)
        if lossy else None
    )

    # ── Focus areas (prefer coaching_v3 > coaching_v2 > scores.weaknesses) ──
    analysis = analysis or {}
    coaching = analysis.get("coaching_v3") or analysis.get("coaching_v2") or {}
    raw_focus = coaching.get("focus_areas", []) if coaching else []

    if raw_focus:
        # Sort by time_loss_s desc if available, take top 3
        sorted_fa = sorted(raw_focus, key=lambda f: f.get("time_loss_s", 0), reverse=True)
        result["focus_areas"] = [
            {"category": f.get("category", "general"), "summary": f.get("summary", "")}
            for f in sorted_fa[:3]
        ]
    else:
        # Fallback to scores.weaknesses (plain strings)
        weaknesses = (scores or {}).get("weaknesses", []) or []
        result["focus_areas"] = [
            {"category": "general", "summary": w}
            for w in weaknesses[:3]
        ]

    # ── Drills (prefer coaching_v3 > coaching_v2) ──
    raw_drills = coaching.get("drills", []) if coaching else []
    if raw_drills:
        sorted_drills = sorted(raw_drills, key=lambda d: d.get("rank", 999))
        result["drills"] = [
            {"title": d.get("title", ""), "target_improvement": d.get("target_improvement", "")}
            for d in sorted_drills[:3]
        ]
    else:
        result["drills"] = []

    # ── Confidence (from theoretical_metrics) ──
    theo_metrics = (theo_data or {}).get("theoretical_metrics", {}) or {}
    conf = theo_metrics.get("confidence")
    if conf and isinstance(conf, dict):
        result["confidence"] = {
            "score": conf.get("confidence_score"),
            "level": conf.get("confidence_level"),
        }
    else:
        result["confidence"] = None

    return result


# ── GET /api/v1/sessions/<id>/reveal ──────────────────────────────────


@bp.route("/sessions/<session_id>/reveal", methods=["GET"])
@_safe_api
def get_reveal(session_id: str) -> tuple[dict, int]:
    """Return a lightweight reveal payload for post-upload display."""
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    scores = models.get_score_details(conn, session_id)
    theo_data = models.get_theoretical_data(conn, session_id)
    analysis = models.get_analysis_json(conn, session_id)

    payload = _build_reveal_payload(session, scores, theo_data, analysis)
    return api_response(payload)


# Dev-plans endpoints moved to api_v1_entities.py (Task 5).
