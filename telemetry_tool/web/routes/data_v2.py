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
from web import models

logger = logging.getLogger(__name__)


def _safe_api(f):
    """Catch unhandled exceptions in API routes — log + return structured error."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except Exception:
            logger.exception("Unhandled error in %s", f.__name__)
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
        }
        for s in recent[:10]  # Table shows 10 most recent
    ]

    return api_response({
        "total_sessions": stats.get("total_sessions", 0),
        "total_drivers": stats.get("total_drivers", 0),
        "total_tracks": stats.get("total_tracks", 0),
        "total_laps": stats.get("total_laps", 0) or 0,
        "pb_time": stats.get("overall_best_time_s"),
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
    """List sessions with pagination.

    Query params:
        limit  (int, default 25)
        offset (int, default 0)
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

    conn = get_db_connection()
    sessions = models.get_sessions(conn, limit=limit, offset=offset)
    total = models.count_sessions(conn)

    return api_response({
        "sessions": sessions,
        "total": total,
        "limit": limit,
        "offset": offset,
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
    return api_response(session)


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
    """
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    lap_num = _get_lap_param(conn, session_id)
    if lap_num is None:
        return api_error(ErrorCode.NOT_FOUND, "No laps available", status=404)

    trace = models.get_gps_trace(conn, session_id, lap_num)
    if trace is None:
        return api_error(
            ErrorCode.NOT_FOUND,
            f"No trace data for lap {lap_num}",
            status=404,
        )

    return api_response({
        "distances": trace.get("distances", []),
        "speeds": trace.get("speeds", []),
        "lap_number": lap_num,
    })


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
        return api_error(ErrorCode.NOT_FOUND, "No laps available", status=404)

    trace = models.get_gps_trace(conn, session_id, lap_num)
    if trace is None:
        return api_error(
            ErrorCode.NOT_FOUND,
            f"No GPS trace for lap {lap_num}",
            status=404,
        )

    return api_response({
        "lat": trace.get("latitudes", []),
        "lon": trace.get("longitudes", []),
        "distances": trace.get("distances", []),
        "speeds": trace.get("speeds", []),
        "lap_number": lap_num,
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
        return api_error(ErrorCode.NOT_FOUND, "No laps available", status=404)

    trace = models.get_gps_trace(conn, session_id, lap_num)
    if trace is None:
        return api_error(
            ErrorCode.NOT_FOUND,
            f"No trace data for lap {lap_num}",
            status=404,
        )

    lat_g = trace.get("accel_lat")
    lon_g = trace.get("accel_long")
    if not lat_g or not lon_g:
        return api_error(
            ErrorCode.NOT_FOUND,
            f"No acceleration data for lap {lap_num}",
            status=404,
        )

    return api_response({
        "lat_g": lat_g,
        "lon_g": lon_g,
        "lap_number": lap_num,
    })


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
        return api_error(
            ErrorCode.NOT_FOUND,
            "No score details for this session",
            status=404,
        )

    return api_response(scores)


# ══════════════════════════════════════════════════════════════════
# 8. GET /api/v1/sessions/<id>/corners
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/corners", methods=["GET"])
@_safe_api
def get_corners(session_id: str):
    """Return corner coaching data for a session.

    Corner coaching is stored inside the theoretical_data table as
    a JSON field (corner_coaching_json).
    """
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    theo = models.get_theoretical_data(conn, session_id)
    if theo is None:
        return api_error(
            ErrorCode.NOT_FOUND,
            "No theoretical data for this session",
            status=404,
        )

    corners = theo.get("corner_coaching")
    if not corners:
        return api_error(
            ErrorCode.NOT_FOUND,
            "No corner coaching data for this session",
            status=404,
        )

    return api_response({"corners": corners})


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
    conn.commit()

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


# Fields the PATCH endpoint accepts directly.
_UPDATABLE_FIELDS = {"session_type", "track_state", "notes"}


@bp.route("/sessions/<session_id>", methods=["PATCH"])
@_safe_api
def update_session(session_id: str):
    """Update editable fields on a session.

    Accepts JSON body with any of: session_type, track_state,
    driver_name, notes.  Unknown fields are silently ignored.
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

    updated_count = 0

    # Handle driver_name specially — upsert driver, then update driver_id.
    driver_name = body.get("driver_name")
    if driver_name and isinstance(driver_name, str):
        driver_id = models.upsert_driver(conn, driver_name)
        models.update_session_field(conn, session_id, "driver_id", driver_id)
        updated_count += 1

    # Handle the straightforward fields.
    for field in _UPDATABLE_FIELDS:
        if field in body:
            models.update_session_field(conn, session_id, field, body[field])
            updated_count += 1

    if updated_count == 0:
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            "No updatable fields provided. "
            "Allowed: session_type, track_state, driver_name, notes",
            status=400,
        )

    conn.commit()

    # Re-fetch and return the updated session.
    updated = models.get_session_by_id(conn, session_id)
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
        return api_error(ErrorCode.NOT_FOUND,
                         "No theoretical data for this session", status=404)

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
        return api_error(ErrorCode.NOT_FOUND,
                         "No reference line for this session", status=404)

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
        return api_error(ErrorCode.NOT_FOUND, "No laps available", status=404)

    trace = models.get_gps_trace(conn, session_id, lap_num)
    if trace is None:
        return api_error(ErrorCode.NOT_FOUND,
                         f"No GPS trace for best lap {lap_num}", status=404)

    return api_response({
        "lat": trace.get("latitudes", []),
        "lon": trace.get("longitudes", []),
        "distances": trace.get("distances", []),
        "speeds": trace.get("speeds", []),
        "lap_number": lap_num,
    })


# ══════════════════════════════════════════════════════════════════
# 16. GET /api/v1/sessions/<id>/corner-positions
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/corner-positions", methods=["GET"])
@_safe_api
def get_corner_positions(session_id: str):
    """Return corner GPS positions from theoretical data or corner_metrics."""
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    # Try corner coaching from theoretical data (has positions)
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
                })

    if not corners:
        # Fall back to corner_metrics summary (unique corner_ids)
        summary = models.get_corner_metrics_summary(conn, session_id)
        for row in summary:
            corners.append({
                "corner_id": row["corner_id"],
                "s_start": None,
                "s_end": None,
                "s_apex": None,
                "direction": None,
                "label": None,
            })

    if not corners:
        return api_error(ErrorCode.NOT_FOUND,
                         "No corner position data for this session", status=404)

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
    if not metrics:
        return api_error(ErrorCode.NOT_FOUND,
                         "No corner metrics for this session", status=404)

    return api_response({"corners": metrics})


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
    if not summary:
        return api_error(ErrorCode.NOT_FOUND,
                         "No corner metrics for this session", status=404)

    return api_response({"corners": summary})


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
        return api_error(ErrorCode.NOT_FOUND,
                         "GPS trace not found for one or both laps", status=404)

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
        return api_error(ErrorCode.NOT_FOUND,
                         "Insufficient trace data for delta computation",
                         status=404)

    time_a = _cumulative_time(dist_a, spd_a)
    time_b = _cumulative_time(dist_b, spd_b)

    # Interpolate to common distance axis (use shorter lap)
    import numpy as np
    max_dist = min(dist_a[-1] if dist_a else 0, dist_b[-1] if dist_b else 0)
    if max_dist <= 0:
        return api_error(ErrorCode.NOT_FOUND,
                         "No valid distance range for delta", status=404)

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
        return api_error(ErrorCode.NOT_FOUND,
                         "No score data for fingerprint", status=404)

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
        return api_error(ErrorCode.NOT_FOUND,
                         "No driver linked to this session", status=404)

    style = models.get_driving_style(conn, driver_id, session_id)
    if style is None:
        return api_error(ErrorCode.NOT_FOUND,
                         "No driving style data for this session", status=404)

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
        return api_error(ErrorCode.NOT_FOUND,
                         "No valid lap times for distribution", status=404)

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
        return api_error(ErrorCode.NOT_FOUND,
                         "No valid lap times for progress", status=404)

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
        return api_error(ErrorCode.NOT_FOUND, "No laps available", status=404)

    trace = models.get_gps_trace(conn, session_id, lap_num)
    if trace is None:
        return api_error(ErrorCode.NOT_FOUND,
                         f"No trace for lap {lap_num}", status=404)

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
        return api_error(ErrorCode.NOT_FOUND,
                         "No corner metrics for brake precision", status=404)

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

    return api_error(ErrorCode.NOT_FOUND,
                     "No stint analysis for this session", status=404)


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
        return api_response(analysis["sector_analysis"])

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

    return api_error(ErrorCode.NOT_FOUND,
                     "No sector analysis for this session", status=404)
