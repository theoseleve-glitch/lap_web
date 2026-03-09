"""Execution scorer — speed, accel, braking efficiency + granular corner analysis."""
from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np

from scoring.constants import (
    BRAKE_INTENSITY_FULL,
    BRAKE_INTENSITY_ZERO,
    BRAKE_POINT_FULL_M,
    BRAKE_POINT_ZERO_M,
    CORNER_SPD_FULL_RATIO,
    CORNER_SPD_ZERO_RATIO,
    EXEC_ACCEL_FULL_RATIO,
    EXEC_ACCEL_ZERO_RATIO,
    EXEC_BRAKE_FULL_RATIO,
    EXEC_BRAKE_ZERO_RATIO,
    EXEC_GRAN_W_BRAKING,
    EXEC_GRAN_W_CORNER_SPD,
    EXEC_GRAN_W_EXIT,
    EXEC_GRAN_W_LINE,
    EXEC_SPEED_FULL_RATIO,
    EXEC_SPEED_ZERO_RATIO,
    EXEC_W_ACCEL,
    EXEC_W_BRAKE,
    EXEC_W_SPEED,
    EXIT_SPD_FULL_DEFICIT_MPS,
    EXIT_SPD_ZERO_DEFICIT_MPS,
    GRIP_UTIL_FULL_PCT,
    GRIP_UTIL_ZERO_PCT,
    LINE_QUALITY_FULL_CV,
    LINE_QUALITY_ZERO_CV,
    MAX_EXECUTION,
    PHYS_EXEC_ACCEL_FULL_RATIO,
    PHYS_EXEC_ACCEL_ZERO_RATIO,
    PHYS_EXEC_BRAKE_FULL_RATIO,
    PHYS_EXEC_BRAKE_ZERO_RATIO,
    PHYS_EXEC_SPEED_FULL_RATIO,
    PHYS_EXEC_SPEED_ZERO_RATIO,
)
from scoring.helpers import _get, _ratio_score

logger = logging.getLogger(__name__)


def _score_execution(
    m:  dict[str, Any],
    th: dict[str, Any],
    *,
    simulation_method: str = "percentile_envelope",
) -> tuple[float, dict[str, Any]]:
    """
    Score execution quality: speed, accel, and braking efficiency vs theory.

    When *simulation_method* is ``"physics"``, more lenient thresholds are
    used because the theoretical reference is a genuinely achievable limit
    rather than an impossibly optimistic composite.

    Required metric keys
    ~~~~~~~~~~~~~~~~~~~~
    *m*:  ``speed_mean_mps``, ``accel_max_mps2``, ``braking_max_mps2``
    *th*: same keys

    Missing values fall back to partial credit (0.5 ratio).
    """
    is_physics = simulation_method in (
        "physics", "hybrid",
        "kart_envelope_qss", "kart_envelope_casadi",
    )

    # Select threshold set

    if is_physics:
        spd_full,  spd_zero  = PHYS_EXEC_SPEED_FULL_RATIO, PHYS_EXEC_SPEED_ZERO_RATIO
        acc_full,  acc_zero  = PHYS_EXEC_ACCEL_FULL_RATIO, PHYS_EXEC_ACCEL_ZERO_RATIO
        brk_full,  brk_zero  = PHYS_EXEC_BRAKE_FULL_RATIO, PHYS_EXEC_BRAKE_ZERO_RATIO
    else:
        spd_full,  spd_zero  = EXEC_SPEED_FULL_RATIO, EXEC_SPEED_ZERO_RATIO
        acc_full,  acc_zero  = EXEC_ACCEL_FULL_RATIO, EXEC_ACCEL_ZERO_RATIO
        brk_full,  brk_zero  = EXEC_BRAKE_FULL_RATIO, EXEC_BRAKE_ZERO_RATIO

    def _efficiency(key: str, full: float, zero: float) -> float:
        driver = _get(m,  key)
        theory = _get(th, key)
        if math.isnan(driver) or math.isnan(theory) or theory <= 0:
            return 0.5
        ratio = driver / theory
        return _ratio_score(ratio, full, zero, higher_is_better=True)

    spd_r   = _efficiency("speed_mean_mps",   spd_full, spd_zero)
    accel_r = _efficiency("accel_max_mps2",   acc_full, acc_zero)
    brake_r = _efficiency("braking_max_mps2", brk_full, brk_zero)

    composite = (EXEC_W_SPEED * spd_r + EXEC_W_ACCEL * accel_r + EXEC_W_BRAKE * brake_r)
    score     = round(composite * MAX_EXECUTION, 4)

    return score, {
        "speed_efficiency_ratio":   round(spd_r,   4),
        "accel_efficiency_ratio":   round(accel_r,  4),
        "braking_efficiency_ratio": round(brake_r,  4),
        "simulation_method":        simulation_method,
    }


# =============================================================================

# Granular execution scoring (uses corner_analysis data when available)

# =============================================================================


def compute_granular_execution(
    corner_performances: "list[dict[str, Any]] | None" = None,
    lap_metrics: "list[dict[str, Any]] | None" = None,
) -> dict[str, Any]:
    """
    Compute detailed execution sub-scores from corner analysis data.

    When corner analysis data is available, returns granular sub-scores for:
    - braking_quality (brake point accuracy + intensity + trail braking)
    - corner_speed (apex speed ratio + grip utilisation)
    - exit_quality (throttle application + exit speed)
    - line_quality (repeatability of racing line)

    When corner data is NOT available, returns a neutral estimate based on
    whatever lap-level metrics exist.

    Parameters -- corner_performances:
        List of ``CornerPerformance.to_dict()`` results.
    lap_metrics:
        Per-lap metric dicts with speed/accel features.

    Returns -- -
    dict
        ``composite`` (float 0-1), plus individual sub-scores and detail.
    """
    result: dict[str, Any] = {
        "composite": 0.5,
        "braking_quality": 0.5,
        "corner_speed": 0.5,
        "exit_quality": 0.5,
        "line_quality": 0.5,
        "has_corner_data": False,
        "detail": {},
    }

    if not corner_performances:
        return result

    result["has_corner_data"] = True
    n = len(corner_performances)
    if n == 0:
        return result

    # --- Braking quality -
    bp_deltas = []
    grip_utils = []
    for cp in corner_performances:
        delta_m = cp.get("braking_point_delta_m", 0.0)
        if isinstance(delta_m, (int, float)) and math.isfinite(delta_m):
            bp_deltas.append(abs(delta_m))

        grip = cp.get("grip_utilisation_pct", 0.0)
        if isinstance(grip, (int, float)) and grip > 0:
            grip_utils.append(grip)

    if bp_deltas:
        mean_bp_delta = float(np.mean(bp_deltas))
        brake_point_score = _ratio_score(
            mean_bp_delta, BRAKE_POINT_FULL_M, BRAKE_POINT_ZERO_M,
            higher_is_better=False,
        )
    else:
        brake_point_score = 0.5
        mean_bp_delta = float("nan")

    result["braking_quality"] = round(brake_point_score, 4)
    result["detail"]["mean_bp_delta_m"] = (
        round(mean_bp_delta, 1) if math.isfinite(mean_bp_delta) else None
    )

    # --- Corner speed / grip utilisation -
    apex_ratios = []
    for cp in corner_performances:
        theo_apex = cp.get("theoretical_apex_speed_mps", 0.0)
        actual_apex = cp.get("actual_apex_speed_mps", 0.0)
        if (isinstance(theo_apex, (int, float)) and theo_apex > 1.0
                and isinstance(actual_apex, (int, float)) and actual_apex > 0):
            apex_ratios.append(actual_apex / theo_apex)

    if apex_ratios:
        mean_apex_ratio = float(np.mean(apex_ratios))
        apex_score = _ratio_score(
            mean_apex_ratio, CORNER_SPD_FULL_RATIO, CORNER_SPD_ZERO_RATIO,
            higher_is_better=True,
        )
    else:
        apex_score = 0.5
        mean_apex_ratio = float("nan")

    if grip_utils:
        mean_grip = float(np.mean(grip_utils))
        grip_score = _ratio_score(
            mean_grip, GRIP_UTIL_FULL_PCT, GRIP_UTIL_ZERO_PCT,
            higher_is_better=True,
        )
    else:
        grip_score = 0.5
        mean_grip = float("nan")

    # Corner speed = blend of apex ratio and grip utilisation

    corner_spd_score = 0.6 * apex_score + 0.4 * grip_score
    result["corner_speed"] = round(corner_spd_score, 4)
    result["detail"]["mean_apex_speed_ratio"] = (
        round(mean_apex_ratio, 4) if math.isfinite(mean_apex_ratio) else None
    )
    result["detail"]["mean_grip_utilisation_pct"] = (
        round(mean_grip, 1) if math.isfinite(mean_grip) else None
    )

    # --- Exit / throttle quality -
    exit_deficits = []
    for cp in corner_performances:
        theo_exit = cp.get("theoretical_exit_speed_mps", 0.0)
        actual_exit = cp.get("actual_exit_speed_mps", 0.0)
        if (isinstance(theo_exit, (int, float)) and theo_exit > 1.0
                and isinstance(actual_exit, (int, float)) and actual_exit > 0):
            deficit = theo_exit - actual_exit
            exit_deficits.append(max(0.0, deficit))

    if exit_deficits:
        mean_exit_deficit = float(np.mean(exit_deficits))
        exit_score = _ratio_score(
            mean_exit_deficit, EXIT_SPD_FULL_DEFICIT_MPS, EXIT_SPD_ZERO_DEFICIT_MPS,
            higher_is_better=False,
        )
    else:
        exit_score = 0.5
        mean_exit_deficit = float("nan")

    result["exit_quality"] = round(exit_score, 4)
    result["detail"]["mean_exit_speed_deficit_mps"] = (
        round(mean_exit_deficit, 2) if math.isfinite(mean_exit_deficit) else None
    )

    # --- Line quality (repeatability) -
    # Use time-loss variance across corners as proxy for line consistency

    time_losses = [
        cp.get("time_loss_s", 0.0) for cp in corner_performances
        if isinstance(cp.get("time_loss_s"), (int, float))
           and math.isfinite(cp.get("time_loss_s", float("nan")))
    ]
    if len(time_losses) >= 3:
        loss_arr = np.array(time_losses)
        loss_mean = float(loss_arr.mean())
        if loss_mean > 0.001:
            loss_cv = float(loss_arr.std() / loss_mean)
        else:
            loss_cv = 0.0
        line_score = _ratio_score(
            loss_cv, LINE_QUALITY_FULL_CV, LINE_QUALITY_ZERO_CV,
            higher_is_better=False,
        )
    else:
        line_score = 0.5
        loss_cv = float("nan")

    result["line_quality"] = round(line_score, 4)
    result["detail"]["time_loss_cv"] = (
        round(loss_cv, 4) if math.isfinite(loss_cv) else None
    )

    # --- Composite -
    composite = (
        EXEC_GRAN_W_BRAKING * result["braking_quality"]
        + EXEC_GRAN_W_CORNER_SPD * result["corner_speed"]
        + EXEC_GRAN_W_EXIT * result["exit_quality"]
        + EXEC_GRAN_W_LINE * result["line_quality"]
    )
    result["composite"] = round(composite, 4)

    logger.info(
        "Granular execution: braking=%.3f, corner_spd=%.3f, "
        "exit=%.3f, line=%.3f, composite=%.3f",
        result["braking_quality"], result["corner_speed"],
        result["exit_quality"], result["line_quality"], composite,
    )
    return result


def enhance_execution_with_controls(
    base_result: dict[str, Any],
    controls_analysis: "dict[int, list[dict]] | None" = None,
) -> dict[str, Any]:
    """Enhance granular execution score using real brake/throttle/steering data.

    When controls data is available from Tier 2+ adapters, this replaces the
    accel-proxy-based braking and exit quality scores with direct pedal-trace
    measurements for higher accuracy.

    Parameters
    ----------
    base_result:
        Output from ``compute_granular_execution()``.
    controls_analysis:
        Per-lap controls analysis from ``controls_physics.analyze_corners_with_controls()``.
        Keys are lap numbers, values are lists of enriched corner dicts.

    Returns the base_result dict with updated scores and a ``controls_enhanced`` flag.
    """
    if not controls_analysis:
        return base_result

    # Aggregate controls metrics across all laps
    trail_brake_pcts: list[float] = []
    brake_modulation_scores: list[float] = []
    throttle_rates: list[float] = []
    coasting_m_total = 0.0
    steering_smoothness_scores: list[float] = []

    for _lap_num, corners in controls_analysis.items():
        for c in corners:
            # Trail braking
            tb = c.get("trail_brake_pct")
            if isinstance(tb, (int, float)) and math.isfinite(tb):
                trail_brake_pcts.append(tb)
            # Brake modulation
            bm = c.get("brake_modulation_score")
            if isinstance(bm, (int, float)) and math.isfinite(bm):
                brake_modulation_scores.append(bm)
            # Throttle application rate
            tar = c.get("exit_application_rate")
            if isinstance(tar, (int, float)) and math.isfinite(tar):
                throttle_rates.append(tar)
            # Coasting
            cz = c.get("coasting_zones")
            if isinstance(cz, list):
                for zone in cz:
                    coasting_m_total += zone.get("duration_m", 0.0)
            # Steering smoothness
            ss = c.get("steering_smoothness")
            if isinstance(ss, (int, float)) and math.isfinite(ss):
                steering_smoothness_scores.append(ss)

    enhanced = False

    # Enhance braking quality with trail braking data
    if trail_brake_pcts:
        mean_trail = float(np.mean(trail_brake_pcts))
        # Good trail braking = 30-70% of corner has simultaneous brake+steer
        # Score: 0 at 0%, peaks at 50%, drops above 80% (excessive overlap)
        if mean_trail <= 50:
            trail_score = min(1.0, mean_trail / 50.0)
        else:
            trail_score = max(0.0, 1.0 - (mean_trail - 50) / 50.0)

        # Blend: 60% trail braking + 40% original brake point accuracy
        old_braking = base_result.get("braking_quality", 0.5)
        base_result["braking_quality"] = round(
            0.6 * trail_score + 0.4 * old_braking, 4,
        )
        base_result["detail"]["mean_trail_brake_pct"] = round(mean_trail, 1)
        enhanced = True

    # Enhance exit quality with throttle application data
    if throttle_rates:
        mean_rate = float(np.mean(throttle_rates))
        # Good exit: progressive but confident throttle (1-5 pct/m)
        if mean_rate <= 0:
            throttle_score = 0.0
        elif mean_rate <= 5.0:
            throttle_score = min(1.0, mean_rate / 3.0)
        else:
            throttle_score = max(0.3, 1.0 - (mean_rate - 5.0) / 10.0)

        old_exit = base_result.get("exit_quality", 0.5)
        base_result["exit_quality"] = round(
            0.5 * throttle_score + 0.5 * old_exit, 4,
        )
        base_result["detail"]["mean_throttle_rate_pct_per_m"] = round(mean_rate, 2)
        enhanced = True

    # Steering smoothness bonus
    if steering_smoothness_scores:
        mean_smooth = float(np.mean(steering_smoothness_scores))
        old_line = base_result.get("line_quality", 0.5)
        base_result["line_quality"] = round(
            0.4 * mean_smooth + 0.6 * old_line, 4,
        )
        base_result["detail"]["mean_steering_smoothness"] = round(mean_smooth, 3)
        enhanced = True

    if enhanced:
        # Recompute composite
        composite = (
            EXEC_GRAN_W_BRAKING * base_result["braking_quality"]
            + EXEC_GRAN_W_CORNER_SPD * base_result["corner_speed"]
            + EXEC_GRAN_W_EXIT * base_result["exit_quality"]
            + EXEC_GRAN_W_LINE * base_result["line_quality"]
        )
        base_result["composite"] = round(composite, 4)
        base_result["controls_enhanced"] = True
        logger.info(
            "Controls-enhanced execution: braking=%.3f, exit=%.3f, "
            "line=%.3f, composite=%.3f",
            base_result["braking_quality"], base_result["exit_quality"],
            base_result["line_quality"], composite,
        )

    return base_result
