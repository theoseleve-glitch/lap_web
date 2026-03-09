"""Weekend routes — group sessions into race weekends."""

from __future__ import annotations

from flask import (
    Blueprint,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

from web.db import get_db_connection
from web.models import (
from web.api_utils import api_error, api_response, ErrorCode
    add_session_to_weekend,
    create_weekend,
    delete_weekend,
    get_all_tracks,
    get_all_weekends,
    get_sessions,
    get_weekend_by_id,
    get_weekend_sessions,
    remove_session_from_weekend,
    reorder_weekend_sessions,
    swap_weekend_session_order,
    update_weekend,
)

bp = Blueprint("weekends", __name__, url_prefix="/weekends")


@bp.route("/")
def weekend_list():
    """All weekends."""
    conn = get_db_connection()
    weekends = get_all_weekends(conn)
    return render_template("weekend_list.html", weekends=weekends)


@bp.route("/new", methods=["GET", "POST"])
def weekend_new():
    """Create a new weekend."""
    conn = get_db_connection()

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Weekend name is required.", "error")
            return redirect(url_for("weekends.weekend_new"))

        weekend_id = create_weekend(
            conn,
            name=name,
            track_id=request.form.get("track_id") or None,
            start_date=request.form.get("start_date") or None,
            end_date=request.form.get("end_date") or None,
            notes=request.form.get("notes") or None,
        )

        # Attach sessions selected via the interactive picker
        session_ids = request.form.getlist("session_ids")
        for order, sid in enumerate(session_ids):
            sid = sid.strip()
            if sid:
                add_session_to_weekend(conn, weekend_id, sid, order)

        conn.commit()
        n_added = len([s for s in session_ids if s.strip()])
        msg = f"Weekend '{name}' created"
        if n_added:
            msg += f" with {n_added} session{'s' if n_added != 1 else ''}"
        flash(msg + ".", "success")
        return redirect(url_for("weekends.weekend_detail", weekend_id=weekend_id))

    tracks = get_all_tracks(conn)
    return render_template("weekend_form.html", weekend=None, tracks=tracks)


@bp.route("/<int:weekend_id>")
def weekend_detail(weekend_id: int):
    """Weekend detail with session list and summary."""
    conn = get_db_connection()
    weekend = get_weekend_by_id(conn, weekend_id)
    if weekend is None:
        abort(404)

    sessions = get_weekend_sessions(conn, weekend_id)

    # Compute summary stats.
    summary = None
    insights = None
    try:
        from cross_session import compute_weekend_insights, compute_weekend_summary
        summary = compute_weekend_summary(conn, weekend_id)
        insights = compute_weekend_insights(conn, weekend_id)
    except ImportError:
        pass

    return render_template(
        "weekend_detail.html",
        weekend=weekend,
        sessions=sessions,
        summary=summary,
        insights=insights,
    )


@bp.route("/<int:weekend_id>/edit", methods=["GET", "POST"])
def weekend_edit(weekend_id: int):
    """Edit a weekend."""
    conn = get_db_connection()
    weekend = get_weekend_by_id(conn, weekend_id)
    if weekend is None:
        abort(404)

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Weekend name is required.", "error")
            return redirect(url_for("weekends.weekend_edit", weekend_id=weekend_id))

        update_weekend(
            conn,
            weekend_id=weekend_id,
            name=name,
            track_id=request.form.get("track_id") or None,
            start_date=request.form.get("start_date") or None,
            end_date=request.form.get("end_date") or None,
            notes=request.form.get("notes") or None,
        )

        # Sync sessions: remove old, add new from picker
        existing_sessions = get_weekend_sessions(conn, weekend_id)
        old_ids = {s["session_id"] for s in existing_sessions}
        new_ids_list = request.form.getlist("session_ids")
        new_ids = {sid.strip() for sid in new_ids_list if sid.strip()}

        # Remove sessions no longer selected
        for sid in old_ids - new_ids:
            remove_session_from_weekend(conn, weekend_id, sid)

        # Add newly selected sessions
        # Determine order starting after existing max
        order = 0
        for sid in new_ids_list:
            sid = sid.strip()
            if sid and sid not in old_ids:
                add_session_to_weekend(conn, weekend_id, sid, order)
            order += 1

        conn.commit()
        flash("Weekend updated.", "success")
        return redirect(url_for("weekends.weekend_detail", weekend_id=weekend_id))

    # GET: pass pre-selected session IDs for the picker
    existing_sessions = get_weekend_sessions(conn, weekend_id)
    pre_selected_ids = [s["session_id"] for s in existing_sessions]
    tracks = get_all_tracks(conn)
    return render_template(
        "weekend_form.html",
        weekend=weekend,
        tracks=tracks,
        pre_selected_ids=pre_selected_ids,
    )


@bp.route("/<int:weekend_id>/delete", methods=["POST"])
def weekend_delete(weekend_id: int):
    """Delete a weekend."""
    conn = get_db_connection()
    weekend = get_weekend_by_id(conn, weekend_id)
    if weekend is None:
        abort(404)

    delete_weekend(conn, weekend_id)
    conn.commit()
    flash("Weekend deleted.", "success")
    return redirect(url_for("weekends.weekend_list"))


@bp.route("/<int:weekend_id>/add_session", methods=["POST"])
def weekend_add_session(weekend_id: int):
    """Add a session to a weekend."""
    conn = get_db_connection()
    session_id = request.form.get("session_id", "").strip()
    if not session_id:
        flash("No session selected.", "error")
        return redirect(url_for("weekends.weekend_detail", weekend_id=weekend_id))

    order = request.form.get("session_order", "0")
    try:
        order = int(order)
    except ValueError:
        order = 0

    add_session_to_weekend(conn, weekend_id, session_id, order)
    conn.commit()
    flash("Session added to weekend.", "success")
    return redirect(url_for("weekends.weekend_detail", weekend_id=weekend_id))


@bp.route("/<int:weekend_id>/remove_session", methods=["POST"])
def weekend_remove_session(weekend_id: int):
    """Remove a session from a weekend."""
    conn = get_db_connection()
    session_id = request.form.get("session_id", "").strip()
    if session_id:
        remove_session_from_weekend(conn, weekend_id, session_id)
        conn.commit()
        flash("Session removed.", "success")
    return redirect(url_for("weekends.weekend_detail", weekend_id=weekend_id))


@bp.route("/<int:weekend_id>/reorder", methods=["POST"])
def weekend_reorder(weekend_id: int):
    """Swap a session with its neighbor (AJAX endpoint)."""
    conn = get_db_connection()
    data = request.get_json(silent=True) or {}
    session_id = data.get("session_id", "")
    direction = data.get("direction", "down")
    if not session_id:
        return api_error(ErrorCode.VALIDATION_ERROR, "missing session_id", status=400)
    swap_weekend_session_order(conn, weekend_id, session_id, direction)
    conn.commit()
    return api_response({"message": "ok"})


@bp.route("/<int:weekend_id>/reorder_all", methods=["POST"])
def weekend_reorder_all(weekend_id: int):
    """Reorder all sessions (drag-and-drop AJAX endpoint)."""
    conn = get_db_connection()
    data = request.get_json(silent=True) or {}
    session_ids = data.get("session_ids", [])
    if not session_ids:
        return api_error(ErrorCode.VALIDATION_ERROR, "missing session_ids", status=400)
    reorder_weekend_sessions(conn, weekend_id, session_ids)
    conn.commit()
    return api_response({"message": "ok"})
