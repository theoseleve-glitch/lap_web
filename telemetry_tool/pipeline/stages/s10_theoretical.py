"""
Stage 10 — Theoretical Lap Computation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Cascading theoretical-lap solver:
  Priority 0: kart_envelope solver (via theoretical_adapter)
  Priority 1: Hybrid physics simulation (via lap_simulation)
  Priority 2: Adaptive percentile envelope (via theoretical_engine)

After the theoretical lap is computed, follow-up sub-steps extract
metrics, run plausibility cross-validation, compute confidence
assessment, and invoke the unified optimal solver.
"""
from __future__ import annotations

import logging
import math
import os
from typing import Any, Optional

import numpy as np
import pandas as pd

from pipeline.helpers import (
    _COL_DIST,
    _COL_SPEED,
    lazy_import,
    theoretical_metrics_from_lap,
)

logger = logging.getLogger(__name__)


# ── Step 10: Theoretical lap ───────────────────────────────────────────


def run_theoretical(
    resampled_laps: dict[int, pd.DataFrame],
    curvature_profile: Optional[pd.DataFrame],
    friction_circle: Any,
    vehicle_params: Any,
    data_quality_rpt: Any,
    valid_times: Optional[list[tuple[int, float]]],
    *,
    channel_discovery: Any = None,
    n_resample_points: int = 1000,
    best_n_lap_indices: Optional[list[int]] = None,
    excluded_laps: frozenset[int] = frozenset(),
    inclusion_policy: Any = None,
    clustering_result: Any = None,
    phases_df: Optional[pd.DataFrame] = None,
    lap_to_phase: Optional[dict[int, int]] = None,
    grip_map: Any = None,
    friction_envelope: Any = None,
    distance_quality: Any = None,
) -> tuple[
    Optional[pd.DataFrame],  # theoretical_lap
    str,                      # sim_method
    Any,                      # sim_result
    Optional[list[dict]],     # corner_coaching
    Optional[pd.DataFrame],   # delta_map
    Optional[dict[str, Any]], # session_scalars
    Optional[list],           # laps_for_theo_ref
]:
    """Run theoretical lap computation.

    Returns
    -------
    (theoretical_lap_df, sim_method, sim_result, corner_coaching,
     delta_map, session_scalars, laps_for_theo_ref)
    """
    sim_method: str = "none"
    sim_result: Any = None
    corner_coaching: Optional[list[dict[str, Any]]] = None
    delta_map: Optional[pd.DataFrame] = None
    session_scalars: Optional[dict[str, Any]] = None
    laps_for_theo_ref: Optional[list] = None

    # Gate: skip when distance quality is degraded
    if (
        distance_quality is not None
        and hasattr(distance_quality, "gate_advanced")
        and distance_quality.gate_advanced
    ):
        logger.warning(
            "Theoretical lap SKIPPED: distance quality gate active (status=%s).",
            getattr(distance_quality, "status", "unknown"),
        )
        return None, sim_method, sim_result, corner_coaching, delta_map, session_scalars, None

    best_driver_time = float("inf")
    if valid_times:
        best_driver_time = min(t for _, t in valid_times)

    # ── Priority 0: kart_envelope solver ──────────────────────────
    try:
        adapter_mod = lazy_import("theoretical_adapter")
        if adapter_mod is not None:
            adapter_result = adapter_mod.compute_theoretical_via_envelope(
                resampled_laps,
                curvature_profile,
                vehicle_params,
                data_quality_rpt,
                best_driver_time_s=(
                    best_driver_time if math.isfinite(best_driver_time) else None
                ),
            )
            sim_method = adapter_result.method
            sim_result = adapter_result.theoretical_result
            corner_coaching = adapter_result.corner_coaching
            delta_map = adapter_result.delta_map
            if adapter_result.session_scalars is not None:
                sc = adapter_result.session_scalars
                session_scalars = {
                    "mu": round(sc.mu_session, 4),
                    "p": round(sc.p_session, 4),
                    "b": round(sc.b_session, 4),
                    "confidence": round(sc.confidence, 4),
                    "condition_label": sc.condition_label,
                }
            logger.info(
                "kart_envelope solver [%s]: %.2fs (driver best %.2fs).",
                adapter_result.method,
                adapter_result.theoretical_result.lap_time_s
                if adapter_result.theoretical_result
                else float("nan"),
                best_driver_time,
            )
            return (
                adapter_result.theoretical_df,
                sim_method,
                sim_result,
                corner_coaching,
                delta_map,
                session_scalars,
                None,
            )
    except Exception as exc:
        logger.warning(
            "kart_envelope adapter failed: %s — falling back to legacy engines.",
            exc,
        )

    # ── Priority 1: Hybrid physics simulation ─────────────────────
    sim_mod = lazy_import("lap_simulation")
    if sim_mod is not None:
        try:
            grade_prof = None
            if curvature_profile is not None and "grade" in curvature_profile.columns:
                grade_vals = curvature_profile["grade"].values
                if np.isfinite(grade_vals).sum() > 10:
                    grade_prof = grade_vals

            rr = vehicle_params.rolling_resistance_est if vehicle_params else 0.015
            aero = vehicle_params.aero_drag_factor_est if vehicle_params else 0.0

            sp_pct = 98.0
            if data_quality_rpt is not None:
                sp_pct = data_quality_rpt.recommended_speed_percentile

            result = sim_mod.simulate_with_fallback(
                resampled_laps,
                curvature_profile,
                friction_circle,
                driver_best_time_s=(
                    best_driver_time if math.isfinite(best_driver_time) else None
                ),
                grade_profile=grade_prof,
                rolling_resistance=rr,
                aero_drag_factor=aero,
                speed_percentile=sp_pct,
                grip_map=grip_map,
                friction_envelope=friction_envelope,
            )
            sim_method = result.method
            sim_result = result
            logger.info(
                "Simulation [%s]: %.2fs (driver best %.2fs, ratio %.1f%%).",
                result.method,
                result.lap_time_s,
                best_driver_time,
                (
                    result.lap_time_s / best_driver_time * 100
                    if math.isfinite(best_driver_time) and best_driver_time > 0
                    else float("nan")
                ),
            )
            theo_df = sim_mod.result_to_theoretical_df(result)
            return (theo_df, sim_method, sim_result, corner_coaching, delta_map, session_scalars, None)
        except Exception as exc:
            logger.warning(
                "Simulation (with fallback) failed: %s — "
                "falling back to percentile envelope via theoretical_engine.",
                exc,
            )

    # ── Priority 2: Adaptive percentile envelope ──────────────────
    theo_mod = lazy_import("theoretical_engine")
    if theo_mod is None:
        raise ImportError(
            "No simulation method available: both lap_simulation and "
            "theoretical_engine are unavailable."
        )

    sorted_keys = sorted(resampled_laps.keys())

    # Apply channel discovery transforms
    if channel_discovery is not None:
        try:
            cd_mod = lazy_import("channel_discovery")
            apply_fn = getattr(cd_mod, "apply_discovery", None) if cd_mod else None
        except Exception:
            apply_fn = None
        if apply_fn is not None:
            laps_list = [apply_fn(resampled_laps[k], channel_discovery) for k in sorted_keys]
        else:
            laps_list = [resampled_laps[k] for k in sorted_keys]
    else:
        laps_list = [resampled_laps[k] for k in sorted_keys]

    # Pre-filter to best-N% laps
    if best_n_lap_indices:
        laps_for_theo = [
            laps_list[i]
            for i in best_n_lap_indices
            if i < len(laps_list) and sorted_keys[i] not in excluded_laps
        ]
        keys_for_theo = [
            sorted_keys[i]
            for i in best_n_lap_indices
            if i < len(sorted_keys) and sorted_keys[i] not in excluded_laps
        ]
        logger.info(
            "Theoretical envelope: using %d best-N%% laps (out of %d total).",
            len(laps_for_theo),
            len(laps_list),
        )
    else:
        laps_for_theo = laps_list
        keys_for_theo = sorted_keys

    # Filter by inclusion policy
    if inclusion_policy is not None and hasattr(inclusion_policy, "learning_laps"):
        learning_set = set(inclusion_policy.learning_laps)
        filtered = [
            (lap, key)
            for lap, key in zip(laps_for_theo, keys_for_theo)
            if key in learning_set
        ]
        if len(filtered) >= 3:
            laps_for_theo = [x[0] for x in filtered]
            keys_for_theo = [x[1] for x in filtered]
            logger.info(
                "Theoretical envelope: filtered to %d learning laps "
                "(excluded %d by inclusion policy).",
                len(laps_for_theo),
                len(sorted_keys) - len(laps_for_theo),
            )
        else:
            logger.warning(
                "Inclusion policy leaves only %d laps — using all %d.",
                len(filtered),
                len(laps_for_theo),
            )

    # Filter by selected cluster
    if clustering_result is not None and not clustering_result.fallback:
        selected = [
            c
            for c in clustering_result.clusters
            if c.cluster_id == clustering_result.selected_cluster_id
        ]
        if selected:
            cluster_laps = set(selected[0].lap_numbers)
            cluster_filtered = [
                (lap, key)
                for lap, key in zip(laps_for_theo, keys_for_theo)
                if key in cluster_laps
            ]
            if len(cluster_filtered) >= 3:
                laps_for_theo = [x[0] for x in cluster_filtered]
                keys_for_theo = [x[1] for x in cluster_filtered]
                logger.info(
                    "Theoretical envelope: filtered to %d laps from cluster %d (purity=%.2f).",
                    len(laps_for_theo),
                    clustering_result.selected_cluster_id,
                    clustering_result.purity_score,
                )
            else:
                logger.warning(
                    "Cluster filtering leaves only %d laps — using all %d learning laps.",
                    len(cluster_filtered),
                    len(laps_for_theo),
                )

    # Adaptive percentile from data quality
    speed_pct = 98.0
    accel_pct = 99.0
    if data_quality_rpt is not None:
        speed_pct = data_quality_rpt.recommended_speed_percentile
        accel_pct = data_quality_rpt.recommended_accel_percentile

    # Traffic masks
    traffic_masks = (
        inclusion_policy.traffic_masks
        if inclusion_policy is not None and hasattr(inclusion_policy, "traffic_masks")
        else None
    )

    # Phase-aware variant
    if hasattr(theo_mod, "build_theoretical_lap_phase_aware") and phases_df is not None:
        sim_method = "percentile_envelope_phase_aware"
        laps_for_theo_ref = laps_for_theo
        theo_df = theo_mod.build_theoretical_lap_phase_aware(
            laps_for_theo,
            phases_df=phases_df,
            lap_to_phase=lap_to_phase,
            n_points=n_resample_points,
            lap_keys=keys_for_theo,
            speed_percentile=speed_pct,
            accel_percentile=accel_pct,
            masks=traffic_masks,
        )
        return (theo_df, sim_method, sim_result, corner_coaching, delta_map, session_scalars, laps_for_theo)

    # Standard adaptive percentile
    sim_method = "percentile_envelope"
    laps_for_theo_ref = laps_for_theo

    try:
        theo_df = theo_mod.build_theoretical_lap(
            laps_for_theo,
            n_points=n_resample_points,
            speed_percentile=speed_pct,
            accel_percentile=accel_pct,
            masks=traffic_masks,
        )
    except TypeError:
        # Older theoretical_engine without percentile/masks kwargs
        theo_df = theo_mod.build_theoretical_lap(
            laps_for_theo,
            n_points=n_resample_points,
        )

    return (theo_df, sim_method, sim_result, corner_coaching, delta_map, session_scalars, laps_for_theo)


# ── Step 10a: Theoretical metrics ──────────────────────────────────────


def run_theoretical_metrics(
    theoretical_lap: Optional[pd.DataFrame],
    sim_method: str,
    sim_result: Any,
    data_quality_rpt: Any,
) -> dict[str, Any]:
    """Extract scalar metrics from the theoretical lap.

    Uses :func:`pipeline.helpers.theoretical_metrics_from_lap`.
    """
    if theoretical_lap is None:
        raise ValueError("No theoretical lap from step 10 -- cannot compute metrics.")
    return theoretical_metrics_from_lap(
        theoretical_lap,
        simulation_method=sim_method,
        sim_result=sim_result,
        data_quality=data_quality_rpt,
    )


# ── Step 10b-i: Plausibility cross-validation ─────────────────────────


def run_plausibility(
    theoretical_lap: Optional[pd.DataFrame],
    laps_for_theo: Optional[list[pd.DataFrame]],
) -> Any:
    """Cross-validate theoretical lap against a hold-out set.

    Returns a plausibility result object, or ``None`` if unavailable.
    """
    theo_mod = lazy_import("theoretical_engine")
    if theoretical_lap is None or theo_mod is None:
        return None
    if not hasattr(theo_mod, "split_laps_train_holdout"):
        return None
    if not hasattr(theo_mod, "compute_theoretical_plausibility"):
        return None
    if laps_for_theo is None or len(laps_for_theo) < 4:
        return None

    _, holdout, _ = theo_mod.split_laps_train_holdout(laps_for_theo)
    if not holdout:
        return None

    return theo_mod.compute_theoretical_plausibility(theoretical_lap, holdout)


# ── Step 10b-ii: Confidence assessment ─────────────────────────────────


def run_confidence(
    *,
    resampled_laps: dict[int, pd.DataFrame],
    sim_method: Optional[str],
    data_quality_rpt: Any,
    distance_quality: Any,
    inclusion_policy: Any,
    clustering_result: Any,
    curvature_quality: Optional[dict[str, Any]],
    sensor_fusion: Optional[dict[str, Any]],
    plausibility: Any = None,
    theo_metrics: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    """Compute confidence assessment for the theoretical lap.

    Returns a confidence dict (with optional plausibility penalty applied),
    or ``None`` if the confidence module is unavailable.
    """
    conf_mod = lazy_import("confidence")
    if conf_mod is None:
        return None

    # Gather inputs
    n_learn = 0
    if inclusion_policy is not None:
        n_learn = len(inclusion_policy.learning_laps)
    else:
        n_learn = len(resampled_laps)

    dq_conf = 0.5
    if data_quality_rpt is not None:
        dq_conf = data_quality_rpt.overall_confidence

    dist_status = "good"
    if distance_quality is not None:
        if isinstance(distance_quality, dict):
            dist_status = distance_quality.get("status", "good")
        elif hasattr(distance_quality, "status"):
            dist_status = distance_quality.status

    c_purity = 1.0
    if clustering_result is not None:
        c_purity = clustering_result.purity_score

    ch_cov = 0.5
    if data_quality_rpt is not None:
        ch_cov = max(data_quality_rpt.gps_quality, data_quality_rpt.accel_quality)

    solver = sim_method or "percentile_envelope"

    curv_rel = 0.5
    if curvature_quality and isinstance(curvature_quality, dict):
        curv_rel = curvature_quality.get("quality_score", 0.5)

    fuse_conf = -1.0
    if sensor_fusion and isinstance(sensor_fusion, dict):
        fuse_conf = sensor_fusion.get("confidence", -1.0)

    confidence = conf_mod.compute_confidence(
        n_learning_laps=n_learn,
        data_quality_confidence=dq_conf,
        distance_quality_status=dist_status,
        cluster_purity=c_purity,
        channel_coverage=ch_cov,
        solver_method=solver,
        curvature_reliability=curv_rel,
        fusion_confidence=fuse_conf,
    )

    if confidence is None:
        return None

    conf_dict = confidence.to_dict()

    # Inject plausibility penalty if overfit suspected
    if plausibility is not None and plausibility.overfit_suspected:
        reasons = conf_dict.get("confidence_reasons", [])
        reasons.insert(0, "overfit_suspected: theoretical may be unreachable")
        conf_dict["confidence_reasons"] = reasons
        raw_score = conf_dict.get("confidence_score", 100)
        penalized = int(raw_score * plausibility.plausibility_score)
        conf_dict["confidence_score"] = max(0, penalized)
        if penalized >= 75:
            conf_dict["confidence_level"] = "high"
        elif penalized >= 45:
            conf_dict["confidence_level"] = "medium"
        else:
            conf_dict["confidence_level"] = "low"

    return conf_dict


# ── Step 10b-iii: Unified optimal solver ───────────────────────────────


def run_optimal_v2(
    theoretical_lap: Optional[pd.DataFrame],
    resampled_laps: dict[int, pd.DataFrame],
    curvature_profile: Optional[pd.DataFrame],
    grip_map: Any,
    *,
    speed_pct: float = 98.0,
    corners: Optional[list[dict[str, Any]]] = None,
) -> Optional[dict[str, Any]]:
    """Run the unified optimal solver (feature-flagged by ``OPTIMAL_V2``).

    Returns a dict with optimal results (including optional corner
    saturation and coaching labels), or ``None`` if skipped / unavailable.
    """
    if os.environ.get("OPTIMAL_V2", "0") not in ("1", "true", "yes"):
        return None

    opt_mod = lazy_import("optimal_solver")
    if opt_mod is None:
        return None
    if theoretical_lap is None:
        return None

    theo_mod = lazy_import("theoretical_engine")

    # Build OptimalCaps from percentile envelope
    caps = None
    if theo_mod is not None and resampled_laps:
        try:
            curv_arr = np.zeros(len(theoretical_lap))
            if (
                curvature_profile is not None
                and "curvature_1pm" in curvature_profile.columns
            ):
                cp_dist = curvature_profile["distance_m"].values
                cp_curv = curvature_profile["curvature_1pm"].values
                theo_dist = theoretical_lap["distance_m"].values
                curv_arr = np.interp(theo_dist, cp_dist, cp_curv)

            laps_list = [resampled_laps[k] for k in sorted(resampled_laps.keys())]
            if hasattr(theo_mod, "caps_from_percentile_envelope"):
                caps = theo_mod.caps_from_percentile_envelope(
                    laps_list,
                    curv_arr,
                    speed_percentile=speed_pct,
                )
        except Exception as exc:
            logger.debug("caps_from_percentile_envelope failed: %s", exc)

    if caps is None:
        return None

    # Apply grip map override
    if grip_map is not None and not grip_map.is_global_fallback and caps.mu is None:
        mu_arr = np.array(
            [grip_map.mu_at(float(d), "p95") for d in caps.distance_m]
        )
        caps.mu = mu_arr

    # Try solve with uncertainty bands first
    result_with_bands = None
    if hasattr(theo_mod, "caps_from_percentile_envelope_with_bands"):
        try:
            caps_nom, caps_low, caps_high = (
                theo_mod.caps_from_percentile_envelope_with_bands(
                    laps_list,
                    curv_arr,
                    speed_percentile=speed_pct,
                )
            )
            for c in (caps_nom, caps_low, caps_high):
                if grip_map is not None and not grip_map.is_global_fallback and c.mu is None:
                    c.mu = np.array(
                        [grip_map.mu_at(float(d), "p95") for d in c.distance_m]
                    )
            result_with_bands = opt_mod.solve_optimal_speed_with_bands(
                caps_nom,
                caps_low,
                caps_high,
            )
        except Exception as exc:
            logger.debug("solve_optimal_speed_with_bands failed: %s", exc)

    optimal_result = result_with_bands if result_with_bands is not None else opt_mod.solve_optimal_speed(caps)

    if optimal_result is None:
        return None

    output = optimal_result.to_dict()

    # Corner saturation
    if corners and hasattr(opt_mod, "compute_corner_saturation"):
        try:
            corner_dicts = [
                c if isinstance(c, dict) else c.to_dict() for c in corners
            ]
            sats = opt_mod.compute_corner_saturation(optimal_result, corner_dicts)
            output["corner_saturation"] = [s.to_dict() for s in sats]
        except Exception:
            logger.debug("Corner saturation failed", exc_info=True)

    # Corner coaching labels
    ca_mod = lazy_import("corner_analysis")
    if ca_mod is not None and corners and hasattr(ca_mod, "compute_corner_coaching_labels"):
        try:
            corner_dicts = [
                c if isinstance(c, dict) else c.to_dict() for c in corners
            ]
            coaching_labels = ca_mod.compute_corner_coaching_labels(
                corners=corner_dicts,
                limiting_factors=optimal_result.limiting_factor,
                distance_m=optimal_result.distance_m,
                lap_length_m=float(optimal_result.distance_m[-1]),
            )
            output["corner_coaching_labels"] = coaching_labels
        except Exception:
            logger.debug("Corner coaching labels failed", exc_info=True)

    return output


# ── Step 10c: Queue OCP theoretical (background) ─────────────────────


def queue_ocp_theoretical(
    session_id: int | str | None,
    workspace_id: int | None,
) -> Optional[str]:
    """Queue the OCP solver as a background Celery task.

    Returns the Celery task ID, or None if skipped.
    Non-blocking — the pipeline continues immediately.
    """
    if session_id is None:
        return None
    if os.environ.get("THEORETICAL_OCP", "1") in ("0", "false", "no"):
        return None

    try:
        from tasks.ocp_tasks import run_ocp_for_session

        # Use .delay() for async Celery dispatch if available
        if hasattr(run_ocp_for_session, "delay"):
            task = run_ocp_for_session.delay(session_id, workspace_id)
            logger.info("OCP task queued for session %s: task_id=%s", session_id, task.id)
            return str(task.id)

        # Fallback: run synchronously (local dev without Celery)
        logger.info("OCP running synchronously for session %s (no Celery)", session_id)
        run_ocp_for_session(session_id, workspace_id)
        return "direct"
    except Exception:
        logger.debug("OCP theoretical queuing failed", exc_info=True)
        return None
