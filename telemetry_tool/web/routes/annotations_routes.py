"""Annotation management routes."""

from __future__ import annotations

from flask import Blueprint, render_template, abort

from web.db import get_db_connection
from web.models import get_session_by_id

bp = Blueprint("annotations", __name__, url_prefix="/annotations")


@bp.route("/session/<session_id>")
def session_annotations(session_id: str):
    """Show annotations for a session."""
    conn = get_db_connection()
    session = get_session_by_id(conn, session_id)
    if not session:
        abort(404)
    return render_template("annotations.html", session=session)


@bp.route("/search")
def search_page():
    """Search annotations across all sessions."""
    return render_template("annotation_search.html")
