"""
routes/data_v2_channels.py
--------------------------
Rich telemetry channel endpoints for the Universal Adapter pipeline.

These endpoints serve per-lap channel data (pedals, tire temps, RPM/gear,
wheel slip, brake temps, fuel) stored as JSON columns in ``gps_traces``.

Endpoints:
    GET /api/v1/sessions/<id>/channels          - Available channels list
    GET /api/v1/sessions/<id>/pedals?lap=N       - Throttle, brake, steering
    GET /api/v1/sessions/<id>/tire-temps?lap=N   - Per-corner tire temperatures
    GET /api/v1/sessions/<id>/wheel-slip?lap=N   - Per-corner slip ratios
    GET /api/v1/sessions/<id>/rpm-gear?lap=N     - RPM + gear + speed
    GET /api/v1/sessions/<id>/brake-temps?lap=N  - Per-corner brake temperatures
    GET /api/v1/sessions/<id>/fuel               - Fuel level per lap
"""
from __future__ import annotations

import logging
from functools import wraps

from flask import Blueprint, request

from web.api_utils import api_error, api_response, ErrorCode
from web.db import get_db_connection
from web import models

logger = logging.getLogger(__name__)


def _safe_api(f):
    """Catch unhandled exceptions — log and return structured error."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except Exception:
            from flask import g
            req_id = getattr(g, "request_id", "?")
            logger.exception(
                "Unhandled error in %s [%s %s] request_id=%s",
                f.__name__, request.method, request.path, req_id,
            )
            return api_error(ErrorCode.INTERNAL_ERROR,
                             "Internal server error", status=500)
    return wrapper


bp = Blueprint("data_v2_channels", __name__, url_prefix="/api/v1")


# ── Helpers ───────────────────────────────────────────────────────


def _get_lap_param(conn, session_id: str) -> int | None:
    """Read the ?lap= query parameter or fall back to best/first lap."""
    raw = request.args.get("lap")
    if raw is not None:
        try:
            return int(raw)
        except (ValueError, TypeError):
            return None
    # Fallback: best lap, then first lap.
    laps = models.get_laps_for_session(conn, session_id)
    if not laps:
        return None
    for lap in laps:
        if lap.get("is_best"):
            return lap["lap_number"]
    return laps[0]["lap_number"]


def _channel_unavailable(channel_name: str):
    """Standard response when a channel has no data."""
    return api_response({
        "available": False,
        "message": f"No {channel_name} data available for this session.",
    })


# ══════════════════════════════════════════════════════════════════
# 1. GET /api/v1/sessions/<id>/channels — Available channels
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/channels", methods=["GET"])
@_safe_api
def session_channels(session_id: str):
    """Return which rich telemetry channels are available for a session."""
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if not session:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    availability = models.get_channel_availability(conn, session_id)
    if not availability:
        return api_response({
            "session_id": session_id,
            "channels": {},
            "has_rich_data": False,
            "message": "No telemetry trace data found for this session.",
        })

    has_rich = any(availability.values())
    return api_response({
        "session_id": session_id,
        "channels": availability,
        "has_rich_data": has_rich,
    })


# ══════════════════════════════════════════════════════════════════
# 2. GET /api/v1/sessions/<id>/pedals — Throttle, brake, steering
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/pedals", methods=["GET"])
@_safe_api
def session_pedals(session_id: str):
    """Return throttle, brake, and steering data for a lap."""
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if not session:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    lap = _get_lap_param(conn, session_id)
    if lap is None:
        return api_error(ErrorCode.NOT_FOUND, "No laps found", status=404)

    data = models.get_channel_data(conn, session_id, lap)
    if data is None:
        return _channel_unavailable("pedal")

    has_any = any(k in data for k in ("throttle", "brake", "steering"))
    if not has_any:
        return _channel_unavailable("pedal")

    return api_response({
        "session_id": session_id,
        "lap_number": lap,
        "available": True,
        "distances": data.get("distances", []),
        "throttle": data.get("throttle"),
        "brake": data.get("brake"),
        "steering": data.get("steering"),
    })


# ══════════════════════════════════════════════════════════════════
# 3. GET /api/v1/sessions/<id>/tire-temps — Per-corner tire temps
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/tire-temps", methods=["GET"])
@_safe_api
def session_tire_temps(session_id: str):
    """Return per-corner, per-zone tire temperatures for a lap."""
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if not session:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    lap = _get_lap_param(conn, session_id)
    if lap is None:
        return api_error(ErrorCode.NOT_FOUND, "No laps found", status=404)

    data = models.get_channel_data(conn, session_id, lap)
    if data is None or "tire_temps" not in data:
        return _channel_unavailable("tire temperature")

    return api_response({
        "session_id": session_id,
        "lap_number": lap,
        "available": True,
        "distances": data.get("distances", []),
        "tire_temps": data["tire_temps"],
    })


# ══════════════════════════════════════════════════════════════════
# 4. GET /api/v1/sessions/<id>/wheel-slip — Per-corner slip ratios
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/wheel-slip", methods=["GET"])
@_safe_api
def session_wheel_slip(session_id: str):
    """Return per-corner wheel slip ratios for a lap."""
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if not session:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    lap = _get_lap_param(conn, session_id)
    if lap is None:
        return api_error(ErrorCode.NOT_FOUND, "No laps found", status=404)

    data = models.get_channel_data(conn, session_id, lap)
    if data is None or "wheel_slip" not in data:
        return _channel_unavailable("wheel slip")

    return api_response({
        "session_id": session_id,
        "lap_number": lap,
        "available": True,
        "distances": data.get("distances", []),
        "wheel_slip": data["wheel_slip"],
    })


# ══════════════════════════════════════════════════════════════════
# 5. GET /api/v1/sessions/<id>/rpm-gear — RPM + gear + speed
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/rpm-gear", methods=["GET"])
@_safe_api
def session_rpm_gear(session_id: str):
    """Return RPM, gear, and speed arrays for a lap."""
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if not session:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    lap = _get_lap_param(conn, session_id)
    if lap is None:
        return api_error(ErrorCode.NOT_FOUND, "No laps found", status=404)

    data = models.get_channel_data(conn, session_id, lap)
    if data is None:
        return _channel_unavailable("RPM/gear")

    has_any = any(k in data for k in ("rpm", "gear"))
    if not has_any:
        return _channel_unavailable("RPM/gear")

    return api_response({
        "session_id": session_id,
        "lap_number": lap,
        "available": True,
        "distances": data.get("distances", []),
        "speeds": data.get("speeds", []),
        "rpm": data.get("rpm"),
        "gear": data.get("gear"),
    })


# ══════════════════════════════════════════════════════════════════
# 6. GET /api/v1/sessions/<id>/brake-temps — Per-corner brake temps
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/brake-temps", methods=["GET"])
@_safe_api
def session_brake_temps(session_id: str):
    """Return per-corner brake temperatures for a lap."""
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if not session:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    lap = _get_lap_param(conn, session_id)
    if lap is None:
        return api_error(ErrorCode.NOT_FOUND, "No laps found", status=404)

    data = models.get_channel_data(conn, session_id, lap)
    if data is None or "brake_temps" not in data:
        return _channel_unavailable("brake temperature")

    return api_response({
        "session_id": session_id,
        "lap_number": lap,
        "available": True,
        "distances": data.get("distances", []),
        "brake_temps": data["brake_temps"],
    })


# ══════════════════════════════════════════════════════════════════
# 7. GET /api/v1/sessions/<id>/fuel — Fuel level per lap
# ══════════════════════════════════════════════════════════════════


@bp.route("/sessions/<session_id>/fuel", methods=["GET"])
@_safe_api
def session_fuel(session_id: str):
    """Return fuel level data.

    If ?lap=N is provided, return the trace for that specific lap.
    Otherwise return a summary across all laps with available fuel data.
    """
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if not session:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    raw_lap = request.args.get("lap")

    if raw_lap is not None:
        # Single-lap mode.
        try:
            lap = int(raw_lap)
        except (ValueError, TypeError):
            return api_error(ErrorCode.VALIDATION_ERROR,
                             "Invalid lap number", status=400)

        data = models.get_channel_data(conn, session_id, lap)
        if data is None or "fuel" not in data:
            return _channel_unavailable("fuel")

        return api_response({
            "session_id": session_id,
            "lap_number": lap,
            "available": True,
            "distances": data.get("distances", []),
            "fuel": data["fuel"],
        })

    # Summary mode: check first available lap for fuel presence.
    lap_numbers = models.get_gps_lap_numbers(conn, session_id)
    if not lap_numbers:
        return _channel_unavailable("fuel")

    fuel_summary = []
    for ln in lap_numbers:
        data = models.get_channel_data(conn, session_id, ln)
        if data and "fuel" in data and data["fuel"]:
            # Take the first value in the fuel array as the starting fuel.
            start_fuel = data["fuel"][0]
            end_fuel = data["fuel"][-1]
            fuel_summary.append({
                "lap_number": ln,
                "fuel_start": start_fuel,
                "fuel_end": end_fuel,
            })

    if not fuel_summary:
        return _channel_unavailable("fuel")

    return api_response({
        "session_id": session_id,
        "available": True,
        "laps": fuel_summary,
    })
