"""14-step pipeline orchestrator for the sim optimizer.

Every step is wrapped in _safe_step() for graceful degradation.
If a step fails, subsequent steps receive None and degrade gracefully.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, TypeVar

import numpy as np
import pandas as pd
from scipy.ndimage import uniform_filter1d

from kart_envelope.track.geometry import TrackGeometry
from telemetry_tool.sim_optimizer.analysis.corner_coaching import (
    CornerDelta,
    analyze_corners,
)
from telemetry_tool.sim_optimizer.analysis.delta import LapDelta, compute_lap_delta
from telemetry_tool.sim_optimizer.analysis.validation import (
    validate_against_iracing_optimal,
)
from telemetry_tool.sim_optimizer.config import SimOptimizerConfig, default_config
from telemetry_tool.sim_optimizer.ingest.highrate import unpack_highrate
from telemetry_tool.sim_optimizer.ingest.raw_channels import (
    RawChannelSet,
    extract_raw_channels,
)
from telemetry_tool.sim_optimizer.ingest.segment_filter import compute_segment_mask
from telemetry_tool.sim_optimizer.output.summary import build_session_summary
from telemetry_tool.sim_optimizer.param_id.aero_model import AeroModel, identify_aero_model
from telemetry_tool.sim_optimizer.param_id.brake_model import BrakeModel, identify_brake_model
from telemetry_tool.sim_optimizer.param_id.mass_model import MassModel, identify_mass_model
from telemetry_tool.sim_optimizer.param_id.powertrain_model import (
    PowertrainModel,
    identify_powertrain_model,
)
from telemetry_tool.sim_optimizer.param_id.suspension_model import (
    SuspensionModel,
    identify_suspension_model,
)
from telemetry_tool.sim_optimizer.param_id.tyre_model import TyreModel, identify_tyre_model
from telemetry_tool.sim_optimizer.param_id.vehicle_model import VehicleModel
from telemetry_tool.sim_optimizer.reconstruction.input_trace import (
    TheoreticalInputTrace,
    reconstruct_inputs,
)
from telemetry_tool.sim_optimizer.solver.qss_enhanced import (
    SimSolverError,
    SimTheoreticalResult,
    compute_sim_theoretical_lap,
)

log = logging.getLogger(__name__)
T = TypeVar("T")

# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------


@dataclass
class SimOptimizerResult:
    """Complete output of the sim optimizer pipeline."""

    vehicle_model: VehicleModel | None = None
    theoretical: SimTheoreticalResult | None = None
    input_trace: TheoreticalInputTrace | None = None
    delta: LapDelta | None = None
    corners: list[CornerDelta] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.theoretical is not None


# ---------------------------------------------------------------------------
# Safe step wrapper
# ---------------------------------------------------------------------------


def _safe_step(name: str, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T | None:
    """Execute a pipeline step, catching all exceptions."""
    try:
        result = fn(*args, **kwargs)
        log.info("Step '%s' completed successfully", name)
        return result
    except Exception as exc:
        log.warning("Step '%s' failed: %s", name, exc, exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Track geometry builder
# ---------------------------------------------------------------------------

_SMOOTH_WINDOW = 15  # samples for curvature smoothing


def _build_track_geometry(channels: RawChannelSet) -> TrackGeometry | None:
    """Build TrackGeometry from raw world positions and lap distance.

    Uses observed curvature: kappa = lat_accel / speed^2, smoothed.
    Falls back to positional curvature if lat_accel unavailable.
    """
    if channels.lap_dist_m is None or channels.pos_x is None or channels.pos_y is None:
        log.warning("Missing lap_dist_m, pos_x, or pos_y — cannot build geometry")
        return None

    if channels.speed_mps is None:
        log.warning("Missing speed — cannot build geometry")
        return None

    dist = channels.lap_dist_m.copy()
    x = channels.pos_x.copy()
    y = channels.pos_y.copy()
    speed = channels.speed_mps.copy()

    # Sort by distance
    order = np.argsort(dist)
    dist = dist[order]
    x = x[order]
    y = y[order]
    speed = speed[order]

    # Remove duplicate distance values
    unique_mask = np.diff(dist, prepend=-np.inf) > 0.01
    if np.sum(unique_mask) < 3:
        log.warning("Fewer than 3 unique distance points — cannot build geometry")
        return None
    dist = dist[unique_mask]
    x = x[unique_mask]
    y = y[unique_mask]
    speed = speed[unique_mask]

    n = len(dist)

    # Compute heading from position
    dx = np.gradient(x, dist)
    dy = np.gradient(y, dist)
    heading = np.arctan2(dy, dx)

    # Unwrap heading for continuity
    heading = np.unwrap(heading)

    # Curvature: prefer observed (lat_accel / v^2) for accuracy
    lat_accel_sorted = None
    if channels.lat_accel is not None:
        lat_accel_sorted = channels.lat_accel[order][unique_mask]

    if lat_accel_sorted is not None:
        speed_safe = np.maximum(speed, 5.0)
        curvature = lat_accel_sorted / (speed_safe ** 2)
    else:
        # Fallback: positional curvature dtheta/ds
        curvature = np.gradient(heading, dist)

    # Smooth curvature
    if n >= _SMOOTH_WINDOW:
        curvature = uniform_filter1d(curvature, size=_SMOOTH_WINDOW, mode="wrap")

    lap_length = float(dist[-1] - dist[0])
    if lap_length <= 0:
        log.warning("Lap length is zero or negative")
        return None

    # Build elevation if available
    elevation = np.zeros(n)
    if channels.pos_z is not None:
        z_sorted = channels.pos_z[order][unique_mask]
        elevation = z_sorted

    return TrackGeometry(
        distance_m=dist,
        curvature_1pm=np.abs(curvature),
        heading_rad=heading,
        x_ref_m=x,
        y_ref_m=y,
        lap_length_m=lap_length,
        signed_curvature_1pm=curvature,
        elevation_m=elevation,
    )


# ---------------------------------------------------------------------------
# Best lap selection
# ---------------------------------------------------------------------------


def _select_best_lap(
    channels: RawChannelSet,
    best_lap_number: int | None,
) -> int | None:
    """Return the best lap number to optimize.

    If *best_lap_number* is given and present, use it.
    Otherwise pick the lap with the most clean (on-track) samples.
    """
    if channels.lap is None:
        return None

    laps = channels.lap.copy()
    unique_laps = np.unique(laps[~np.isnan(laps)]).astype(int)

    if len(unique_laps) == 0:
        return None

    if best_lap_number is not None and best_lap_number in unique_laps:
        return best_lap_number

    # Pick lap with most samples
    best = unique_laps[0]
    best_count = 0
    for lap_num in unique_laps:
        count = int(np.sum(laps == lap_num))
        if count > best_count:
            best_count = count
            best = lap_num

    return int(best)


# ---------------------------------------------------------------------------
# Helper: safe array fallback
# ---------------------------------------------------------------------------


def _arr_or_zeros(arr: np.ndarray | None, n: int) -> np.ndarray:
    """Return *arr* if not None, else zeros of length *n*."""
    if arr is not None:
        return arr
    return np.zeros(n)


def _arr_or_fill(arr: np.ndarray | None, n: int, fill: float) -> np.ndarray:
    """Return *arr* if not None, else constant array."""
    if arr is not None:
        return arr
    return np.full(n, fill)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def optimize_session(
    raw_df: pd.DataFrame,
    normalized_df: pd.DataFrame | None = None,
    *,
    config: SimOptimizerConfig | None = None,
    best_lap_number: int | None = None,
) -> SimOptimizerResult:
    """Run the full 14-step sim optimizer pipeline.

    Parameters
    ----------
    raw_df : pd.DataFrame
        Raw iRacing Parquet sidecar data (irsdk__ prefixed columns).
    normalized_df : pd.DataFrame | None
        Optional normalized telemetry (for comparison target).
    config : SimOptimizerConfig | None
        Configuration. Uses defaults if None.
    best_lap_number : int | None
        Which lap to optimize. If None, uses the lap with most samples.
    """
    cfg = config or default_config()
    result = SimOptimizerResult()
    n = len(raw_df)

    # ── Step 1: Extract raw channels ─────────────────────────────────
    channels = _safe_step("extract_raw_channels", extract_raw_channels, raw_df, config=cfg)
    if channels is None:
        result.errors.append("Failed to extract raw channels")
        return result

    ns = channels.n_samples

    # ── Step 2: Unpack 360 Hz data ───────────────────────────────────
    highrate = _safe_step("unpack_highrate", unpack_highrate, raw_df, config=cfg)

    # ── Step 3: Segment filter ───────────────────────────────────────
    mask = _safe_step("segment_filter", compute_segment_mask, channels, config=cfg)

    # ── Step 4: Select best lap ──────────────────────────────────────
    best_lap = _select_best_lap(channels, best_lap_number)
    log.info("Selected lap %s for optimization", best_lap)

    # ── Step 5: Mass model ───────────────────────────────────────────
    mass_model = _safe_step(
        "mass_model",
        identify_mass_model,
        speed_mps=_arr_or_zeros(channels.speed_mps, ns),
        long_accel=_arr_or_zeros(channels.long_accel, ns),
        throttle=_arr_or_zeros(channels.throttle, ns),
        fuel_level_l=_arr_or_fill(channels.fuel_level, ns, 30.0),
        bop_penalty_kg=_arr_or_zeros(channels.weight_penalty_kg, ns),
        config=cfg,
    )
    if mass_model is None:
        mass_model = MassModel(
            base_mass_kg=cfg.mass_default_kg,
            fuel_density_kg_l=cfg.mass_fuel_density_kg_l,
            bop_penalty_kg=0.0,
        )
    mass_kg = mass_model.total_mass_kg(30.0)

    # ── Step 6: Aero model ───────────────────────────────────────────
    speed_safe = np.maximum(_arr_or_zeros(channels.speed_mps, ns), 1.0)
    lat_accel_arr = _arr_or_zeros(channels.lat_accel, ns)
    curvature_est = np.abs(lat_accel_arr) / speed_safe ** 2

    aero_model = _safe_step(
        "aero_model",
        identify_aero_model,
        speed_mps=_arr_or_zeros(channels.speed_mps, ns),
        long_accel=_arr_or_zeros(channels.long_accel, ns),
        throttle=_arr_or_zeros(channels.throttle, ns),
        brake=_arr_or_zeros(channels.brake, ns),
        curvature=curvature_est,
        air_density=_arr_or_fill(channels.air_density, ns, 1.18),
        car_dist_ahead=_arr_or_fill(channels.car_dist_ahead, ns, 500.0),
        mass_kg=mass_kg,
        config=cfg,
    )
    if aero_model is None:
        aero_model = AeroModel(
            cda=cfg.aero_cda_default,
            cla=cfg.aero_cla_default,
            air_density=1.18,
        )

    # ── Step 7: Powertrain model ─────────────────────────────────────
    powertrain_model = _safe_step(
        "powertrain_model",
        identify_powertrain_model,
        rpm=_arr_or_zeros(channels.rpm, ns),
        gear=_arr_or_fill(channels.gear, ns, 1.0),
        throttle=_arr_or_zeros(channels.throttle, ns),
        speed_mps=_arr_or_zeros(channels.speed_mps, ns),
        long_accel=_arr_or_zeros(channels.long_accel, ns),
        mass_kg=mass_kg,
        config=cfg,
    )
    if powertrain_model is None:
        powertrain_model = PowertrainModel(
            gear_torque_maps={},
            wheel_radius_m=0.33,
            transmission_efficiency=cfg.powertrain_transmission_efficiency,
            rr_c0=cfg.powertrain_rr_c0,
            rr_c1=cfg.powertrain_rr_c1,
        )

    # ── Step 8: Brake model ──────────────────────────────────────────
    brake_model = _safe_step(
        "brake_model",
        identify_brake_model,
        speed_mps=_arr_or_zeros(channels.speed_mps, ns),
        long_accel=_arr_or_zeros(channels.long_accel, ns),
        brake=_arr_or_zeros(channels.brake, ns),
        brake_raw=_arr_or_zeros(channels.brake_raw, ns),
        abs_active=_arr_or_zeros(channels.brake_abs_active, ns).astype(bool),
        brake_bias=_arr_or_fill(channels.dc_brake_bias, ns, 56.0),
        config=cfg,
    )
    if brake_model is None:
        brake_model = BrakeModel(
            max_decel_mps2=10.0,
            brake_bias_front=0.56,
            fade_onset_temp_c=400.0,
            fade_rate=0.001,
        )

    # ── Step 9: Suspension model ─────────────────────────────────────
    suspension_model = _safe_step(
        "suspension_model",
        identify_suspension_model,
        shock_defl_lf=channels.shock_defl_lf,
        shock_defl_rf=channels.shock_defl_rf,
        shock_defl_lr=channels.shock_defl_lr,
        shock_defl_rr=channels.shock_defl_rr,
        lat_accel=_arr_or_zeros(channels.lat_accel, ns),
        long_accel=_arr_or_zeros(channels.long_accel, ns),
        mass_kg=mass_kg,
        config=cfg,
    )
    if suspension_model is None:
        suspension_model = SuspensionModel(
            spring_rate_lf=50000,
            spring_rate_rf=50000,
            spring_rate_lr=45000,
            spring_rate_rr=45000,
            static_defl_m=0.05,
        )

    # ── Step 10: Tyre model ──────────────────────────────────────────
    tyre_model = _safe_step(
        "tyre_model",
        identify_tyre_model,
        slip_ratio=None,
        longitudinal_force=None,
        lateral_slip=None,
        lateral_force=None,
        tyre_load=None,
        config=cfg,
    )
    if tyre_model is None:
        tyre_model = TyreModel()

    # Assemble VehicleModel
    vehicle = VehicleModel(
        tyre=tyre_model,
        aero=aero_model,
        powertrain=powertrain_model,
        brake=brake_model,
        suspension=suspension_model,
        mass=mass_model,
    )
    result.vehicle_model = vehicle

    # ── Step 11: Build track geometry ────────────────────────────────
    geometry = _safe_step("track_geometry", _build_track_geometry, channels)
    if geometry is None:
        result.errors.append("Failed to build track geometry")
        return result

    # ── Step 12: QSS solver ──────────────────────────────────────────
    fuel = float(np.median(channels.fuel_level)) if channels.fuel_level is not None else 30.0
    theoretical = _safe_step(
        "qss_solver",
        compute_sim_theoretical_lap,
        geometry,
        vehicle,
        fuel_level_l=fuel,
        config=cfg,
    )
    if theoretical is None:
        result.errors.append("Solver failed")
        return result
    result.theoretical = theoretical

    # ── Step 13: Input reconstruction ────────────────────────────────
    trace = _safe_step(
        "input_reconstruction",
        reconstruct_inputs,
        theoretical,
        vehicle,
        geometry,
        fuel_level_l=fuel,
    )
    result.input_trace = trace

    # ── Step 14: Delta analysis + corner coaching ────────────────────
    if trace is not None and channels.speed_mps is not None:
        actual_speed = channels.speed_mps
        actual_throttle = _arr_or_zeros(channels.throttle, ns)
        actual_brake = _arr_or_zeros(channels.brake, ns)
        actual_steering = (
            np.degrees(channels.steering_rad)
            if channels.steering_rad is not None
            else np.zeros(ns)
        )
        actual_dist = (
            channels.lap_dist_m
            if channels.lap_dist_m is not None
            else np.linspace(0, geometry.lap_length_m, ns)
        )

        delta = _safe_step(
            "delta_analysis",
            compute_lap_delta,
            actual_dist,
            actual_speed,
            actual_throttle,
            actual_brake,
            actual_steering,
            trace.distance_m,
            trace.speed_mps,
            trace.throttle_pct,
            trace.brake_pct,
            trace.steering_deg,
        )
        result.delta = delta

        if delta is not None:
            corners = _safe_step(
                "corner_coaching",
                analyze_corners,
                delta,
                geometry.curvature_1pm,
                geometry.distance_m,
                actual_brake,
                trace.brake_pct,
                actual_speed,
                trace.speed_mps,
                actual_throttle,
                trace.throttle_pct,
            )
            result.corners = corners or []

    # Validation
    validation = _safe_step(
        "validation",
        validate_against_iracing_optimal,
        theoretical.lap_time_s,
        channels.delta_to_optimal,
    )

    # Summary
    result.summary = (
        _safe_step(
            "summary",
            build_session_summary,
            theoretical,
            trace,
            result.corners,
            vehicle,
            validation or {},
        )
        or {}
    )

    return result
