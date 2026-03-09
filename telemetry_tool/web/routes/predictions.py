"""Blueprint for predictive and simulation pages."""
from __future__ import annotations

import logging

from flask import Blueprint, render_template, request

from web.db import get_db_connection

logger = logging.getLogger(__name__)
bp = Blueprint("predictions", __name__, url_prefix="/predictions")

@bp.route("/what-if/<session_id>")
def what_if_page(session_id: str):
    """What-if simulator page."""
    conn = get_db_connection()
    from web.models import get_session_by_id
    session = get_session_by_id(conn, session_id)
    if session is None:
        from flask import abort
        abort(404)
    return render_template("what_if.html", session=session)

@bp.route("/setup-tracker")
def setup_tracker_page():
    """Setup correlation tracker page."""
    conn = get_db_connection()
    drivers = conn.execute("SELECT driver_id, driver_name FROM drivers ORDER BY driver_name").fetchall()
    tracks = conn.execute("SELECT track_id, track_name FROM tracks ORDER BY track_name").fetchall()
    return render_template("setup_tracker.html", drivers=[dict(d) for d in drivers], tracks=[dict(t) for t in tracks])


@bp.route("/weight-simulator")
def weight_simulator_page():
    """Weight effect simulator page."""
    conn = get_db_connection()
    drivers = conn.execute("SELECT driver_id, driver_name FROM drivers ORDER BY driver_name").fetchall()
    tracks = conn.execute("SELECT track_id, track_name FROM tracks ORDER BY track_name").fetchall()
    return render_template("weight_simulator.html", drivers=[dict(d) for d in drivers], tracks=[dict(t) for t in tracks])


@bp.route("/race-strategy")
def race_strategy_page():
    """Race strategy planner page."""
    conn = get_db_connection()
    drivers = conn.execute("SELECT driver_id, driver_name FROM drivers ORDER BY driver_name").fetchall()
    tracks = conn.execute("SELECT track_id, track_name FROM tracks ORDER BY track_name").fetchall()
    return render_template(
        "race_strategy.html",
        drivers=[dict(d) for d in drivers],
        tracks=[dict(t) for t in tracks],
    )
