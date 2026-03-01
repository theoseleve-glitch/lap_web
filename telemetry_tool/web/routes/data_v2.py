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

import logging
from pathlib import Path

from flask import Blueprint, request, send_file

from web.api_utils import api_error, api_response, ErrorCode
from web.db import get_db_connection
from web import models

logger = logging.getLogger(__name__)

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
