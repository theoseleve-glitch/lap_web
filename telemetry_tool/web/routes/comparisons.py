"""Comparison routes — head-to-head session and driver comparisons."""

from __future__ import annotations

from flask import Blueprint, abort, jsonify, render_template, request

from web.db import get_db_connection
from web.models import (
    get_driver_profile,
    get_driver_progression,
    get_driving_style,
    get_gps_lap_numbers,
    get_gps_trace,
    get_laps_for_session,
    get_score_details,
    get_session_by_id,
)

bp = Blueprint("comparisons", __name__, url_prefix="/compare")


def _session_summary(conn, session_id: str) -> dict | None:
    """Build a rich session dict for comparison."""
    session = get_session_by_id(conn, session_id)
    if session is None:
        return None
    laps = get_laps_for_session(conn, session_id)
    score = get_score_details(conn, session_id)

    best_lap_num = None
    for lap in laps:
        if lap.get("is_best"):
            best_lap_num = lap["lap_number"]
            break

    style = None
    if session.get("driver_id"):
        style = get_driving_style(conn, session["driver_id"], session_id)

    return {
        **session,
        "laps": laps,
        "score": score,
        "best_lap_number": best_lap_num,
        "driving_style": style,
    }


def _driver_summary(conn, driver_id: int) -> dict | None:
    """Build a rich driver dict for comparison."""
    row = conn.execute(
        "SELECT * FROM drivers WHERE driver_id = :did",
        {"did": driver_id},
    ).fetchone()
    if row is None:
        return None
    driver = dict(row)
    profile = get_driver_profile(conn, driver_id)
    progression = get_driver_progression(conn, driver_id)

    # Latest style
    from web.models import get_driver_style_history
    styles = get_driver_style_history(conn, driver_id)
    latest_style = styles[-1] if styles else None

    # Session stats
    stats = conn.execute(
        "SELECT COUNT(*) as n_sessions, SUM(n_laps) as total_laps, "
        "MIN(best_lap_time_s) as best_time, AVG(total_score) as avg_score, "
        "MAX(total_score) as best_score "
        "FROM sessions WHERE driver_id = :did",
        {"did": driver_id},
    ).fetchone()

    # Recent sessions
    sessions = conn.execute(
        "SELECT s.session_id, s.session_date, s.best_lap_time_s, "
        "s.total_score, s.grade, s.track_id, t.track_name "
        "FROM sessions s LEFT JOIN tracks t ON s.track_id = t.track_id "
        "WHERE s.driver_id = :did ORDER BY s.session_date DESC LIMIT 10",
        {"did": driver_id},
    ).fetchall()

    return {
        **driver,
        "profile": profile,
        "progression": progression,
        "latest_style": latest_style,
        "stats": dict(stats) if stats else {},
        "recent_sessions": [dict(r) for r in sessions],
    }


@bp.route("/")
def compare_form():
    """Show comparison selector form."""
    conn = get_db_connection()
    sessions = conn.execute(
        "SELECT s.session_id, s.session_date, s.best_lap_time_s, "
        "d.driver_name, t.track_name "
        "FROM sessions s "
        "JOIN drivers d ON s.driver_id = d.driver_id "
        "LEFT JOIN tracks t ON s.track_id = t.track_id "
        "ORDER BY s.session_date DESC LIMIT 100"
    ).fetchall()
    sessions = [dict(r) for r in sessions]

    drivers = conn.execute(
        "SELECT d.driver_id, d.driver_name, COUNT(s.session_id) as n_sessions "
        "FROM drivers d LEFT JOIN sessions s ON d.driver_id = s.driver_id "
        "GROUP BY d.driver_id ORDER BY d.driver_name"
    ).fetchall()
    drivers = [dict(r) for r in drivers]

    return render_template(
        "compare.html",
        sessions=sessions,
        drivers=drivers,
    )


@bp.route("/sessions")
def compare_sessions():
    """Side-by-side session comparison."""
    conn = get_db_connection()
    sid_a = request.args.get("a", "")
    sid_b = request.args.get("b", "")

    if not sid_a or not sid_b:
        return render_template("compare.html",
                               sessions=[], drivers=[],
                               error="Select two sessions to compare.")

    sum_a = _session_summary(conn, sid_a)
    sum_b = _session_summary(conn, sid_b)

    if sum_a is None or sum_b is None:
        abort(404)

    return render_template(
        "compare_sessions.html",
        session_a=sum_a,
        session_b=sum_b,
    )


@bp.route("/drivers")
def compare_drivers():
    """Side-by-side driver comparison."""
    conn = get_db_connection()
    did_a = request.args.get("a", 0, type=int)
    did_b = request.args.get("b", 0, type=int)

    if not did_a or not did_b:
        return render_template("compare.html",
                               sessions=[], drivers=[],
                               error="Select two drivers to compare.")

    drv_a = _driver_summary(conn, did_a)
    drv_b = _driver_summary(conn, did_b)

    if drv_a is None or drv_b is None:
        abort(404)

    return render_template(
        "compare_drivers.html",
        driver_a=drv_a,
        driver_b=drv_b,
    )


@bp.route("/api/session_pair")
def session_pair_api():
    """Return speed traces for two sessions (for overlay chart)."""
    conn = get_db_connection()
    sid_a = request.args.get("a", "")
    sid_b = request.args.get("b", "")

    traces = {}
    for sid, label_suffix in [(sid_a, "A"), (sid_b, "B")]:
        if not sid:
            continue
        session = get_session_by_id(conn, sid)
        if session is None:
            continue
        laps = get_laps_for_session(conn, sid)
        best_lap = None
        for lap in laps:
            if lap.get("is_best"):
                best_lap = lap["lap_number"]
                break
        if best_lap:
            gps = get_gps_trace(conn, sid, best_lap)
            if gps:
                traces[sid] = {
                    "label": f"{session.get('session_date', '?')} - {session.get('driver_name', '?')} ({label_suffix})",
                    "distances": gps["distances"],
                    "speeds": gps["speeds"],
                }

    return jsonify({"traces": traces})
