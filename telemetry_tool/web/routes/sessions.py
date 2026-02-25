"""Session routes — list and detail views."""

from __future__ import annotations

import os
from pathlib import Path

from flask import Blueprint, abort, flash, redirect, render_template, request, send_file, url_for

from web.db import get_db_connection
from web.models import (
    count_sessions,
    get_all_karts,
    get_condition_phases,
    get_driving_style,
    get_laps_for_session,
    get_score_details,
    get_session_by_id,
    get_sessions,
    get_gps_lap_numbers,
    get_theoretical_data,
    link_session_kart,
)

bp = Blueprint("sessions", __name__, url_prefix="/sessions")


@bp.route("/")
def session_list():
    """Paginated session list with optional filters."""
    conn = get_db_connection()
    page = request.args.get("page", 1, type=int)
    per_page = 25
    offset = (page - 1) * per_page
    sessions = get_sessions(conn, limit=per_page, offset=offset)
    total = count_sessions(conn)
    total_pages = max(1, (total + per_page - 1) // per_page)
    return render_template(
        "session_list.html",
        sessions=sessions,
        page=page,
        total_pages=total_pages,
        total=total,
    )


@bp.route("/<session_id>")
def session_detail(session_id: str):
    """Single session view with scores, laps, GPS trace."""
    conn = get_db_connection()
    session = get_session_by_id(conn, session_id)
    if session is None:
        abort(404)

    laps = get_laps_for_session(conn, session_id)

    # Compute total session duration from lap times (for 6h+ endurance gate)
    total_session_time = sum(
        lap.get("lap_time_s", 0) or 0 for lap in laps
        if lap.get("lap_time_s") is not None
    )

    score = get_score_details(conn, session_id)
    phases = get_condition_phases(conn, session_id)
    gps_laps = get_gps_lap_numbers(conn, session_id)

    # Find the best lap number for default GPS display.
    best_lap = None
    for lap in laps:
        if lap.get("is_best"):
            best_lap = lap["lap_number"]
            break

    # Driving style (Phase 3).
    driving_style = None
    if session.get("driver_id"):
        driving_style = get_driving_style(conn, session["driver_id"], session_id)

    # Theoretical lap data (Phase 4).
    theoretical = get_theoretical_data(conn, session_id)

    # Kart info + kart list for linking.
    kart = None
    if session.get("kart_id"):
        from web.models import get_kart_by_id
        kart = get_kart_by_id(conn, session["kart_id"])
    karts = get_all_karts(conn)

    return render_template(
        "session_detail.html",
        session=session,
        laps=laps,
        score=score,
        phases=phases,
        gps_laps=gps_laps,
        best_lap=best_lap,
        driving_style=driving_style,
        theoretical=theoretical,
        total_session_time=total_session_time,
        kart=kart,
        karts=karts,
    )


@bp.route("/<session_id>/report")
def session_report(session_id: str):
    """Serve the HTML report file directly from its stored path."""
    conn = get_db_connection()
    session = get_session_by_id(conn, session_id)
    if session is None:
        abort(404)

    report_path = session.get("html_report_path")
    if not report_path:
        abort(404)

    # Handle both absolute paths and relative paths.
    p = Path(report_path)
    if not p.is_absolute():
        # Try relative to current working directory.
        p = Path.cwd() / p
    if not p.exists():
        # Try looking in the Results directory.
        results_dir = Path.cwd() / "Results"
        if results_dir.exists():
            for candidate in results_dir.rglob(p.name):
                if candidate.exists():
                    p = candidate
                    break

    if not p.exists():
        abort(404)

    # Path traversal guard: only serve files within the project directory
    allowed_root = Path.cwd().resolve()
    resolved = p.resolve()
    if not str(resolved).startswith(str(allowed_root)):
        abort(403)

    return send_file(str(resolved), mimetype="text/html")


@bp.route("/<session_id>/kart", methods=["POST"])
def set_session_kart(session_id: str):
    """Link or unlink a kart to this session."""
    conn = get_db_connection()
    session = get_session_by_id(conn, session_id)
    if session is None:
        abort(404)

    kart_id_raw = request.form.get("kart_id", "").strip()
    kart_id = int(kart_id_raw) if kart_id_raw else None

    link_session_kart(conn, session_id, kart_id)
    conn.commit()
    flash("Kart updated." if kart_id else "Kart unlinked.", "success")
    return redirect(url_for("sessions.session_detail", session_id=session_id))
