"""API endpoints for sim optimizer theoretical lap data.

Endpoints:
    GET /api/v1/sessions/<id>/theoretical          - Full theoretical result
    GET /api/v1/sessions/<id>/theoretical/delta     - Delta vs actual (optional ?lap=N)
    GET /api/v1/sessions/<id>/theoretical/corners   - Corner coaching ranked by time loss
"""
from __future__ import annotations

import logging

from flask import Blueprint, request

from web.api_utils import ErrorCode, api_error, api_response

logger = logging.getLogger(__name__)

bp = Blueprint("theoretical", __name__, url_prefix="/api/v1")


def _load_session_raw_data(session_id: str) -> tuple[dict | None, str | None]:
    """Load raw telemetry data for a session.

    Returns (data_dict, error_message).
    For MVP: returns None with message indicating feature is pending raw data storage.
    In production: loads from Parquet sidecar stored during upload.
    """
    # MVP stub -- raw sidecar storage not yet wired
    return None, "Raw telemetry sidecar not available for this session"


@bp.route("/sessions/<session_id>/theoretical", methods=["GET"])
def get_theoretical(session_id: str):
    """Get theoretical optimal lap for a session.

    Returns speed profile, input traces, vehicle model summary, and lap time.
    """
    try:
        raw_data, err = _load_session_raw_data(session_id)
        if raw_data is None:
            return api_error(
                ErrorCode.DATA_UNAVAILABLE,
                f"Theoretical analysis not available: {err}",
                status=404,
            )

        # When raw data is available:
        # from telemetry_tool.sim_optimizer.pipeline import optimize_session
        # result = optimize_session(raw_df)
        # if not result.success:
        #     return api_error(ErrorCode.INTERNAL_ERROR, "Optimizer failed", status=500)
        # return api_response({
        #     "session_id": session_id,
        #     "lap_time_s": result.theoretical.lap_time_s,
        #     "speed_profile": serialize_theoretical_trace(result.input_trace),
        #     "vehicle_model": result.vehicle_model.to_dict(),
        #     "summary": result.summary,
        # })

        return api_error(ErrorCode.DATA_UNAVAILABLE, "Theoretical analysis not yet available", status=404)
    except Exception:
        logger.exception("Error computing theoretical for session %s", session_id)
        return api_error(ErrorCode.INTERNAL_ERROR, "Internal error", status=500)


@bp.route("/sessions/<session_id>/theoretical/delta", methods=["GET"])
def get_theoretical_delta(session_id: str):
    """Get delta between actual and theoretical lap.

    Optional query param: ?lap=N (default: best lap)

    Returns distance-aligned time delta, speed delta, and input deltas.
    """
    lap_number = request.args.get("lap", type=int)

    try:
        raw_data, err = _load_session_raw_data(session_id)
        if raw_data is None:
            return api_error(ErrorCode.DATA_UNAVAILABLE, f"Delta not available: {err}", status=404)

        return api_error(ErrorCode.DATA_UNAVAILABLE, "Delta analysis not yet available", status=404)
    except Exception:
        logger.exception("Error computing delta for session %s", session_id)
        return api_error(ErrorCode.INTERNAL_ERROR, "Internal error", status=500)


@bp.route("/sessions/<session_id>/theoretical/corners", methods=["GET"])
def get_theoretical_corners(session_id: str):
    """Get per-corner coaching ranked by time loss.

    Returns corners with: time_loss_s, root_cause, coaching_text,
    brake_point_delta_m, apex_speed_delta_kph, exit_throttle_delta_pct.
    """
    try:
        raw_data, err = _load_session_raw_data(session_id)
        if raw_data is None:
            return api_error(ErrorCode.DATA_UNAVAILABLE, f"Corner coaching not available: {err}", status=404)

        return api_error(ErrorCode.DATA_UNAVAILABLE, "Corner coaching not yet available", status=404)
    except Exception:
        logger.exception("Error computing corners for session %s", session_id)
        return api_error(ErrorCode.INTERNAL_ERROR, "Internal error", status=500)
