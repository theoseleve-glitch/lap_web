"""JSON API endpoints for entity management (drivers, tracks, karts, weekends, etc.).

All endpoints use the standard api_response()/api_error() envelope.
Field names are mapped to match frontend expectations.
"""
from __future__ import annotations

import logging
from flask import Blueprint, request
from web.api_utils import api_response, api_error, ErrorCode
from db import queries as Q

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
