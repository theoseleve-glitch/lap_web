"""JSON API endpoints for entity management (drivers, tracks, karts, weekends, etc.).

All endpoints use the standard api_response()/api_error() envelope.
Field names are mapped to match frontend expectations.
"""
from __future__ import annotations

import logging
from flask import Blueprint, request
from web.api_utils import api_response, api_error, ErrorCode
from db import queries as Q
import web.models as models

logger = logging.getLogger(__name__)

bp = Blueprint("api_v1_entities", __name__, url_prefix="/api/v1")


def _get_conn():
    """Get DB connection — overridden in tests."""
    from web.routes.data_v2 import get_db_connection
    return get_db_connection()


# ══════════════════════════════════════════════════════════════════
# Drivers
# ══════════════════════════════════════════════════════════════════

def _map_driver(row):
    """Map DB driver row to frontend-expected field names."""
    d = dict(row)
    return {
        "id": d["driver_id"],
        "name": d["driver_name"],
        "notes": d.get("notes"),
        "created_at": d.get("created_at"),
        "session_count": d.get("session_count", 0),
        "personal_best_s": d.get("personal_best_s"),
        "mean_score": d.get("mean_score"),
    }


@bp.route("/drivers", methods=["GET"])
def list_drivers():
    conn = _get_conn()
    rows = conn.execute(Q.SELECT_ALL_DRIVERS).fetchall()
    return api_response([_map_driver(r) for r in rows])


@bp.route("/drivers/<int:driver_id>", methods=["GET"])
def get_driver(driver_id):
    conn = _get_conn()
    row = conn.execute(
        "SELECT d.*, COUNT(s.session_id) AS session_count, "
        "MIN(s.best_lap_time_s) AS personal_best_s, AVG(s.total_score) AS mean_score "
        "FROM drivers d LEFT JOIN sessions s ON d.driver_id = s.driver_id "
        "WHERE d.driver_id = ?", (driver_id,)
    ).fetchone()
    if not row or row["driver_id"] is None:
        return api_error(ErrorCode.NOT_FOUND, "Driver not found", status=404)
    return api_response(_map_driver(row))


@bp.route("/drivers/<int:driver_id>", methods=["PATCH"])
def patch_driver(driver_id):
    conn = _get_conn()
    row = conn.execute("SELECT * FROM drivers WHERE driver_id = ?", (driver_id,)).fetchone()
    if not row:
        return api_error(ErrorCode.NOT_FOUND, "Driver not found", status=404)
    body = request.get_json(silent=True) or {}
    allowed = {"driver_name", "notes"}
    sets, vals = [], []
    for f in allowed:
        if f in body:
            sets.append(f"{f} = ?")
            vals.append(body[f])
    # Also accept "name" mapped to "driver_name"
    if "name" in body and "driver_name" not in body:
        sets.append("driver_name = ?")
        vals.append(body["name"])
    if not sets:
        return api_error(ErrorCode.VALIDATION_ERROR, "No updatable fields", status=400)
    vals.append(driver_id)
    conn.execute(f"UPDATE drivers SET {', '.join(sets)} WHERE driver_id = ?", vals)
    conn.commit()
    updated = conn.execute(
        "SELECT d.*, COUNT(s.session_id) AS session_count, "
        "MIN(s.best_lap_time_s) AS personal_best_s, AVG(s.total_score) AS mean_score "
        "FROM drivers d LEFT JOIN sessions s ON d.driver_id = s.driver_id "
        "WHERE d.driver_id = ?", (driver_id,)
    ).fetchone()
    return api_response(_map_driver(updated))


# ══════════════════════════════════════════════════════════════════
# Tracks
# ══════════════════════════════════════════════════════════════════

def _map_track(row):
    d = dict(row)
    return {
        "id": d["track_id"],
        "name": d["track_name"],
        "lap_length_m": d.get("lap_length_m"),
        "has_joker": bool(d.get("has_joker")),
        "session_count": d.get("session_count", 0),
        "best_time_s": d.get("best_time_s"),
        "created_at": d.get("created_at"),
        "updated_at": d.get("updated_at"),
    }


@bp.route("/tracks", methods=["GET"])
def list_tracks():
    conn = _get_conn()
    rows = conn.execute(Q.SELECT_ALL_TRACKS).fetchall()
    return api_response([_map_track(r) for r in rows])


@bp.route("/tracks/<track_id>", methods=["GET"])
def get_track(track_id):
    conn = _get_conn()
    row = conn.execute(
        "SELECT t.*, COUNT(s.session_id) AS session_count, "
        "MIN(s.best_lap_time_s) AS best_time_s "
        "FROM tracks t LEFT JOIN sessions s ON t.track_id = s.track_id "
        "WHERE t.track_id = ?", (track_id,)
    ).fetchone()
    if not row or row["track_id"] is None:
        return api_error(ErrorCode.NOT_FOUND, "Track not found", status=404)
    return api_response(_map_track(row))


@bp.route("/tracks/<track_id>", methods=["PATCH"])
def patch_track(track_id):
    conn = _get_conn()
    row = conn.execute(Q.SELECT_TRACK_BY_ID, {"track_id": track_id}).fetchone()
    if not row:
        return api_error(ErrorCode.NOT_FOUND, "Track not found", status=404)
    body = request.get_json(silent=True) or {}
    allowed = {"track_name", "has_joker", "joker_distance_delta_m", "joker_time_delta_s"}
    sets, vals = [], []
    for f in allowed:
        if f in body:
            sets.append(f"{f} = ?")
            vals.append(body[f])
    if "name" in body and "track_name" not in body:
        sets.append("track_name = ?")
        vals.append(body["name"])
    if not sets:
        return api_error(ErrorCode.VALIDATION_ERROR, "No updatable fields", status=400)
    sets.append("updated_at = datetime('now')")
    vals.append(track_id)
    conn.execute(f"UPDATE tracks SET {', '.join(sets)} WHERE track_id = ?", vals)
    conn.commit()
    updated = conn.execute(
        "SELECT t.*, COUNT(s.session_id) AS session_count, "
        "MIN(s.best_lap_time_s) AS best_time_s "
        "FROM tracks t LEFT JOIN sessions s ON t.track_id = s.track_id "
        "WHERE t.track_id = ?", (track_id,)
    ).fetchone()
    return api_response(_map_track(updated))


# ══════════════════════════════════════════════════════════════════
# Karts
# ══════════════════════════════════════════════════════════════════

def _map_kart(row):
    """Map DB kart row to frontend-expected field names."""
    d = dict(row) if not isinstance(row, dict) else row
    return {
        "id": d["kart_id"],
        "name": d["kart_name"],
        "manufacturer": d.get("manufacturer"),
        "model": d.get("model"),
        "engine": d.get("engine"),
        "power_hp": d.get("power_hp"),
        "weight_kg": d.get("kart_weight_kg"),
        "notes": d.get("notes"),
        "created_at": d.get("created_at"),
        "session_count": d.get("session_count", 0),
    }


@bp.route("/karts", methods=["GET"])
def list_karts():
    conn = _get_conn()
    rows = models.get_all_karts(conn)
    return api_response([_map_kart(r) for r in rows])


@bp.route("/karts", methods=["POST"])
def create_kart():
    conn = _get_conn()
    body = request.get_json(silent=True) or {}
    name = body.get("name") or body.get("kart_name")
    if not name:
        return api_error(ErrorCode.VALIDATION_ERROR, "name is required", status=400)
    kart_id = models.create_kart(
        conn,
        kart_name=name,
        predefined_kart_id=body.get("predefined_kart_id"),
        manufacturer=body.get("manufacturer"),
        model=body.get("model"),
        engine=body.get("engine"),
        power_hp=body.get("power_hp"),
        kart_weight_kg=body.get("weight_kg") or body.get("kart_weight_kg"),
        notes=body.get("notes"),
    )
    conn.commit()
    kart = models.get_kart_by_id(conn, kart_id)
    return api_response(_map_kart(kart), status=201)


@bp.route("/karts/<int:kart_id>", methods=["GET"])
def get_kart(kart_id):
    conn = _get_conn()
    kart = models.get_kart_by_id(conn, kart_id)
    if not kart:
        return api_error(ErrorCode.NOT_FOUND, "Kart not found", status=404)
    d = dict(kart) if not isinstance(kart, dict) else kart.copy()
    count = conn.execute(
        "SELECT COUNT(*) AS c FROM sessions WHERE kart_id = ?", (kart_id,)
    ).fetchone()
    d["session_count"] = count["c"] if count else 0
    return api_response(_map_kart(d))


@bp.route("/karts/<int:kart_id>", methods=["PATCH"])
def patch_kart(kart_id):
    conn = _get_conn()
    kart = models.get_kart_by_id(conn, kart_id)
    if not kart:
        return api_error(ErrorCode.NOT_FOUND, "Kart not found", status=404)
    body = request.get_json(silent=True) or {}
    update_data = {}
    if "name" in body:
        update_data["kart_name"] = body["name"]
    if "kart_name" in body:
        update_data["kart_name"] = body["kart_name"]
    for f in ("manufacturer", "model", "engine", "power_hp", "notes"):
        if f in body:
            update_data[f] = body[f]
    if "weight_kg" in body:
        update_data["kart_weight_kg"] = body["weight_kg"]
    if "kart_weight_kg" in body:
        update_data["kart_weight_kg"] = body["kart_weight_kg"]
    if not update_data:
        return api_error(ErrorCode.VALIDATION_ERROR, "No updatable fields", status=400)
    models.update_kart(conn, kart_id, update_data)
    conn.commit()
    updated = models.get_kart_by_id(conn, kart_id)
    return api_response(_map_kart(updated))


@bp.route("/karts/<int:kart_id>", methods=["DELETE"])
def delete_kart(kart_id):
    conn = _get_conn()
    kart = models.get_kart_by_id(conn, kart_id)
    if not kart:
        return api_error(ErrorCode.NOT_FOUND, "Kart not found", status=404)
    count = conn.execute(
        "SELECT COUNT(*) AS c FROM sessions WHERE kart_id = ?", (kart_id,)
    ).fetchone()
    if count and count["c"] > 0:
        return api_error(
            ErrorCode.CONFLICT,
            f"Cannot delete kart with {count['c']} linked session(s). Unlink sessions first.",
            status=409,
        )
    conn.execute("DELETE FROM karts WHERE kart_id = ?", (kart_id,))
    conn.commit()
    return api_response({"deleted": True})


@bp.route("/predefined-karts", methods=["GET"])
def list_predefined_karts():
    conn = _get_conn()
    grouped = models.get_predefined_karts_grouped(conn)
    return api_response(grouped)


# ══════════════════════════════════════════════════════════════════
# Weekends
# ══════════════════════════════════════════════════════════════════

def _map_weekend(row):
    """Map DB weekend row to frontend-expected field names."""
    d = dict(row)
    return {
        "id": d["weekend_id"],
        "name": d.get("name"),
        "track_id": d.get("track_id"),
        "track_name": d.get("track_name"),
        "start_date": d.get("start_date"),
        "end_date": d.get("end_date"),
        "notes": d.get("notes"),
        "session_count": d.get("session_count", 0),
        "created_at": d.get("created_at"),
    }


@bp.route("/weekends", methods=["GET"])
def list_weekends():
    conn = _get_conn()
    rows = conn.execute(Q.SELECT_ALL_WEEKENDS).fetchall()
    return api_response([_map_weekend(r) for r in rows])


@bp.route("/weekends", methods=["POST"])
def create_weekend():
    conn = _get_conn()
    body = request.get_json(silent=True) or {}
    name = body.get("name")
    if not name:
        return api_error(ErrorCode.VALIDATION_ERROR, "name is required", status=400)
    conn.execute(Q.INSERT_WEEKEND, {
        "name": name,
        "track_id": body.get("track_id"),
        "start_date": body.get("start_date"),
        "end_date": body.get("end_date"),
        "notes": body.get("notes"),
    })
    conn.commit()
    wid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    row = conn.execute(Q.SELECT_WEEKEND_BY_ID, {"weekend_id": wid}).fetchone()
    result = _map_weekend(row)
    result["session_count"] = 0
    return api_response(result, status=201)


@bp.route("/weekends/<int:weekend_id>", methods=["GET"])
def get_weekend(weekend_id):
    conn = _get_conn()
    row = conn.execute(Q.SELECT_WEEKEND_BY_ID, {"weekend_id": weekend_id}).fetchone()
    if not row:
        return api_error(ErrorCode.NOT_FOUND, "Weekend not found", status=404)
    result = _map_weekend(row)
    sessions = conn.execute(Q.SELECT_WEEKEND_SESSIONS, {"weekend_id": weekend_id}).fetchall()
    result["sessions"] = [dict(s) for s in sessions]
    result["session_count"] = len(sessions)
    return api_response(result)


@bp.route("/weekends/<int:weekend_id>", methods=["PATCH"])
def patch_weekend(weekend_id):
    conn = _get_conn()
    existing = conn.execute(Q.SELECT_WEEKEND_BY_ID, {"weekend_id": weekend_id}).fetchone()
    if not existing:
        return api_error(ErrorCode.NOT_FOUND, "Weekend not found", status=404)
    body = request.get_json(silent=True) or {}
    ed = dict(existing)
    conn.execute(Q.UPDATE_WEEKEND, {
        "weekend_id": weekend_id,
        "name": body.get("name", ed.get("name")),
        "track_id": body.get("track_id", ed.get("track_id")),
        "start_date": body.get("start_date", ed.get("start_date")),
        "end_date": body.get("end_date", ed.get("end_date")),
        "notes": body.get("notes", ed.get("notes")),
    })
    conn.commit()
    updated = conn.execute(Q.SELECT_WEEKEND_BY_ID, {"weekend_id": weekend_id}).fetchone()
    result = _map_weekend(updated)
    return api_response(result)


@bp.route("/weekends/<int:weekend_id>", methods=["DELETE"])
def delete_weekend(weekend_id):
    conn = _get_conn()
    existing = conn.execute(Q.SELECT_WEEKEND_BY_ID, {"weekend_id": weekend_id}).fetchone()
    if not existing:
        return api_error(ErrorCode.NOT_FOUND, "Weekend not found", status=404)
    conn.execute(Q.DELETE_ALL_WEEKEND_SESSIONS, {"weekend_id": weekend_id})
    conn.execute(Q.DELETE_WEEKEND, {"weekend_id": weekend_id})
    conn.commit()
    return api_response({"deleted": True})


# ══════════════════════════════════════════════════════════════════
# Leaderboard
# ══════════════════════════════════════════════════════════════════

@bp.route("/leaderboard", methods=["GET"])
def leaderboard():
    conn = _get_conn()
    track_id = request.args.get("track_id")
    driver_id = request.args.get("driver_id")
    limit = request.args.get("limit", 50, type=int)

    where_clauses = ["s.best_lap_time_s IS NOT NULL"]
    params = []
    if track_id:
        where_clauses.append("s.track_id = ?")
        params.append(track_id)
    if driver_id:
        where_clauses.append("s.driver_id = ?")
        params.append(int(driver_id))

    where_sql = " AND ".join(where_clauses)
    params.append(limit)

    rows = conn.execute(
        f"SELECT s.session_id, s.session_date, s.best_lap_time_s, "
        f"s.total_score, s.track_state, s.n_laps, "
        f"d.driver_name, t.track_name, s.track_id "
        f"FROM sessions s "
        f"JOIN drivers d ON s.driver_id = d.driver_id "
        f"LEFT JOIN tracks t ON s.track_id = t.track_id "
        f"WHERE {where_sql} "
        f"ORDER BY s.best_lap_time_s ASC "
        f"LIMIT ?",
        params,
    ).fetchall()
    return api_response([dict(r) for r in rows])


# ══════════════════════════════════════════════════════════════════
# Development Plans
# ══════════════════════════════════════════════════════════════════

def _map_plan(row):
    """Map DB development_plan row to frontend-expected field names."""
    d = dict(row)
    return {
        "id": d["id"],
        "driver_id": d["driver_id"],
        "plan_name": d.get("plan_name"),
        "template_id": d.get("template_id"),
        "level": d.get("level"),
        "status": d.get("status"),
        "created_at": d.get("created_at"),
        "updated_at": d.get("updated_at"),
    }


@bp.route("/dev-plans", methods=["GET"])
def list_dev_plans():
    conn = _get_conn()
    driver_id = request.args.get("driver_id", type=int)
    if driver_id:
        rows = conn.execute(Q.SELECT_PLANS_FOR_DRIVER, {"driver_id": driver_id}).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM development_plans ORDER BY created_at DESC"
        ).fetchall()
    return api_response([_map_plan(r) for r in rows])


@bp.route("/dev-plans", methods=["POST"])
def create_dev_plan():
    conn = _get_conn()
    body = request.get_json(silent=True) or {}
    driver_id = body.get("driver_id")
    plan_name = body.get("plan_name")
    if not driver_id or not plan_name:
        return api_error(ErrorCode.VALIDATION_ERROR, "driver_id and plan_name are required", status=400)
    conn.execute(Q.INSERT_DEVELOPMENT_PLAN, {
        "driver_id": driver_id,
        "plan_name": plan_name,
        "template_id": body.get("template_id"),
        "level": body.get("level", "intermediate"),
        "weeks_json": body.get("weeks_json", "[]"),
        "progress_json": body.get("progress_json"),
    })
    conn.commit()
    pid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    row = conn.execute(Q.SELECT_PLAN_BY_ID, {"id": pid}).fetchone()
    return api_response(_map_plan(row), status=201)


@bp.route("/dev-plans/<int:plan_id>", methods=["GET"])
def get_dev_plan(plan_id):
    conn = _get_conn()
    row = conn.execute(Q.SELECT_PLAN_BY_ID, {"id": plan_id}).fetchone()
    if not row:
        return api_error(ErrorCode.NOT_FOUND, "Plan not found", status=404)
    return api_response(_map_plan(row))


@bp.route("/dev-plans/<int:plan_id>", methods=["PATCH"])
def patch_dev_plan(plan_id):
    conn = _get_conn()
    row = conn.execute(Q.SELECT_PLAN_BY_ID, {"id": plan_id}).fetchone()
    if not row:
        return api_error(ErrorCode.NOT_FOUND, "Plan not found", status=404)
    body = request.get_json(silent=True) or {}
    progress_json = body.get("progress_json")
    if progress_json is None:
        return api_error(ErrorCode.VALIDATION_ERROR, "progress_json is required", status=400)
    conn.execute(Q.UPDATE_PLAN_PROGRESS, {"id": plan_id, "progress_json": progress_json})
    conn.commit()
    updated = conn.execute(Q.SELECT_PLAN_BY_ID, {"id": plan_id}).fetchone()
    return api_response(_map_plan(updated))


@bp.route("/dev-plans/<int:plan_id>", methods=["DELETE"])
def delete_dev_plan(plan_id):
    conn = _get_conn()
    row = conn.execute(Q.SELECT_PLAN_BY_ID, {"id": plan_id}).fetchone()
    if not row:
        return api_error(ErrorCode.NOT_FOUND, "Plan not found", status=404)
    conn.execute(Q.DELETE_DEVELOPMENT_PLAN, {"id": plan_id})
    conn.commit()
    return api_response({"deleted": True})
