"""Pipeline runner — wraps the friction estimation stack as a callable.

This module mirrors the logic in scripts/replay_daytona_friction.py but
takes a manifest-driven DatasetEntry and returns a structured
PipelineResult that the validation harness can score.

Frozen-by-default. Adaptation flags are off unless explicitly enabled
via PipelineConfig.allow_*_fit. This is the load-bearing rule for
honest cross-track transfer measurement.

The runner does NOT touch:
  - The OCP solver itself
  - The replay_daytona_friction.py baseline script

Anything broken with the underlying stack will surface here, not here.
"""
from __future__ import annotations

import logging
import os
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import numpy as np

from track_surface.condition_bucketing import (
    ACTIVE_BUCKETS,
    TRANSITION_BUCKET,
    BucketKey,
    BucketedSurfaceField,
    assign_bucket_keys,
)
from track_surface.robust_ocp import (
    PlannerMode,
    RobustGripConfig,
    compare_modes,
)
from track_surface.surface_field import SurfaceField, SurfaceFieldConfig
from track_surface.surface_inverse_solver import (
    ExcitationConfig,
    solve_lambda_surface,
)
from track_surface.tire_model import TireInputs, TireParams, predict_tire_forces
from track_surface.validation.manifest import DatasetEntry, VehicleSpec
from track_surface.wheel_kinematics.dataclasses import CarGeometry
from track_surface.wheel_kinematics.slip_angles import compute_slip_angles

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────

_G: Final[float] = 9.80665
_EARTH_R: Final[float] = 6371000.0
_TYPE_DTYPE: Final[dict] = {1: np.uint8, 2: np.int32, 3: np.uint32, 4: np.float32, 5: np.float64}
_TYPE_SIZE: Final[dict] = {1: 1, 2: 4, 3: 4, 4: 4, 5: 8}


# ── Configuration ────────────────────────────────────────────


@dataclass(frozen=True)
class PipelineConfig:
    """All non-vehicle pipeline knobs.

    These are the ESTIMATOR / FIELD parameters that should stay frozen
    across sessions in Pass 1. Vehicle-specific values come from the
    DatasetEntry's VehicleSpec, not from here.
    """

    # ── Road state estimator ─────────────────────────────────
    roll_compliance_init_rad_per_mps2: float = 0.005
    pitch_compliance_init_rad_per_mps2: float = 0.003
    smooth_window: int = 60                # samples (1s @ 60Hz)
    transition_threshold: float = 0.008    # |d(bank)/dt|

    # ── Subsampling ──────────────────────────────────────────
    subsample_step: int = 10               # process every Nth sample for speed

    # ── Surface field grid ───────────────────────────────────
    field_ds_m: float = 5.0
    field_dn_m: float = 1.0
    field_n_range_m: float = 12.0

    # ── Adaptation flags (FROZEN BY DEFAULT) ────────────────
    allow_roll_compliance_fit: bool = False
    allow_tire_d_scale_fit: bool = False

    # ── Excitation / inverse solver ──────────────────────────
    excitation: ExcitationConfig = field(default_factory=ExcitationConfig)

    # ── Robust OCP config ────────────────────────────────────
    robust_config: RobustGripConfig = field(default_factory=RobustGripConfig)

    # ── Validity gates ───────────────────────────────────────
    min_speed_for_valid: float = 5.0

    # ── Persistence layer (off by default) ──────────────────
    # When set, the harness will:
    #   1. Resolve the vehicle to a CalibrationProfile via the registry
    #      (otherwise uses VehicleSpec defaults)
    #   2. Load/create the matching CrossSessionAccumulator
    #   3. After the live bucketed field is built, attempt to merge it
    #   4. Compute layered fallback metrics (current+accumulated)
    #   5. Save the accumulator
    calibration_registry_path: str | None = None
    accumulator_dir: str | None = None
    accumulator_min_obs_per_cell: int = 3
    accumulator_divergence_sigmas: float = 3.0
    accumulator_save_after_merge: bool = True

    # ── Transition gate (defaults to multi-criterion gate) ──
    # The legacy single-axis gate is reachable for A/B comparison via
    # use_multi_criterion_gate=False.
    use_multi_criterion_gate: bool = True


# ── Result ───────────────────────────────────────────────────


@dataclass
class PipelineResult:
    """Structured snapshot of one full pipeline run.

    Carries everything the metrics module needs, plus enough raw arrays
    that the reporter can produce diagnostic plots later.

    All numpy arrays are sample-aligned to `n_valid` length unless
    documented otherwise.
    """

    # ── Identification ───────────────────────────────────────
    dataset_id: str
    ibt_path: str
    pipeline_version: str = "v1"
    config_summary: dict[str, Any] = field(default_factory=dict)

    # ── Sample accounting ────────────────────────────────────
    n_samples_total: int = 0
    n_valid: int = 0

    # ── Lap structure ────────────────────────────────────────
    best_lap: int = -1
    best_lap_time_s: float = 0.0
    n_laps: int = 0
    lap_times_s: dict[int, float] = field(default_factory=dict)
    track_length_m: float = 0.0

    # ── Road state ───────────────────────────────────────────
    bank_min_deg: float = 0.0
    bank_max_deg: float = 0.0
    bank_mean_abs_deg: float = 0.0
    grade_min_deg: float = 0.0
    grade_max_deg: float = 0.0
    n_transition_quarantined: int = 0
    transition_pct: float = 0.0
    a_lat_raw_mean: float = 0.0
    a_lat_tire_mean: float = 0.0

    # ── Roll compliance ──────────────────────────────────────
    roll_compliance_used: float = 0.0
    roll_compliance_fitted: float | None = None
    roll_compliance_fit_diagnostics: dict[str, float] | None = None

    # ── Tire model ───────────────────────────────────────────
    tire_d1_lat_used: float = 0.0
    tire_d1_long_used: float = 0.0
    tire_d_fit_result: dict[str, float] | None = None

    # ── Inverse solver ───────────────────────────────────────
    n_accepted_blocks: int = 0
    n_rejected_blocks: int = 0
    reject_reasons: dict[str, int] = field(default_factory=dict)
    lambda_count: int = 0
    lambda_mean: float = 0.0
    lambda_median: float = 0.0
    lambda_std: float = 0.0
    lambda_p5: float = 0.0
    lambda_p95: float = 0.0
    lambda_min: float = 0.0
    lambda_max: float = 0.0
    excitation_mean: float = 0.0

    # ── Per-lap stability ────────────────────────────────────
    lap_lambdas: dict[int, float] = field(default_factory=dict)

    # ── Field summary ────────────────────────────────────────
    field_grid_shape: tuple[int, int] = (0, 0)
    field_cells_observed: int = 0
    field_cells_total: int = 0
    field_coverage_pct: float = 0.0
    field_mean_observed: float = 0.0
    field_std_observed: float = 0.0
    field_mean_confidence: float = 0.0
    field_high_conf_cells: int = 0
    field_zero_conf_cells: int = 0
    field_max_obs_per_cell: int = 0

    # ── Bucket diagnostics ───────────────────────────────────
    bucket_diagnostics: dict[str, dict[str, Any]] = field(default_factory=dict)
    bucket_active_count: int = 0
    bucket_sparse_count: int = 0
    bucket_fallback_distribution: dict[int, int] = field(default_factory=dict)

    # ── Racing line structure ────────────────────────────────
    racing_line_center_lambda: float = 0.0
    racing_line_left_lambda: float = 0.0
    racing_line_right_lambda: float = 0.0

    # ── Residual diagnostics ─────────────────────────────────
    fy_residual_mean: float = 0.0
    fy_residual_std: float = 0.0
    fx_residual_mean: float = 0.0
    fx_residual_std: float = 0.0

    # ── Planner outputs ──────────────────────────────────────
    planner_nominal_mean_mu: float = 0.0
    planner_robust_mean_mu: float = 0.0
    planner_exploitable_mean_mu: float = 0.0
    planner_n_trusted: int = 0
    planner_n_degraded: int = 0
    planner_n_transition_excluded: int = 0
    planner_max_robust_penalty: float = 0.0
    planner_sectors_most_tightened: list[tuple[float, float]] = field(default_factory=list)

    # ── Transition gate diagnostics ─────────────────────────
    gate_kind: str = "single_axis"     # "single_axis" | "multi_criterion"
    gate_accept_pct: float = 0.0
    gate_reason_counts: dict[str, int] = field(default_factory=dict)
    gate_regime_counts: dict[str, int] = field(default_factory=dict)
    gate_n_unstable_runs: int = 0
    gate_longest_unstable_run: int = 0

    # ── Persistence layer (filled when accumulator_dir is set) ──
    calibration_profile_id: str | None = None
    calibration_source: str | None = None    # "registry_active" | "class_fallback" | "default" | "none"
    accumulator_key: str | None = None
    accumulator_n_sessions_before: int = 0   # how many sessions were in the accumulator before this run
    accumulator_n_sessions_after: int = 0    # after this run (before+1 if accepted, else =before)
    merge_outcome: str | None = None         # "accepted" | "rejected:<reason>" | "skipped"
    merge_rejected_buckets: list[str] = field(default_factory=list)
    accumulated_fallback_distribution: dict[int, int] = field(default_factory=dict)
    accumulated_evidence_source_counts: dict[str, int] = field(default_factory=dict)

    # ── Bookkeeping ──────────────────────────────────────────
    elapsed_s: float = 0.0
    pipeline_warnings: list[str] = field(default_factory=list)
    exception: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.exception is None and self.lambda_count > 0


# ── .ibt extraction (mirrored from replay script) ────────────


def extract_channels(path: Path) -> dict[str, np.ndarray]:
    """Parse an iRacing .ibt file into a flat dict of channel arrays."""
    # Imported lazily because the path manipulation in the extractor
    # module is invasive when imported eagerly at module load.
    from lap_oracle.extractors.iracing_ibt import _parse_header, _parse_var_headers

    with open(path, "rb") as f:
        header_bytes = f.read(max(4096, 144 * 500 + 200))
        hdr = _parse_header(header_bytes)
        vars_map = _parse_var_headers(header_bytes, hdr)
        file_size = os.path.getsize(path)
        num_samples = (file_size - hdr["data_start"]) // hdr["buf_len"]
        f.seek(hdr["data_start"])
        raw = f.read(hdr["buf_len"] * num_samples)
        arr = np.frombuffer(raw, dtype=np.uint8).reshape(num_samples, hdr["buf_len"])

    data = {}
    for name, info in vars_map.items():
        if info.get("count", 1) != 1:
            continue
        t = info["type"]
        if t not in _TYPE_SIZE:
            continue
        off, sz, dt = info["offset"], _TYPE_SIZE[t], _TYPE_DTYPE[t]
        data[name] = np.frombuffer(arr[:, off:off + sz].tobytes(), dtype=dt).astype(np.float64)
    return data


# ── Stage helpers ────────────────────────────────────────────


def _build_geometry(vehicle: VehicleSpec) -> CarGeometry:
    """Build the kinematics geometry from a VehicleSpec."""
    return CarGeometry(
        wheelbase_m=vehicle.wheelbase_m,
        track_front_m=vehicle.track_front_m,
        track_rear_m=vehicle.track_rear_m,
        cg_to_front_m=vehicle.wheelbase_m * (1.0 - vehicle.weight_dist_front),
        cg_to_rear_m=vehicle.wheelbase_m * vehicle.weight_dist_front,
        steer_ratio=vehicle.steer_ratio,
        max_steer_rad=0.5,
        camber_fl_rad=np.radians(vehicle.camber_front_deg),
        camber_fr_rad=np.radians(vehicle.camber_front_deg),
        camber_rl_rad=np.radians(vehicle.camber_rear_deg),
        camber_rr_rad=np.radians(vehicle.camber_rear_deg),
    )


def _project_xy_meters(lat_deg: np.ndarray, lon_deg: np.ndarray) -> tuple[np.ndarray, np.ndarray, float, float]:
    """Project lat/lon to local meters using the dataset mean as origin."""
    lat_rad = np.radians(lat_deg)
    lon_rad = np.radians(lon_deg)
    lat_ref = float(np.nanmean(lat_rad))
    lon_ref = float(np.nanmean(lon_rad))
    x_m = _EARTH_R * (lon_rad - lon_ref) * np.cos(lat_ref)
    y_m = _EARTH_R * (lat_rad - lat_ref)
    return x_m, y_m, lat_ref, lon_ref


def _compute_lap_times(lap: np.ndarray, session_time: np.ndarray, lap_dist_pct: np.ndarray) -> dict[int, float]:
    """Return {lap_number: lap_time_s} for laps with >=500 samples covering >=95% of the lap."""
    lap_times: dict[int, float] = {}
    unique_laps = np.unique(lap[lap > 0])
    for lnum in unique_laps:
        mask = lap == lnum
        if mask.sum() < 500:
            continue
        pct = lap_dist_pct[mask]
        if pct.max() - pct.min() < 0.95:
            continue
        lap_times[int(lnum)] = float(session_time[mask][-1] - session_time[mask][0])
    return lap_times


# ── The big one ──────────────────────────────────────────────


def run_pipeline(
    entry: DatasetEntry,
    config: PipelineConfig | None = None,
) -> PipelineResult:
    """Run the full friction estimation + planner pipeline on one dataset.

    Returns a PipelineResult. Catches stage exceptions so the harness
    can keep running across all datasets without crashing. The exception
    string is recorded for the reporter.
    """
    if config is None:
        config = PipelineConfig()

    result = PipelineResult(
        dataset_id=entry.id,
        ibt_path=entry.ibt_path,
        config_summary={
            "subsample_step": config.subsample_step,
            "field_ds_m": config.field_ds_m,
            "field_dn_m": config.field_dn_m,
            "allow_roll_compliance_fit": config.allow_roll_compliance_fit,
            "allow_tire_d_scale_fit": config.allow_tire_d_scale_fit,
            "vehicle_class": entry.vehicle.klass,
            "track_regime": entry.track.regime,
        },
    )
    t_start = time.perf_counter()

    try:
        _execute(entry, config, result)
    except Exception as e:  # pragma: no cover — surfaces upstream bugs
        logger.exception("Pipeline failed on %s", entry.id)
        result.exception = f"{type(e).__name__}: {e}"
    finally:
        result.elapsed_s = time.perf_counter() - t_start

    return result


def _execute(entry: DatasetEntry, config: PipelineConfig, result: PipelineResult) -> None:
    """Run all pipeline stages. Mutates `result` in place."""
    # Lazy imports — these are heavy and we want pipeline_runner.py
    # to be importable without all of them resolving when only the
    # manifest is needed (e.g. in tests).
    from track_surface.beta_estimator import estimate_beta_offline_smooth
    from track_surface.centerline import extract_centerline
    from track_surface.frenet import FrenetFrame
    from track_surface.physics_grip import (
        build_vehicle_geometry,
        compute_per_wheel_normal_loads,
        compute_per_wheel_tangential_forces,
    )
    from track_surface.road_state_estimator import (
        RoadEstimatorConfig,
        estimate_road_state_batch,
    )

    ibt_path = Path(entry.ibt_path)
    if not ibt_path.is_file():
        raise FileNotFoundError(f"IBT file not found: {ibt_path}")

    # ── 1. Channel extraction ────────────────────────────────
    ch = extract_channels(ibt_path)
    result.n_samples_total = len(ch["Lat"])

    valid = (
        ch["IsOnTrack"].astype(bool)
        & (ch["Lat"] != 0.0)
        & (ch["Lon"] != 0.0)
        & (ch["Speed"] > config.min_speed_for_valid)
    )
    result.n_valid = int(valid.sum())
    if result.n_valid < 1000:
        result.pipeline_warnings.append(
            f"too_few_valid_samples: only {result.n_valid} samples passed validity gate"
        )
        return

    # ── 2. Geometry from VehicleSpec ─────────────────────────
    geom = _build_geometry(entry.vehicle)

    tire_params = TireParams(
        d1_lat=entry.vehicle.tire_d1_lat_default,
        d1_long=entry.vehicle.tire_d1_long_default,
        d2_lat=-0.0001,
        d2_long=-0.0001,
    )
    result.tire_d1_lat_used = tire_params.d1_lat
    result.tire_d1_long_used = tire_params.d1_long

    phys_geom = build_vehicle_geometry(
        None,
        shock_defl_mean=None,
        cg_height_default=entry.vehicle.cg_height_m,
        weight_dist_front_default=entry.vehicle.weight_dist_front,
    )

    # ── 3. Slice valid samples ───────────────────────────────
    speed = ch["Speed"][valid]
    a_long = ch["LongAccel"][valid]
    a_lat = ch["LatAccel"][valid]
    roll = ch["Roll"][valid]
    pitch = ch["Pitch"][valid]
    steer = ch["SteeringWheelAngle"][valid]
    yaw_rate = ch["YawRate"][valid]
    lap = ch["Lap"][valid]
    session_time = ch["SessionTime"][valid]
    lap_dist_pct = ch["LapDistPct"][valid]
    lat_deg = ch["Lat"][valid]
    lon_deg = ch["Lon"][valid]

    # ── 4. Road state estimation ─────────────────────────────
    road_config = RoadEstimatorConfig(
        roll_compliance_rad_per_mps2=config.roll_compliance_init_rad_per_mps2,
        pitch_compliance_rad_per_mps2=config.pitch_compliance_init_rad_per_mps2,
        smooth_window=config.smooth_window,
    )
    bank_est, grade_est, a_lat_tire, a_long_tire, road_quality = estimate_road_state_batch(
        speed=speed, a_lat=a_lat, a_long=a_long,
        yaw_rate=yaw_rate, roll=roll, pitch=pitch,
        config=road_config,
    )
    result.bank_min_deg = float(np.degrees(bank_est.min()))
    result.bank_max_deg = float(np.degrees(bank_est.max()))
    result.bank_mean_abs_deg = float(np.degrees(np.abs(bank_est).mean()))
    result.grade_min_deg = float(np.degrees(grade_est.min()))
    result.grade_max_deg = float(np.degrees(grade_est.max()))
    result.a_lat_raw_mean = float(a_lat.mean())
    result.a_lat_tire_mean = float(a_lat_tire.mean())

    # ── 5. Roll compliance (optional adapt) ──────────────────
    rh_available = all(
        k in ch for k in ["LFrideHeight", "RFrideHeight", "LRrideHeight", "RRrideHeight"]
    )
    ride_heights: np.ndarray | None = None
    if rh_available and entry.session.ride_height_available:
        ride_heights = np.column_stack([
            ch["LFrideHeight"][valid],
            ch["RFrideHeight"][valid],
            ch["LRrideHeight"][valid],
            ch["RRrideHeight"][valid],
        ])

    if config.allow_roll_compliance_fit and ride_heights is not None:
        from track_surface.roll_compliance_fit import fit_roll_compliance

        bank_grad = np.abs(np.gradient(bank_est))
        rc_result = fit_roll_compliance(
            ride_heights=ride_heights,
            a_lat_tire=a_lat_tire,
            bank_rad=bank_est,
            bank_gradient=bank_grad,
            speed=speed,
            transition_mask=np.abs(bank_grad) > config.transition_threshold,
            road_quality=road_quality,
            current_compliance=road_config.roll_compliance_rad_per_mps2,
        )
        result.roll_compliance_fitted = float(rc_result.compliance_rad_per_mps2)
        result.roll_compliance_fit_diagnostics = {
            "flat_residual_before": rc_result.flat_residual_before,
            "flat_residual_after": rc_result.flat_residual_after,
            "banked_residual_before": rc_result.banked_residual_before,
            "banked_residual_after": rc_result.banked_residual_after,
            "n_samples_flat": rc_result.n_samples_flat,
            "n_samples_banked": rc_result.n_samples_banked,
        }
        # Apply fitted compliance and re-run road state
        road_config.roll_compliance_rad_per_mps2 = rc_result.compliance_rad_per_mps2
        bank_est, grade_est, a_lat_tire, a_long_tire, road_quality = estimate_road_state_batch(
            speed=speed, a_lat=a_lat, a_long=a_long,
            yaw_rate=yaw_rate, roll=roll, pitch=pitch,
            config=road_config,
        )

    result.roll_compliance_used = float(road_config.roll_compliance_rad_per_mps2)

    # ── Transition mask ──────────────────────────────────────
    # Two paths:
    #   - single_axis: the legacy bank-gradient cliff (kept for A/B)
    #   - multi_criterion: combine bank/grade/yaw/steer/a_lat/ride_height/
    #     road_quality with a hysteresis state machine (entry/exit/dwell/padding)
    # The mask semantics are identical in both paths (True = transition,
    # downstream code is unchanged).
    if config.use_multi_criterion_gate:
        from track_surface.multi_criterion_transition_gate import (
            TransitionGateConfig,
            apply_gate,
        )
        gate_cfg = TransitionGateConfig(
            sample_rate_hz=60.0,  # iRacing telemetry rate
        )
        gate_result = apply_gate(
            bank_est=bank_est,
            grade_est=grade_est,
            yaw_rate=yaw_rate,
            steer=steer,
            a_lat=a_lat,
            road_quality=road_quality,
            ride_heights=ride_heights,
            config=gate_cfg,
        )
        transition_mask = gate_result.reject_mask
        result.gate_kind = "multi_criterion"
        result.gate_accept_pct = float(gate_result.diagnostics.accept_pct)
        result.gate_reason_counts = dict(gate_result.diagnostics.reason_counts)
        result.gate_regime_counts = dict(gate_result.diagnostics.regime_counts)
        result.gate_n_unstable_runs = int(gate_result.diagnostics.n_unstable_runs)
        result.gate_longest_unstable_run = int(gate_result.diagnostics.longest_unstable_run)
    else:
        bank_gradient = np.abs(np.gradient(bank_est))
        transition_mask = bank_gradient > config.transition_threshold
        result.gate_kind = "single_axis"
        result.gate_accept_pct = float((~transition_mask).mean() * 100.0)
        result.gate_reason_counts = {
            "bank_transition": int(transition_mask.sum()),
        }
        result.gate_regime_counts = {
            "stable_flat": int((~transition_mask & (np.abs(bank_est) <= 0.08)).sum()),
            "stable_banked": int((~transition_mask & (np.abs(bank_est) > 0.08)).sum()),
            "unstable": int(transition_mask.sum()),
        }
        result.gate_n_unstable_runs = 0  # not computed in legacy mode
        result.gate_longest_unstable_run = 0

    result.n_transition_quarantined = int(transition_mask.sum())
    result.transition_pct = float(transition_mask.mean() * 100.0)

    # ── 6. Per-wheel loads + body forces ─────────────────────
    a_lat_for_forces = a_lat_tire
    a_long_for_forces = a_long_tire
    loads = compute_per_wheel_normal_loads(
        mass_kg=entry.vehicle.mass_kg,
        speed_mps=speed,
        a_long_body=a_long_for_forces,
        a_lat_body=a_lat_for_forces,
        roll_rad=roll,
        pitch_rad=pitch,
        aero_cla=entry.vehicle.aero_cla,
        air_density=1.225,
        geom=phys_geom,
    )
    drive_rear_only = entry.vehicle.drive_layout == "RWD"
    _ = compute_per_wheel_tangential_forces(
        mass_kg=entry.vehicle.mass_kg,
        fz_per_wheel=loads.fz,
        a_long_body=a_long_for_forces,
        a_lat_body=a_lat_for_forces,
        brake_line_press=None,
        brake_bias_front=entry.vehicle.brake_bias_front,
        drive_rear_only=drive_rear_only,
    )

    # Per-wheel observed forces by Fz ratio (matches replay script)
    fz_sum = np.maximum(loads.fz.sum(axis=1), 1.0)
    fx_obs = np.zeros_like(loads.fz)
    fy_obs = np.zeros_like(loads.fz)
    f_lat_total = entry.vehicle.mass_kg * (-a_lat_for_forces)
    f_long_total = entry.vehicle.mass_kg * a_long_for_forces
    for w in range(4):
        fy_obs[:, w] = f_lat_total * loads.fz[:, w] / fz_sum
        fx_obs[:, w] = f_long_total * loads.fz[:, w] / fz_sum

    # ── 7. Slip angles via beta estimator ────────────────────
    vy_est, beta_est, beta_std, beta_quality = estimate_beta_offline_smooth(
        speed=speed,
        yaw_rate=yaw_rate,
        a_lat_tire=a_lat_tire,
        cg_to_rear_m=geom.cg_to_rear_m,
        dt=1.0 / 60.0,
        road_quality=road_quality,
    )

    n_samples = result.n_valid
    step = config.subsample_step
    alpha_per_wheel = np.zeros((n_samples, 4))
    for i in range(0, n_samples, step):
        wk = compute_slip_angles(
            vx_body=float(speed[i]),
            vy_body=float(vy_est[i]),
            yaw_rate=float(yaw_rate[i]),
            steer_wheel_rad=float(steer[i]),
            geom=geom,
        )
        end = min(i + step, n_samples)
        if wk.alpha_fl is not None:
            alpha_per_wheel[i:end, 0] = wk.alpha_fl
            alpha_per_wheel[i:end, 1] = wk.alpha_fr
            alpha_per_wheel[i:end, 2] = wk.alpha_rl
            alpha_per_wheel[i:end, 3] = wk.alpha_rr
        else:
            alpha_per_wheel[i:end, 0] = wk.alpha_f_axle
            alpha_per_wheel[i:end, 1] = wk.alpha_f_axle
            alpha_per_wheel[i:end, 2] = wk.alpha_r_axle
            alpha_per_wheel[i:end, 3] = wk.alpha_r_axle

    # ── 8. Inverse solver (initial pass) ─────────────────────
    camber_arr = np.array([
        geom.camber_fl_rad, geom.camber_fr_rad,
        geom.camber_rl_rad, geom.camber_rr_rad,
    ])
    lambda_per_sample, conf_per_sample, exc_per_sample, n_acc, n_rej, reasons = (
        _run_inverse_solver(
            n_samples=n_samples,
            step=step,
            alpha_per_wheel=alpha_per_wheel,
            fz_per_wheel=loads.fz,
            fx_obs=fx_obs,
            fy_obs=fy_obs,
            speed=speed,
            camber_arr=camber_arr,
            tire_params=tire_params,
            excitation_config=config.excitation,
        )
    )
    result.n_accepted_blocks = n_acc
    result.n_rejected_blocks = n_rej
    result.reject_reasons = reasons

    # ── 9. Tire D scale fit (optional adapt) ─────────────────
    if config.allow_tire_d_scale_fit:
        from track_surface.tire_parameter_fit import (
            apply_d_scale,
            curate_calibration_set,
            fit_lateral_d_scale,
        )

        bank_grad = np.abs(np.gradient(bank_est))
        curation = curate_calibration_set(
            bank_rad=bank_est,
            bank_gradient=bank_grad,
            a_lat_tire=a_lat_for_forces,
            speed=speed,
            beta_quality=beta_quality,
            road_quality=road_quality,
            fz_per_wheel=loads.fz,
            alpha_per_wheel=alpha_per_wheel,
            transition_mask=transition_mask,
        )
        if curation.n_selected >= 200:
            fit = fit_lateral_d_scale(
                lambda_raw=lambda_per_sample,
                confidence=conf_per_sample,
                curation_mask=curation.mask,
                lap_numbers=lap.astype(int),
            )
            result.tire_d_fit_result = {
                "k_lat": float(fit.k_lat),
                "k_lat_std": float(fit.k_lat_std),
                "n_train": int(fit.n_train),
                "n_validation": int(fit.n_validation),
                "train_median_before": float(fit.train_median_lambda_before),
                "train_median_after": float(fit.train_median_lambda_after),
                "validation_median_before": float(fit.validation_median_lambda_before),
                "validation_median_after": float(fit.validation_median_lambda_after),
            }
            tire_params = TireParams(
                d1_lat=apply_d_scale(tire_params.d1_lat, fit.k_lat),
                d1_long=tire_params.d1_long,
                d2_lat=tire_params.d2_lat,
                d2_long=tire_params.d2_long,
                b_lat=tire_params.b_lat,
                c_lat=tire_params.c_lat,
                b_long=tire_params.b_long,
                c_long=tire_params.c_long,
            )
            result.tire_d1_lat_used = float(tire_params.d1_lat)
            # Re-run inverse solver with fitted params
            lambda_per_sample, conf_per_sample, exc_per_sample, n_acc, n_rej, reasons = (
                _run_inverse_solver(
                    n_samples=n_samples,
                    step=step,
                    alpha_per_wheel=alpha_per_wheel,
                    fz_per_wheel=loads.fz,
                    fx_obs=fx_obs,
                    fy_obs=fy_obs,
                    speed=speed,
                    camber_arr=camber_arr,
                    tire_params=tire_params,
                    excitation_config=config.excitation,
                )
            )
            result.n_accepted_blocks = n_acc
            result.n_rejected_blocks = n_rej
            result.reject_reasons = reasons
        else:
            result.pipeline_warnings.append(
                f"tire_d_fit_skipped: only {curation.n_selected} curated samples "
                f"(need >= 200)"
            )

    # ── 10. Lambda statistics ────────────────────────────────
    has_lambda = np.isfinite(lambda_per_sample)
    valid_lambda = lambda_per_sample[has_lambda]
    if len(valid_lambda) > 0:
        result.lambda_count = int(len(valid_lambda))
        result.lambda_mean = float(valid_lambda.mean())
        result.lambda_median = float(np.median(valid_lambda))
        result.lambda_std = float(valid_lambda.std())
        result.lambda_p5 = float(np.percentile(valid_lambda, 5))
        result.lambda_p95 = float(np.percentile(valid_lambda, 95))
        result.lambda_min = float(valid_lambda.min())
        result.lambda_max = float(valid_lambda.max())
    else:
        result.pipeline_warnings.append(
            "no_lambda_recovered: inverse solver rejected all samples"
        )
        return
    result.excitation_mean = float(exc_per_sample[exc_per_sample > 0].mean()
                                   if (exc_per_sample > 0).any() else 0.0)

    # ── 11. Lap times + best lap ─────────────────────────────
    lap_times = _compute_lap_times(lap, session_time, lap_dist_pct)
    result.lap_times_s = {int(k): float(v) for k, v in lap_times.items()}
    result.n_laps = len(lap_times)
    if not lap_times:
        result.pipeline_warnings.append("no_complete_laps: lap-time computation found nothing")
        return
    best_lap = min(lap_times.keys(), key=lambda k: lap_times[k])
    result.best_lap = int(best_lap)
    result.best_lap_time_s = float(lap_times[best_lap])

    # ── 12. Frenet from best lap ─────────────────────────────
    x_m, y_m, _, _ = _project_xy_meters(lat_deg, lon_deg)
    best_mask = lap == best_lap
    cl_xy = np.column_stack([x_m[best_mask], y_m[best_mask]])
    cl, total_length = extract_centerline([cl_xy], ds_m=2.0)
    frenet = FrenetFrame.from_centerline(cl)
    result.track_length_m = float(total_length)
    s_proj, n_proj = frenet.xy_to_sn(x_m, y_m)

    # ── 13. Build surface field (single, for legacy stats) ──
    # Use the manifest's authoritative track length when available so the
    # grid is identical across all sessions on the same track. This is
    # required for the accumulator's grid_mismatch guard to accept
    # successive sessions on the same track.
    grid_length = (
        entry.track.track_length_m
        if entry.track.track_length_m is not None
        else total_length
    )
    s_bins = np.arange(0, grid_length + config.field_ds_m, config.field_ds_m)
    n_bins = np.arange(-config.field_n_range_m,
                       config.field_n_range_m + config.field_dn_m,
                       config.field_dn_m)

    field = SurfaceField(s_bins, n_bins, SurfaceFieldConfig(
        condition_label="dry",
        compound_label=f"{entry.vehicle.klass.lower()}_default",
    ))
    conf_adjusted = conf_per_sample.copy()
    conf_adjusted[transition_mask] *= 0.2  # 80% penalty at transitions
    field.update_batch(
        s_proj[has_lambda], n_proj[has_lambda],
        lambda_per_sample[has_lambda], conf_adjusted[has_lambda],
        obs_variance=0.04,
    )
    field.apply_spatial_smoothing()

    fs = field.summary()
    result.field_grid_shape = (int(fs["grid_shape"][0]), int(fs["grid_shape"][1]))
    result.field_cells_observed = int(fs["cells_observed"])
    result.field_cells_total = int(fs["cells_total"])
    result.field_coverage_pct = float(fs["coverage_pct"])
    result.field_mean_observed = float(fs["mean_lambda_observed"])
    result.field_std_observed = float(fs["std_lambda_observed"])
    result.field_mean_confidence = float(fs["mean_confidence"])
    result.field_max_obs_per_cell = int(fs["max_observations_per_cell"])
    conf_map = field.confidence_map
    result.field_high_conf_cells = int((conf_map > 0.5).sum())
    result.field_zero_conf_cells = int((conf_map == 0).sum())

    # ── 14. Racing line structure ────────────────────────────
    s_sample = np.linspace(100, max(101.0, total_length - 100), 50)
    center_lam = [field.query(float(s), 0.0)[0] for s in s_sample]
    left_lam = [field.query(float(s), 4.0)[0] for s in s_sample]
    right_lam = [field.query(float(s), -4.0)[0] for s in s_sample]
    result.racing_line_center_lambda = float(np.mean(center_lam))
    result.racing_line_left_lambda = float(np.mean(left_lam))
    result.racing_line_right_lambda = float(np.mean(right_lam))

    # ── 15. Per-lap stability ────────────────────────────────
    lap_lambdas: dict[int, float] = {}
    for lnum in list(lap_times.keys())[:20]:
        mask_lap = (lap == lnum) & has_lambda
        if mask_lap.sum() > 50:
            lap_lambdas[int(lnum)] = float(np.nanmean(lambda_per_sample[mask_lap]))
    result.lap_lambdas = lap_lambdas

    # ── 16. Bucketed field + planner comparison ─────────────
    # Bucket each sample then build a bucketed field
    bucket_keys = assign_bucket_keys(
        bank_rad=bank_est,
        transition_mask=transition_mask,
        lap_numbers=lap.astype(int),
    )
    bucketed = BucketedSurfaceField(s_bins, n_bins)
    bucketed.update(
        s=s_proj[has_lambda],
        n=n_proj[has_lambda],
        lambda_vals=lambda_per_sample[has_lambda],
        confidence=conf_adjusted[has_lambda],
        bucket_keys=bucket_keys[has_lambda],
        obs_variance=0.04,
    )
    bucketed.apply_spatial_smoothing()

    bd = bucketed.diagnostics()
    result.bucket_diagnostics = bd
    active = sum(1 for k, v in bd.items() if v.get("n_cells", 0) > 0)
    sparse = sum(1 for k, v in bd.items() if 0 < v.get("n_cells", 0) < 20)
    result.bucket_active_count = active
    result.bucket_sparse_count = sparse

    # Build a centerline grid for the planner comparison
    s_grid = np.linspace(0, total_length, max(2, int(total_length / 10.0)))
    # Assign bucket key per grid point — by the modal bucket of nearby samples
    grid_buckets = _assign_grid_buckets(
        s_grid=s_grid,
        s_proj=s_proj,
        bucket_keys=bucket_keys,
    )
    fallback_dist: dict[int, int] = {0: 0, 1: 0, 2: 0}
    for s, key in zip(s_grid, grid_buckets):
        if key == TRANSITION_BUCKET:
            fallback_dist[2] += 1
            continue
        q = bucketed.query(float(s), 0.0, key)
        fallback_dist[q.fallback_depth] = fallback_dist.get(q.fallback_depth, 0) + 1
    result.bucket_fallback_distribution = fallback_dist

    diag = compare_modes(
        bucketed_field=bucketed,
        s_grid=s_grid,
        bucket_keys_per_s=grid_buckets,
        config=config.robust_config,
    )
    result.planner_nominal_mean_mu = float(diag.nominal_mean_mu)
    result.planner_robust_mean_mu = float(diag.robust_mean_mu)
    result.planner_exploitable_mean_mu = float(diag.exploitable_mean_mu)
    result.planner_n_trusted = int(diag.n_trusted_exploitable)
    result.planner_n_degraded = int(diag.n_degraded_exploitable)
    result.planner_n_transition_excluded = int(diag.n_transition_excluded)
    result.planner_max_robust_penalty = float(diag.max_robust_penalty)
    result.planner_sectors_most_tightened = list(diag.sectors_most_tightened)

    # ── 17. Residual diagnostics (FL wheel) ──────────────────
    fy_residuals = []
    fx_residuals = []
    for i in range(0, n_samples, step):
        if not np.isfinite(lambda_per_sample[i]):
            continue
        w = 0
        inp = TireInputs(
            alpha=float(alpha_per_wheel[i, w]),
            kappa=None,
            fz=float(loads.fz[i, w]),
            camber=float(camber_arr[w]),
            vx=float(speed[i]),
        )
        pred = predict_tire_forces(inp, tire_params)
        fy_residuals.append(float(fy_obs[i, w]) - pred.fy)
        fx_residuals.append(float(fx_obs[i, w]) - pred.fx)

    if fy_residuals:
        result.fy_residual_mean = float(np.mean(fy_residuals))
        result.fy_residual_std = float(np.std(fy_residuals))
        result.fx_residual_mean = float(np.mean(fx_residuals))
        result.fx_residual_std = float(np.std(fx_residuals))

    # ── 18. Persistence layer (registry + accumulator) ───────
    # Off unless calibration_registry_path or accumulator_dir is set.
    _maybe_run_persistence(
        config=config,
        entry=entry,
        result=result,
        bucketed=bucketed,
        s_grid=s_grid,
        grid_buckets=grid_buckets,
    )


def _maybe_run_persistence(
    *,
    config: PipelineConfig,
    entry: DatasetEntry,
    result: PipelineResult,
    bucketed: BucketedSurfaceField,
    s_grid: np.ndarray,
    grid_buckets: np.ndarray,
) -> None:
    """Attach persistence + accumulator behavior if configured.

    Resolves the calibration profile, tries to merge the current
    session into the per-(track, profile) accumulator, and computes
    layered fallback diagnostics.

    Failures here are recorded into result.pipeline_warnings — they
    must not crash the pipeline.
    """
    from track_surface.cross_session_accumulator import (
        AccumulatorConfig,
        AccumulatorKey,
        AccumulatorRegistry,
        SessionFingerprint,
        TrackFingerprint,
        layered_query,
    )
    from track_surface.vehicle_calibration_registry import (
        VehicleCalibrationRegistry,
    )

    if not (config.calibration_registry_path or config.accumulator_dir):
        return

    # ── Resolve calibration ──────────────────────────────────
    profile_id = "vehicle_spec_default"
    source = "default"
    if config.calibration_registry_path:
        try:
            registry = VehicleCalibrationRegistry.load(config.calibration_registry_path)
            resolved = registry.resolve(
                vehicle_key=_vehicle_key(entry.vehicle.name),
                vehicle_class=entry.vehicle.klass,
            )
            profile_id = resolved.profile.profile_id
            source = resolved.source
        except Exception as e:  # pragma: no cover
            result.pipeline_warnings.append(
                f"calibration_registry_load_failed: {type(e).__name__}: {e}"
            )
    result.calibration_profile_id = profile_id
    result.calibration_source = source

    if not config.accumulator_dir:
        return

    # ── Build identities ─────────────────────────────────────
    # Prefer the manifest's declared track length (authoritative,
    # session-independent). Fall back to the measured length if the
    # manifest didn't provide one. This ensures two sessions on the
    # same track land in the same accumulator even when their measured
    # centerline lengths differ slightly.
    canonical_length = (
        entry.track.track_length_m
        if entry.track.track_length_m is not None
        else float(result.track_length_m)
    )
    track_fp = TrackFingerprint(
        name=entry.track.name,
        layout=entry.track.layout,
        length_m=canonical_length,
    )
    acc_key = AccumulatorKey(
        track_fingerprint=track_fp,
        calibration_profile_id=profile_id,
    )
    result.accumulator_key = acc_key.key

    session_fp = SessionFingerprint(
        session_id=entry.id,
        track_fingerprint=track_fp,
        calibration_profile_id=profile_id,
        n_valid_samples=int(result.n_valid),
    )

    # ── Get / create accumulator ─────────────────────────────
    acc_registry = AccumulatorRegistry(config.accumulator_dir)
    acc = acc_registry.get_or_create(
        acc_key, bucketed.s_bins, bucketed.n_bins,
        config=AccumulatorConfig(
            min_obs_per_cell=config.accumulator_min_obs_per_cell,
            divergence_sigmas=config.accumulator_divergence_sigmas,
        ),
    )
    result.accumulator_n_sessions_before = len(acc.contributions)

    # ── Merge ────────────────────────────────────────────────
    outcome = acc.add_session(session_fp, bucketed)
    if hasattr(outcome, "rejected_buckets"):  # SessionContribution
        result.merge_outcome = "accepted"
        result.merge_rejected_buckets = list(outcome.rejected_buckets)
    else:  # MergeRejection
        result.merge_outcome = f"rejected:{outcome.reason}"

    result.accumulator_n_sessions_after = len(acc.contributions)

    # ── Layered fallback metrics over the planner grid ───────
    fb_dist: dict[int, int] = {0: 0, 1: 0, 2: 0}
    src_counts: dict[str, int] = {}
    for s, key in zip(s_grid, grid_buckets):
        if key == TRANSITION_BUCKET:
            fb_dist[2] += 1
            src_counts["transition_excluded"] = src_counts.get("transition_excluded", 0) + 1
            continue
        lq = layered_query(
            s=float(s), n=0.0, bucket=key,
            current=bucketed, accumulator=acc,
        )
        fb_dist[lq.fallback_depth] = fb_dist.get(lq.fallback_depth, 0) + 1
        src_counts[lq.evidence_source] = src_counts.get(lq.evidence_source, 0) + 1
    result.accumulated_fallback_distribution = fb_dist
    result.accumulated_evidence_source_counts = src_counts

    # ── Save ─────────────────────────────────────────────────
    if config.accumulator_save_after_merge:
        try:
            acc_registry.save(acc)
        except Exception as e:  # pragma: no cover
            result.pipeline_warnings.append(
                f"accumulator_save_failed: {type(e).__name__}: {e}"
            )


def _vehicle_key(vehicle_name: str) -> str:
    """Stable lookup key from a human vehicle name.

    Lowercases, strips spaces and punctuation. Mirrors how iRacing
    derives its internal vehicle identifiers from display names.
    """
    keep = (c.lower() for c in vehicle_name if c.isalnum())
    return "".join(keep)


# ── Inverse solver loop (extracted for reuse before/after fit) ──


def _run_inverse_solver(
    *,
    n_samples: int,
    step: int,
    alpha_per_wheel: np.ndarray,
    fz_per_wheel: np.ndarray,
    fx_obs: np.ndarray,
    fy_obs: np.ndarray,
    speed: np.ndarray,
    camber_arr: np.ndarray,
    tire_params: TireParams,
    excitation_config: ExcitationConfig,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, int, int, dict[str, int]]:
    """Inner loop of the inverse solver.

    Returns
    -------
    lambda_per_sample : (n_samples,) float, NaN where rejected
    conf_per_sample   : (n_samples,) float
    exc_per_sample    : (n_samples,) float
    n_accepted_blocks : int
    n_rejected_blocks : int
    reject_reasons    : dict[str, int]
    """
    lambda_per_sample = np.full(n_samples, np.nan)
    conf_per_sample = np.zeros(n_samples)
    exc_per_sample = np.zeros(n_samples)
    n_accepted = 0
    n_rejected = 0
    reasons: dict[str, int] = {}

    for i in range(0, n_samples, step):
        wheel_lambdas: list[float] = []
        wheel_confs: list[float] = []
        wheel_excitations: list[float] = []

        for w in range(4):
            inp = TireInputs(
                alpha=float(alpha_per_wheel[i, w]),
                kappa=None,
                fz=float(fz_per_wheel[i, w]),
                camber=float(camber_arr[w]),
                vx=float(speed[i]),
            )
            est = solve_lambda_surface(
                fx_obs=float(fx_obs[i, w]),
                fy_obs=float(fy_obs[i, w]),
                tire_input=inp,
                tire_params=tire_params,
                config=excitation_config,
            )
            if est.lambda_surface is not None:
                wheel_lambdas.append(est.lambda_surface)
                wheel_confs.append(est.confidence)
            wheel_excitations.append(est.excitation)
            if est.flags.get("rejected"):
                for reason in est.flags.get("reject_reasons", []):
                    reasons[reason] = reasons.get(reason, 0) + 1

        end = min(i + step, n_samples)
        if wheel_lambdas:
            w_arr = np.array(wheel_confs)
            l_arr = np.array(wheel_lambdas)
            lam = float(np.sum(l_arr * w_arr) / np.sum(w_arr))
            conf = float(np.mean(w_arr))
            lambda_per_sample[i:end] = lam
            conf_per_sample[i:end] = conf
            n_accepted += 1
        else:
            n_rejected += 1
        if wheel_excitations:
            exc_per_sample[i:end] = np.mean(wheel_excitations)

    return lambda_per_sample, conf_per_sample, exc_per_sample, n_accepted, n_rejected, reasons


# ── Grid bucket assignment ───────────────────────────────────


def _assign_grid_buckets(
    *,
    s_grid: np.ndarray,
    s_proj: np.ndarray,
    bucket_keys: np.ndarray,
    window_m: float = 25.0,
) -> np.ndarray:
    """For each grid s, pick the modal bucket of nearby samples.

    If no samples are within window, default to flat/mid (a neutral
    active bucket that lets the planner query fallback gracefully).
    """
    out = np.empty(len(s_grid), dtype=object)
    for i, s in enumerate(s_grid):
        nearby = np.abs(s_proj - s) < window_m
        if nearby.sum() == 0:
            out[i] = BucketKey("flat", "mid")
            continue
        keys_here = bucket_keys[nearby]
        # Manual mode (avoid scipy dependency for one operation)
        counts: dict[BucketKey, int] = {}
        for k in keys_here:
            counts[k] = counts.get(k, 0) + 1
        out[i] = max(counts.items(), key=lambda kv: kv[1])[0]
    return out
