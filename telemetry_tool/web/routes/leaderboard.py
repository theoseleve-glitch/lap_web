"""Leaderboard route — ranked drivers with track filtering."""

from __future__ import annotations

from flask import Blueprint, render_template, request

from web.db import get_db_connection

bp = Blueprint("leaderboard", __name__, url_prefix="/leaderboard")


@bp.route("/")
def leaderboard():
    """Driver leaderboard ranked by best time or score, with track filter."""
    conn = get_db_connection()
    track_id = request.args.get("track", "")
    sort_by = request.args.get("sort", "best_time")  # best_time | avg_score | sessions

    # Get tracks for filter dropdown.
    tracks = conn.execute(
        "SELECT t.track_id, t.track_name, COUNT(s.session_id) as n_sessions "
        "FROM tracks t JOIN sessions s ON t.track_id = s.track_id "
        "GROUP BY t.track_id ORDER BY t.track_name"
    ).fetchall()
    tracks = [dict(r) for r in tracks]

    # Build leaderboard query.
    where = ""
    params = {}
    if track_id:
        where = "WHERE s.track_id = :track_id"
        params["track_id"] = track_id

    rows = conn.execute(f"""
        SELECT d.driver_id, d.driver_name,
               COUNT(DISTINCT s.session_id) AS session_count,
               SUM(s.n_laps) AS total_laps,
               MIN(s.best_lap_time_s) AS best_time_s,
               AVG(s.total_score) AS avg_score,
               MAX(s.total_score) AS best_score,
               AVG(s.best_lap_time_s) AS avg_best_time_s
        FROM drivers d
        JOIN sessions s ON d.driver_id = s.driver_id
        {where}
        GROUP BY d.driver_id
        HAVING session_count > 0
        ORDER BY
            CASE WHEN :sort_by = 'best_time' THEN MIN(s.best_lap_time_s) END ASC,
            CASE WHEN :sort_by = 'avg_score' THEN AVG(s.total_score) END DESC,
            CASE WHEN :sort_by = 'sessions' THEN COUNT(DISTINCT s.session_id) END DESC
    """, {**params, "sort_by": sort_by}).fetchall()

    leaders = []
    for i, r in enumerate(rows, 1):
        d = dict(r)
        d["rank"] = i

        # Get latest driving style.
        style_row = conn.execute(
            "SELECT dsf.style_label FROM driving_style_features dsf "
            "JOIN sessions s ON dsf.session_id = s.session_id "
            "WHERE dsf.driver_id = :did ORDER BY s.session_date DESC LIMIT 1",
            {"did": d["driver_id"]},
        ).fetchone()
        d["style_label"] = dict(style_row)["style_label"] if style_row else None

        # Get improvement trend from profile.
        profile_row = conn.execute(
            "SELECT improvement_trend FROM driver_profiles WHERE driver_id = :did",
            {"did": d["driver_id"]},
        ).fetchone()
        d["trend"] = dict(profile_row)["improvement_trend"] if profile_row else None

        leaders.append(d)

    # Track name for display.
    track_name = None
    if track_id:
        for t in tracks:
            if t["track_id"] == track_id:
                track_name = t["track_name"]
                break

    return render_template(
        "leaderboard.html",
        leaders=leaders,
        tracks=tracks,
        selected_track=track_id,
        track_name=track_name,
        sort_by=sort_by,
    )
