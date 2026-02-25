"""Dashboard route — main landing page."""

from __future__ import annotations

from flask import Blueprint, render_template

from web.db import get_db_connection
from web.models import get_dashboard_stats, get_sessions

bp = Blueprint("dashboard", __name__)


@bp.route("/")
def index():
    """Main dashboard: recent sessions, quick stats."""
    conn = get_db_connection()
    stats = get_dashboard_stats(conn)
    recent = get_sessions(conn, limit=10)
    return render_template(
        "dashboard.html",
        stats=stats,
        recent_sessions=recent,
    )
