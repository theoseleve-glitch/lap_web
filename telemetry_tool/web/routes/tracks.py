"""Track routes — list and detail views, track records management, S/F editing, sectors, deletion."""

from __future__ import annotations

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for

from web.api_utils import api_response
from web.db import get_db_connection
from web.models import (
    delete_track_cascade,
    delete_track_record,
    delete_track_sector,
    get_all_tracks,
    get_track_by_id,
    get_track_records,
    get_track_sectors,
    reset_track_start_finish,
    update_track_start_finish,
    upsert_track_record,
    upsert_track_sector,
)

bp = Blueprint("tracks", __name__, url_prefix="/tracks")


@bp.route("/")
def track_list():
    """All known tracks."""
    conn = get_db_connection()
    tracks = get_all_tracks(conn)
    return render_template("track_list.html", tracks=tracks)


@bp.route("/<track_id>")
def track_detail(track_id: str):
    """Single track overview."""
    conn = get_db_connection()
    track = get_track_by_id(conn, track_id)
    if track is None:
        abort(404)

    # Get sessions at this track.
    sessions = conn.execute(
        "SELECT s.*, COALESCE(d.driver_name, 'Unknown') AS driver_name FROM sessions s "
        "LEFT JOIN drivers d ON s.driver_id = d.driver_id "
        "WHERE s.track_id = :track_id "
        "ORDER BY s.session_date DESC;",
        {"track_id": track_id},
    ).fetchall()
    sessions = [dict(r) for r in sessions]

    # Track records.
    records = get_track_records(conn, track_id)

    # Track sectors.
    sectors = get_track_sectors(conn, track_id)

    # Condition reference line info.
    ref_info = {}
    for cond, col in [("dry", "dry_ref_session_id"), ("wet", "wet_ref_session_id")]:
        ref_sid = track.get(col)
        if ref_sid:
            ref_sess = conn.execute(
                "SELECT s.session_id, s.session_date, s.best_lap_time_s, "
                "d.driver_name FROM sessions s "
                "JOIN drivers d ON s.driver_id = d.driver_id "
                "WHERE s.session_id = :sid",
                {"sid": ref_sid},
            ).fetchone()
            ref_info[cond] = dict(ref_sess) if ref_sess else None
        else:
            ref_info[cond] = None

    return render_template(
        "track_detail.html",
        track=track,
        sessions=sessions,
        records=records,
        sectors=sectors,
        ref_info=ref_info,
    )


@bp.route("/<track_id>/records/add", methods=["POST"])
def add_record(track_id: str):
    """Add or update a track record."""
    conn = get_db_connection()
    track = get_track_by_id(conn, track_id)
    if track is None:
        abort(404)

    try:
        time_str = request.form.get("record_time_s", "").strip()
        if not time_str:
            flash("Record time is required.", "error")
            return redirect(url_for("tracks.track_detail", track_id=track_id))
        time_s = float(time_str)
        if time_s <= 0:
            flash("Record time must be positive.", "error")
            return redirect(url_for("tracks.track_detail", track_id=track_id))
    except ValueError:
        flash("Invalid time value.", "error")
        return redirect(url_for("tracks.track_detail", track_id=track_id))

    upsert_track_record(
        conn,
        track_id=track_id,
        record_time_s=time_s,
        record_holder=request.form.get("record_holder") or None,
        record_date=request.form.get("record_date") or None,
        vehicle_class=request.form.get("vehicle_class") or None,
        source=request.form.get("source") or None,
    )
    conn.commit()
    flash("Track record saved.", "success")
    return redirect(url_for("tracks.track_detail", track_id=track_id))


@bp.route("/<track_id>/records/<int:record_id>/delete", methods=["POST"])
def remove_record(track_id: str, record_id: int):
    """Delete a track record."""
    conn = get_db_connection()
    delete_track_record(conn, record_id)
    conn.commit()
    flash("Record deleted.", "success")
    return redirect(url_for("tracks.track_detail", track_id=track_id))


@bp.route("/<track_id>/rename", methods=["POST"])
def rename_track(track_id: str):
    """Rename a track."""
    conn = get_db_connection()
    track = get_track_by_id(conn, track_id)
    if track is None:
        abort(404)

    new_name = request.form.get("track_name", "").strip()
    if not new_name:
        flash("Track name cannot be empty.", "error")
        return redirect(url_for("tracks.track_detail", track_id=track_id))

    conn.execute(
        "UPDATE tracks SET track_name = :name, updated_at = datetime('now') "
        "WHERE track_id = :tid",
        {"name": new_name, "tid": track_id},
    )
    conn.commit()

    # Also update tracks.json if it exists.
    try:
        from track_detection import _save_db, load_track_database
        db = load_track_database()
        for entry in db:
            if entry.get("track_id") == track_id:
                entry["track_name"] = new_name
                break
        _save_db(db)
    except Exception:
        pass  # Non-critical — DB is the source of truth for web display.

    flash(f"Track renamed to '{new_name}'.", "success")
    return redirect(url_for("tracks.track_detail", track_id=track_id))


@bp.route("/<track_id>/joker", methods=["POST"])
def update_joker(track_id: str):
    """Update joker lap settings for a track."""
    conn = get_db_connection()
    track = get_track_by_id(conn, track_id)
    if track is None:
        abort(404)

    has_joker = 1 if request.form.get("has_joker") == "1" else 0
    distance_delta = None
    time_delta = None

    if has_joker:
        try:
            d = request.form.get("joker_distance_delta_m", "").strip()
            distance_delta = float(d) if d else None
        except ValueError:
            flash("Invalid distance delta value.", "error")
            return redirect(url_for("tracks.track_detail", track_id=track_id))
        try:
            t = request.form.get("joker_time_delta_s", "").strip()
            time_delta = float(t) if t else None
        except ValueError:
            flash("Invalid time delta value.", "error")
            return redirect(url_for("tracks.track_detail", track_id=track_id))

    conn.execute(
        "UPDATE tracks SET has_joker = :has_joker, "
        "joker_distance_delta_m = :joker_distance_delta_m, "
        "joker_time_delta_s = :joker_time_delta_s, "
        "updated_at = datetime('now') WHERE track_id = :tid",
        {
            "has_joker": has_joker,
            "joker_distance_delta_m": distance_delta,
            "joker_time_delta_s": time_delta,
            "tid": track_id,
        },
    )
    conn.commit()

    flash("Joker settings updated." if has_joker else "Joker lap disabled.", "success")
    return redirect(url_for("tracks.track_detail", track_id=track_id))


# ── Start/Finish editing ─────────────────────────────────────
@bp.route("/<track_id>/start_finish", methods=["POST"])
def update_start_finish(track_id: str):
    """Update or reset start/finish GPS position."""
    conn = get_db_connection()
    track = get_track_by_id(conn, track_id)
    if track is None:
        abort(404)

    action = request.form.get("action", "update")
    if action == "reset":
        reset_track_start_finish(conn, track_id)
        flash("Start/finish reset to auto-detected position.", "success")
    else:
        try:
            lat = float(request.form["lat"])
            lon = float(request.form["lon"])
        except (KeyError, ValueError):
            flash("Invalid coordinates.", "error")
            return redirect(url_for("tracks.track_detail", track_id=track_id))
        update_track_start_finish(conn, track_id, lat, lon)
        flash("Start/finish position updated.", "success")
    conn.commit()
    return redirect(url_for("tracks.track_detail", track_id=track_id))


# ── Track Sectors ─────────────────────────────────────────────
@bp.route("/<track_id>/sectors/add", methods=["POST"])
def add_sector(track_id: str):
    """Add a sector split point."""
    conn = get_db_connection()
    track = get_track_by_id(conn, track_id)
    if track is None:
        abort(404)

    try:
        lat = float(request.form["lat"])
        lon = float(request.form["lon"])
    except (KeyError, ValueError):
        flash("Invalid coordinates.", "error")
        return redirect(url_for("tracks.track_detail", track_id=track_id))

    dist_raw = request.form.get("distance_m", "").strip()
    try:
        distance_m = float(dist_raw) if dist_raw else None
    except ValueError:
        distance_m = None

    upsert_track_sector(conn, track_id, lat, lon, distance_m)
    conn.commit()
    flash("Sector added.", "success")
    return redirect(url_for("tracks.track_detail", track_id=track_id))


@bp.route("/<track_id>/sectors/<int:sector_id>/delete", methods=["POST"])
def remove_sector(track_id: str, sector_id: int):
    """Delete a sector split point."""
    conn = get_db_connection()
    delete_track_sector(conn, track_id, sector_id)
    conn.commit()
    flash("Sector removed.", "success")
    return redirect(url_for("tracks.track_detail", track_id=track_id))


@bp.route("/<track_id>/sectors", methods=["GET"])
def api_sectors(track_id: str):
    """JSON API: list sectors for a track."""
    conn = get_db_connection()
    sectors = get_track_sectors(conn, track_id)
    return api_response(sectors)


# ── Track Deletion ────────────────────────────────────────────
@bp.route("/<track_id>/delete", methods=["POST"])
def delete_track(track_id: str):
    """Delete a track and all dependent data (cascade)."""
    conn = get_db_connection()
    track = get_track_by_id(conn, track_id)
    if track is None:
        abort(404)

    track_name = track.get("track_name") or track["track_id"]
    counts = delete_track_cascade(conn, track_id)
    conn.commit()

    total_sessions = counts.get("sessions", 0)
    flash(f"Track '{track_name}' deleted ({total_sessions} session(s) removed).", "success")
    return redirect(url_for("tracks.track_list"))
