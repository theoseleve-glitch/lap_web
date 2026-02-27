"""
sensitivity.py
--------------
Corner-level sensitivity optimizer for "brake earlier/later",
"turn-in earlier/later", apex timing and line-shape what-if analysis.

The optimizer:
1. Detects baseline brake and turn-in markers per corner.
2. Sweeps a deterministic multi-axis grid around those markers.
3. Runs a constrained forward rollout for each candidate.
4. Accepts a candidate only if time gain exceeds threshold.
5. Stitches accepted corner updates into an ideal lap profile and applies
   a global forward/backward consistency pass.
"""
from __future__ import annotations

import csv
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from kart_envelope.config import KartEnvelopeConfig
from kart_envelope.envelope.capability import CapabilityEnvelope, train_capability_envelope
from kart_envelope.ingest.columns import (
    COL_ACCEL_LAT,
    COL_ACCEL_LONG,
    COL_DIST,
    COL_SPEED,
)
from kart_envelope.ingest.acd_parser import load_acd_engine_data, resolve_acd_path
from kart_envelope.ingest.metadata import SessionMetadata
from kart_envelope.inference.session_scalars import SessionScalars
from kart_envelope.track.geometry import TrackGeometry
from telemetry_tool.lap_simulation import VehicleModel, fit_vehicle_model

logger = logging.getLogger(__name__)

try:
    from numba import njit  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - optional
    njit = None  # type: ignore[assignment]


@dataclass
class CornerRecommendation:
    """Top-level recommendation for one corner."""

    corner_id: int
    gain_s: float
    brake_shift_s: float
    turn_shift_m: float
    baseline_corner_time_s: float
    optimized_corner_time_s: float
    brake_point_m: float
    turn_in_point_m: float
    apex_shift_input_m: float = 0.0
    line_curvature_scale: float = 1.0
    apex_point_m: float = float("nan")
    apex_shift_m: float = float("nan")
    apex_speed_mps: float = float("nan")
    lat_force_scale: float = 1.0
    brake_force_scale: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "corner_id": self.corner_id,
            "gain_s": round(self.gain_s, 4),
            "brake_shift_s": round(self.brake_shift_s, 4),
            "turn_shift_m": round(self.turn_shift_m, 3),
            "apex_shift_input_m": round(self.apex_shift_input_m, 3),
            "line_curvature_scale": round(self.line_curvature_scale, 4),
            "baseline_corner_time_s": round(self.baseline_corner_time_s, 4),
            "optimized_corner_time_s": round(self.optimized_corner_time_s, 4),
            "brake_point_m": round(self.brake_point_m, 3),
            "turn_in_point_m": round(self.turn_in_point_m, 3),
            "apex_point_m": round(self.apex_point_m, 3),
            "apex_shift_m": round(self.apex_shift_m, 3),
            "apex_speed_mps": round(self.apex_speed_mps, 3),
            "lat_force_scale": round(self.lat_force_scale, 4),
            "brake_force_scale": round(self.brake_force_scale, 4),
        }


@dataclass
class _CornerRollout:
    distance_m: np.ndarray
    speed_mps: np.ndarray
    corner_time_s: float
    feasible: bool
    reason: str = ""
    exit_speed_mps: float = 0.0
    brake_point_m: float = 0.0
    turn_in_point_m: float = 0.0
    apex_shift_input_m: float = 0.0
    apex_point_m: float = float("nan")
    apex_speed_mps: float = float("nan")
    line_curvature_scale: float = 1.0
    lat_force_scale: float = 1.0
    brake_force_scale: float = 1.0


@dataclass
class _CornerMLDataset:
    feature_matrix: np.ndarray  # cols: [entry_speed, brake_offset, turn_offset]
    target_time_s: np.ndarray
    feature_scale: np.ndarray


@dataclass(frozen=True)
class SensitivityRuntimeContext:
    """Reusable runtime context for repeated corner-sensitivity calls in one session."""

    env_session: CapabilityEnvelope
    envelope_source: str
    vehicle_model: VehicleModel | None
    ml_datasets: dict[int, _CornerMLDataset]
    ml_training_rows: int


@dataclass
class SensitivitySessionResult:
    """Session-level result from sensitivity optimization."""

    baseline_lap_time_s: float
    ideal_lap_time_s: float
    total_gain_s: float
    accepted_count: int
    evaluated_count: int
    recommendations: list[CornerRecommendation] = field(default_factory=list)
    candidate_rows: list[dict[str, Any]] = field(default_factory=list)
    sector_rows: list[dict[str, Any]] = field(default_factory=list)
    distance_m: np.ndarray = field(default_factory=lambda: np.array([], dtype=float))
    baseline_speed_mps: np.ndarray = field(default_factory=lambda: np.array([], dtype=float))
    ideal_speed_mps: np.ndarray = field(default_factory=lambda: np.array([], dtype=float))
    ml_enabled: bool = False
    ml_training_rows: int = 0
    ml_used_corners: int = 0
    target_lap_time_s: float | None = None
    target_gap_s: float | None = None
    target_status: str = "not_set"
    target_force_scale: float = 1.0
    envelope_source: str = "library"
    gain_shrink_factor: float = 1.0
    uncertainty_lap_time_low_s: float | None = None
    uncertainty_lap_time_high_s: float | None = None
    reliability: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline_lap_time_s": round(self.baseline_lap_time_s, 4),
            "ideal_lap_time_s": round(self.ideal_lap_time_s, 4),
            "total_gain_s": round(self.total_gain_s, 4),
            "accepted_count": int(self.accepted_count),
            "evaluated_count": int(self.evaluated_count),
            "recommendations": [r.to_dict() for r in self.recommendations],
            "sector_rows": self.sector_rows,
            "ml_enabled": bool(self.ml_enabled),
            "ml_training_rows": int(self.ml_training_rows),
            "ml_used_corners": int(self.ml_used_corners),
            "target_lap_time_s": (
                round(float(self.target_lap_time_s), 4)
                if self.target_lap_time_s is not None
                else None
            ),
            "target_gap_s": (
                round(float(self.target_gap_s), 4)
                if self.target_gap_s is not None
                else None
            ),
            "target_status": self.target_status,
            "target_force_scale": round(float(self.target_force_scale), 4),
            "envelope_source": self.envelope_source,
            "gain_shrink_factor": round(float(self.gain_shrink_factor), 4),
            "uncertainty_lap_time_low_s": (
                round(float(self.uncertainty_lap_time_low_s), 4)
                if self.uncertainty_lap_time_low_s is not None
                else None
            ),
            "uncertainty_lap_time_high_s": (
                round(float(self.uncertainty_lap_time_high_s), 4)
                if self.uncertainty_lap_time_high_s is not None
                else None
            ),
            "reliability": self.reliability,
        }


def optimize_corner_sensitivity(
    best_lap_df: pd.DataFrame,
    resampled_laps: dict[int, pd.DataFrame],
    geometry: TrackGeometry,
    envelope: CapabilityEnvelope,
    scalars: SessionScalars,
    metadata: SessionMetadata,
    corners: list[dict[str, Any]],
    config: KartEnvelopeConfig,
    runtime_context: SensitivityRuntimeContext | None = None,
) -> SensitivitySessionResult:
    """Run corner sensitivity sweep and build an ideal lap profile."""
    _require_columns(best_lap_df, [COL_DIST, COL_SPEED])

    distance = geometry.distance_m.astype(float)
    kappa = geometry.curvature_1pm.astype(float)
    if len(distance) < 3:
        raise ValueError("Track geometry must have at least 3 points.")

    dr_dist = pd.to_numeric(best_lap_df[COL_DIST], errors="coerce").values
    dr_speed = pd.to_numeric(best_lap_df[COL_SPEED], errors="coerce").values
    mask = np.isfinite(dr_dist) & np.isfinite(dr_speed)
    dr_dist = dr_dist[mask]
    dr_speed = dr_speed[mask]
    if len(dr_dist) < 3:
        raise ValueError("Best lap data has insufficient valid speed samples.")

    order = np.argsort(dr_dist)
    dr_dist = dr_dist[order]
    dr_speed = np.maximum(dr_speed[order], config.solver_min_speed_mps)
    dr_dist, keep = np.unique(dr_dist, return_index=True)
    dr_speed = dr_speed[keep]

    baseline_speed = np.interp(
        distance,
        dr_dist,
        dr_speed,
        left=float(dr_speed[0]),
        right=float(dr_speed[-1]),
    )
    baseline_speed = np.clip(
        baseline_speed,
        config.solver_min_speed_mps,
        config.solver_max_speed_mps,
    )

    if runtime_context is None:
        runtime_context = prepare_sensitivity_runtime(
            resampled_laps=resampled_laps,
            geometry=geometry,
            envelope=envelope,
            scalars=scalars,
            metadata=metadata,
            corners=corners,
            config=config,
        )
    env_session = runtime_context.env_session
    envelope_source = runtime_context.envelope_source
    vehicle_model = runtime_context.vehicle_model
    ml_datasets = runtime_context.ml_datasets if config.sensitivity_ml_enable else {}
    ml_training_rows = runtime_context.ml_training_rows if config.sensitivity_ml_enable else 0
    ml_used_corners = 0

    shift_candidates = _build_shift_candidates(config)
    cond_lbl = str(metadata.condition_label or scalars.condition_label or "").strip().lower()
    cond_force_penalty = _condition_force_penalty(cond_lbl, config)
    lat_gain = max(float(config.sensitivity_lat_force_gain) * cond_force_penalty, 0.0)
    brake_gain = max(float(config.sensitivity_brake_force_gain) * cond_force_penalty, 0.0)
    lat_force_scales = _build_force_scale_grid(
        gain=lat_gain,
        n_points=config.sensitivity_force_grid_size,
        underdrive_only=config.sensitivity_underdrive_only,
    )
    brake_force_scales = _build_force_scale_grid(
        gain=brake_gain,
        n_points=config.sensitivity_force_grid_size,
        underdrive_only=config.sensitivity_underdrive_only,
    )

    ideal_speed = baseline_speed.copy()
    lap_start = float(distance[0])
    lap_end = float(distance[-1])
    current_lap_time = _integrate_range(distance, ideal_speed, lap_start, lap_end)
    candidates: list[dict[str, Any]] = []
    recommendations: list[CornerRecommendation] = []
    evaluated = 0
    accepted = 0

    for corner in corners:
        s_start = float(corner.get("s_start", 0.0))
        s_end = float(corner.get("s_end", 0.0))
        s_apex = float(corner.get("s_apex", 0.5 * (s_start + s_end)))
        corner_id = int(corner.get("corner_id", 0))
        if s_end <= s_start:
            continue

        zone_start = max(float(distance[0]), s_start - config.sensitivity_entry_margin_m)
        zone_end = min(float(distance[-1]), s_end + config.sensitivity_exit_margin_m)
        if zone_end <= zone_start:
            continue

        current_corner_time = _integrate_range(distance, ideal_speed, s_start, s_end)
        start_speed = _interp(distance, ideal_speed, zone_start)

        baseline_brake = _estimate_brake_point(best_lap_df, s_start, zone_start)
        baseline_turn = _estimate_turn_in_point(best_lap_df, distance, kappa, s_start, s_apex)
        ml_dataset = ml_datasets.get(corner_id)
        baseline_features = _corner_ml_features(
            entry_speed=start_speed,
            corner_start=s_start,
            brake_point=baseline_brake,
            turn_in_point=baseline_turn,
        )
        baseline_ml_time = (
            _predict_corner_time_knn(ml_dataset, baseline_features, config)
            if ml_dataset is not None
            else None
        )
        best_rollout: _CornerRollout | None = None
        best_brake_shift = 0.0
        best_turn_shift = 0.0
        best_apex_shift_input = 0.0
        best_line_curvature_scale = 1.0
        best_lat_force_scale = 1.0
        best_brake_force_scale = 1.0
        best_eval_corner_time = float("inf")
        best_candidate_ml_applied = False

        for b_shift, t_shift, apex_shift_input, line_curvature_scale in shift_candidates:
            for lat_force_scale in lat_force_scales:
                for brake_force_scale in brake_force_scales:
                    rollout = _rollout_corner(
                        distance=distance,
                        kappa=kappa,
                        speed_reference=ideal_speed,
                        zone_start=zone_start,
                        zone_end=zone_end,
                        corner_start=s_start,
                        corner_apex=s_apex,
                        corner_end=s_end,
                        start_speed=start_speed,
                        baseline_brake_point=baseline_brake,
                        baseline_turn_in=baseline_turn,
                        brake_shift_s=float(b_shift),
                        turn_shift_m=float(t_shift),
                        apex_shift_m_input=float(apex_shift_input),
                        line_curvature_scale=float(line_curvature_scale),
                        lat_force_scale=float(lat_force_scale),
                        brake_force_scale=float(brake_force_scale),
                        env=env_session,
                        vehicle_model=vehicle_model,
                        config=config,
                    )
                    evaluated += 1
                    eval_corner_time = rollout.corner_time_s
                    ml_corner_time: float | None = None
                    candidate_ml_applied = False
                    if rollout.feasible and ml_dataset is not None and baseline_ml_time is not None:
                        cand_features = _corner_ml_features(
                            entry_speed=start_speed,
                            corner_start=s_start,
                            brake_point=rollout.brake_point_m,
                            turn_in_point=rollout.turn_in_point_m,
                        )
                        ml_corner_time = _predict_corner_time_knn(ml_dataset, cand_features, config)
                        if ml_corner_time is not None:
                            eval_corner_time = _blend_corner_time(
                                baseline_corner_time_s=current_corner_time,
                                physics_corner_time_s=rollout.corner_time_s,
                                ml_baseline_corner_time_s=baseline_ml_time,
                                ml_corner_time_s=ml_corner_time,
                                reference_penalty_s=_reference_penalty_s(
                                    brake_shift_s=float(b_shift),
                                    turn_shift_m=float(t_shift),
                                    apex_shift_m_input=float(apex_shift_input),
                                    line_curvature_scale=float(line_curvature_scale),
                                    config=config,
                                ),
                                config=config,
                            )
                            candidate_ml_applied = True

                    gain = current_corner_time - eval_corner_time if rollout.feasible else 0.0
                    apex_shift_m = (
                        float(rollout.apex_point_m - s_apex)
                        if np.isfinite(float(rollout.apex_point_m))
                        else float("nan")
                    )
                    candidates.append({
                        "corner_id": corner_id,
                        "brake_shift_s": float(b_shift),
                        "turn_shift_m": float(t_shift),
                        "apex_shift_input_m": float(apex_shift_input),
                        "line_curvature_scale": float(line_curvature_scale),
                        "lat_force_scale": float(lat_force_scale),
                        "brake_force_scale": float(brake_force_scale),
                        "feasible": bool(rollout.feasible),
                        "reason": rollout.reason,
                        "corner_time_s": round(float(rollout.corner_time_s), 6),
                        "eval_corner_time_s": round(float(eval_corner_time), 6),
                        "ml_corner_time_s": (
                            round(float(ml_corner_time), 6)
                            if ml_corner_time is not None
                            else None
                        ),
                        "gain_s": round(float(gain), 6),
                        "exit_speed_mps": round(float(rollout.exit_speed_mps), 6),
                        "brake_point_m": round(float(rollout.brake_point_m), 6),
                        "turn_in_point_m": round(float(rollout.turn_in_point_m), 6),
                        "apex_point_m": (
                            round(float(rollout.apex_point_m), 6)
                            if np.isfinite(float(rollout.apex_point_m))
                            else None
                        ),
                        "apex_shift_m": (
                            round(float(apex_shift_m), 6)
                            if np.isfinite(float(apex_shift_m))
                            else None
                        ),
                        "apex_speed_mps": (
                            round(float(rollout.apex_speed_mps), 6)
                            if np.isfinite(float(rollout.apex_speed_mps))
                            else None
                        ),
                    })

                    if not rollout.feasible:
                        continue
                    if best_rollout is None or eval_corner_time < best_eval_corner_time:
                        best_rollout = rollout
                        best_brake_shift = float(b_shift)
                        best_turn_shift = float(t_shift)
                        best_apex_shift_input = float(apex_shift_input)
                        best_line_curvature_scale = float(line_curvature_scale)
                        best_lat_force_scale = float(lat_force_scale)
                        best_brake_force_scale = float(brake_force_scale)
                        best_eval_corner_time = float(eval_corner_time)
                        best_candidate_ml_applied = candidate_ml_applied

        if best_rollout is None:
            continue

        gain_s = current_corner_time - best_eval_corner_time
        if gain_s <= config.sensitivity_accept_gain_s:
            continue

        zone_mask = (distance >= zone_start) & (distance <= zone_end)
        if np.any(zone_mask):
            trial_speed = ideal_speed.copy()
            trial_speed[zone_mask] = np.interp(
                distance[zone_mask],
                best_rollout.distance_m,
                best_rollout.speed_mps,
            )
            trial_speed = _blend_patched_zone_edges(
                distance=distance,
                base_speed=ideal_speed,
                patched_speed=trial_speed,
                zone_start=zone_start,
                zone_end=zone_end,
                blend_m=max(0.0, float(config.sensitivity_patch_blend_m)),
            )
            if config.sensitivity_apply_global_consistency_after_corner:
                trial_speed = _global_consistency_pass(
                    distance=distance,
                    kappa=kappa,
                    speed_seed=trial_speed,
                    env=env_session,
                    vehicle_model=vehicle_model,
                    lat_force_scale=best_lat_force_scale,
                    brake_force_scale=best_brake_force_scale,
                    config=config,
                )
            trial_lap_time = _integrate_range(distance, trial_speed, lap_start, lap_end)
            lap_gain_s = current_lap_time - trial_lap_time
            if lap_gain_s <= 1e-5:
                continue

            ideal_speed = trial_speed
            current_lap_time = trial_lap_time
            accepted += 1
            if best_candidate_ml_applied:
                ml_used_corners += 1
            recommendations.append(CornerRecommendation(
                corner_id=corner_id,
                gain_s=lap_gain_s,
                brake_shift_s=best_brake_shift,
                turn_shift_m=best_turn_shift,
                apex_shift_input_m=best_apex_shift_input,
                line_curvature_scale=best_line_curvature_scale,
                baseline_corner_time_s=current_corner_time,
                optimized_corner_time_s=best_eval_corner_time,
                brake_point_m=best_rollout.brake_point_m,
                turn_in_point_m=best_rollout.turn_in_point_m,
                apex_point_m=best_rollout.apex_point_m,
                apex_shift_m=float(best_rollout.apex_point_m - s_apex),
                apex_speed_mps=best_rollout.apex_speed_mps,
                lat_force_scale=best_lat_force_scale,
                brake_force_scale=best_brake_force_scale,
            ))

    baseline_lap_time = _integrate_range(distance, baseline_speed, lap_start, lap_end)
    ideal_lap_time = current_lap_time
    total_gain = baseline_lap_time - ideal_lap_time
    target_scale = 1.0

    calibrated_speed, calibrated_time, target_scale = _apply_target_calibration(
        distance=distance,
        kappa=kappa,
        baseline_speed=baseline_speed,
        speed_seed=ideal_speed,
        current_time_s=ideal_lap_time,
        env=env_session,
        vehicle_model=vehicle_model,
        config=config,
    )
    if calibrated_time < ideal_lap_time - 1e-6:
        ideal_speed = calibrated_speed
        ideal_lap_time = calibrated_time
        total_gain = baseline_lap_time - ideal_lap_time

    if ideal_lap_time > baseline_lap_time:
        logger.info(
            "Sensitivity pass produced slower stitched lap (%.4fs > %.4fs); "
            "reverting to baseline profile.",
            ideal_lap_time,
            baseline_lap_time,
        )
        ideal_speed = baseline_speed.copy()
        ideal_lap_time = baseline_lap_time
        total_gain = 0.0
        accepted = 0
        recommendations = []
        ml_used_corners = 0

    gain_shrink = _resolve_gain_shrink_factor(metadata, config)
    if gain_shrink < 0.999 and total_gain > 0:
        ideal_speed, ideal_lap_time, recommendations = _apply_gain_shrinkage(
            distance=distance,
            baseline_speed=baseline_speed,
            ideal_speed=ideal_speed,
            recommendations=recommendations,
            gain_shrink=float(gain_shrink),
        )
        total_gain = max(0.0, baseline_lap_time - ideal_lap_time)

    target_lap_time = config.sensitivity_target_lap_time_s

    # Global profile smoothing for all simulation outputs.
    if config.optimal_profile_smoothing_enable and total_gain > 0:
        desired_time = float(ideal_lap_time)
        smoothed = _smooth_profile_by_distance(
            distance=distance,
            speed=ideal_speed,
            window_m=max(0.25, float(config.optimal_profile_smoothing_window_m)),
            passes=max(1, int(config.optimal_profile_smoothing_passes)),
        )
        smoothed = np.maximum(smoothed, baseline_speed)
        smoothed_time = _integrate_range(distance, smoothed, lap_start, lap_end)
        if config.optimal_profile_smoothing_preserve_lap_time:
            smoothed, smoothed_time, _ = _rescale_profile_to_target_lap(
                distance=distance,
                baseline_speed=baseline_speed,
                reference_speed=smoothed,
                target_lap_time_s=desired_time,
                max_gain_scale=2.5,
            )
        if smoothed_time < baseline_lap_time - 1e-6:
            ideal_speed = smoothed
            ideal_lap_time = smoothed_time
            total_gain = max(0.0, baseline_lap_time - ideal_lap_time)

    # Bidirectional target alignment: if optimistic, scale gains down;
    # if conservative, scale gains up (bounded) to approach target lap.
    if (
        config.sensitivity_target_align_enable
        and target_lap_time is not None
        and float(target_lap_time) > 0
        and total_gain > 0
    ):
        aligned_speed, aligned_time, align_scale = _rescale_profile_to_target_lap(
            distance=distance,
            baseline_speed=baseline_speed,
            reference_speed=ideal_speed,
            target_lap_time_s=float(target_lap_time),
            max_gain_scale=max(1.0, float(config.sensitivity_target_align_max_gain_scale)),
        )
        if abs(aligned_time - ideal_lap_time) > 1e-4:
            ideal_speed = aligned_speed
            ideal_lap_time = aligned_time
            total_gain = max(0.0, baseline_lap_time - ideal_lap_time)
            target_scale = float(align_scale)
            if recommendations:
                scaled_recs: list[CornerRecommendation] = []
                for rec in recommendations:
                    gain = float(rec.gain_s) * float(align_scale)
                    gain = max(0.0, min(gain, max(0.0, float(rec.baseline_corner_time_s) - 0.01)))
                    scaled_recs.append(CornerRecommendation(
                        corner_id=rec.corner_id,
                        gain_s=gain,
                        brake_shift_s=rec.brake_shift_s,
                        turn_shift_m=rec.turn_shift_m,
                        apex_shift_input_m=rec.apex_shift_input_m,
                        line_curvature_scale=rec.line_curvature_scale,
                        baseline_corner_time_s=rec.baseline_corner_time_s,
                        optimized_corner_time_s=max(0.01, rec.baseline_corner_time_s - gain),
                        brake_point_m=rec.brake_point_m,
                        turn_in_point_m=rec.turn_in_point_m,
                        apex_point_m=rec.apex_point_m,
                        apex_shift_m=rec.apex_shift_m,
                        apex_speed_mps=rec.apex_speed_mps,
                        lat_force_scale=rec.lat_force_scale,
                        brake_force_scale=rec.brake_force_scale,
                    ))
                recommendations = scaled_recs

    # Final smoothing pass after target alignment to keep the published
    # optimal profile visually stable while preserving the solved lap time.
    if config.optimal_profile_smoothing_enable and total_gain > 0:
        final_sm = _smooth_profile_by_distance(
            distance=distance,
            speed=ideal_speed,
            window_m=max(0.25, float(config.optimal_profile_smoothing_window_m)),
            passes=max(1, int(config.optimal_profile_smoothing_passes)),
        )
        final_sm = np.maximum(final_sm, baseline_speed)
        if config.optimal_profile_smoothing_preserve_lap_time:
            final_sm, final_time, _ = _rescale_profile_to_target_lap(
                distance=distance,
                baseline_speed=baseline_speed,
                reference_speed=final_sm,
                target_lap_time_s=float(ideal_lap_time),
                max_gain_scale=2.5,
            )
        else:
            final_time = _integrate_range(distance, final_sm, lap_start, lap_end)
        if final_time < baseline_lap_time - 1e-6:
            ideal_speed = final_sm
            ideal_lap_time = final_time
            total_gain = max(0.0, baseline_lap_time - ideal_lap_time)

    target_gap = None
    target_status = "not_set"
    if target_lap_time is not None and target_lap_time > 0:
        target_gap = ideal_lap_time - float(target_lap_time)
        tol = max(float(config.sensitivity_target_tolerance_s), 0.0)
        if target_gap < -tol:
            target_status = "too_optimistic"
        elif target_gap > tol:
            target_status = "too_conservative"
        else:
            target_status = "on_target"

    recommendations.sort(key=lambda r: r.gain_s, reverse=True)
    recommendations = recommendations[: config.sensitivity_top_recommendations]
    unc_low, unc_high = _estimate_lap_time_uncertainty(
        baseline_lap_time_s=baseline_lap_time,
        ideal_lap_time_s=ideal_lap_time,
        candidate_rows=candidates,
        recommendations=recommendations,
        gain_shrink=float(gain_shrink),
        config=config,
    )
    reliability = _compute_reliability_metrics(
        evaluated_count=evaluated,
        accepted_count=accepted,
        candidate_rows=candidates,
        recommendations=recommendations,
        total_gain_s=total_gain,
        baseline_lap_time_s=baseline_lap_time,
        gain_shrink=float(gain_shrink),
        scalars_confidence=float(scalars.confidence),
        ml_enabled=bool(config.sensitivity_ml_enable),
        ml_training_rows=ml_training_rows,
        ml_used_corners=ml_used_corners,
    )
    sector_rows = _compute_sector_rows(
        distance=distance,
        baseline_speed=baseline_speed,
        ideal_speed=ideal_speed,
        n_sectors=config.sensitivity_n_sectors,
    )

    return SensitivitySessionResult(
        baseline_lap_time_s=baseline_lap_time,
        ideal_lap_time_s=ideal_lap_time,
        total_gain_s=total_gain,
        accepted_count=accepted,
        evaluated_count=evaluated,
        recommendations=recommendations,
        candidate_rows=candidates,
        sector_rows=sector_rows,
        distance_m=distance,
        baseline_speed_mps=baseline_speed,
        ideal_speed_mps=ideal_speed,
        ml_enabled=bool(config.sensitivity_ml_enable),
        ml_training_rows=ml_training_rows,
        ml_used_corners=ml_used_corners,
        target_lap_time_s=target_lap_time,
        target_gap_s=target_gap,
        target_status=target_status,
        target_force_scale=target_scale,
        envelope_source=envelope_source,
        gain_shrink_factor=float(gain_shrink),
        uncertainty_lap_time_low_s=unc_low,
        uncertainty_lap_time_high_s=unc_high,
        reliability=reliability,
    )


def prepare_sensitivity_runtime(
    resampled_laps: dict[int, pd.DataFrame],
    geometry: TrackGeometry,
    envelope: CapabilityEnvelope,
    scalars: SessionScalars,
    metadata: SessionMetadata,
    corners: list[dict[str, Any]],
    config: KartEnvelopeConfig,
) -> SensitivityRuntimeContext:
    """Build reusable runtime objects shared by multiple lap optimizations."""
    env_session, envelope_source = _session_envelope(
        envelope=envelope,
        scalars=scalars,
        metadata=metadata,
        resampled_laps=resampled_laps,
        config=config,
    )
    vehicle_model = _build_vehicle_model(resampled_laps, env_session, metadata, config)
    ml_datasets = (
        _build_corner_ml_datasets(
            resampled_laps,
            corners,
            geometry.distance_m.astype(float),
            geometry.curvature_1pm.astype(float),
            config,
        )
        if config.sensitivity_ml_enable
        else {}
    )
    ml_training_rows = int(sum(len(ds.target_time_s) for ds in ml_datasets.values()))
    if config.sensitivity_ml_enable:
        logger.info(
            "Corner ML layer: %d corner model(s), %d training row(s).",
            len(ml_datasets),
            ml_training_rows,
        )
    return SensitivityRuntimeContext(
        env_session=env_session,
        envelope_source=envelope_source,
        vehicle_model=vehicle_model,
        ml_datasets=ml_datasets,
        ml_training_rows=ml_training_rows,
    )


def _session_envelope(
    envelope: CapabilityEnvelope,
    scalars: SessionScalars,
    metadata: SessionMetadata,
    resampled_laps: dict[int, pd.DataFrame],
    config: KartEnvelopeConfig,
) -> tuple[CapabilityEnvelope, str]:
    tire_scale = _tire_condition_scale(metadata, scalars)
    lat_prior, drive_prior, brake_prior = _hybrid_force_priors(metadata, config)
    base = envelope.scaled(
        mu=scalars.mu_session * tire_scale,
        p_drive=scalars.p_session * tire_scale,
        b_brake=scalars.b_session * tire_scale,
    )
    base = base.scaled(
        mu=lat_prior,
        p_drive=drive_prior,
        b_brake=brake_prior,
    )
    if not config.sensitivity_use_session_envelope:
        return base, "library_scaled"

    if not resampled_laps:
        return base, "library_scaled"

    try:
        # Fit from the whole cleaned session (all laps), not only the best lap.
        session_env = train_capability_envelope(
            sessions=[resampled_laps],
            config=config,
            track_id=envelope.track_id or metadata.track_name or "",
            kart_id=envelope.kart_id or metadata.kart_id,
        )
    except Exception as exc:
        logger.warning("Session-envelope fit failed; using library envelope only: %s", exc)
        return base, "library_scaled"

    blend = float(np.clip(config.sensitivity_session_envelope_blend, 0.0, 1.0))
    if blend <= 0.0:
        return base, "library_scaled"

    return _blend_envelopes(base, session_env, blend=blend), "library+session_blend"


def _blend_envelopes(
    base: CapabilityEnvelope,
    session_env: CapabilityEnvelope,
    *,
    blend: float,
) -> CapabilityEnvelope:
    """Blend two envelopes on the base speed grid."""
    w = float(np.clip(blend, 0.0, 1.0))
    if w <= 0.0:
        return base
    if w >= 1.0:
        return session_env

    v = np.asarray(base.v_grid, dtype=float)
    ay_s = np.interp(v, session_env.v_grid, session_env.ay_max)
    axd_s = np.interp(v, session_env.v_grid, session_env.ax_drive_max)
    axb_s = np.interp(v, session_env.v_grid, session_env.ax_brake_max)
    p = (1.0 - w) * float(base.p_combined) + w * float(session_env.p_combined)

    return CapabilityEnvelope(
        v_grid=v.copy(),
        ay_max=np.maximum((1.0 - w) * base.ay_max + w * ay_s, 0.1),
        ax_drive_max=np.maximum((1.0 - w) * base.ax_drive_max + w * axd_s, 0.1),
        ax_brake_max=np.maximum((1.0 - w) * base.ax_brake_max + w * axb_s, 0.1),
        p_combined=float(np.clip(p, 1.1, 3.0)),
        track_id=base.track_id or session_env.track_id,
        kart_id=base.kart_id or session_env.kart_id,
        n_sessions=max(base.n_sessions, session_env.n_sessions),
        n_laps=max(base.n_laps, session_env.n_laps),
    )


def _hybrid_force_priors(
    metadata: SessionMetadata,
    config: KartEnvelopeConfig,
) -> tuple[float, float, float]:
    """
    Return mild priors for (lateral, drive, brake) from engine + mass metadata.

    These are intentionally conservative multipliers and are applied on top
    of telemetry-derived session scalars.
    """
    total_mass = _total_mass_kg(metadata, config)
    mass_ratio = float(np.clip(175.0 / max(total_mass, 1.0), 0.75, 1.25))
    mass_lat = mass_ratio ** 0.06
    mass_drive = mass_ratio ** 0.05
    mass_brake = mass_ratio ** 0.08

    engine_type = str(getattr(metadata, "engine_type", "") or "").strip().lower()
    kart_class = str(metadata.kart_class or "").strip().lower()

    drive_low = 1.00
    drive_high = 1.00
    brake = 1.00
    if any(tok in engine_type for tok in ("electric", "ev")):
        drive_low, drive_high, brake = 1.10, 1.02, 1.06
    elif any(tok in engine_type for tok in ("2t", "2-stroke", "kz", "x30", "rotax")) or kart_class == "2t":
        drive_low, drive_high, brake = 0.95, 1.08, 1.04
    elif any(tok in engine_type for tok in ("4t", "4-stroke", "rental", "l206", "gx")) or kart_class == "4t":
        drive_low, drive_high, brake = 1.04, 0.97, 1.00

    size_cc = getattr(metadata, "engine_size_cc", None)
    disp = 1.0
    if size_cc is not None:
        ref_cc = 125.0 if kart_class == "2t" else 200.0
        ratio = float(np.clip(float(size_cc) / ref_cc, 0.6, 1.8))
        disp = ratio ** 0.10

    # For envelope-level priors we use the mid-point drive factor.
    drive_mid = 0.5 * (drive_low + drive_high)
    lat_prior = float(np.clip(mass_lat, 0.90, 1.10))
    drive_prior = float(np.clip(drive_mid * disp * mass_drive, 0.85, 1.15))
    brake_prior = float(np.clip(brake * (disp ** 0.04) * mass_brake, 0.88, 1.15))
    return lat_prior, drive_prior, brake_prior


def _build_vehicle_model(
    resampled_laps: dict[int, pd.DataFrame],
    env: CapabilityEnvelope,
    metadata: SessionMetadata,
    config: KartEnvelopeConfig,
) -> VehicleModel | None:
    try:
        model = fit_vehicle_model(resampled_laps, env)
    except Exception as exc:
        logger.warning("Vehicle model fit failed; sensitivity rollout uses envelope only: %s", exc)
        return None

    # Hybrid priors from engine architecture + displacement + mass.
    total_mass = _total_mass_kg(metadata, config)
    engine_type = str(getattr(metadata, "engine_type", "") or "").strip().lower()
    kart_class = str(metadata.kart_class or "").strip().lower()
    size_cc = getattr(metadata, "engine_size_cc", None)

    drive_low = 1.00
    drive_high = 1.00
    brake_gain = 1.00
    if any(tok in engine_type for tok in ("electric", "ev")):
        drive_low, drive_high, brake_gain = 1.12, 1.03, 1.08
    elif any(tok in engine_type for tok in ("2t", "2-stroke", "kz", "x30", "rotax")) or kart_class == "2t":
        drive_low, drive_high, brake_gain = 0.95, 1.10, 1.05
    elif any(tok in engine_type for tok in ("4t", "4-stroke", "rental", "l206", "gx")) or kart_class == "4t":
        drive_low, drive_high, brake_gain = 1.05, 0.96, 1.00

    disp = 1.0
    if size_cc is not None:
        ref_cc = 125.0 if kart_class == "2t" else 200.0
        ratio = float(np.clip(float(size_cc) / ref_cc, 0.6, 1.8))
        disp = ratio ** 0.12

    mass_ratio = float(np.clip(175.0 / max(total_mass, 1.0), 0.75, 1.25))
    drive_mass = mass_ratio ** 0.05
    brake_mass = mass_ratio ** 0.08

    v = np.asarray(model.v_knots, dtype=float)
    if len(v) > 1 and float(v[-1] - v[0]) > 1e-6:
        v_norm = (v - float(v[0])) / float(v[-1] - v[0])
    else:
        v_norm = np.zeros_like(v)
    drive_shape = (drive_low * (1.0 - v_norm) + drive_high * v_norm) * disp * drive_mass
    drive_shape = np.clip(drive_shape, 0.80, 1.25)

    model.traction_force_per_kg = np.maximum(model.traction_force_per_kg * drive_shape, 0.1)
    model.braking_force_per_kg = np.maximum(
        model.braking_force_per_kg * np.clip(brake_gain * (disp ** 0.04) * brake_mass, 0.85, 1.20),
        0.1,
    )
    model.power_envelope_w_per_kg = np.maximum(
        model.power_envelope_w_per_kg * np.clip(0.5 * (drive_low + drive_high) * disp * drive_mass, 0.80, 1.20),
        1.0,
    )

    acd_peak_kw = _apply_acd_engine_curve(
        model=model,
        metadata=metadata,
        total_mass=total_mass,
        config=config,
    )

    peak_kw = _resolve_peak_power_kw(metadata)
    if peak_kw is None:
        peak_kw = acd_peak_kw
    if peak_kw is None or total_mass <= 0:
        return model

    p_w_per_kg = float(peak_kw) * 1000.0 / total_mass
    if p_w_per_kg <= 0:
        return model

    if acd_peak_kw is None:
        model.estimated_peak_power_w_per_kg = p_w_per_kg
        model.power_envelope_w_per_kg = np.minimum(
            model.power_envelope_w_per_kg,
            np.full_like(model.power_envelope_w_per_kg, p_w_per_kg),
        )
    else:
        model.estimated_peak_power_w_per_kg = max(
            float(model.estimated_peak_power_w_per_kg),
            p_w_per_kg,
        )
        # Keep ACD curve shape but prevent unrealistic peaks.
        hard_cap = p_w_per_kg * 1.08
        model.power_envelope_w_per_kg = np.minimum(
            model.power_envelope_w_per_kg,
            np.full_like(model.power_envelope_w_per_kg, hard_cap),
        )
    return model


def _apply_acd_engine_curve(
    model: VehicleModel,
    metadata: SessionMetadata,
    total_mass: float,
    config: KartEnvelopeConfig,
) -> float | None:
    """
    Apply de-crypted ACD torque/RPM curve to the fitted vehicle model.

    Returns scaled peak power [kW] if ACD data is available.
    """
    if total_mass <= 0:
        return None

    acd_path = resolve_acd_path(metadata)
    if acd_path is None:
        return None

    try:
        acd = load_acd_engine_data(acd_path)
    except Exception as exc:
        logger.warning("Failed to load ACD curve from %s: %s", acd_path, exc)
        return None

    quality = float(np.clip(config.sensitivity_kart_quality_scale, 0.75, 1.30))

    # Backfill metadata fields from ACD when missing.
    if metadata.engine_peak_torque_nm is None and acd.peak_torque_nm is not None:
        metadata.engine_peak_torque_nm = float(acd.peak_torque_nm) * quality
    if metadata.engine_peak_power_kw is None and acd.peak_power_kw is not None:
        metadata.engine_peak_power_kw = float(acd.peak_power_kw) * quality
    if metadata.engine_peak_power_hp is None and acd.peak_power_hp is not None:
        metadata.engine_peak_power_hp = float(acd.peak_power_hp) * quality
    if metadata.kart_weight_kg is None and acd.total_mass_kg is not None:
        est = float(acd.total_mass_kg) - float(metadata.driver_weight_kg)
        if est > 1.0:
            metadata.kart_weight_kg = est

    if len(acd.rpm) < 2 or len(acd.power_kw) < 2:
        return (
            float(acd.peak_power_kw) * quality
            if acd.peak_power_kw is not None
            else None
        )

    v = np.asarray(model.v_knots, dtype=float)
    if len(v) < 2:
        return (
            float(acd.peak_power_kw) * quality
            if acd.peak_power_kw is not None
            else None
        )

    v_ref = float(np.nanmax(v))
    if not math.isfinite(v_ref) or v_ref <= 0:
        v_ref = 1.0

    rpm_min = (
        float(acd.minimum_rpm)
        if acd.minimum_rpm is not None and acd.minimum_rpm > 0
        else float(acd.rpm[0])
    )
    rpm_max = (
        float(acd.limiter_rpm)
        if acd.limiter_rpm is not None and acd.limiter_rpm > rpm_min
        else float(acd.rpm[-1])
    )
    if rpm_max <= rpm_min:
        rpm_max = rpm_min + 1000.0

    rpm_at_v = rpm_min + np.clip(v, 0.0, v_ref) / v_ref * (rpm_max - rpm_min)
    p_curve_kw = np.interp(
        rpm_at_v,
        acd.rpm,
        acd.power_kw,
        left=float(acd.power_kw[0]),
        right=float(acd.power_kw[-1]),
    ) * quality
    p_curve_w_per_kg = np.maximum(p_curve_kw * 1000.0 / total_mass, 0.1)

    blend = float(np.clip(config.sensitivity_acd_power_blend, 0.0, 1.0))
    traction_floor = float(np.clip(config.sensitivity_acd_traction_floor_ratio, 0.4, 1.2))

    base_power = np.asarray(model.power_envelope_w_per_kg, dtype=float)
    target_power = np.maximum(base_power, p_curve_w_per_kg)
    model.power_envelope_w_per_kg = np.maximum(
        (1.0 - blend) * base_power + blend * target_power,
        0.1,
    )

    v_safe = np.maximum(v, 1.0)
    power_accel = model.power_envelope_w_per_kg / v_safe
    model.traction_force_per_kg = np.maximum(
        model.traction_force_per_kg,
        power_accel * traction_floor,
    )

    peak_kw = acd.peak_power_kw
    if peak_kw is None or peak_kw <= 0:
        return None
    return float(peak_kw) * quality


def _build_corner_ml_datasets(
    resampled_laps: dict[int, pd.DataFrame],
    corners: list[dict[str, Any]],
    distance: np.ndarray,
    kappa: np.ndarray,
    config: KartEnvelopeConfig,
) -> dict[int, _CornerMLDataset]:
    grouped_features: dict[int, list[np.ndarray]] = {}
    grouped_targets: dict[int, list[float]] = {}

    for corner in corners:
        s_start = float(corner.get("s_start", 0.0))
        s_end = float(corner.get("s_end", 0.0))
        s_apex = float(corner.get("s_apex", 0.5 * (s_start + s_end)))
        corner_id = int(corner.get("corner_id", 0))
        if corner_id <= 0 or s_end <= s_start:
            continue

        zone_start = max(float(distance[0]), s_start - config.sensitivity_entry_margin_m)
        if zone_start >= s_end:
            continue

        for lap_df in resampled_laps.values():
            if COL_DIST not in lap_df.columns or COL_SPEED not in lap_df.columns:
                continue

            s_lap = pd.to_numeric(lap_df[COL_DIST], errors="coerce").values
            v_lap = pd.to_numeric(lap_df[COL_SPEED], errors="coerce").values
            mask = np.isfinite(s_lap) & np.isfinite(v_lap)
            if np.sum(mask) < 3:
                continue
            s_lap = s_lap[mask]
            v_lap = v_lap[mask]

            order = np.argsort(s_lap)
            s_lap = s_lap[order]
            v_lap = v_lap[order]
            s_lap, keep = np.unique(s_lap, return_index=True)
            v_lap = v_lap[keep]
            if len(s_lap) < 3:
                continue

            entry_speed = _interp(s_lap, v_lap, zone_start)
            brake_point = _estimate_brake_point(lap_df, s_start, zone_start)
            turn_in_point = _estimate_turn_in_point(lap_df, distance, kappa, s_start, s_apex)
            corner_time = _integrate_range(s_lap, v_lap, s_start, s_end)
            if not math.isfinite(corner_time) or corner_time <= 0:
                continue

            feat = _corner_ml_features(
                entry_speed=entry_speed,
                corner_start=s_start,
                brake_point=brake_point,
                turn_in_point=turn_in_point,
            )
            if not np.all(np.isfinite(feat)):
                continue

            grouped_features.setdefault(corner_id, []).append(feat)
            grouped_targets.setdefault(corner_id, []).append(float(corner_time))

    out: dict[int, _CornerMLDataset] = {}
    for corner_id, feats in grouped_features.items():
        targets = grouped_targets.get(corner_id, [])
        if len(feats) < config.sensitivity_ml_min_samples or len(targets) != len(feats):
            continue
        x = np.asarray(feats, dtype=float)
        y = np.asarray(targets, dtype=float)
        scale = np.nanstd(x, axis=0)
        scale = np.where(np.isfinite(scale) & (scale > 1e-6), scale, 1.0)
        out[corner_id] = _CornerMLDataset(
            feature_matrix=x,
            target_time_s=y,
            feature_scale=scale,
        )

    return out


def _corner_ml_features(
    entry_speed: float,
    corner_start: float,
    brake_point: float,
    turn_in_point: float,
) -> np.ndarray:
    return np.array([
        float(entry_speed),
        float(corner_start - brake_point),
        float(turn_in_point - corner_start),
    ], dtype=float)


def _predict_corner_time_knn(
    dataset: _CornerMLDataset | None,
    features: np.ndarray,
    config: KartEnvelopeConfig,
) -> float | None:
    if dataset is None or len(dataset.target_time_s) == 0:
        return None

    x = np.asarray(features, dtype=float)
    if x.shape != (3,) or not np.all(np.isfinite(x)):
        return None

    x_mat = dataset.feature_matrix
    y = dataset.target_time_s
    scale = np.where(dataset.feature_scale > 1e-6, dataset.feature_scale, 1.0)

    diff = (x_mat - x) / scale
    dist = np.sqrt(np.sum(diff * diff, axis=1))
    finite = np.isfinite(dist) & np.isfinite(y)
    if np.sum(finite) == 0:
        return None

    dist = dist[finite]
    y = y[finite]
    k = int(max(1, config.sensitivity_ml_k_neighbors))
    k = min(k, len(dist))
    if k <= 0:
        return None

    idx = np.argpartition(dist, k - 1)[:k]
    d = dist[idx]
    yy = y[idx]
    if len(yy) == 0:
        return None

    if config.sensitivity_ml_enable_outlier_filter and len(yy) >= 4:
        med = float(np.median(yy))
        mad = float(np.median(np.abs(yy - med)))
        if mad > 1e-9:
            inlier = np.abs(yy - med) <= (3.0 * 1.4826 * mad)
            if np.any(inlier):
                d = d[inlier]
                yy = yy[inlier]
    if len(yy) == 0:
        return None

    trim_q = float(np.clip(config.sensitivity_ml_robust_trim_q, 0.0, 0.2))
    if trim_q > 0 and len(yy) >= 5:
        lo = float(np.quantile(yy, trim_q))
        hi = float(np.quantile(yy, 1.0 - trim_q))
        keep = (yy >= lo) & (yy <= hi)
        if np.any(keep):
            d = d[keep]
            yy = yy[keep]
    if len(yy) == 0:
        return None

    w = 1.0 / (d + 1e-6)
    w_sum = float(np.sum(w))
    if w_sum <= 0:
        return None
    return float(np.sum(w * yy) / w_sum)


def _blend_corner_time(
    baseline_corner_time_s: float,
    physics_corner_time_s: float,
    ml_baseline_corner_time_s: float,
    ml_corner_time_s: float,
    reference_penalty_s: float,
    config: KartEnvelopeConfig,
) -> float:
    blend = float(np.clip(config.sensitivity_ml_blend, 0.0, 1.0))
    if blend <= 0:
        return float(physics_corner_time_s)

    phys_delta = float(physics_corner_time_s - baseline_corner_time_s)
    ml_delta = float(ml_corner_time_s - ml_baseline_corner_time_s)
    blended_delta = (1.0 - blend) * phys_delta + blend * ml_delta

    if config.sensitivity_ml_enable_ensemble:
        ref_w = float(np.clip(config.sensitivity_ml_ensemble_reference_weight, 0.0, 0.5))
        blended_delta *= (1.0 - ref_w)

    blended_delta += max(float(reference_penalty_s), 0.0)

    max_corr = max(float(config.sensitivity_ml_max_correction_s), 0.0)
    if max_corr > 0:
        correction = blended_delta - phys_delta
        blended_delta = phys_delta + float(np.clip(correction, -max_corr, max_corr))

    return max(float(baseline_corner_time_s + blended_delta), 0.01)


def _total_mass_kg(metadata: SessionMetadata, config: KartEnvelopeConfig) -> float:
    kart_mass = metadata.kart_weight_kg
    if kart_mass is None:
        if str(metadata.kart_class).lower() == "2t":
            kart_mass = config.default_kart_weight_kg_2t
        else:
            kart_mass = config.default_kart_weight_kg_4t
    return max(float(metadata.driver_weight_kg) + float(kart_mass), 1.0)


def _resolve_peak_power_kw(metadata: SessionMetadata) -> float | None:
    peak_kw = getattr(metadata, "engine_peak_power_kw", None)
    if peak_kw is not None:
        try:
            peak_kw = float(peak_kw)
            if peak_kw > 0:
                return peak_kw
        except (TypeError, ValueError):
            pass

    peak_hp = getattr(metadata, "engine_peak_power_hp", None)
    if peak_hp is not None:
        try:
            peak_hp = float(peak_hp)
            if peak_hp > 0:
                return peak_hp * 0.745699872
        except (TypeError, ValueError):
            pass
    return None


def _tire_condition_scale(metadata: SessionMetadata, scalars: SessionScalars) -> float:
    tire = str(getattr(metadata, "tire_type", "slick") or "slick").strip().lower()
    cond = str(metadata.condition_label or scalars.condition_label or "dry").strip().lower()

    # Multipliers are intentionally mild because session scalars already encode
    # most condition effects from observed telemetry.
    table = {
        ("slick", "dry"): 1.00,
        ("slick", "damp"): 0.96,
        ("slick", "wet"): 0.88,
        ("slick", "greasy"): 0.92,
        ("wet", "dry"): 0.94,
        ("wet", "damp"): 1.00,
        ("wet", "wet"): 1.00,
        ("wet", "greasy"): 0.99,
    }
    return table.get((tire, cond), 1.00)


def _rollout_corner(
    distance: np.ndarray,
    kappa: np.ndarray,
    speed_reference: np.ndarray,
    zone_start: float,
    zone_end: float,
    corner_start: float,
    corner_apex: float,
    corner_end: float,
    start_speed: float,
    baseline_brake_point: float,
    baseline_turn_in: float,
    brake_shift_s: float,
    turn_shift_m: float,
    apex_shift_m_input: float,
    line_curvature_scale: float,
    lat_force_scale: float,
    brake_force_scale: float,
    env: CapabilityEnvelope,
    vehicle_model: VehicleModel | None,
    config: KartEnvelopeConfig,
) -> _CornerRollout:
    mask = (distance >= zone_start) & (distance <= zone_end)
    if np.sum(mask) < 3:
        return _CornerRollout(
            distance_m=np.array([zone_start, zone_end], dtype=float),
            speed_mps=np.array([start_speed, start_speed], dtype=float),
            corner_time_s=float("inf"),
            feasible=False,
            reason="zone_too_short",
        )

    s = distance[mask]
    if np.any(np.diff(s) <= 0):
        return _CornerRollout(
            distance_m=s,
            speed_mps=np.full_like(s, start_speed),
            corner_time_s=float("inf"),
            feasible=False,
            reason="non_monotonic_distance",
        )

    kappa_shifted = np.interp(
        s - turn_shift_m,
        distance,
        kappa,
        left=float(kappa[0]),
        right=float(kappa[-1]),
    )
    line_scale = float(np.clip(line_curvature_scale, 0.75, 1.20))
    kappa_shifted = np.abs(kappa_shifted) * line_scale

    v_brake_ref = _interp(distance, speed_reference, baseline_brake_point)
    s_brake = baseline_brake_point + brake_shift_s * max(v_brake_ref, config.solver_min_speed_mps)
    s_brake = float(np.clip(s_brake, zone_start, corner_end))
    corner_len = max(0.0, corner_end - corner_start)
    if corner_len > 1.0:
        s_apex_target = float(np.clip(
            corner_apex + apex_shift_m_input,
            corner_start + 0.5,
            corner_end - 0.5,
        ))
    else:
        s_apex_target = float(np.clip(corner_apex, zone_start, corner_end))
    s_turn_hi = s_apex_target - 0.25 if s_apex_target > zone_start + 0.5 else corner_end
    s_turn = float(np.clip(baseline_turn_in + turn_shift_m, zone_start, max(zone_start, s_turn_hi)))
    line_path_penalty = float(np.clip(config.sensitivity_line_path_penalty, 0.0, 1.0))
    line_path_scale = 1.0 + line_path_penalty * (max(1.0 / max(line_scale, 1e-6) - 1.0, 0.0) ** 2)

    v = np.zeros_like(s, dtype=float)
    v[0] = float(np.clip(start_speed, config.solver_min_speed_mps, config.solver_max_speed_mps))
    lat_scale = float(np.clip(lat_force_scale, 0.70, 1.50))
    brake_scale = float(np.clip(brake_force_scale, 0.70, 1.50))

    feasible = True
    reason = ""
    overspeed_count = 0

    for i in range(len(s) - 1):
        ds = s[i + 1] - s[i]
        if ds <= 0:
            feasible = False
            reason = "non_positive_step"
            break
        in_corner = (s[i] >= corner_start) and (s[i] <= corner_end)
        ds_eff = ds * line_path_scale if in_corner else ds

        v_cur = float(max(v[i], config.solver_min_speed_mps))
        a_lat = v_cur * v_cur * kappa_shifted[i] if kappa_shifted[i] > 0 else 0.0
        a_lat_equiv = a_lat / max(lat_scale, 1e-6)
        a_drive = float(env.max_longitudinal_accel(v_cur, a_lat_equiv, braking=False))
        if vehicle_model is not None:
            try:
                a_drive = min(a_drive, float(vehicle_model.traction_accel(v_cur)))
            except Exception:
                pass

        a_brake = float(env.max_longitudinal_accel(v_cur, a_lat_equiv, braking=True)) * brake_scale
        if s[i] < s_brake:
            a_min = -config.sensitivity_coast_decel_mps2
        elif s[i] < s_turn:
            a_min = -a_brake
        elif s[i] < s_apex_target:
            a_min = -0.75 * a_brake
        else:
            a_min = -a_brake

        a_max = max(a_drive, 0.0)
        v_corner_next = float(env.max_cornering_speed(kappa_shifted[i + 1]))
        if math.isfinite(v_corner_next):
            v_corner_next *= math.sqrt(lat_scale)
        v_corner_next = float(np.clip(v_corner_next, config.solver_min_speed_mps, config.solver_max_speed_mps))

        a_req = (v_corner_next * v_corner_next - v_cur * v_cur) / (2.0 * max(ds_eff, 1e-6))
        a_cmd = float(np.clip(a_req, a_min, a_max))
        if s[i] >= s_apex_target and a_cmd < 0 and v_cur < v_corner_next * 0.97:
            a_cmd = 0.0

        v_next_sq = max(v_cur * v_cur + 2.0 * a_cmd * ds_eff, config.solver_min_speed_mps ** 2)
        v_next = math.sqrt(v_next_sq)
        if v_next > v_corner_next * config.sensitivity_max_overspeed_ratio:
            overspeed_count += 1
            if overspeed_count > 2:
                feasible = False
                reason = "corner_overspeed"
                break

        v_next = min(v_next, v_corner_next * 1.001)
        v[i + 1] = float(np.clip(v_next, config.solver_min_speed_mps, config.solver_max_speed_mps))

    if not feasible:
        return _CornerRollout(
            distance_m=s,
            speed_mps=v,
            corner_time_s=float("inf"),
            feasible=False,
            reason=reason,
            brake_point_m=s_brake,
            turn_in_point_m=s_turn,
            apex_shift_input_m=float(apex_shift_m_input),
            line_curvature_scale=line_scale,
            lat_force_scale=lat_scale,
            brake_force_scale=brake_scale,
        )

    corner_time = _integrate_range(s, v, corner_start, corner_end)
    apex_mask = (s >= corner_start) & (s <= corner_end)
    if np.any(apex_mask):
        s_corner = s[apex_mask]
        v_corner = v[apex_mask]
        apex_idx = int(np.argmin(v_corner))
        apex_point_m = float(s_corner[apex_idx])
        apex_speed_mps = float(v_corner[apex_idx])
    else:
        apex_point_m = float(np.clip(s_apex_target, float(s[0]), float(s[-1])))
        apex_speed_mps = float(_interp(s, v, apex_point_m))
    if not math.isfinite(corner_time) or corner_time <= 0:
        return _CornerRollout(
            distance_m=s,
            speed_mps=v,
            corner_time_s=float("inf"),
            feasible=False,
            reason="invalid_corner_time",
            brake_point_m=s_brake,
            turn_in_point_m=s_turn,
            apex_shift_input_m=float(apex_shift_m_input),
            apex_point_m=apex_point_m,
            apex_speed_mps=apex_speed_mps,
            line_curvature_scale=line_scale,
            lat_force_scale=lat_scale,
            brake_force_scale=brake_scale,
        )

    return _CornerRollout(
        distance_m=s,
        speed_mps=v,
        corner_time_s=corner_time,
        feasible=True,
        exit_speed_mps=_interp(s, v, corner_end),
        brake_point_m=s_brake,
        turn_in_point_m=s_turn,
        apex_shift_input_m=float(apex_shift_m_input),
        apex_point_m=apex_point_m,
        apex_speed_mps=apex_speed_mps,
        line_curvature_scale=line_scale,
        lat_force_scale=lat_scale,
        brake_force_scale=brake_scale,
    )


def _global_consistency_pass(
    distance: np.ndarray,
    kappa: np.ndarray,
    speed_seed: np.ndarray,
    env: CapabilityEnvelope,
    vehicle_model: VehicleModel | None,
    config: KartEnvelopeConfig,
    lat_force_scale: float = 1.0,
    brake_force_scale: float = 1.0,
) -> np.ndarray:
    v = np.asarray(speed_seed, dtype=float).copy()
    v = np.clip(v, config.solver_min_speed_mps, config.solver_max_speed_mps)
    lat_scale = float(np.clip(lat_force_scale, 0.70, 1.50))
    brake_scale = float(np.clip(brake_force_scale, 0.70, 1.50))

    v_corner = np.array(
        [float(env.max_cornering_speed(abs(k))) * math.sqrt(lat_scale) for k in kappa],
        dtype=float,
    )
    v_corner = np.clip(v_corner, config.solver_min_speed_mps, config.solver_max_speed_mps)
    v = np.minimum(v, v_corner)

    for _ in range(config.sensitivity_consistency_iterations):
        # Forward accel feasibility
        for i in range(len(v) - 1):
            ds = distance[i + 1] - distance[i]
            if ds <= 0:
                continue
            v_cur = max(v[i], config.solver_min_speed_mps)
            a_lat = v_cur * v_cur * abs(kappa[i]) if kappa[i] > 0 else 0.0
            a_lat_equiv = a_lat / max(lat_scale, 1e-6)
            a_drive = float(env.max_longitudinal_accel(v_cur, a_lat_equiv, braking=False))
            if vehicle_model is not None:
                try:
                    a_drive = min(a_drive, float(vehicle_model.traction_accel(v_cur)))
                except Exception:
                    pass
            v_allow = math.sqrt(max(v_cur * v_cur + 2.0 * max(a_drive, 0.0) * ds, 0.0))
            v[i + 1] = min(v[i + 1], v_allow, v_corner[i + 1], config.solver_max_speed_mps)
            v[i + 1] = max(v[i + 1], config.solver_min_speed_mps)

        # Backward braking feasibility
        for i in range(len(v) - 1, 0, -1):
            ds = distance[i] - distance[i - 1]
            if ds <= 0:
                continue
            v_cur = max(v[i], config.solver_min_speed_mps)
            a_lat = v_cur * v_cur * abs(kappa[i]) if kappa[i] > 0 else 0.0
            a_lat_equiv = a_lat / max(lat_scale, 1e-6)
            a_brake = float(env.max_longitudinal_accel(v_cur, a_lat_equiv, braking=True)) * brake_scale
            v_allow_prev = math.sqrt(max(v_cur * v_cur + 2.0 * max(a_brake, 0.0) * ds, 0.0))
            v[i - 1] = min(v[i - 1], v_allow_prev, v_corner[i - 1], config.solver_max_speed_mps)
            v[i - 1] = max(v[i - 1], config.solver_min_speed_mps)

    return v


def _build_force_scale_grid(
    gain: float,
    n_points: int,
    underdrive_only: bool,
) -> np.ndarray:
    n = int(max(1, n_points))
    g = float(max(gain, 0.0))
    if n == 1 or g <= 1e-6:
        return np.array([1.0], dtype=float)
    if underdrive_only:
        return np.linspace(1.0, 1.0 + g, n, dtype=float)
    return np.linspace(max(0.2, 1.0 - g), 1.0 + g, n, dtype=float)


def _build_shift_candidates(
    config: KartEnvelopeConfig,
) -> list[tuple[float, float, float, float]]:
    """Build (brake, turn, apex, line) candidate tuples."""
    max_brake = float(max(config.sensitivity_brake_shift_s, 0.0))
    max_turn = float(max(config.sensitivity_turn_shift_m, 0.0))
    max_apex = float(max(config.sensitivity_apex_shift_m, 0.0))

    if not config.sensitivity_two_stage_search:
        axis_brake = np.linspace(-max_brake, max_brake, int(max(1, config.sensitivity_grid_size)))
        axis_turn = np.linspace(-max_turn, max_turn, int(max(1, config.sensitivity_grid_size)))
        base_pairs = [(float(b), float(t)) for b in axis_brake for t in axis_turn]
    else:
        n_coarse = int(max(3, config.sensitivity_two_stage_coarse_grid_size))
        n_refine = int(max(3, config.sensitivity_two_stage_refine_grid_size))
        top_n = int(max(1, config.sensitivity_two_stage_top_n))

        axis_brake_coarse = np.linspace(-max_brake, max_brake, n_coarse)
        axis_turn_coarse = np.linspace(-max_turn, max_turn, n_coarse)
        coarse_pairs = [(float(b), float(t)) for b in axis_brake_coarse for t in axis_turn_coarse]

        if len(axis_brake_coarse) > 1:
            step_b = float(abs(axis_brake_coarse[1] - axis_brake_coarse[0]))
        else:
            step_b = float(max_brake)
        if len(axis_turn_coarse) > 1:
            step_t = float(abs(axis_turn_coarse[1] - axis_turn_coarse[0]))
        else:
            step_t = float(max_turn)
        step_b = max(step_b, 1e-6)
        step_t = max(step_t, 1e-6)

        anchor_sorted = sorted(
            coarse_pairs,
            key=lambda bt: ((bt[0] / step_b) ** 2 + (bt[1] / step_t) ** 2),
        )
        anchors = anchor_sorted[:top_n]

        base_pairs = []
        seen: set[tuple[int, int]] = set()

        def _append_pair(b: float, t: float) -> None:
            b = float(np.clip(b, -max_brake, max_brake))
            t = float(np.clip(t, -max_turn, max_turn))
            key = (int(round(b * 1e6)), int(round(t * 1e6)))
            if key not in seen:
                seen.add(key)
                base_pairs.append((b, t))

        for b, t in coarse_pairs:
            _append_pair(b, t)

        ref_b = np.linspace(-0.5 * step_b, 0.5 * step_b, n_refine)
        ref_t = np.linspace(-0.5 * step_t, 0.5 * step_t, n_refine)
        for b0, t0 in anchors:
            for db in ref_b:
                for dt in ref_t:
                    _append_pair(b0 + float(db), t0 + float(dt))

    axis_apex = (
        np.array([0.0], dtype=float)
        if max_apex <= 1e-9
        else np.linspace(-max_apex, max_apex, int(max(1, config.sensitivity_apex_grid_size)))
    )
    axis_line = _build_line_scale_grid(
        gain=float(max(config.sensitivity_line_curvature_gain, 0.0)),
        n_points=int(max(1, config.sensitivity_line_grid_size)),
        underdrive_only=bool(config.sensitivity_underdrive_only),
    )
    out: list[tuple[float, float, float, float]] = []
    for b, t in base_pairs:
        for a in axis_apex:
            for line in axis_line:
                out.append((float(b), float(t), float(a), float(line)))
    return out


def _build_line_scale_grid(
    gain: float,
    n_points: int,
    underdrive_only: bool,
) -> np.ndarray:
    n = int(max(1, n_points))
    g = float(np.clip(gain, 0.0, 0.35))
    if n == 1 or g <= 1e-6:
        return np.array([1.0], dtype=float)
    if underdrive_only:
        # line_scale < 1.0 => larger effective radius (flatter curvature).
        return np.linspace(1.0 - g, 1.0, n, dtype=float)
    return np.linspace(1.0 - g, 1.0 + g, n, dtype=float)


def _condition_force_penalty(condition_label: str, config: KartEnvelopeConfig) -> float:
    cond = str(condition_label or "").strip().lower().replace("_", " ").replace("-", " ")
    if not cond:
        return 1.0

    if "wet" in cond:
        return float(np.clip(config.sensitivity_force_penalty_wet, 0.60, 1.10))
    if "damp" in cond:
        return float(np.clip(config.sensitivity_force_penalty_damp, 0.60, 1.10))
    if "greasy" in cond:
        return float(np.clip(config.sensitivity_force_penalty_greasy, 0.60, 1.10))
    if "green" in cond:
        return float(np.clip(config.sensitivity_force_penalty_green, 0.60, 1.10))
    return 1.0


def _reference_penalty_s(
    brake_shift_s: float,
    turn_shift_m: float,
    apex_shift_m_input: float,
    line_curvature_scale: float,
    config: KartEnvelopeConfig,
) -> float:
    """
    Conservative penalty for large shift excursions when ML is blended in.

    This avoids aggressive extrapolation when the candidate is far from
    observed driving points.
    """
    max_b = max(float(config.sensitivity_brake_shift_s), 1e-6)
    max_t = max(float(config.sensitivity_turn_shift_m), 1e-6)
    max_a = max(float(config.sensitivity_apex_shift_m), 1e-6)
    max_l = max(float(config.sensitivity_line_curvature_gain), 1e-6)
    nb = abs(float(brake_shift_s)) / max_b
    nt = abs(float(turn_shift_m)) / max_t
    na = abs(float(apex_shift_m_input)) / max_a
    nl = abs(float(1.0 - line_curvature_scale)) / max_l
    radial = 0.25 * (nb * nb + nt * nt + na * na + nl * nl)
    scale = (
        float(np.clip(config.sensitivity_ml_ensemble_reference_weight, 0.0, 1.0))
        * float(max(config.sensitivity_ml_max_correction_s, 0.0))
    )
    return float(max(0.0, radial * scale))


def _resolve_gain_shrink_factor(
    metadata: SessionMetadata,
    config: KartEnvelopeConfig,
) -> float:
    default = float(np.clip(
        config.sensitivity_gain_shrinkage_default,
        config.sensitivity_gain_shrinkage_min,
        config.sensitivity_gain_shrinkage_max,
    ))
    path_s = config.sensitivity_gain_shrinkage_csv
    if not path_s:
        return default

    path = Path(path_s)
    if not path.is_absolute():
        path = Path.cwd() / path
    if not path.exists():
        return default

    track = _norm_key(getattr(metadata, "track_name", None))
    kart = _norm_key(getattr(metadata, "kart_id", None))
    cond = _norm_key(getattr(metadata, "condition_label", None))
    best_match: float | None = None

    try:
        with open(path, encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                try:
                    raw = (
                        row.get("gain_shrink_factor")
                        or row.get("shrink_factor")
                        or row.get("factor")
                    )
                    if raw is None:
                        continue
                    val = float(raw)
                except (TypeError, ValueError):
                    continue

                r_track = _norm_key(row.get("track"))
                r_kart = _norm_key(row.get("kart_id") or row.get("kart"))
                r_cond = _norm_key(row.get("condition") or row.get("condition_label"))
                if r_track and track and r_track != track:
                    continue
                if r_kart and kart and r_kart != kart:
                    continue
                if r_cond and cond and r_cond != cond:
                    continue
                best_match = val
                break
    except Exception as exc:
        logger.warning("Failed reading gain shrinkage file %s: %s", path, exc)
        return default

    out = default if best_match is None else float(best_match)
    return float(np.clip(
        out,
        config.sensitivity_gain_shrinkage_min,
        config.sensitivity_gain_shrinkage_max,
    ))


def _apply_gain_shrinkage(
    distance: np.ndarray,
    baseline_speed: np.ndarray,
    ideal_speed: np.ndarray,
    recommendations: list[CornerRecommendation],
    gain_shrink: float,
) -> tuple[np.ndarray, float, list[CornerRecommendation]]:
    w = float(np.clip(gain_shrink, 0.0, 1.0))
    shrunk_speed = np.asarray(baseline_speed, dtype=float) + w * (
        np.asarray(ideal_speed, dtype=float) - np.asarray(baseline_speed, dtype=float)
    )
    shrunk_speed = np.maximum(shrunk_speed, 0.5)
    shrunk_time = _integrate_range(
        distance,
        shrunk_speed,
        float(distance[0]),
        float(distance[-1]),
    )

    shrunk_recs: list[CornerRecommendation] = []
    for rec in recommendations:
        gain = max(0.0, float(rec.gain_s) * w)
        shrunk_recs.append(CornerRecommendation(
            corner_id=rec.corner_id,
            gain_s=gain,
            brake_shift_s=rec.brake_shift_s,
            turn_shift_m=rec.turn_shift_m,
            apex_shift_input_m=rec.apex_shift_input_m,
            line_curvature_scale=rec.line_curvature_scale,
            baseline_corner_time_s=rec.baseline_corner_time_s,
            optimized_corner_time_s=max(0.01, rec.baseline_corner_time_s - gain),
            brake_point_m=rec.brake_point_m,
            turn_in_point_m=rec.turn_in_point_m,
            apex_point_m=rec.apex_point_m,
            apex_shift_m=rec.apex_shift_m,
            apex_speed_mps=rec.apex_speed_mps,
            lat_force_scale=rec.lat_force_scale,
            brake_force_scale=rec.brake_force_scale,
        ))
    return shrunk_speed, float(shrunk_time), shrunk_recs


def _estimate_lap_time_uncertainty(
    baseline_lap_time_s: float,
    ideal_lap_time_s: float,
    candidate_rows: list[dict[str, Any]],
    recommendations: list[CornerRecommendation],
    gain_shrink: float,
    config: KartEnvelopeConfig,
) -> tuple[float | None, float | None]:
    if not config.sensitivity_uncertainty_enable:
        return None, None

    corner_gain_pool: dict[int, list[float]] = {}
    for row in candidate_rows:
        if not bool(row.get("feasible", False)):
            continue
        cid = int(row.get("corner_id", 0))
        g = float(row.get("gain_s", 0.0) or 0.0)
        if cid > 0 and g > 0:
            corner_gain_pool.setdefault(cid, []).append(g * gain_shrink)

    if not recommendations:
        sigma = float(max(config.sensitivity_uncertainty_sigma_floor_s, 0.01))
        return max(0.01, ideal_lap_time_s - sigma), ideal_lap_time_s + sigma

    pools: list[np.ndarray] = []
    for rec in recommendations:
        gains = corner_gain_pool.get(int(rec.corner_id))
        if not gains:
            gains = [max(float(rec.gain_s), 0.0)]
        pools.append(np.asarray(gains, dtype=float))

    n_boot = int(max(8, config.sensitivity_uncertainty_bootstrap_n))
    rng = np.random.default_rng(42)
    samples = np.empty(n_boot, dtype=float)
    for i in range(n_boot):
        total_gain = 0.0
        for gains in pools:
            if len(gains) == 0:
                continue
            total_gain += float(gains[rng.integers(0, len(gains))])
        samples[i] = max(0.01, float(baseline_lap_time_s) - total_gain)

    q_low = float(np.quantile(samples, 0.10))
    q_high = float(np.quantile(samples, 0.90))
    sigma_floor = float(max(config.sensitivity_uncertainty_sigma_floor_s, 0.01))
    low = min(q_low, float(ideal_lap_time_s) - sigma_floor)
    high = max(q_high, float(ideal_lap_time_s) + sigma_floor)
    if low > high:
        low, high = high, low
    return max(0.01, low), max(high, 0.02)


def _compute_reliability_metrics(
    evaluated_count: int,
    accepted_count: int,
    candidate_rows: list[dict[str, Any]],
    recommendations: list[CornerRecommendation],
    total_gain_s: float,
    baseline_lap_time_s: float,
    gain_shrink: float,
    scalars_confidence: float,
    ml_enabled: bool,
    ml_training_rows: int,
    ml_used_corners: int,
) -> dict[str, Any]:
    feasible = sum(1 for row in candidate_rows if bool(row.get("feasible", False)))
    positive = sum(1 for row in candidate_rows if float(row.get("gain_s", 0.0) or 0.0) > 1e-6)
    feasible_ratio = (feasible / evaluated_count) if evaluated_count > 0 else 0.0
    positive_ratio = (positive / evaluated_count) if evaluated_count > 0 else 0.0
    if recommendations:
        accepted_ratio = float(accepted_count) / max(len(recommendations), 1)
    else:
        accepted_ratio = 1.0 if accepted_count == 0 else 0.0
    accepted_ratio = float(np.clip(accepted_ratio, 0.0, 1.0))
    gain_pct = (100.0 * total_gain_s / baseline_lap_time_s) if baseline_lap_time_s > 1e-9 else 0.0
    confidence = float(np.clip(scalars_confidence, 0.0, 1.0))
    shrink_closeness = float(np.clip(1.0 - abs(1.0 - gain_shrink), 0.0, 1.0))
    score = float(np.clip(
        0.40 * confidence +
        0.25 * feasible_ratio +
        0.20 * positive_ratio +
        0.15 * shrink_closeness,
        0.0,
        1.0,
    ))

    return {
        "score": round(score, 4),
        "feasible_ratio": round(feasible_ratio, 4),
        "positive_gain_ratio": round(positive_ratio, 4),
        "accepted_ratio": round(float(accepted_ratio), 4),
        "gain_pct": round(float(gain_pct), 4),
        "scalars_confidence": round(confidence, 4),
        "gain_shrink_factor": round(float(gain_shrink), 4),
        "ml_enabled": bool(ml_enabled),
        "ml_training_rows": int(ml_training_rows),
        "ml_used_corners": int(ml_used_corners),
    }


def _norm_key(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def _apply_target_calibration(
    distance: np.ndarray,
    kappa: np.ndarray,
    baseline_speed: np.ndarray,
    speed_seed: np.ndarray,
    current_time_s: float,
    env: CapabilityEnvelope,
    vehicle_model: VehicleModel | None,
    config: KartEnvelopeConfig,
) -> tuple[np.ndarray, float, float]:
    """
    Optional global underdrive calibration to approach target lap time.

    Returns ``(speed_profile, lap_time_s, applied_force_scale)``.
    """
    target = config.sensitivity_target_lap_time_s
    if target is None or target <= 0:
        return speed_seed, float(current_time_s), 1.0

    baseline = np.asarray(baseline_speed, dtype=float)
    seed = np.maximum(np.asarray(speed_seed, dtype=float), baseline)
    if len(seed) != len(distance) or len(baseline) != len(distance):
        return seed, float(current_time_s), 1.0

    template_delta = np.clip(seed - baseline, 0.0, None)
    if float(np.nanmax(template_delta)) <= 1e-9:
        return seed, float(current_time_s), 1.0

    local_weight = _target_alignment_weight(kappa, baseline)
    template_delta = template_delta * local_weight
    if float(np.nanmax(template_delta)) <= 1e-9:
        return seed, float(current_time_s), 1.0

    max_scale = max(1.0, float(config.sensitivity_target_max_force_scale))
    n_grid = int(max(2, config.sensitivity_target_grid_size))
    scales = np.linspace(1.0, max_scale, n_grid)

    best_speed = seed
    best_time = float(current_time_s)
    best_scale = 1.0
    for scale in scales:
        env_scaled = env.scaled(mu=float(scale), p_drive=float(scale), b_brake=float(scale))
        cand_seed = np.maximum(baseline + float(scale) * template_delta, baseline)
        cand = _global_consistency_pass(
            distance=distance,
            kappa=kappa,
            speed_seed=cand_seed,
            env=env_scaled,
            vehicle_model=vehicle_model,
            config=config,
            lat_force_scale=float(scale),
            brake_force_scale=float(scale),
        )
        cand = np.maximum(cand, baseline)
        t = _integrate_range(distance, cand, float(distance[0]), float(distance[-1]))
        if t < best_time - 1e-6:
            best_speed = cand
            best_time = t
            best_scale = float(scale)
        if best_time <= target:
            break

    return best_speed, best_time, best_scale


def _target_alignment_weight(kappa: np.ndarray, baseline_speed: np.ndarray) -> np.ndarray:
    """
    Build a spatial weight that focuses target-alignment gains in braking/corner zones.

    Output in [0, 1] with a low floor to preserve continuity.
    """
    k = np.abs(np.asarray(kappa, dtype=float))
    v = np.asarray(baseline_speed, dtype=float)
    if len(k) != len(v) or len(k) == 0:
        return np.ones_like(v, dtype=float)

    k_ref = float(np.nanpercentile(k, 90)) if np.any(np.isfinite(k)) else 0.0
    if not np.isfinite(k_ref) or k_ref <= 1e-9:
        curv_w = np.zeros_like(k)
    else:
        curv_w = np.clip(k / k_ref, 0.0, 1.0)

    if len(v) >= 3:
        dv = np.diff(v, prepend=v[0])
        decel = np.clip(-dv, 0.0, None)
        d_ref = float(np.nanpercentile(decel, 90)) if np.any(np.isfinite(decel)) else 0.0
        decel_w = np.clip(decel / d_ref, 0.0, 1.0) if d_ref > 1e-9 else np.zeros_like(v)
    else:
        decel_w = np.zeros_like(v)

    w = 0.12 + 0.68 * curv_w + 0.20 * decel_w
    return np.clip(w, 0.05, 1.0)


def _compute_sector_rows(
    distance: np.ndarray,
    baseline_speed: np.ndarray,
    ideal_speed: np.ndarray,
    n_sectors: int,
) -> list[dict[str, Any]]:
    if n_sectors < 1:
        return []
    s0 = float(distance[0])
    s1 = float(distance[-1])
    total = s1 - s0
    if total <= 0:
        return []

    rows: list[dict[str, Any]] = []
    for idx in range(n_sectors):
        seg_lo = s0 + total * idx / n_sectors
        seg_hi = s0 + total * (idx + 1) / n_sectors
        t_base = _integrate_range(distance, baseline_speed, seg_lo, seg_hi)
        t_ideal = _integrate_range(distance, ideal_speed, seg_lo, seg_hi)
        rows.append({
            "sector": f"S{idx + 1}",
            "s_start_m": round(seg_lo, 3),
            "s_end_m": round(seg_hi, 3),
            "baseline_time_s": round(t_base, 6),
            "ideal_time_s": round(t_ideal, 6),
            "gain_s": round(t_base - t_ideal, 6),
        })
    return rows


def _estimate_brake_point(
    lap_df: pd.DataFrame,
    corner_start: float,
    zone_start: float,
) -> float:
    if COL_DIST not in lap_df.columns:
        return corner_start

    s = pd.to_numeric(lap_df[COL_DIST], errors="coerce").values
    if COL_ACCEL_LONG in lap_df.columns:
        ax = pd.to_numeric(lap_df[COL_ACCEL_LONG], errors="coerce").values
    else:
        ax = np.zeros_like(s)

    mask = (
        np.isfinite(s) & np.isfinite(ax) &
        (s >= zone_start) & (s <= corner_start)
    )
    idx = np.where(mask)[0]
    if len(idx) == 0:
        return corner_start

    for i in reversed(idx):
        if ax[i] > -1.0:
            return float(s[i])
    return float(s[idx[0]])


def _estimate_turn_in_point(
    lap_df: pd.DataFrame,
    distance: np.ndarray,
    kappa: np.ndarray,
    corner_start: float,
    corner_apex: float,
) -> float:
    if COL_DIST not in lap_df.columns:
        return corner_start

    s = pd.to_numeric(lap_df[COL_DIST], errors="coerce").values
    if COL_ACCEL_LAT in lap_df.columns:
        ay = np.abs(pd.to_numeric(lap_df[COL_ACCEL_LAT], errors="coerce").values)
    elif COL_SPEED in lap_df.columns:
        v = pd.to_numeric(lap_df[COL_SPEED], errors="coerce").values
        k = np.interp(s, distance, np.abs(kappa), left=0.0, right=0.0)
        ay = np.abs(v * v * k)
    else:
        return corner_start

    mask = (
        np.isfinite(s) & np.isfinite(ay) &
        (s >= corner_start - 20.0) & (s <= corner_apex)
    )
    if not np.any(mask):
        return corner_start

    ay_zone = ay[mask]
    threshold = max(1.0, 0.35 * float(np.nanpercentile(ay_zone, 90)))
    s_zone = s[mask]
    idx = np.where(ay_zone >= threshold)[0]
    if len(idx) == 0:
        return corner_start
    return float(s_zone[idx[0]])


def _interp(x: np.ndarray, y: np.ndarray, x0: float) -> float:
    return float(np.interp(x0, x, y, left=float(y[0]), right=float(y[-1])))


def _integrate_range(
    distance: np.ndarray,
    speed: np.ndarray,
    s_lo: float,
    s_hi: float,
) -> float:
    if s_hi <= s_lo:
        return 0.0

    mask = (distance >= s_lo) & (distance <= s_hi)
    s = distance[mask]
    v = speed[mask]

    if len(s) == 0:
        s = np.array([s_lo, s_hi], dtype=float)
        v = np.array([
            _interp(distance, speed, s_lo),
            _interp(distance, speed, s_hi),
        ], dtype=float)
    else:
        if s[0] > s_lo:
            s = np.insert(s, 0, s_lo)
            v = np.insert(v, 0, _interp(distance, speed, s_lo))
        if s[-1] < s_hi:
            s = np.append(s, s_hi)
            v = np.append(v, _interp(distance, speed, s_hi))

    ds = np.diff(s)
    v_avg = 0.5 * (v[:-1] + v[1:])
    v_avg = np.maximum(v_avg, 0.5)
    return float(np.sum(ds / v_avg))


def _blend_patched_zone_edges(
    distance: np.ndarray,
    base_speed: np.ndarray,
    patched_speed: np.ndarray,
    *,
    zone_start: float,
    zone_end: float,
    blend_m: float,
) -> np.ndarray:
    """
    Smooth transitions at patched zone boundaries to avoid step artifacts.
    """
    out = np.asarray(patched_speed, dtype=float).copy()
    if len(out) != len(distance) or len(out) != len(base_speed):
        return out
    b = float(max(0.0, blend_m))
    if b <= 1e-6 or zone_end <= zone_start:
        return out

    base = np.asarray(base_speed, dtype=float)
    m_start = (distance >= zone_start) & (distance <= zone_start + b)
    if np.any(m_start):
        alpha = np.clip((distance[m_start] - zone_start) / b, 0.0, 1.0)
        out[m_start] = (1.0 - alpha) * base[m_start] + alpha * out[m_start]

    m_end = (distance >= zone_end - b) & (distance <= zone_end)
    if np.any(m_end):
        alpha = np.clip((zone_end - distance[m_end]) / b, 0.0, 1.0)
        out[m_end] = (1.0 - alpha) * base[m_end] + alpha * out[m_end]
    return out


def _window_points_from_distance(distance: np.ndarray, window_m: float) -> int:
    if len(distance) < 3:
        return 1
    ds = np.diff(distance)
    ds = ds[np.isfinite(ds) & (ds > 1e-6)]
    if len(ds) == 0:
        return 1
    mean_ds = float(np.mean(ds))
    pts = int(max(1, round(float(window_m) / max(mean_ds, 1e-6))))
    if pts % 2 == 0:
        pts += 1
    return max(1, pts)


def _smooth_profile_by_distance(
    distance: np.ndarray,
    speed: np.ndarray,
    *,
    window_m: float,
    passes: int,
) -> np.ndarray:
    out = np.asarray(speed, dtype=float).copy()
    if len(out) < 3:
        return out
    w = _window_points_from_distance(distance, window_m)
    if w <= 1:
        return out
    k = np.ones(w, dtype=float) / float(w)
    pad = w // 2
    n_pass = int(max(1, passes))
    for _ in range(n_pass):
        ext = np.pad(out, (pad, pad), mode="edge")
        out = np.convolve(ext, k, mode="valid")
    return out


def _rescale_profile_to_target_lap(
    distance: np.ndarray,
    baseline_speed: np.ndarray,
    reference_speed: np.ndarray,
    target_lap_time_s: float,
    *,
    max_gain_scale: float,
) -> tuple[np.ndarray, float, float]:
    baseline = np.asarray(baseline_speed, dtype=float)
    reference = np.maximum(np.asarray(reference_speed, dtype=float), baseline)
    if len(distance) < 2 or len(reference) != len(distance):
        t = _integrate_range(distance, baseline, float(distance[0]), float(distance[-1])) if len(distance) > 1 else 0.0
        return baseline, float(t), 0.0

    lap_start = float(distance[0])
    lap_end = float(distance[-1])
    t_base = _integrate_range(distance, baseline, lap_start, lap_end)
    if not np.isfinite(target_lap_time_s) or target_lap_time_s <= 1e-6:
        return reference, _integrate_range(distance, reference, lap_start, lap_end), 1.0

    delta = np.clip(reference - baseline, 0.0, None)
    if float(np.nanmax(delta)) <= 1e-9:
        return baseline, t_base, 0.0

    hi = float(max(max_gain_scale, 1e-3))
    lo = 0.0
    t_fast = _integrate_range(distance, baseline + hi * delta, lap_start, lap_end)
    t_slow = t_base
    tgt = float(np.clip(float(target_lap_time_s), min(t_fast, t_slow), max(t_fast, t_slow)))

    for _ in range(36):
        mid = 0.5 * (lo + hi)
        t_mid = _integrate_range(distance, baseline + mid * delta, lap_start, lap_end)
        if t_mid > tgt:
            lo = mid
        else:
            hi = mid

    scale = float(hi)
    out = np.maximum(baseline + scale * delta, 0.5)
    t_out = _integrate_range(distance, out, lap_start, lap_end)
    return out, float(t_out), scale


def _require_columns(df: pd.DataFrame, cols: list[str]) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")
