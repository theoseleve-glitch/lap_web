"""Export and report generation routes."""

from __future__ import annotations

from flask import Blueprint, render_template, abort

from web.db import get_db_connection
from web.models import get_session_by_id

bp = Blueprint("exports", __name__, url_prefix="/exports")


@bp.route("/")
def export_index():
    """List sessions available for export."""
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT s.session_id, s.session_date, s.session_type, "
        "       s.best_lap_time_s, s.total_score, s.lap_count, "
        "       d.driver_name, t.track_name "
        "FROM sessions s "
        "JOIN drivers d ON s.driver_id = d.driver_id "
        "LEFT JOIN tracks t ON s.track_id = t.track_id "
        "ORDER BY s.session_date DESC"
    ).fetchall()
    sessions = [dict(r) for r in rows]
    return render_template("exports.html", sessions=sessions)


@bp.route("/session/<session_id>")
def export_builder(session_id: str):
    """Show export builder for a session."""
    conn = get_db_connection()
    session = get_session_by_id(conn, session_id)
    if not session:
        abort(404)

    # Available sections for export
    sections = [
        {"id": "summary", "name": "Session Summary", "default": True},
        {"id": "lap_times", "name": "Lap Times Table", "default": True},
        {"id": "score_breakdown", "name": "Score Breakdown", "default": True},
        {"id": "speed_trace", "name": "Speed Trace Chart", "default": True},
        {"id": "gps_map", "name": "GPS Track Map", "default": False},
        {"id": "gg_diagram", "name": "G-G Diagram", "default": False},
        {"id": "corner_coaching", "name": "Corner Coaching", "default": False},
        {"id": "brake_precision", "name": "Brake Precision", "default": False},
        {"id": "throttle_map", "name": "Throttle Map", "default": False},
        {"id": "consistency_heatmap", "name": "Consistency Heatmap", "default": False},
        {"id": "cross_session", "name": "Cross-Session Comparison", "default": False},
        {"id": "debrief", "name": "AI Debrief Notes", "default": True},
    ]

    return render_template("export_builder.html", session=session, sections=sections)
