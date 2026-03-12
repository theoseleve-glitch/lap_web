"""Kart routes — list, detail, CRUD for user karts."""

from __future__ import annotations

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from web.db import get_db_connection
from web.models import (
    create_kart,
    delete_kart,
    get_all_karts,
    get_kart_by_id,
    get_predefined_karts_grouped,
    update_kart,
)

bp = Blueprint("karts", __name__, url_prefix="/karts")


@bp.route("/")
def kart_list():
    """All user karts."""
    conn = get_db_connection()
    karts = get_all_karts(conn)
    return render_template("kart_list.html", karts=karts)


@bp.route("/<int:kart_id>")
def kart_detail(kart_id: int):
    """Single kart overview."""
    conn = get_db_connection()
    kart = get_kart_by_id(conn, kart_id)
    if kart is None:
        abort(404)

    # Sessions using this kart.
    sessions = conn.execute(
        "SELECT s.*, COALESCE(d.driver_name, 'Unknown') AS driver_name, "
        "COALESCE(t.track_name, s.track_id) AS track_name_display "
        "FROM sessions s "
        "LEFT JOIN drivers d ON s.driver_id = d.driver_id "
        "LEFT JOIN tracks t ON s.track_id = t.track_id "
        "WHERE s.kart_id = ? ORDER BY s.session_date DESC",
        (kart_id,),
    ).fetchall()
    sessions = [dict(r) for r in sessions]

    return render_template("kart_detail.html", kart=kart, sessions=sessions)


@bp.route("/new", methods=["GET", "POST"])
def new_kart():
    """Create a new kart."""
    conn = get_db_connection()

    if request.method == "POST":
        kart_name = request.form.get("kart_name", "").strip()
        if not kart_name:
            flash("Kart name is required.", "error")
            return redirect(url_for("karts.new_kart"))

        pred_id_raw = request.form.get("predefined_kart_id", "").strip()
        try:
            pred_id = int(pred_id_raw) if pred_id_raw else None
        except (ValueError, TypeError):
            pred_id = None

        def _flt(key):
            v = request.form.get(key, "").strip()
            try:
                return float(v) if v else None
            except ValueError:
                return None

        kart_id = create_kart(
            conn,
            kart_name=kart_name,
            predefined_kart_id=pred_id,
            manufacturer=request.form.get("manufacturer", "").strip() or None,
            model=request.form.get("model", "").strip() or None,
            engine=request.form.get("engine", "").strip() or None,
            power_hp=_flt("power_hp"),
            kart_weight_kg=_flt("kart_weight_kg"),
            notes=request.form.get("notes", "").strip() or None,
        )
        conn.commit()
        flash(f"Kart '{kart_name}' created.", "success")
        return redirect(url_for("karts.kart_detail", kart_id=kart_id))

    predefined = get_predefined_karts_grouped(conn)
    return render_template("kart_form.html", kart=None, predefined=predefined)


@bp.route("/<int:kart_id>/edit", methods=["GET", "POST"])
def edit_kart(kart_id: int):
    """Edit a kart."""
    conn = get_db_connection()
    kart = get_kart_by_id(conn, kart_id)
    if kart is None:
        abort(404)

    if request.method == "POST":
        def _flt(key):
            v = request.form.get(key, "").strip()
            try:
                return float(v) if v else None
            except ValueError:
                return None

        data = {
            "kart_name": request.form.get("kart_name", "").strip() or kart["kart_name"],
            "manufacturer": request.form.get("manufacturer", "").strip() or None,
            "model": request.form.get("model", "").strip() or None,
            "engine": request.form.get("engine", "").strip() or None,
            "power_hp": _flt("power_hp"),
            "kart_weight_kg": _flt("kart_weight_kg"),
            "notes": request.form.get("notes", "").strip() or None,
        }
        update_kart(conn, kart_id, data)
        conn.commit()
        flash("Kart updated.", "success")
        return redirect(url_for("karts.kart_detail", kart_id=kart_id))

    predefined = get_predefined_karts_grouped(conn)
    return render_template("kart_form.html", kart=kart, predefined=predefined)


@bp.route("/<int:kart_id>/delete", methods=["POST"])
def remove_kart(kart_id: int):
    """Delete a kart (unlinks sessions)."""
    conn = get_db_connection()
    kart = get_kart_by_id(conn, kart_id)
    if kart is None:
        abort(404)

    name = kart["kart_name"]
    delete_kart(conn, kart_id)
    conn.commit()
    flash(f"Kart '{name}' deleted.", "success")
    return redirect(url_for("karts.kart_list"))
