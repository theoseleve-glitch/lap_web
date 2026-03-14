"""JSON API endpoints for entity management (drivers, tracks, karts, weekends, etc.).

All endpoints use the standard api_response()/api_error() envelope.
Field names are mapped to match frontend expectations.
"""
from __future__ import annotations

import logging

from flask import Blueprint, g, request

import web.models as models
from db import queries as Q
from web.api_utils import ErrorCode, api_error, api_response
from web.repos.delete_cascade import delete_entity_cascade, get_delete_impact

logger = logging.getLogger(__name__)

bp = Blueprint("api_v1_entities", __name__, url_prefix="/api/v1")


@bp.before_request
def _apply_rate_limit():
    from web.rate_limit import rate_limit as _rl_decorator
    tier = "write" if request.method in ("DELETE", "PATCH", "POST", "PUT") else "read"
    @_rl_decorator(tier=tier)
    def _check():
        return None
    result = _check()
    if result is not None:
        return result


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
        "has_profile": d.get("has_profile", False),
        "style_label": d.get("style_label"),
        "total_laps": d.get("total_laps", 0),
    }


@bp.route("/drivers", methods=["GET"])
def list_drivers():
    conn = _get_conn()
    from web.repos.driver_repo import get_all_drivers
    rows = get_all_drivers(conn)
    return api_response([_map_driver(r) for r in rows])


def _verify_driver(conn, driver_id):
    """Return driver row or None."""
    return conn.execute(
        "SELECT * FROM drivers WHERE driver_id = ?", (driver_id,)
    ).fetchone()


@bp.route("/drivers/<int:driver_id>", methods=["GET"])
def get_driver(driver_id):
    conn = _get_conn()
    row = conn.execute(
        "SELECT d.*, COUNT(s.session_id) AS session_count, "
        "MIN(s.best_lap_time_s) AS personal_best_s, AVG(s.total_score) AS mean_score "
        "FROM drivers d LEFT JOIN sessions s ON d.driver_id = s.driver_id AND s.deleted_at IS NULL "
        "WHERE d.driver_id = ? "
        "GROUP BY d.driver_id", (driver_id,)
    ).fetchone()
    if not row or row["driver_id"] is None:
        return api_error(ErrorCode.NOT_FOUND, "Driver not found", status=404)
    result = _map_driver(row)
    from web.repos.driver_repo import get_driver_profile
    profile = get_driver_profile(conn, driver_id)
    result["profile"] = dict(profile) if profile else None
    return api_response(result)


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
        "FROM drivers d LEFT JOIN sessions s ON d.driver_id = s.driver_id AND s.deleted_at IS NULL "
        "WHERE d.driver_id = ? "
        "GROUP BY d.driver_id", (driver_id,)
    ).fetchone()
    return api_response(_map_driver(updated))


@bp.route("/drivers/<int:driver_id>/progression", methods=["GET"])
def get_driver_progression(driver_id):
    conn = _get_conn()
    if not _verify_driver(conn, driver_id):
        return api_error(ErrorCode.NOT_FOUND, "Driver not found", status=404)
    from web.repos.driver_repo import get_driver_progression as _get_prog
    prog = _get_prog(conn, driver_id)
    return api_response({"driver_id": driver_id, "progression": prog})


@bp.route("/drivers/<int:driver_id>/style-history", methods=["GET"])
def get_driver_style_history(driver_id):
    conn = _get_conn()
    if not _verify_driver(conn, driver_id):
        return api_error(ErrorCode.NOT_FOUND, "Driver not found", status=404)
    from web.repos.driver_repo import get_driver_style_history as _get_style
    history = _get_style(conn, driver_id)
    for h in history:
        h.pop("strengths_json", None)
        h.pop("weaknesses_json", None)
    return api_response({"driver_id": driver_id, "history": history})


@bp.route("/drivers/<int:driver_id>/badges", methods=["GET"])
def get_driver_badges(driver_id):
    conn = _get_conn()
    if not _verify_driver(conn, driver_id):
        return api_error(ErrorCode.NOT_FOUND, "Driver not found", status=404)
    rows = conn.execute(
        "SELECT * FROM driver_badges WHERE driver_id = ? ORDER BY earned_at DESC",
        (driver_id,),
    ).fetchall()
    return api_response({"driver_id": driver_id, "badges": [dict(r) for r in rows]})


@bp.route("/drivers/<int:driver_id>/best-ever", methods=["GET"])
def get_driver_best_ever(driver_id):
    conn = _get_conn()
    if not _verify_driver(conn, driver_id):
        return api_error(ErrorCode.NOT_FOUND, "Driver not found", status=404)
    from web.repos.driver_repo import compute_best_ever_relative
    result = compute_best_ever_relative(conn, driver_id)
    return api_response(result)


@bp.route("/drivers/<int:driver_id>/sessions", methods=["GET"])
def get_driver_sessions(driver_id):
    conn = _get_conn()
    if not _verify_driver(conn, driver_id):
        return api_error(ErrorCode.NOT_FOUND, "Driver not found", status=404)
    rows = conn.execute(
        "SELECT s.session_id, s.session_date, s.best_lap_time_s, "
        "s.total_score, s.n_laps, s.track_state, "
        "t.track_name, s.track_id "
        "FROM sessions s "
        "LEFT JOIN tracks t ON s.track_id = t.track_id "
        "WHERE s.driver_id = ? AND s.deleted_at IS NULL "
        "ORDER BY s.session_date DESC",
        (driver_id,),
    ).fetchall()
    return api_response({"driver_id": driver_id, "sessions": [dict(r) for r in rows]})


@bp.route("/drivers/<int:driver_id>/profile", methods=["PATCH"])
def patch_driver_profile(driver_id):
    conn = _get_conn()
    if not _verify_driver(conn, driver_id):
        return api_error(ErrorCode.NOT_FOUND, "Driver not found", status=404)
    body = request.get_json(silent=True) or {}
    field_name = body.get("field")
    value = body.get("value")
    if not field_name:
        return api_error(ErrorCode.VALIDATION_ERROR, "field is required", status=400)
    from web.repos.driver_repo import (
        get_driver_profile, upsert_driver_profile, update_driver_profile_field,
    )
    if get_driver_profile(conn, driver_id) is None:
        upsert_driver_profile(conn, driver_id, {})
        conn.commit()
    try:
        update_driver_profile_field(conn, driver_id, field_name, value)
        conn.commit()
    except ValueError:
        return api_error(ErrorCode.VALIDATION_ERROR, f"Field '{field_name}' is not editable", status=400)
    return api_response({"field": field_name, "value": value})


@bp.route("/drivers/<int:driver_id>", methods=["DELETE"])
def delete_driver(driver_id):
    logger.info("DELETE /drivers/%s — entering handler", driver_id)
    conn = _get_conn()
    if not _verify_driver(conn, driver_id):
        return api_error(ErrorCode.NOT_FOUND, "Driver not found", status=404)
    # CRITICAL: rollback on failure — see delete_track docstring for rationale.
    try:
        result = delete_entity_cascade(conn, "driver", driver_id)
        conn.commit()
        logger.info("DELETE /drivers/%s — success, impact=%s", driver_id, result["impact"])
    except Exception as exc:
        conn.rollback()  # CRITICAL: undo child deletes if parent fails
        logger.exception("DELETE /drivers/%s — cascade failed: %s", driver_id, exc)
        return api_error(ErrorCode.INTERNAL_ERROR, "Delete failed", status=500)
    return api_response(result)


@bp.route("/drivers/<int:driver_id>/delete-impact", methods=["GET"])
def driver_delete_impact(driver_id):
    conn = _get_conn()
    if not _verify_driver(conn, driver_id):
        return api_error(ErrorCode.NOT_FOUND, "Driver not found", status=404)
    result = get_delete_impact(conn, "driver", driver_id)
    return api_response(result)


# ══════════════════════════════════════════════════════════════════
# Tracks
# ══════════════════════════════════════════════════════════════════

def _is_unnamed_track(d: dict) -> bool:
    """True if track_name is missing or looks like an auto-generated UUID."""
    name = (d.get("track_name") or "").strip()
    tid = (d.get("track_id") or "").strip()
    if not name:
        return True
    # Pipeline falls back to track_id (a UUID) when no name is found
    if name == tid:
        return True
    return False


def _map_track(row):
    d = dict(row)
    return {
        "id": d["track_id"],
        "name": d["track_name"],
        "unnamed": _is_unnamed_track(d),
        "lap_length_m": d.get("lap_length_m"),
        "has_joker": bool(d.get("has_joker")),
        "session_count": d.get("session_count", 0),
        "best_time_s": d.get("best_time_s"),
        "lap_count": d.get("lap_count"),
        "start_lat": d.get("start_lat"),
        "start_lon": d.get("start_lon"),
        "created_at": d.get("created_at"),
        "updated_at": d.get("updated_at"),
    }


@bp.route("/tracks", methods=["GET"])
def list_tracks():
    conn = _get_conn()

    include_unnamed = request.args.get("include_unnamed", "0") == "1"
    rows = conn.execute(Q.SELECT_ALL_TRACKS).fetchall()
    mapped = [_map_track(r) for r in rows]
    if not include_unnamed:
        mapped = [t for t in mapped if not t["unnamed"]]
    return api_response(mapped)


@bp.route("/tracks/<track_id>", methods=["GET"])
def get_track(track_id):
    conn = _get_conn()
    row = conn.execute(
        "SELECT t.*, COUNT(s.session_id) AS session_count, "
        "MIN(s.best_lap_time_s) AS best_time_s, "
        "COALESCE(SUM(s.n_laps), 0) AS lap_count "
        "FROM tracks t LEFT JOIN sessions s ON t.track_id = s.track_id AND s.deleted_at IS NULL "
        "WHERE t.track_id = ? "
        "GROUP BY t.track_id", (track_id,)
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
        "MIN(s.best_lap_time_s) AS best_time_s, "
        "COALESCE(SUM(s.n_laps), 0) AS lap_count "
        "FROM tracks t LEFT JOIN sessions s ON t.track_id = s.track_id AND s.deleted_at IS NULL "
        "WHERE t.track_id = ? "
        "GROUP BY t.track_id", (track_id,)
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


@bp.route("/tracks/<track_id>", methods=["DELETE"])
def delete_track(track_id):
    """Delete a track and all child data via cascade.

    CRITICAL: The try/except + conn.rollback() pattern is required. Without
    the explicit rollback, close_pg() commits partial child deletes when the
    parent DELETE fails (FK constraint from an unlisted table), causing data
    corruption where sessions vanish but the track remains. Do NOT remove
    the rollback or restructure without understanding delete_cascade.py.
    """
    conn = _get_conn()
    row = conn.execute("SELECT * FROM tracks WHERE track_id = ?", (track_id,)).fetchone()
    if not row:
        return api_error(ErrorCode.NOT_FOUND, "Track not found", status=404)
    try:
        result = delete_entity_cascade(conn, "track", track_id)
        conn.commit()
    except Exception as exc:
        conn.rollback()  # CRITICAL: undo child deletes if parent fails
        logger.exception("DELETE /tracks/%s — cascade failed: %s", track_id, exc)
        return api_error(ErrorCode.INTERNAL_ERROR, "Delete failed", status=500)
    return api_response(result)


@bp.route("/tracks/<track_id>/delete-impact", methods=["GET"])
def track_delete_impact(track_id):
    conn = _get_conn()
    row = conn.execute("SELECT track_id FROM tracks WHERE track_id = ?", (track_id,)).fetchone()
    if not row:
        return api_error(ErrorCode.NOT_FOUND, "Track not found", status=404)
    result = get_delete_impact(conn, "track", track_id)
    return api_response(result)


@bp.route("/tracks/<track_id>/sessions", methods=["GET"])
def list_track_sessions(track_id):
    conn = _get_conn()
    row = conn.execute("SELECT track_id FROM tracks WHERE track_id = ?", (track_id,)).fetchone()
    if not row:
        return api_error(ErrorCode.NOT_FOUND, "Track not found", status=404)
    rows = conn.execute(
        "SELECT s.session_id, s.session_date, s.best_lap_time_s, s.total_score, "
        "s.n_laps, s.track_state, d.driver_name "
        "FROM sessions s "
        "LEFT JOIN drivers d ON s.driver_id = d.driver_id "
        "WHERE s.track_id = ? AND s.deleted_at IS NULL "
        "ORDER BY s.session_date DESC",
        (track_id,),
    ).fetchall()
    return api_response([dict(r) for r in rows])


@bp.route("/tracks/<track_id>/evolution", methods=["GET"])
def track_evolution(track_id):
    """Aggregate evolution data: lap trends, sector breakdown, corner metrics."""
    conn = _get_conn()
    row = conn.execute("SELECT track_id FROM tracks WHERE track_id = ?", (track_id,)).fetchone()
    if not row:
        return api_error(ErrorCode.NOT_FOUND, "Track not found", status=404)

    # Lap time trend: best lap per session, ordered by date
    sessions = conn.execute(
        "SELECT s.session_id, s.session_date, s.best_lap_time_s, s.total_score, "
        "s.n_laps, s.track_state, d.driver_name "
        "FROM sessions s "
        "LEFT JOIN drivers d ON s.driver_id = d.driver_id "
        "WHERE s.track_id = ? AND s.deleted_at IS NULL AND s.best_lap_time_s IS NOT NULL "
        "ORDER BY s.session_date ASC",
        (track_id,),
    ).fetchall()
    lap_trend = [dict(r) for r in sessions]

    # Sector breakdown: best sector times per session
    sector_data = []
    for sess in lap_trend:
        sid = sess["session_id"]
        sectors = conn.execute(
            "SELECT sector_index, MIN(sector_time_s) AS best_sector_time_s "
            "FROM sector_times WHERE session_id = ? "
            "GROUP BY sector_index ORDER BY sector_index",
            (sid,),
        ).fetchall()
        if sectors:
            sector_data.append({
                "session_id": sid,
                "session_date": sess["session_date"],
                "sectors": [dict(s) for s in sectors],
            })

    # Corner metrics aggregated: avg time loss per corner across all sessions
    corner_metrics = conn.execute(
        "SELECT cm.corner_index, AVG(cm.time_loss_s) AS avg_time_loss_s, "
        "AVG(cm.min_speed_mps) AS avg_min_speed_mps, COUNT(*) AS sample_count "
        "FROM corner_metrics cm "
        "JOIN sessions s ON cm.session_id = s.session_id "
        "WHERE s.track_id = ? AND s.deleted_at IS NULL "
        "GROUP BY cm.corner_index "
        "ORDER BY AVG(cm.time_loss_s) DESC",
        (track_id,),
    ).fetchall()

    return api_response({
        "lap_trend": lap_trend,
        "sector_breakdown": sector_data,
        "corner_metrics": [dict(r) for r in corner_metrics],
    })


@bp.route("/tracks/<track_id>/sectors", methods=["GET"])
def list_track_sectors(track_id):
    conn = _get_conn()
    from web.repos.track_repo import get_track_sectors
    sectors = get_track_sectors(conn, track_id)
    return api_response(sectors)


@bp.route("/tracks/<track_id>/sectors", methods=["POST"])
def add_track_sector(track_id):
    conn = _get_conn()
    row = conn.execute("SELECT track_id FROM tracks WHERE track_id = ?", (track_id,)).fetchone()
    if not row:
        return api_error(ErrorCode.NOT_FOUND, "Track not found", status=404)
    body = request.get_json(silent=True) or {}
    lat = body.get("lat") or body.get("latitude")
    lon = body.get("lon") or body.get("longitude")
    if lat is None or lon is None:
        return api_error(ErrorCode.VALIDATION_ERROR, "lat and lon are required", status=400)
    from web.repos.track_repo import upsert_track_sector
    sector_id = upsert_track_sector(conn, track_id, float(lat), float(lon), body.get("distance_m"))
    conn.commit()
    return api_response({"sector_id": sector_id}, status=201)


@bp.route("/tracks/<track_id>/sectors/<int:sector_id>", methods=["DELETE"])
def remove_track_sector(track_id, sector_id):
    conn = _get_conn()
    from web.repos.track_repo import delete_track_sector
    delete_track_sector(conn, track_id, sector_id)
    conn.commit()
    return api_response({"deleted": True})


@bp.route("/tracks/<track_id>/records", methods=["GET"])
def list_track_records(track_id):
    conn = _get_conn()
    from web.repos.track_repo import get_track_records
    records = get_track_records(conn, track_id)
    return api_response(records)


@bp.route("/tracks/<track_id>/records", methods=["POST"])
def add_track_record(track_id):
    conn = _get_conn()
    row = conn.execute("SELECT track_id FROM tracks WHERE track_id = ?", (track_id,)).fetchone()
    if not row:
        return api_error(ErrorCode.NOT_FOUND, "Track not found", status=404)
    body = request.get_json(silent=True) or {}
    record_time = body.get("record_time_s")
    if record_time is None:
        return api_error(ErrorCode.VALIDATION_ERROR, "record_time_s is required", status=400)
    from web.repos.track_repo import upsert_track_record
    upsert_track_record(
        conn, track_id,
        record_time_s=float(record_time),
        record_holder=body.get("record_holder"),
        record_date=body.get("record_date"),
        vehicle_class=body.get("vehicle_class"),
        source=body.get("source"),
    )
    conn.commit()
    return api_response({"saved": True}, status=201)


@bp.route("/tracks/<track_id>/records/<int:record_id>", methods=["DELETE"])
def remove_track_record(track_id, record_id):
    conn = _get_conn()
    from web.repos.track_repo import delete_track_record
    delete_track_record(conn, record_id)
    conn.commit()
    return api_response({"deleted": True})


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
        "SELECT COUNT(*) AS c FROM sessions WHERE kart_id = ? AND deleted_at IS NULL", (kart_id,)
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
    # CRITICAL: rollback on failure — see delete_track docstring for rationale.
    try:
        result = delete_entity_cascade(conn, "kart", kart_id)
        conn.commit()
    except Exception as exc:
        conn.rollback()  # CRITICAL: undo child deletes if parent fails
        logger.exception("DELETE /karts/%s — cascade failed: %s", kart_id, exc)
        return api_error(ErrorCode.INTERNAL_ERROR, "Delete failed", status=500)
    return api_response(result)


@bp.route("/karts/<int:kart_id>/delete-impact", methods=["GET"])
def kart_delete_impact(kart_id):
    conn = _get_conn()
    kart = models.get_kart_by_id(conn, kart_id)
    if not kart:
        return api_error(ErrorCode.NOT_FOUND, "Kart not found", status=404)
    result = get_delete_impact(conn, "kart", kart_id)
    return api_response(result)


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
        "sessions_count": d.get("session_count", 0),
        "created_at": d.get("created_at"),
    }


@bp.route("/weekends", methods=["GET"])
def list_weekends():
    conn = _get_conn()
    rows = conn.execute(Q.SELECT_ALL_WEEKENDS).fetchall()
    return api_response({"weekends": [_map_weekend(r) for r in rows]})


@bp.route("/weekends", methods=["POST"])
def create_weekend():
    conn = _get_conn()
    body = request.get_json(silent=True) or {}
    name = body.get("name")
    if not name:
        return api_error(ErrorCode.VALIDATION_ERROR, "name is required", status=400)
    cur = conn.execute(Q.INSERT_WEEKEND, {
        "name": name,
        "track_id": body.get("track_id"),
        "start_date": body.get("start_date"),
        "end_date": body.get("end_date"),
        "notes": body.get("notes"),
    })
    row = cur.fetchone()
    conn.commit()
    if row is None:
        return api_error(ErrorCode.INTERNAL_ERROR, "Failed to create weekend", status=500)
    wid = row[0] if not isinstance(row, dict) else row.get("weekend_id")
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
    # CRITICAL: rollback on failure — see delete_track docstring for rationale.
    try:
        result = delete_entity_cascade(conn, "weekend", weekend_id)
        conn.commit()
    except Exception as exc:
        conn.rollback()  # CRITICAL: undo child deletes if parent fails
        logger.exception("DELETE /weekends/%s — cascade failed: %s", weekend_id, exc)
        return api_error(ErrorCode.INTERNAL_ERROR, "Delete failed", status=500)
    return api_response(result)


@bp.route("/weekends/<int:weekend_id>/delete-impact", methods=["GET"])
def weekend_delete_impact(weekend_id):
    conn = _get_conn()
    existing = conn.execute(Q.SELECT_WEEKEND_BY_ID, {"weekend_id": weekend_id}).fetchone()
    if not existing:
        return api_error(ErrorCode.NOT_FOUND, "Weekend not found", status=404)
    result = get_delete_impact(conn, "weekend", weekend_id)
    return api_response(result)


# ══════════════════════════════════════════════════════════════════
# Leaderboard
# ══════════════════════════════════════════════════════════════════

@bp.route("/leaderboard", methods=["GET"])
def leaderboard():
    conn = _get_conn()
    track_id = request.args.get("track_id")
    driver_id = request.args.get("driver_id")
    limit = min(request.args.get("limit", 50, type=int), 200)

    where_clauses = ["s.best_lap_time_s IS NOT NULL"]
    params = []
    if track_id:
        where_clauses.append("s.track_id = ?")
        params.append(track_id)
    if driver_id:
        try:
            driver_id_int = int(driver_id)
        except (ValueError, TypeError):
            return api_error(ErrorCode.VALIDATION_ERROR, "driver_id must be an integer", status=400)
        where_clauses.append("s.driver_id = ?")
        params.append(driver_id_int)

    where_sql = " AND ".join(where_clauses)
    params.append(limit)

    rows = conn.execute(
        f"SELECT s.session_id, s.session_date, s.best_lap_time_s, "
        f"s.total_score, s.track_state, s.n_laps, "
        f"d.driver_name, t.track_name, s.track_id "
        f"FROM sessions s "
        f"LEFT JOIN drivers d ON s.driver_id = d.driver_id "
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
    import json as _json
    d = dict(row)
    weeks_raw = d.get("weeks_json")
    progress_raw = d.get("progress_json")
    try:
        weeks = _json.loads(weeks_raw) if weeks_raw else []
    except (TypeError, _json.JSONDecodeError):
        weeks = []
    return {
        "id": d["id"],
        "driver_id": d["driver_id"],
        "plan_name": d.get("plan_name"),
        "template_id": d.get("template_id"),
        "level": d.get("level"),
        "status": d.get("status"),
        "weeks": weeks,
        "progress_json": progress_raw,
        "created_at": d.get("created_at"),
        "updated_at": d.get("updated_at"),
    }


@bp.route("/dev-plans/templates", methods=["GET"])
def list_dev_plan_templates():
    """Return available plan templates."""
    from development_plan import get_plan_templates
    return api_response(get_plan_templates())


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

    template_id = body.get("template_id")
    if template_id:
        from development_plan import create_plan_from_template
        try:
            result = create_plan_from_template(conn, driver_id, template_id, plan_name)
            return api_response(result, status=201)
        except ValueError as exc:
            return api_error(ErrorCode.NOT_FOUND, str(exc), status=404)

    cur = conn.execute(Q.INSERT_DEVELOPMENT_PLAN, {
        "driver_id": driver_id,
        "plan_name": plan_name,
        "template_id": None,
        "level": body.get("level", "intermediate"),
        "weeks_json": body.get("weeks_json", "[]"),
        "progress_json": body.get("progress_json"),
    })
    row = cur.fetchone()
    conn.commit()
    if row is None:
        return api_error(ErrorCode.INTERNAL_ERROR, "Failed to create development plan", status=500)
    pid = row[0] if not isinstance(row, dict) else row.get("id")
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

    _ALLOWED = {"progress_json", "plan_name", "status"}
    updates = {k: v for k, v in body.items() if k in _ALLOWED}
    if not updates:
        return api_error(ErrorCode.VALIDATION_ERROR, "No updatable fields provided", status=400)

    set_clauses = ", ".join(f"{k} = :{k}" for k in updates)
    updates["id"] = plan_id
    conn.execute(f"UPDATE development_plans SET {set_clauses} WHERE id = :id", updates)
    conn.commit()
    updated = conn.execute(Q.SELECT_PLAN_BY_ID, {"id": plan_id}).fetchone()
    return api_response(_map_plan(updated))


@bp.route("/dev-plans/<int:plan_id>", methods=["DELETE"])
def delete_dev_plan(plan_id):
    conn = _get_conn()
    row = conn.execute(Q.SELECT_PLAN_BY_ID, {"id": plan_id}).fetchone()
    if not row:
        return api_error(ErrorCode.NOT_FOUND, "Plan not found", status=404)
    # CRITICAL: rollback on failure — see delete_track docstring for rationale.
    try:
        result = delete_entity_cascade(conn, "dev_plan", plan_id)
        conn.commit()
    except Exception as exc:
        conn.rollback()  # CRITICAL: undo child deletes if parent fails
        logger.exception("DELETE /dev-plans/%s — cascade failed: %s", plan_id, exc)
        return api_error(ErrorCode.INTERNAL_ERROR, "Delete failed", status=500)
    return api_response(result)


@bp.route("/dev-plans/<int:plan_id>/delete-impact", methods=["GET"])
def dev_plan_delete_impact(plan_id):
    conn = _get_conn()
    row = conn.execute(Q.SELECT_PLAN_BY_ID, {"id": plan_id}).fetchone()
    if not row:
        return api_error(ErrorCode.NOT_FOUND, "Plan not found", status=404)
    result = get_delete_impact(conn, "dev_plan", plan_id)
    return api_response(result)


# ══════════════════════════════════════════════════════════════════
# Gamification
# ══════════════════════════════════════════════════════════════════

def _workspace_id() -> int:
    return getattr(g, "workspace_id", 1)


@bp.route("/drivers/<int:driver_id>/progress", methods=["GET"])
def get_driver_progress_api(driver_id):
    """Full driver progress: XP, level, streak, achievements."""
    conn = _get_conn()
    row = _verify_driver(conn, driver_id)
    if not row:
        return api_error(ErrorCode.NOT_FOUND, "Driver not found", status=404)
    try:
        from gamification.xp import get_driver_progress as _get_progress
        from gamification.achievements import get_achievement_status
        wid = _workspace_id()
        progress = _get_progress(conn, driver_id, wid)
        progress["achievements"] = get_achievement_status(conn, driver_id, wid)
        return api_response(progress)
    except Exception:
        logger.warning("Gamification progress failed for driver %s", driver_id, exc_info=True)
        return api_response({"total_xp": 0, "level": 0, "achievements": []})


@bp.route("/drivers/<int:driver_id>/achievements", methods=["GET"])
def get_driver_achievements(driver_id):
    """All 15 achievements with locked/unlocked state."""
    conn = _get_conn()
    row = _verify_driver(conn, driver_id)
    if not row:
        return api_error(ErrorCode.NOT_FOUND, "Driver not found", status=404)
    try:
        from gamification.achievements import get_achievement_status
        return api_response(get_achievement_status(conn, driver_id, _workspace_id()))
    except Exception:
        logger.warning("Achievements failed for driver %s", driver_id, exc_info=True)
        return api_response([])


@bp.route("/dev-plans/<int:plan_id>/drills/<int:week>/<int:drill_idx>/execute", methods=["POST"])
def execute_drill(plan_id, week, drill_idx):
    """Log a drill execution, optionally linking to a session. Awards XP on 'completed'."""
    conn = _get_conn()
    row = conn.execute(Q.SELECT_PLAN_BY_ID, {"id": plan_id}).fetchone()
    if not row:
        return api_error(ErrorCode.NOT_FOUND, "Plan not found", status=404)
    body = request.get_json(silent=True) or {}
    session_id = body.get("session_id")
    status = body.get("status", "attempted")
    if status not in ("attempted", "completed", "skipped"):
        return api_error(ErrorCode.VALIDATION_ERROR, "status must be attempted, completed, or skipped", status=400)
    notes = body.get("notes")
    driver_id = dict(row)["driver_id"]
    wid = _workspace_id()
    try:
        from gamification.queries import insert_drill_execution
        exec_id = insert_drill_execution(
            conn, wid, driver_id, plan_id, week, drill_idx,
            session_id, status, notes,
        )
        xp_result = None
        if status == "completed":
            from gamification.xp import award_drill_xp
            xp_result = award_drill_xp(conn, driver_id, wid, plan_id)
        conn.commit()
        return api_response({"execution_id": exec_id, "status": status, "xp_result": xp_result}, status=201)
    except Exception:
        logger.warning("Drill execution failed for plan %s", plan_id, exc_info=True)
        return api_error(ErrorCode.SERVER_ERROR, "Failed to log drill execution", status=500)


@bp.route("/dev-plans/<int:plan_id>/executions", methods=["GET"])
def list_drill_executions(plan_id):
    """All drill executions for a plan with session details."""
    conn = _get_conn()
    row = conn.execute(Q.SELECT_PLAN_BY_ID, {"id": plan_id}).fetchone()
    if not row:
        return api_error(ErrorCode.NOT_FOUND, "Plan not found", status=404)
    try:
        from gamification.queries import get_plan_executions
        return api_response(get_plan_executions(conn, plan_id, _workspace_id()))
    except Exception:
        logger.warning("Drill executions fetch failed for plan %s", plan_id, exc_info=True)
        return api_response([])
