"""API endpoints for sim optimizer theoretical lap data.

Endpoints:
    GET /api/v1/sessions/<id>/theoretical          - Full theoretical result
    GET /api/v1/sessions/<id>/theoretical/delta     - Delta vs actual (optional ?lap=N)
    GET /api/v1/sessions/<id>/theoretical/corners   - Corner coaching ranked by time loss
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

import pandas as pd
from flask import Blueprint, current_app, request

from web.api_utils import ErrorCode, api_error, api_response
from web.db import get_db_connection

logger = logging.getLogger(__name__)

bp = Blueprint("theoretical", __name__, url_prefix="/api/v1")

# ── Sidecar storage directory ─────────────────────────────────────────────
# Raw Parquet sidecars are stored at: <SIDECAR_ROOT>/<session_id>/raw_sidecar.parquet
# Default: data/sidecars/ relative to project root, overridable via config.
_SIDECAR_ROOT: Path | None = None


def _get_sidecar_root() -> Path:
    """Resolve sidecar storage root, caching after first call."""
    global _SIDECAR_ROOT
    if _SIDECAR_ROOT is not None:
        return _SIDECAR_ROOT

    # 1. SIDECAR_ROOT env var — the production layout (Docker volume
    #    /data/sidecars), and the ONLY resolution that works in the Celery
    #    worker that WRITES sidecars: the worker has no Flask app context, so
    #    current_app below raises and the relative default would land at the
    #    unmounted /app/data/sidecars. Must match track_surface.store and
    #    web.storage_quota so the writer, reader and quota all agree.
    env_root = os.environ.get("SIDECAR_ROOT")
    if env_root:
        _SIDECAR_ROOT = Path(env_root)
        _SIDECAR_ROOT.mkdir(parents=True, exist_ok=True)
        return _SIDECAR_ROOT

    # 2. Flask config (web process, if explicitly configured)
    try:
        configured = current_app.config.get("RAW_SIDECAR_DIR")
        if configured:
            _SIDECAR_ROOT = Path(configured)
            _SIDECAR_ROOT.mkdir(parents=True, exist_ok=True)
            return _SIDECAR_ROOT
    except RuntimeError:
        pass

    # 3. Default: data/sidecars/ relative to this file's location
    _SIDECAR_ROOT = Path(__file__).resolve().parent.parent.parent.parent / "data" / "sidecars"
    _SIDECAR_ROOT.mkdir(parents=True, exist_ok=True)
    return _SIDECAR_ROOT


def _load_session_raw_data(session_id: str) -> tuple[pd.DataFrame | None, str | None]:
    """Load raw telemetry sidecar for a session.

    Looks for a Parquet file at <sidecar_root>/<session_id>/raw_sidecar.parquet.
    Returns (DataFrame, None) on success, or (None, error_message) on failure.
    """
    sidecar_dir = _get_sidecar_root() / str(session_id)
    parquet_path = sidecar_dir / "raw_sidecar.parquet"

    if not parquet_path.exists():
        return None, "Raw telemetry sidecar not available for this session"

    try:
        df = pd.read_parquet(parquet_path)
        if df.empty:
            return None, "Raw sidecar is empty"

        # Verify it has irsdk__ columns
        irsdk_cols = [c for c in df.columns if c.startswith("irsdk__")]
        if len(irsdk_cols) < 5:
            return None, f"Sidecar has only {len(irsdk_cols)} irsdk__ columns (need >= 5)"

        logger.info(
            "Loaded raw sidecar for session %s: %d rows, %d irsdk__ channels",
            session_id, len(df), len(irsdk_cols),
        )
        return df, None
    except Exception as exc:
        logger.warning("Failed to load sidecar for %s: %s", session_id, exc)
        return None, f"Error loading raw data: {exc}"


def _run_optimizer(raw_df: pd.DataFrame, best_lap: int | None = None):
    """Run the sim optimizer pipeline. Returns SimOptimizerResult."""
    from telemetry_tool.sim_optimizer.pipeline import optimize_session
    return optimize_session(raw_df, best_lap_number=best_lap)


@bp.route("/sessions/<session_id>/theoretical", methods=["GET"])
def get_theoretical(session_id: str):
    """Get theoretical optimal lap for a session.

    Returns speed profile, input traces, vehicle model summary, and lap time.
    """
    try:
        raw_df, err = _load_session_raw_data(session_id)
        if raw_df is None:
            return api_error(
                ErrorCode.DATA_UNAVAILABLE,
                f"Theoretical analysis not available: {err}",
                status=404,
            )

        result = _run_optimizer(raw_df)
        if not result.success:
            errors = "; ".join(result.errors) if result.errors else "Unknown"
            return api_error(
                ErrorCode.INTERNAL_ERROR,
                f"Optimizer failed: {errors}",
                status=500,
            )

        from telemetry_tool.sim_optimizer.output.traces import serialize_theoretical_trace

        response = {
            "session_id": session_id,
            "theoretical_lap_time_s": round(float(result.theoretical.lap_time_s), 3),
            "summary": result.summary,
        }
        if result.input_trace is not None:
            response["trace"] = serialize_theoretical_trace(result.input_trace)
        if result.vehicle_model is not None and hasattr(result.vehicle_model, "to_dict"):
            response["vehicle_model"] = result.vehicle_model.to_dict()

        return api_response(response)

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
        raw_df, err = _load_session_raw_data(session_id)
        if raw_df is None:
            return api_error(ErrorCode.DATA_UNAVAILABLE, f"Delta not available: {err}", status=404)

        result = _run_optimizer(raw_df, best_lap=lap_number)
        if not result.success:
            errors = "; ".join(result.errors) if result.errors else "Unknown"
            return api_error(ErrorCode.INTERNAL_ERROR, f"Optimizer failed: {errors}", status=500)

        if result.delta is None:
            return api_error(
                ErrorCode.DATA_UNAVAILABLE,
                "Delta computation failed (no actual vs theoretical comparison available)",
                status=404,
            )

        from telemetry_tool.sim_optimizer.output.traces import serialize_lap_delta

        response = {
            "session_id": session_id,
            "lap": lap_number,
            "delta": serialize_lap_delta(result.delta),
        }
        if result.theoretical:
            response["theoretical_lap_time_s"] = round(float(result.theoretical.lap_time_s), 3)

        return api_response(response)

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
        raw_df, err = _load_session_raw_data(session_id)
        if raw_df is None:
            return api_error(ErrorCode.DATA_UNAVAILABLE, f"Corner coaching not available: {err}", status=404)

        result = _run_optimizer(raw_df)
        if not result.success:
            errors = "; ".join(result.errors) if result.errors else "Unknown"
            return api_error(ErrorCode.INTERNAL_ERROR, f"Optimizer failed: {errors}", status=500)

        if not result.corners:
            return api_error(
                ErrorCode.DATA_UNAVAILABLE,
                "No corner coaching data available",
                status=404,
            )

        corners_list = []
        for c in sorted(
            result.corners,
            key=lambda x: getattr(x, "time_loss_s", 0.0) if not isinstance(x, dict) else x.get("time_loss_s", 0.0),
            reverse=True,
        ):
            if hasattr(c, "to_dict"):
                corners_list.append(c.to_dict())
            elif isinstance(c, dict):
                corners_list.append(c)
            else:
                corners_list.append({
                    "corner_id": getattr(c, "corner_id", None),
                    "time_loss_s": getattr(c, "time_loss_s", 0.0),
                    "root_cause": getattr(c, "root_cause", ""),
                    "coaching_text": getattr(c, "coaching_text", ""),
                    "brake_point_delta_m": getattr(c, "brake_point_delta_m", 0.0),
                    "apex_speed_delta_kph": getattr(c, "apex_speed_delta_kph", 0.0),
                    "exit_throttle_delta_pct": getattr(c, "exit_throttle_delta_pct", 0.0),
                })

        response = {
            "session_id": session_id,
            "n_corners": len(corners_list),
            "corners": corners_list,
        }
        if result.theoretical:
            response["theoretical_lap_time_s"] = round(float(result.theoretical.lap_time_s), 3)
        if result.summary:
            response["total_time_loss_s"] = result.summary.get("total_time_loss_s", 0.0)

        return api_response(response)

    except Exception:
        logger.exception("Error computing corners for session %s", session_id)
        return api_error(ErrorCode.INTERNAL_ERROR, "Internal error", status=500)


# ── Sidecar storage helper (used by upload endpoint) ─────────────────────

def store_raw_sidecar(session_id: str, raw_df: pd.DataFrame) -> Path:
    """Store a raw telemetry DataFrame as Parquet sidecar for a session.

    Called from the upload endpoint when an .ibt file is uploaded.

    Returns the path to the stored Parquet file.
    """
    sidecar_dir = _get_sidecar_root() / str(session_id)
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = sidecar_dir / "raw_sidecar.parquet"
    raw_df.to_parquet(parquet_path, index=False)
    logger.info("Stored raw sidecar for session %s: %d rows", session_id, len(raw_df))
    return parquet_path
