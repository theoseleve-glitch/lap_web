"""Custom dashboard routes."""

from __future__ import annotations

from flask import Blueprint, abort, render_template

from web.db import get_db_connection

bp = Blueprint("dashboards", __name__, url_prefix="/dashboards")


@bp.route("/")
def dashboard_list():
    """List all custom dashboards."""
    conn = get_db_connection()
    from dashboard_builder import get_dashboards, get_widget_registry
    dashboards = get_dashboards(conn)
    widgets = get_widget_registry()
    return render_template("custom_dashboard.html", dashboards=dashboards, widgets=widgets)


@bp.route("/<int:dashboard_id>")
def dashboard_view(dashboard_id: int):
    """View a specific dashboard."""
    conn = get_db_connection()
    from dashboard_builder import get_dashboard, get_widget_registry
    dashboard = get_dashboard(conn, dashboard_id)
    if not dashboard:
        abort(404)
    widgets = get_widget_registry()
    return render_template("dashboard_view.html", dashboard=dashboard, widgets=widgets)
