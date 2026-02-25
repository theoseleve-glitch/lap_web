"""Data health dashboard route — view data quality metrics across sessions."""

from __future__ import annotations

import json

from flask import Blueprint, render_template, request

from web.db import get_db_connection

bp = Blueprint("data_health", __name__, url_prefix="/data-health")


@bp.route("/")
def data_health_list():
    """Data health overview: list all sessions with quality scores."""
    conn = get_db_connection()

    rows = conn.execute("""
        SELECT dh.*,
               s.session_date, s.session_type, s.track_state,
               s.n_laps, s.best_lap_time_s, s.total_score, s.grade,
               d.driver_name, t.track_name
        FROM data_health dh
        JOIN sessions s ON dh.session_id = s.session_id
        JOIN drivers d ON s.driver_id = d.driver_id
        LEFT JOIN tracks t ON s.track_id = t.track_id
        ORDER BY dh.overall_score ASC
    """).fetchall()
    sessions = [dict(r) for r in rows]

    # Summary stats
    total = len(sessions)
    if total > 0:
        avg_score = sum(s["overall_score"] or 0 for s in sessions) / total
        poor = sum(1 for s in sessions if (s["overall_score"] or 0) < 50)
        good = sum(1 for s in sessions if (s["overall_score"] or 0) >= 80)
    else:
        avg_score = 0
        poor = 0
        good = 0

    return render_template(
        "data_health.html",
        sessions=sessions,
        total=total,
        avg_score=round(avg_score, 1),
        poor_count=poor,
        good_count=good,
    )


@bp.route("/<session_id>")
def data_health_detail(session_id: str):
    """Detailed data health report for a single session."""
    conn = get_db_connection()

    row = conn.execute(
        "SELECT dh.*, s.session_date, s.session_type, d.driver_name, t.track_name "
        "FROM data_health dh "
        "JOIN sessions s ON dh.session_id = s.session_id "
        "JOIN drivers d ON s.driver_id = d.driver_id "
        "LEFT JOIN tracks t ON s.track_id = t.track_id "
        "WHERE dh.session_id = :session_id",
        {"session_id": session_id},
    ).fetchone()

    if not row:
        return render_template("404.html"), 404

    session_data = dict(row)

    # Parse the report JSON
    report = {}
    if session_data.get("report_json"):
        try:
            report = json.loads(session_data["report_json"])
        except (json.JSONDecodeError, TypeError):
            report = {}

    return render_template(
        "data_health_detail.html",
        session=session_data,
        report=report,
    )
