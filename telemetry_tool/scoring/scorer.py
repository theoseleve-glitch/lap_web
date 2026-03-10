"""Main session scorer — assembles sub-scores into a structured result."""
from __future__ import annotations

import logging
import math
from typing import Any

from scoring.consistency import _score_consistency
from scoring.constants import (
    _SESSION_CATEGORY_CONFIG,
    _SESSION_TYPE_SYNONYMS,
    _SESSION_WEIGHT_OVERRIDES,
    _TRACK_STATE_MODIFIERS,
    ADAPT_V2_STABLE_DEFAULT_FRAC,
    DR_COMBINED_FLOOR,
    DR_EXP_FLOOR,
    DR_EXP_K,
    DR_EXP_L0,
    DR_SES_FLOOR,
    DR_SES_K,
    DR_SES_L0,
    MAX_ADAPTATION,
    MAX_CONSISTENCY,
    MAX_EXECUTION,
    MAX_PACE,
    MAX_ROBUSTNESS,
    STRENGTH_THRESHOLD,
    TOTAL_MAX,
    WEAKNESS_THRESHOLD,
)
from scoring.execution import (
    _score_execution,
    compute_granular_execution,
    enhance_execution_with_controls,
)
from scoring.helpers import (
    _apply_confidence,
    _assign_grade,
    _normalize_session_type,
)
from scoring.pace import _score_pace
from scoring.robustness import _score_robustness

logger = logging.getLogger(__name__)

_BASE_MAXES: dict[str, float] = {
    "pace":        MAX_PACE,
    "consistency": MAX_CONSISTENCY,
    "execution":   MAX_EXECUTION,
    "robustness":  MAX_ROBUSTNESS,
    "adaptation":  MAX_ADAPTATION,
}


def _apply_adaptive_weights(
    raw_scores: dict[str, float],
    session_type: str,
    *,
    track_state: str = "dry",
) -> tuple[dict[str, float], dict[str, float]]:
    """
    Apply 3-layer adaptive weighting: suppression, track-state, normalize.

    Returns (rescaled_scores, effective_maxes) where effective_maxes sum to 100.
    Suppressed categories get score=0 and max=0.
    """
    stype = _normalize_session_type(session_type)
    stype = _SESSION_TYPE_SYNONYMS.get(stype, stype)
    config = _SESSION_CATEGORY_CONFIG.get(stype, {"suppressed": set(), "emphasis": {}})

    suppressed = config["suppressed"]
    emphasis = config["emphasis"]

    # Layer 1: Suppress + emphasize
    adjusted_max: dict[str, float] = {}
    for cat, base in _BASE_MAXES.items():
        if cat in suppressed:
            adjusted_max[cat] = 0.0
        else:
            adjusted_max[cat] = base * emphasis.get(cat, 1.0)

    # Layer 2: Track-state modifiers (only on surviving categories)
    ts_key = track_state.lower().strip() if track_state else "dry"
    ts_mods = _TRACK_STATE_MODIFIERS.get(ts_key, {})
    for cat in adjusted_max:
        if adjusted_max[cat] > 0 and cat in ts_mods:
            adjusted_max[cat] *= ts_mods[cat]

    # Normalize so surviving categories sum to TOTAL_MAX
    total_adjusted = sum(adjusted_max.values())
    if total_adjusted > 0:
        scale = TOTAL_MAX / total_adjusted
        norm_max = {cat: round(v * scale, 4) for cat, v in adjusted_max.items()}
    else:
        norm_max = {cat: 0.0 for cat in _BASE_MAXES}

    # Scale raw scores
    rescaled: dict[str, float] = {}
    for cat, raw in raw_scores.items():
        if cat in suppressed or _BASE_MAXES.get(cat, 0) == 0:
            rescaled[cat] = 0.0
        else:
            fraction = raw / _BASE_MAXES[cat]
            rescaled[cat] = round(fraction * norm_max.get(cat, 0.0), 4)

    return rescaled, norm_max


def _apply_session_weights(
    raw_scores: dict[str, float],
    session_type: str,
) -> dict[str, float]:
    """
    Backward-compatible wrapper around _apply_adaptive_weights.

    Returns only the rescaled scores dict (not the maxes).
    """
    rescaled, _ = _apply_adaptive_weights(raw_scores, session_type)
    return rescaled


def _compute_dr_multiplier(
    total_laps: int = 0,
    session_laps: int = 0,
) -> float:
    """
    Compute a gentle diminishing-returns multiplier.

    Two independent factors stacked multiplicatively:
    - experience_factor: based on driver's lifetime total laps
    - session_factor: based on number of laps in this session

    Both use asymptotic log curves with per-factor and combined floors.
    Returns a value in [DR_COMBINED_FLOOR, 1.0].
    """
    if total_laps <= 0 and session_laps <= 0:
        return 1.0

    exp_factor = max(
        DR_EXP_FLOOR,
        1.0 - DR_EXP_K * math.log(1.0 + max(0, total_laps) / DR_EXP_L0),
    )
    ses_factor = max(
        DR_SES_FLOOR,
        1.0 - DR_SES_K * math.log(1.0 + max(0, session_laps) / DR_SES_L0),
    )
    return max(DR_COMBINED_FLOOR, exp_factor * ses_factor)


def score_session(
    metrics_dict:         dict[str, Any],
    theoretical_metrics:  dict[str, Any],
    session_type:         str = "practice",
    *,
    is_wet:               bool = False,
    track_state:          str = "dry",
    driver_total_laps:    int = 0,
    corner_coaching:      list[dict[str, Any]] | None = None,
    progressive_physics:  dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Compute a structured performance score for a driver session.

    Parameters -- metrics_dict:
        Observed metrics dict for the session.  Expected keys (all optional --  missing values degrade gracefully to partial credit):

        From ``features.compute_lap_time`` / ``compute_consistency_metrics``:
            ``best_s`` -- best lap time [s]
            ``n_laps`` -- number of laps
            ``cv_pct`` -- coefficient of variation [%]
            ``best_to_median_s`` -- gap best -- median [s]

        From ``features.compute_speed_profile_features``:
            ``speed_mean_mps`` -- mean speed [m/s]

        From ``features.compute_accel_features``:
            ``accel_max_mps2`` -- peak acceleration [m/s²]
            ``braking_max_mps2`` -- peak braking [m/s²]

        Robustness (computed upstream or passed directly):
            ``early_mean_s`` -- mean lap time first stint [s]
            ``late_mean_s`` -- mean lap time last  stint [s]
            ``early_yaw_var`` -- yaw variance first stint
            ``late_yaw_var`` -- yaw variance last  stint

    theoretical_metrics:
        Reference metrics for the theoretical lap (same keys as above).

    session_type:
        One of ``"practice"`` (default), ``"qualifying"``, ``"race"``.
        Changes relative emphasis of scoring categories.

    Returns -- -
    dict with keys:
        ``total_score`` -- float in [0, 100]
        ``grade`` -- str  ("S", "A", "B", "C", "D", "F")
        ``sub_scores`` -- dict per category with ``score``, ``max``, ``detail``
        ``strengths`` -- list[str]  (categories at -- deg -- STRENGTH_THRESHOLD of max)
        ``weaknesses`` -- list[str]  (categories at -- deg -- WEAKNESS_THRESHOLD of max)

    Raises -- TypeError
        If *metrics_dict* or *theoretical_metrics* is not a dict.
    """
    if not isinstance(metrics_dict, dict):
        raise TypeError(
            f"metrics_dict must be a dict, got {type(metrics_dict).__name__!r}."
        )
    if not isinstance(theoretical_metrics, dict):
        raise TypeError(
            f"theoretical_metrics must be a dict, got {type(theoretical_metrics).__name__!r}."
        )

    # --- Plausibility bounds validation -- -
    # Log warnings and reduce data_confidence for physically implausible inputs.

    _plausibility_penalty = 0.0
    _PLAUSIBILITY_BOUNDS: list[tuple[str, float, float, str]] = [
        # (key,           lo,   hi,    description)
        ("best_s",        10.0, 600.0, "best lap time [s]"),
        ("speed_mean_mps", 1.0, 120.0, "mean speed [m/s]"),
        ("accel_max_mps2", 0.0, 60.0,  "peak acceleration [m/s^2]"),
        ("braking_max_mps2", 0.0, 80.0, "peak braking [m/s^2]"),
        ("cv_pct",         0.0, 50.0,  "CV [%]"),
        ("best_to_median_s", 0.0, 60.0, "best-to-median gap [s]"),
    ]
    for _pk, _plo, _phi, _pdesc in _PLAUSIBILITY_BOUNDS:
        _pval = metrics_dict.get(_pk)
        if _pval is None:
            continue
        try:
            _pval_f = float(_pval)
        except (TypeError, ValueError):
            continue
        if math.isnan(_pval_f):
            continue
        if _pval_f < _plo or _pval_f > _phi:
            logger.warning(
                "Plausibility: %s = %.4f outside expected [%.1f, %.1f] (%s)",
                _pk, _pval_f, _plo, _phi, _pdesc,
            )
            _plausibility_penalty += 0.10  # 10 % per implausible metric

    # --- Determine simulation method & data confidence -- -

    sim_method = theoretical_metrics.get(
        "simulation_method",
        metrics_dict.get("simulation_method", "percentile_envelope"),
    )
    _raw_conf = theoretical_metrics.get(
        "confidence",
        metrics_dict.get("data_confidence", 1.0),
    )
    data_confidence = float(_raw_conf) if _raw_conf is not None else 1.0
    if math.isnan(data_confidence) or data_confidence < 0:
        data_confidence = 1.0

    # Apply plausibility penalty to data confidence
    if _plausibility_penalty > 0:
        data_confidence = max(0.0, data_confidence - _plausibility_penalty)
        logger.warning(
            "Plausibility penalty %.2f applied; data_confidence reduced to %.2f",
            _plausibility_penalty, data_confidence,
        )

    # --- Compute raw sub-scores -- -

    pace_score,        pace_detail  = _score_pace(
        metrics_dict, theoretical_metrics, simulation_method=str(sim_method or "percentile_envelope"),
    )
    cons_score,        cons_detail  = _score_consistency(
        metrics_dict, theoretical_metrics, is_wet=is_wet,
        session_type=session_type,
    )
    exec_score,        exec_detail  = _score_execution(
        metrics_dict, theoretical_metrics, simulation_method=str(sim_method or "percentile_envelope"),
    )
    # Blend with granular corner-level execution when available
    if corner_coaching:
        granular = compute_granular_execution(corner_performances=corner_coaching)
        # Enhance with real pedal data if progressive physics ran
        if progressive_physics and progressive_physics.get("controls_analysis"):
            granular = enhance_execution_with_controls(
                granular, progressive_physics["controls_analysis"],
            )
        if granular.get("has_corner_data"):
            # 70% granular (corner-level), 30% aggregate (speed/accel/brake)
            granular_score = granular["composite"] * MAX_EXECUTION
            exec_score = round(0.70 * granular_score + 0.30 * exec_score, 4)
            exec_detail["granular"] = granular
            exec_detail["has_corner_data"] = True
    robust_score,      robust_detail= _score_robustness(
        metrics_dict, theoretical_metrics,
    )

    # Adaptation defaults to neutral (75% of max) in score_session;
    # score_session_phase_aware overrides with the real v2 score.
    adapt_default = round(MAX_ADAPTATION * ADAPT_V2_STABLE_DEFAULT_FRAC, 4)

    raw_scores: dict[str, float] = {
        "pace":        pace_score,
        "consistency": cons_score,
        "execution":   exec_score,
        "robustness":  robust_score,
        "adaptation":  adapt_default,
    }

    # --- Apply session-type reweighting -- -

    n_laps = int(metrics_dict.get("n_laps", 0) or 0)
    final_scores, norm_max = _apply_adaptive_weights(
        raw_scores, session_type, track_state=track_state,
    )

    total = round(min(TOTAL_MAX, max(0.0, sum(final_scores.values()))), 4)

    # --- Data confidence weighting -- # When data quality is low, shrink toward a neutral midpoint to avoid

    # misleading high or low scores built on unreliable telemetry.

    total = _apply_confidence(total, data_confidence)

    # --- Diminishing returns (experience + session length) ---
    dr_multiplier = _compute_dr_multiplier(
        total_laps=driver_total_laps, session_laps=n_laps,
    )
    total = round(total * dr_multiplier, 4)

    # --- Assemble sub-scores dict -- -

    details_map = {
        "pace":        pace_detail,
        "consistency": cons_detail,
        "execution":   exec_detail,
        "robustness":  robust_detail,
        "adaptation":  {"source": "default_neutral"},
    }
    labels = {
        "pace":        "Pace",
        "consistency": "Consistency",
        "execution":   "Execution Quality",
        "robustness":  "Racecraft / Endurance Robustness",
        "adaptation":  "Adaptation",
    }

    sub_scores: dict[str, Any] = {}
    strengths:  list[str] = []
    weaknesses: list[str] = []

    for cat in ("pace", "consistency", "execution", "robustness", "adaptation"):
        s   = final_scores[cat]
        mx  = norm_max[cat]
        frac = s / mx if mx > 0 else 0.0

        sub_scores[cat] = {
            "score":  round(s,  4),
            "max":    round(mx, 4),
            "pct":    round(frac * 100, 2),
            "detail": details_map[cat],
        }

        label = labels[cat]
        if frac >= STRENGTH_THRESHOLD:
            strengths.append(label)
        elif frac <= WEAKNESS_THRESHOLD:
            weaknesses.append(label)

    grade = _assign_grade(total)

    result: dict[str, Any] = {
        "total_score":      total,
        "grade":            grade,
        "session_type":     session_type,
        "sub_scores":       sub_scores,
        "strengths":        strengths,
        "weaknesses":       weaknesses,
        "simulation_method": sim_method,
        "data_confidence":  round(data_confidence, 4),
    }

    logger.info(
        "Score: %.2f / %.0f  [%s]  (type=%s, method=%s, conf=%.2f)  "
        "strengths=%s  weaknesses=%s",
        total, TOTAL_MAX, grade, session_type, sim_method, data_confidence,
        strengths, weaknesses,
    )
    return result
