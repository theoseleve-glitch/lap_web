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
    PATCH  /api/v1/sessions/<id>                    - Update session fields
"""
from __future__ import annotations

import json
import logging
import math
from functools import wraps
from pathlib import Path

from flask import Blueprint, request, send_file

from web.api_utils import api_error, api_response, ErrorCode
from web.db import get_db_connection
from web.middleware.audit import audit_log
from web import models

logger = logging.getLogger(__name__)


def _safe_api(f):
    """Catch unhandled exceptions in API routes — log + return structured error."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except Exception:
            from flask import g
            req_id = getattr(g, "request_id", "?")
            logger.exception(
                "Unhandled error in %s [%s %s] request_id=%s",
                f.__name__, request.method, request.path, req_id,
            )
            return api_error(ErrorCode.INTERNAL_ERROR,
                             "Internal server error", status=500)
    return wrapper

bp = Blueprint("data_v2", __name__, url_prefix="/api/v1")


# ── Helpers ───────────────────────────────────────────────────────


def _resolve_lap_number(conn, session_id: str) -> int | None:
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


def _get_lap_param(conn, session_id: str) -> int | None:
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
def dashboard_stats():
    """Return aggregate dashboard statistics.

    Returns total_sessions, total_drivers, total_tracks, total_laps,
    pb_time, avg_score, best_score, plus recent_scores, recent_times,
    and recent_sessions for sparkline and table display.
    """
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

    return api_response({
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
    })


# ══════════════════════════════════════════════════════════════════
# 1. GET /api/v1/sessions — List sessions
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions", methods=["GET"])
@_safe_api
def list_sessions():
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
def session_filter_options():
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
def get_session(session_id: str):
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
    return api_response(result)


# ══════════════════════════════════════════════════════════════════
# 3. GET /api/v1/sessions/<id>/laps — Lap list
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/laps", methods=["GET"])
@_safe_api
def get_laps(session_id: str):
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
def get_speed_trace(session_id: str):
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

    result = {
        "distances": trace.get("distances", []),
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

    return api_response(result)


# ══════════════════════════════════════════════════════════════════
# 5. GET /api/v1/sessions/<id>/gps-trace?lap=N
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/gps-trace", methods=["GET"])
@_safe_api
def get_gps_trace(session_id: str):
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

    return api_response({
        "latitudes": trace.get("latitudes", []),
        "longitudes": trace.get("longitudes", []),
        "distances": trace.get("distances", []),
        "speeds": trace.get("speeds", []),
        "lap_number": lap_num,
        "available": True,
    })


# ══════════════════════════════════════════════════════════════════
# 6. GET /api/v1/sessions/<id>/gg-data?lap=N
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/gg-data", methods=["GET"])
@_safe_api
def get_gg_data(session_id: str):
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
def get_scores(session_id: str):
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

    return api_response(scores)


# ══════════════════════════════════════════════════════════════════
# 8. GET /api/v1/sessions/<id>/corners
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/corners", methods=["GET"])
@_safe_api
def get_corners(session_id: str):
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

        return api_response({
            "corners": corners,
            "available": True,
        })

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

        return api_response({
            "corners": corners,
            "available": True,
        })

    # -- 6. No data at all -----------------------------------------------
    return api_response({
        "corners": [],
        "available": False,
        "reason_code": "NO_CORNER_DATA",
        "message": "Corner detection did not produce results for this session",
    })


# ══════════════════════════════════════════════════════════════════
# 9. DELETE /api/v1/sessions/<id>
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>", methods=["DELETE"])
@_safe_api
def delete_session(session_id: str):
    """Delete a session and all related data."""
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    # Delete from all related tables first (foreign key order).
    # Table names are from the hardcoded _DELETE_RELATED_TABLES constant above.
    for table in _DELETE_RELATED_TABLES:
        assert table in _ALLOWED_DELETE_TABLES, f"Unexpected table: {table}"
        try:
            conn.execute(
                f"DELETE FROM {table} WHERE session_id = :session_id",
                {"session_id": session_id},
            )
        except Exception as exc:
            # Table might not exist in older schema versions — skip
            logger.debug("Skipping delete from %s: %s", table, exc)

    # Delete the session itself.
    conn.execute(
        "DELETE FROM sessions WHERE session_id = :session_id",
        {"session_id": session_id},
    )

    audit_log(
        conn,
        "session.delete",
        {
            "session_id": session_id,
            "tables_cleaned": list(_DELETE_RELATED_TABLES),
        },
    )

    conn.commit()

    try:
        from flask import g
        from telemetry_tool.web.rollups import refresh_rollups
        refresh_rollups(conn, int(g.workspace_id))
    except Exception:
        logger.warning("Rollup refresh failed after delete", exc_info=True)

    logger.info("Deleted session %s and related data", session_id)
    return api_response({"deleted": session_id})


# ══════════════════════════════════════════════════════════════════
# 10. GET /api/v1/compare/sessions?a=X&b=Y — Session comparison
# ══════════════════════════════════════════════════════════════════


@bp.route("/compare/sessions", methods=["GET"])
@_safe_api
def compare_sessions():
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
# 10b. GET /api/v1/compare/drivers?a=X&b=Y — Driver comparison
# ══════════════════════════════════════════════════════════════════


def _driver_data(conn, driver_id: int) -> dict | None:
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
def compare_drivers():
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
def get_report(session_id: str):
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
# 12. PATCH /api/v1/sessions/<id> — Update session fields
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


def _validate_patch_fields(conn, body: dict) -> tuple[list[dict], dict]:
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
def update_session(session_id: str):
    """Update editable fields on a session.

    Accepts JSON body with any of: session_type, track_state,
    driver_name, driver_id, track_id, kart_id, session_date,
    display_name, notes.  Unknown fields are silently ignored.
    Validation is performed before any writes.
    """
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
# 13. GET /api/v1/sessions/<id>/theoretical
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/theoretical", methods=["GET"])
@_safe_api
def get_theoretical(session_id: str):
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
def get_reference_line(session_id: str):
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
def get_best_lap_gps(session_id: str):
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


def _closest_index(distances, target):
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
def get_corner_positions(session_id: str):
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
def get_corner_metrics(session_id: str):
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
def get_corner_metrics_summary(session_id: str):
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
def get_delta(session_id: str):
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
    def _cumulative_time(distances, speeds):
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
def get_fingerprint(session_id: str):
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
    def _pct(val, mx):
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
def get_driving_style(session_id: str):
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
def get_lap_distribution(session_id: str):
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
def get_lap_progress(session_id: str):
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
def get_speed_profile(session_id: str):
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
def get_brake_precision(session_id: str):
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
def get_stint_analysis(session_id: str):
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
def get_sector_times(session_id: str):
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
def get_track_map(session_id: str):
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
def get_sectors(session_id: str):
    """Alias for sector_times — returns sector analysis."""
    return get_sector_times(session_id)


# ══════════════════════════════════════════════════════════════════
# 30. GET /api/v1/sessions/<id>/compare?sessionKeyB=...
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/compare", methods=["GET"])
@_safe_api
def get_session_compare_overlay(session_id: str):
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
    def _cum_time(dists, speeds):
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


def _safe_float(val, default=None):
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
def get_session_compare_sectors(session_id: str):
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
def get_corner_replay_data(session_id: str):
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
def get_corner_mastery(session_id: str):
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
def get_condition_phases(session_id: str):
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
def get_throttle_onset(session_id: str):
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
def get_consistency_heatmap(session_id: str):
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
def get_session_timeline(session_id: str):
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
def get_sector_analysis(session_id: str):
    """Alias for sector_times — desktop tool vanilla JS uses this path."""
    return get_sector_times(session_id)


# ══════════════════════════════════════════════════════════════════
# 41. GET /api/v1/sessions/<id>/comparison-matrix
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/comparison-matrix", methods=["GET"])
@_safe_api
def get_comparison_matrix(session_id: str):
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
def get_cross_session(session_id: str):
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

    return api_response({
        "sessions": traces,
        "available": len(traces) >= 1,
        "focus_session_id": session_id,
    })


# Dev-plans endpoints moved to api_v1_entities.py (Task 5).
