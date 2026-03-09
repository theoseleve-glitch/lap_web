"""Development plan routes."""

from __future__ import annotations

from flask import Blueprint, abort, render_template, request

from web.db import get_db_connection

bp = Blueprint("dev_plans", __name__, url_prefix="/dev-plans")


@bp.route("/")
def plan_list():
    """List plans, optionally filtered by driver."""
    conn = get_db_connection()
    driver_id = request.args.get("driver_id", type=int)

    drivers = conn.execute("SELECT driver_id, driver_name FROM drivers ORDER BY driver_name").fetchall()

    from development_plan import get_plan_templates, get_plans
    plans = get_plans(conn, driver_id) if driver_id else []
    templates = get_plan_templates()

    return render_template("dev_plan.html",
                          drivers=[dict(d) for d in drivers],
                          plans=plans,
                          templates=templates,
                          selected_driver_id=driver_id)


@bp.route("/<int:plan_id>")
def plan_detail(plan_id: int):
    """View a specific plan."""
    conn = get_db_connection()
    from development_plan import get_drill_sessions, get_plan
    plan = get_plan(conn, plan_id)
    if not plan:
        abort(404)

    # Get driver's sessions for the linking dropdown.
    driver_sessions = conn.execute(
        "SELECT s.session_id, s.session_date, s.best_lap_time_s, s.total_score, "
        "s.n_laps, t.track_name FROM sessions s "
        "LEFT JOIN tracks t ON s.track_id = t.track_id "
        "WHERE s.driver_id = :did ORDER BY s.session_date DESC",
        {"did": plan["driver_id"]},
    ).fetchall()
    driver_sessions = [dict(r) for r in driver_sessions]

    # Get already-linked sessions.
    drill_links = get_drill_sessions(conn, plan_id)

    return render_template("dev_plan_detail.html",
                          plan=plan,
                          driver_sessions=driver_sessions,
                          drill_links=drill_links)
