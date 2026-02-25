"""Development plan routes."""

from __future__ import annotations

from flask import Blueprint, render_template, abort, request

from web.db import get_db_connection

bp = Blueprint("dev_plans", __name__, url_prefix="/dev-plans")


@bp.route("/")
def plan_list():
    """List plans, optionally filtered by driver."""
    conn = get_db_connection()
    driver_id = request.args.get("driver_id", type=int)

    drivers = conn.execute("SELECT driver_id, driver_name FROM drivers ORDER BY driver_name").fetchall()

    from development_plan import get_plans, get_plan_templates
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
    from development_plan import get_plan
    plan = get_plan(conn, plan_id)
    if not plan:
        abort(404)
    return render_template("dev_plan_detail.html", plan=plan)
