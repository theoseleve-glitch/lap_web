"""Visualization mode — full-screen analysis workspace."""

from __future__ import annotations

import json

from flask import Blueprint, abort, render_template, request

from web.db import get_db_connection
from web.models import (
    get_gps_lap_numbers,
    get_laps_for_session,
    get_reference_line,
    get_session_by_id,
    get_session_sectors,
)

bp = Blueprint("visualize", __name__, url_prefix="/visualize")


@bp.route("/<session_id>")
def visualize_session(session_id: str):
    """Single-session visualization workspace."""
    conn = get_db_connection()
    session = get_session_by_id(conn, session_id)
    if session is None:
        abort(404)

    laps = get_laps_for_session(conn, session_id)
    gps_laps = get_gps_lap_numbers(conn, session_id)
    sectors = get_session_sectors(conn, session_id)
    ref_line = get_reference_line(conn, session_id)

    best_lap = None
    for lap in laps:
        if lap.get("is_best"):
            best_lap = lap["lap_number"]
            break

    laps_json = json.dumps([
        {
            "lap_number": l["lap_number"],
            "lap_time_s": l.get("lap_time_s"),
            "is_best": bool(l.get("is_best")),
            "is_valid": bool(l.get("is_valid", 1)),
            "invalid_reason": l.get("invalid_reason"),
        }
        for l in laps
        if l.get("lap_time_s") is not None
    ])

    sessions_json = json.dumps([{
        "session_id": session["session_id"],
        "driver_name": session.get("driver_name", ""),
        "track_name": session.get("track_name", ""),
        "session_date": session.get("session_date", ""),
        "session_type": session.get("session_type", ""),
        "track_state": session.get("track_state", ""),
        "n_laps": session.get("n_laps", 0),
        "best_lap_time_s": session.get("best_lap_time_s"),
        "grade": session.get("grade", ""),
    }])

    return render_template(
        "visualize.html",
        session=session,
        sessions_json=sessions_json,
        gps_laps=gps_laps,
        best_lap=best_lap,
        laps_json=laps_json,
        has_sectors=len(sectors) > 0,
        has_ref_line=ref_line is not None,
        multi_mode=False,
    )


@bp.route("/multi")
def visualize_multi():
    """Multi-session visualization (from weekend compare)."""
    session_ids = request.args.get("sessions", "").split(",")
    session_ids = [s.strip() for s in session_ids if s.strip()]
    if not session_ids:
        abort(400)

    conn = get_db_connection()
    sessions_data = []
    all_laps = []
    all_gps_laps = []

    # Use first session as primary
    primary_session = None
    for sid in session_ids:
        session = get_session_by_id(conn, sid)
        if session is None:
            continue
        if primary_session is None:
            primary_session = session

        laps = get_laps_for_session(conn, sid)
        gps_laps = get_gps_lap_numbers(conn, sid)

        sessions_data.append({
            "session_id": session["session_id"],
            "driver_name": session.get("driver_name", ""),
            "track_name": session.get("track_name", ""),
            "session_date": session.get("session_date", ""),
            "session_type": session.get("session_type", ""),
            "track_state": session.get("track_state", ""),
            "n_laps": session.get("n_laps", 0),
            "best_lap_time_s": session.get("best_lap_time_s"),
            "grade": session.get("grade", ""),
        })

        best_lap = None
        for l in laps:
            if l.get("is_best"):
                best_lap = l["lap_number"]
                break

        for l in laps:
            if l.get("lap_time_s") is not None:
                all_laps.append({
                    "session_id": sid,
                    "lap_number": l["lap_number"],
                    "lap_time_s": l.get("lap_time_s"),
                    "is_best": bool(l.get("is_best")),
                    "is_valid": bool(l.get("is_valid", 1)),
                    "invalid_reason": l.get("invalid_reason"),
                })

        for gl in gps_laps:
            all_gps_laps.append({"session_id": sid, "lap_number": gl})

    if primary_session is None:
        abort(404)

    # Get sectors/ref from primary session
    sectors = get_session_sectors(conn, primary_session["session_id"])
    ref_line = get_reference_line(conn, primary_session["session_id"])

    best_lap = None
    for l in all_laps:
        if l.get("is_best") and l["session_id"] == primary_session["session_id"]:
            best_lap = l["lap_number"]
            break

    return render_template(
        "visualize.html",
        session=primary_session,
        sessions_json=json.dumps(sessions_data),
        gps_laps=[g["lap_number"] for g in all_gps_laps
                  if g["session_id"] == primary_session["session_id"]],
        best_lap=best_lap,
        laps_json=json.dumps(all_laps),
        has_sectors=len(sectors) > 0,
        has_ref_line=ref_line is not None,
        multi_mode=True,
    )
