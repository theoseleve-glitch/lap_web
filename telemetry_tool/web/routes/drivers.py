"""Driver routes — list, profile view/edit, progression data, deletion."""

from __future__ import annotations

import json

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for

from web.db import get_db_connection
from web.models import (
    compute_best_ever_relative,
    delete_driver_cascade,
    get_all_drivers,
    get_driver_profile,
    get_driver_progression,
    get_driver_style_history,
    get_driving_style,
    update_driver_profile_field,
    upsert_driver_profile,
)

bp = Blueprint("drivers", __name__, url_prefix="/drivers")


@bp.route("/")
def driver_list():
    """All known drivers with summary stats."""
    conn = get_db_connection()
    drivers = get_all_drivers(conn)
    return render_template("driver_list.html", drivers=drivers)


@bp.route("/<int:driver_id>")
def driver_detail(driver_id: int):
    """Single driver profile view."""
    conn = get_db_connection()

    # Get driver base info.
    row = conn.execute(
        "SELECT * FROM drivers WHERE driver_id = :did",
        {"did": driver_id},
    ).fetchone()
    if row is None:
        abort(404)
    driver = dict(row)

    # Profile (may not exist yet).
    profile = get_driver_profile(conn, driver_id)
    if profile is None:
        # Auto-create a minimal profile from session data.
        stats = conn.execute(
            "SELECT COUNT(*) as n_sessions, SUM(n_laps) as total_laps, "
            "MIN(best_lap_time_s) as best_time, "
            "AVG(total_score) as avg_score "
            "FROM sessions WHERE driver_id = :did",
            {"did": driver_id},
        ).fetchone()
        stats = dict(stats) if stats else {}

        # Find best ever track
        best_track_row = conn.execute(
            "SELECT track_id FROM sessions WHERE driver_id = :did "
            "AND best_lap_time_s IS NOT NULL "
            "ORDER BY best_lap_time_s LIMIT 1",
            {"did": driver_id},
        ).fetchone()

        upsert_driver_profile(conn, driver_id, {
            "total_sessions": stats.get("n_sessions", 0),
            "total_laps": stats.get("total_laps", 0),
            "best_ever_time_s": stats.get("best_time"),
            "best_ever_track_id": dict(best_track_row).get("track_id") if best_track_row else None,
        })
        conn.commit()
        profile = get_driver_profile(conn, driver_id)

    # Best-ever relative performance.
    best_ever = compute_best_ever_relative(conn, driver_id)

    # Progression data.
    progression = get_driver_progression(conn, driver_id)

    # Style history.
    style_history = get_driver_style_history(conn, driver_id)
    latest_style = style_history[-1] if style_history else None

    # Session list for this driver.
    sessions = conn.execute(
        "SELECT s.*, t.track_name FROM sessions s "
        "LEFT JOIN tracks t ON s.track_id = t.track_id "
        "WHERE s.driver_id = :did ORDER BY s.session_date DESC",
        {"did": driver_id},
    ).fetchall()
    sessions = [dict(r) for r in sessions]

    # Earned badges.
    badge_rows = conn.execute(
        "SELECT * FROM driver_badges WHERE driver_id = :did ORDER BY earned_at DESC",
        {"did": driver_id},
    ).fetchall()
    badges = [dict(r) for r in badge_rows]

    return render_template(
        "driver_profile.html",
        driver=driver,
        profile=profile,
        progression=progression,
        latest_style=latest_style,
        style_history=style_history,
        sessions=sessions,
        best_ever=best_ever,
        badges=badges,
    )


@bp.route("/<int:driver_id>/edit", methods=["POST"])
def edit_profile(driver_id: int):
    """Update editable driver profile fields (AJAX endpoint)."""
    conn = get_db_connection()
    data = request.get_json(silent=True) or {}

    field_name = data.get("field")
    value = data.get("value")

    if not field_name:
        return jsonify({"error": "missing field"}), 400

    try:
        # Verify the driver exists.
        driver = conn.execute(
            "SELECT driver_id FROM drivers WHERE driver_id = :did",
            {"did": driver_id},
        ).fetchone()
        if driver is None:
            return jsonify({"error": "driver not found"}), 404

        # Ensure profile exists.
        profile = get_driver_profile(conn, driver_id)
        if profile is None:
            upsert_driver_profile(conn, driver_id, {})
            conn.commit()

        update_driver_profile_field(conn, driver_id, field_name, value)
        conn.commit()
        return jsonify({"ok": True, "field": field_name, "value": value})
    except ValueError as exc:
        return jsonify({"error": "Invalid field or value"}), 400


# ── API endpoints for chart data ────────────────────────────────

@bp.route("/<int:driver_id>/api/progression")
def progression_api(driver_id: int):
    """Return driver progression data as JSON for charts."""
    conn = get_db_connection()
    prog = get_driver_progression(conn, driver_id)
    return jsonify({"driver_id": driver_id, "progression": prog})


@bp.route("/<int:driver_id>/api/style_history")
def style_history_api(driver_id: int):
    """Return driving style feature history as JSON."""
    conn = get_db_connection()
    history = get_driver_style_history(conn, driver_id)
    # Strip heavy JSON fields for chart data.
    for h in history:
        h.pop("strengths_json", None)
        h.pop("weaknesses_json", None)
    return jsonify({"driver_id": driver_id, "history": history})


@bp.route("/<int:driver_id>/delete", methods=["POST"])
def delete_driver(driver_id: int):
    """Delete a driver and all dependent data (cascade)."""
    conn = get_db_connection()
    row = conn.execute(
        "SELECT * FROM drivers WHERE driver_id = :did",
        {"did": driver_id},
    ).fetchone()
    if row is None:
        abort(404)
    driver = dict(row)

    driver_name = driver["driver_name"]
    counts = delete_driver_cascade(conn, driver_id)
    conn.commit()

    total_sessions = counts.get("sessions", 0)
    flash(f"Driver '{driver_name}' deleted ({total_sessions} session(s) removed).", "success")
    return redirect(url_for("drivers.driver_list"))
