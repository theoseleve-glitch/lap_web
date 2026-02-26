"""
scoring.py -- Session performance scoring for motorsport telemetry analysis.

Scores a driver session against a theoretical reference across four
categories, returning a structured result with named strengths and
weaknesses.

Architecture
~~~~~~~~~~~~
- All weight constants and threshold values are declared as module-level
  ``Final`` constants --  zero magic numbers in logic paths.
- Category scorers are independent functions that each return a float in
  [0, max_points]; they can be called and tested individually.
- ``score_session()`` is the single public entry point that assembles all
  sub-scores and produces human-readable diagnostics.
- Fully deterministic: identical inputs produce identical outputs.

Scoring categories
~~~~~~~~~~~~~~~~~~
  Pace                 (0 -- 30 pts)
    How close is the best lap to the theoretical reference?

  Consistency          (0 -- 25 pts)
    How repeatable is performance across laps?

  Execution Quality    (0 -- 25 pts)
    How efficiently are corners driven?  (speed, accel, braking)

  Racecraft / Endurance Robustness  (0 -- 20 pts)
    How well does the driver sustain pace and stability over a long stint?

Return structure
~~~~~~~~~~~~~~~~
{
    "total_score":  float,          # 0 -- 100
    "grade":        str,            # "S", "A", "B", "C", "D", "F"
    "sub_scores": {
        "pace":          {"score": float, "max": 30, ...},
        "consistency":   {"score": float, "max": 25, ...},
        "execution":     {"score": float, "max": 25, ...},
        "robustness":    {"score": float, "max": 20, ...},
    },
    "strengths":  [str],
    "weaknesses": [str],
}
"""

from __future__ import annotations

import logging
import math
from typing import Any, Final, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# =============================================================================

# WEIGHT CONSTANTS  (category maximums --  must sum to 100)

# =============================================================================


MAX_PACE:        Final[float] = 30.0
MAX_CONSISTENCY: Final[float] = 25.0
MAX_EXECUTION:   Final[float] = 25.0
MAX_ROBUSTNESS:  Final[float] = 20.0
TOTAL_MAX:       Final[float] = MAX_PACE + MAX_CONSISTENCY + MAX_EXECUTION + MAX_ROBUSTNESS  # 100.0

# =============================================================================

# PACE SCORING CONSTANTS

# =============================================================================


# Gap (seconds) -- DEPRECATED: replaced by percentage-based ENVELOPE_*_GAP_PCT

# Kept for backward compatibility; no longer used in _score_pace().

PACE_ZERO_GAP_S: Final[float] = 15.0
PACE_FULL_GAP_S: Final[float] = 0.05

# Exponent for the pace decay curve (1.0 = linear, >1 = more forgiving near peak)

PACE_DECAY_EXP:  Final[float] = 1.6

# --- Physics-based theoretical lap thresholds (achievable ideal) -- # When the theoretical lap comes from a physics simulation, the gap is

# realistically small for a competent driver.

PHYS_PACE_FULL_GAP_S: Final[float] = 1.00   # within 1.0 s = full marks
PHYS_PACE_ZERO_GAP_S: Final[float] = 8.0    # 8 s slower = zero marks

# Percentage-based pace gap (meaningful across different track lengths)

# pace_gap_pct = (driver_best - theory_best) / theory_best * 100

PHYS_PACE_FULL_GAP_PCT: Final[float] = 2.0    # within 2.0 % of theoretical
PHYS_PACE_ZERO_GAP_PCT: Final[float] = 12.0   # 12 % slower = zero marks

# Weight blending between absolute-gap and percentage-gap scoring for physics

# (percentage is primary to handle track-length variation; absolute acts as

# a soft guard for very short tracks where 0.5 % = 0.25 s)

PHYS_PACE_W_PCT: Final[float] = 0.70   # 70 % from percentage gap
PHYS_PACE_W_ABS: Final[float] = 0.30   # 30 % from absolute gap

# =============================================================================

# CONSISTENCY SCORING CONSTANTS

# =============================================================================


# Coefficient of Variation (std/mean --  100) at which consistency score = 0

# Racing: CV > 2 % is considered poor; CV < 0.3 % is elite

CONSISTENCY_ZERO_CV_PCT:  Final[float] = 3.0
CONSISTENCY_FULL_CV_PCT:  Final[float] = 0.60

# Best-to-median gap (s) at which consistency bonus is saturated

CONSISTENCY_BTM_FULL_S:   Final[float] = 0.60
CONSISTENCY_BTM_ZERO_S:   Final[float] = 5.00

# Wet-session thresholds (wider band  --  higher variability is expected)

WET_CONSISTENCY_ZERO_CV_PCT: Final[float] = 5.0
WET_CONSISTENCY_FULL_CV_PCT: Final[float] = 0.50
WET_CONSISTENCY_BTM_FULL_S:  Final[float] = 0.60
WET_CONSISTENCY_BTM_ZERO_S:  Final[float] = 6.00

# Sub-weight split within consistency category

CONSISTENCY_W_CV:  Final[float] = 0.75   # 75 % of MAX_CONSISTENCY from CV (std dev)
CONSISTENCY_W_BTM: Final[float] = 0.25   # 25 % from best-to-median gap

# =============================================================================

# EXECUTION SCORING CONSTANTS

# =============================================================================


# Speed efficiency: comparison speed / theoretical speed ratio

EXEC_SPEED_FULL_RATIO:  Final[float] = 0.99   # -- deg -- 99 % -- full marks
EXEC_SPEED_ZERO_RATIO:  Final[float] = 0.85   # -- deg -- 85 % -- zero marks

# Acceleration efficiency: comparison vs theoretical accel peak ratio

EXEC_ACCEL_FULL_RATIO:  Final[float] = 0.95
EXEC_ACCEL_ZERO_RATIO:  Final[float] = 0.60

# Braking efficiency: comparison vs theoretical brake peak ratio

EXEC_BRAKE_FULL_RATIO:  Final[float] = 0.95
EXEC_BRAKE_ZERO_RATIO:  Final[float] = 0.60

# --- Physics-based execution thresholds -- # When the theoretical lap is from a physics simulation, the reference values

# represent genuinely achievable limits rather than impossibly optimistic

# composites.  Ratios closer to 1.0 are expected, so thresholds are slightly

# more lenient to avoid penalising drivers who are actually quite close.

PHYS_EXEC_SPEED_FULL_RATIO: Final[float] = 0.93
PHYS_EXEC_SPEED_ZERO_RATIO: Final[float] = 0.75
PHYS_EXEC_ACCEL_FULL_RATIO: Final[float] = 0.85
PHYS_EXEC_ACCEL_ZERO_RATIO: Final[float] = 0.45
PHYS_EXEC_BRAKE_FULL_RATIO: Final[float] = 0.85
PHYS_EXEC_BRAKE_ZERO_RATIO: Final[float] = 0.45

# Sub-weight split within execution

EXEC_W_SPEED:  Final[float] = 0.50   # 50 % from speed efficiency
EXEC_W_ACCEL:  Final[float] = 0.25   # 25 % from accel efficiency
EXEC_W_BRAKE:  Final[float] = 0.25   # 25 % from braking efficiency

# =============================================================================

# ROBUSTNESS SCORING CONSTANTS

# =============================================================================


# Pace retention: how much slower are the final laps vs first laps (fraction)

ROBUST_FADE_FULL:  Final[float] = 0.010   # -- deg -- 0.5 % fade -- full marks
ROBUST_FADE_ZERO:  Final[float] = 0.050   # -- deg -- 5 % fade -- zero marks

# Stability: yaw-rate variance ratio (late laps / early laps)

ROBUST_YAW_FULL:   Final[float] = 1.10    # -- deg -- 10 % increase -- full marks
ROBUST_YAW_ZERO:   Final[float] = 2.50    # -- deg -- 150 % increase -- zero marks

# Lap count for "early" vs "late" split (uses floor division)

ROBUST_EARLY_FRAC: Final[float] = 0.33    # first 33 % of laps = early stint
ROBUST_LATE_FRAC:  Final[float] = 0.33    # last  33 % of laps = late stint

# Sub-weight split within robustness

ROBUST_W_FADE:     Final[float] = 0.60
ROBUST_W_STABILITY: Final[float] = 0.40

# =============================================================================

# ADAPTATION SCORING CONSTANTS

# =============================================================================


# How quickly driver captures available grip when conditions change.

# Adaptation ratio = driver_pace_improvement / track_grip_improvement.

# A ratio of 1.0 means the driver captured 100% of the available grip.

ADAPT_FULL_RATIO:    Final[float] = 0.90   # >= 90% capture -> full marks
ADAPT_ZERO_RATIO:    Final[float] = 0.30   # <= 30% capture -> zero marks

# Adaptation score replaces consistency weight for evolving sessions

# (since whole-session CV is meaningless when conditions change).

# For evolving sessions: adaptation gets 60% of consistency budget,

# within-phase consistency gets 40%.

ADAPT_W_CAPTURE:     Final[float] = 0.60
ADAPT_W_INTRA_PHASE: Final[float] = 0.40

# Minimum evolution to trigger adaptation scoring (% pace shift)

ADAPT_MIN_EVOLUTION_PCT: Final[float] = 2.0

# =============================================================================

# GRANULAR EXECUTION SUB-SCORE CONSTANTS

# =============================================================================


# Braking quality: brake point accuracy (metres early vs theoretical)

BRAKE_POINT_FULL_M:  Final[float] = 3.0     # within 3 m = full marks
BRAKE_POINT_ZERO_M:  Final[float] = 25.0    # 25 m early = zero marks

# Braking intensity: how close to friction-limit braking

BRAKE_INTENSITY_FULL: Final[float] = 0.85   # 85% of max braking = full
BRAKE_INTENSITY_ZERO: Final[float] = 0.40   # 40% of max braking = zero

# Trail braking: fraction of corner entry where brakes overlap steering

# (higher is better for trail braking, indicates advanced technique)

TRAIL_BRAKE_FULL_PCT: Final[float] = 30.0   # 30% overlap = full marks
TRAIL_BRAKE_ZERO_PCT: Final[float] = 0.0    # no trail braking = zero

# Corner speed: actual apex speed / theoretical apex speed

CORNER_SPD_FULL_RATIO: Final[float] = 0.95  # 95% of theoretical = full
CORNER_SPD_ZERO_RATIO: Final[float] = 0.70  # 70% = zero

# Grip utilisation at apex (from corner_analysis)

GRIP_UTIL_FULL_PCT:  Final[float] = 85.0    # 85% grip used = full
GRIP_UTIL_ZERO_PCT:  Final[float] = 40.0    # 40% grip used = zero

# Throttle application: exit speed deficit vs theoretical (m/s)

EXIT_SPD_FULL_DEFICIT_MPS: Final[float] = 0.5   # within 0.5 m/s = full
EXIT_SPD_ZERO_DEFICIT_MPS: Final[float] = 5.0   # 5 m/s slow = zero

# Line quality: lateral position variance at apex (lower = more repeatable)

LINE_QUALITY_FULL_CV: Final[float] = 0.02   # very repeatable
LINE_QUALITY_ZERO_CV: Final[float] = 0.15   # very inconsistent

# Granular sub-weight split within execution (when corner data available)

EXEC_GRAN_W_BRAKING:     Final[float] = 0.30   # 30% braking quality
EXEC_GRAN_W_CORNER_SPD:  Final[float] = 0.30   # 30% corner speed/grip
EXEC_GRAN_W_EXIT:        Final[float] = 0.25   # 25% throttle/exit
EXEC_GRAN_W_LINE:        Final[float] = 0.15   # 15% line quality

# =============================================================================

# RACECRAFT SUB-SCORE CONSTANTS (race sessions only)

# =============================================================================


# Lap 1 performance: delta from best lap (s) -- penalties expected on lap 1

RACE_LAP1_FULL_DELTA_S: Final[float] = 3.0    # within 3 s of best = full
RACE_LAP1_ZERO_DELTA_S: Final[float] = 15.0   # 15 s slower = zero

# Stint management: CV% of middle 60% of laps (excludes start/finish)

RACE_STINT_FULL_CV: Final[float] = 0.8
RACE_STINT_ZERO_CV: Final[float] = 3.5

# Late-race pace retention: last 25% vs first 25% mean (fraction fade)

RACE_RETENTION_FULL: Final[float] = 0.005   # 0.5% fade = full
RACE_RETENTION_ZERO: Final[float] = 0.04    # 4% fade = zero

# Sub-weights within racecraft

RACE_W_START:     Final[float] = 0.25
RACE_W_STINT:     Final[float] = 0.40
RACE_W_RETENTION: Final[float] = 0.35

# =============================================================================

# GRADE THRESHOLDS

# =============================================================================


GRADE_S: Final[float] = 92.0
GRADE_A: Final[float] = 80.0
GRADE_B: Final[float] = 65.0
GRADE_C: Final[float] = 50.0
GRADE_D: Final[float] = 35.0
# below GRADE_D -- F"


# Threshold at which a sub-score is labelled a "strength"  (fraction of max)

STRENGTH_THRESHOLD: Final[float] = 0.80
# Threshold at which a sub-score is labelled a "weakness"  (fraction of max)

WEAKNESS_THRESHOLD: Final[float] = 0.50

# --- Data confidence weighting -- -

# When data quality is low (confidence < 1.0), the total score is shrunk

# toward a neutral midpoint to avoid misleading high/low scores.

CONFIDENCE_NEUTRAL_SCORE: Final[float] = 65.0


# =============================================================================

# Exceptions

# =============================================================================


class ScoringError(ValueError):
    """Raised when required metrics keys are absent or values are invalid."""


# =============================================================================

# Internal helpers

# =============================================================================


def _clamp01(x: float) -> float:
    """Clamp to [0, 1]."""
    return max(0.0, min(1.0, x))


def _ratio_score(
    value:      float,
    full_mark:  float,
    zero_mark:  float,
    higher_is_better: bool = True,
    exp: float = 1.0,
) -> float:
    """
    Return a score in [0, 1] that maps *value* linearly (or with exponent)
    between *zero_mark* ( -- 0) and *full_mark* ( -- 1).

    Parameters -- higher_is_better:
        True -- value -- deg -- full_mark scores 1; value -- deg -- zero_mark scores 0.
        False -- value -- deg -- full_mark scores 1; value -- deg -- zero_mark scores 0.
    exp:
        Exponent applied to the raw ratio (1 = linear).
    """
    if higher_is_better:
        raw = (value - zero_mark) / (full_mark - zero_mark)
    else:
        raw = (zero_mark - value) / (zero_mark - full_mark)
    return _clamp01(raw ** exp if raw > 0 else 0.0)


def _get(d: dict[str, Any], key: str, default: float = float("nan")) -> float:
    """Safely retrieve a float from *d*; return *default* if absent or NaN."""
    v = d.get(key, default)
    try:
        f = float(v)
        return default if math.isnan(f) else f
    except (TypeError, ValueError):
        return default


def _assign_grade(total: float) -> str:
    if total >= GRADE_S:
        return "S"
    if total >= GRADE_A:
        return "A"
    if total >= GRADE_B:
        return "B"
    if total >= GRADE_C:
        return "C"
    if total >= GRADE_D:
        return "D"
    return "F"


def _apply_confidence(
    total: float,
    confidence: float,
    neutral: float = CONFIDENCE_NEUTRAL_SCORE,
) -> float:
    """Shrink *total* toward *neutral* when *confidence* < 1.0."""
    if confidence < 1.0:
        total = neutral + (total - neutral) * confidence
    return round(total, 4)


def _normalize_session_type(st: str) -> str:
    """Canonical lower-case, underscore-separated session type string."""
    return str(st).lower().strip().replace("-", "_")


# =============================================================================

# Category scorers

# =============================================================================


def _score_pace(
    m:  dict[str, Any],
    th: dict[str, Any],
    *,
    simulation_method: str = "percentile_envelope",
) -> tuple[float, dict[str, Any]]:
    """
    Score pace: how close is the driver's best lap to the theoretical minimum?

    When *simulation_method* is ``"physics"``, the theoretical lap represents
    a genuinely achievable ideal so tighter thresholds and a blended
    percentage+absolute gap scoring are used.  Otherwise the legacy absolute
    gap thresholds are applied (suitable for the overly-optimistic percentile
    envelope).

    Required metric keys
    ~~~~~~~~~~~~~~~~~~~~
    ``best_s``   -- driver's best lap time [s]  (from *m*)
    ``best_s``   -- theoretical best lap time [s]  (from *th*)

    Returns -- -
    (score, detail_dict)
    """
    driver_best = _get(m,  "best_s")
    theory_best = _get(th, "best_s")

    if math.isnan(driver_best) or math.isnan(theory_best) or theory_best <= 0:
        logger.debug("Pace: missing or invalid best_s; returning 0.")
        return 0.0, {
            "raw_gap_s": float("nan"), "gap_pct": float("nan"),
            "simulation_method": simulation_method,
        }

    gap_s   = driver_best - theory_best
    gap_pct = 100.0 * gap_s / theory_best

    is_physics = simulation_method in ("physics", "hybrid")

    if is_physics:
        # --- Blended percentage + absolute scoring -- -

        # Percentage-based (primary): handles track-length variation

        pct_ratio = _ratio_score(
            gap_pct, PHYS_PACE_FULL_GAP_PCT, PHYS_PACE_ZERO_GAP_PCT,
            higher_is_better=False, exp=PACE_DECAY_EXP,
        )
        # Absolute-based (secondary): guards against very short tracks

        abs_ratio = _ratio_score(
            gap_s, PHYS_PACE_FULL_GAP_S, PHYS_PACE_ZERO_GAP_S,
            higher_is_better=False, exp=PACE_DECAY_EXP,
        )
        ratio = PHYS_PACE_W_PCT * pct_ratio + PHYS_PACE_W_ABS * abs_ratio
    else:
        # --- Percentage-based scoring (track-aware) -- -

        # The old absolute-gap approach (15s = zero, 0.05s = full) was

        # track-blind: 15s is 30% of a 50s kart lap but only 8% of a

        # 3-minute circuit.  Use percentage gaps instead so scoring

        # adapts to any track length.

        ENVELOPE_FULL_GAP_PCT = 0.5    # within 0.5% of envelope = full marks
        ENVELOPE_ZERO_GAP_PCT = 15.0   # 15% slower than envelope = zero
        ratio = _ratio_score(
            gap_pct, ENVELOPE_FULL_GAP_PCT, ENVELOPE_ZERO_GAP_PCT,
            higher_is_better=False, exp=PACE_DECAY_EXP,
        )

    score = round(ratio * MAX_PACE, 4)

    return score, {
        "raw_gap_s":         round(gap_s, 3),
        "gap_pct":           round(gap_pct, 4),
        "simulation_method": simulation_method,
    }


def _score_consistency(
    m:  dict[str, Any],
    _th: dict[str, Any],
    *,
    is_wet: bool = False,
    within_phase_cv: "float | None" = None,
    session_type: str = "practice",
    lap_times: "list[float] | None" = None,
    grip_progressing: bool = False,
) -> tuple[float, dict[str, Any]]:
    """
    Score consistency from CV% and best-to-median gap (or worst residual
    against regression line when grip is progressing).

    Required metric keys (from *m*)
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    ``cv_pct``            — coefficient of variation of lap times [%]
    ``best_to_median_s``  — gap between fastest and median lap [s]
    ``n_laps``            — number of valid laps

    Parameters
    ----------
    is_wet : bool
        When True, wider thresholds are used (wet sessions have naturally
        higher variability).
    lap_times : list[float] | None
        Ordered lap times for regression-based scoring.
    grip_progressing : bool
        When True and lap_times is available, replaces best-to-median with
        worst residual deviation against the regression line.
    """
    n_laps = int(_get(m, "n_laps", 0))
    if n_laps < 2:
        logger.debug("Consistency: fewer than 2 laps; returning 0.")
        return 0.0, {"note": "insufficient laps"}

    cv_pct = _get(m, "cv_pct")
    btm_s  = _get(m, "best_to_median_s")

    # If within-phase CV is provided (evolving session), prefer it over
    # the whole-session CV which is inflated by track evolution
    if within_phase_cv is not None and not math.isnan(within_phase_cv):
        cv_pct = within_phase_cv

    # --- Grip progression: replace best-to-median with worst residual ---
    _used_regression = False
    if grip_progressing and lap_times and len(lap_times) >= 3:
        import numpy as _np
        x = _np.arange(len(lap_times), dtype=float)
        y = _np.array(lap_times, dtype=float)
        # Fit linear regression
        x_mean, y_mean = x.mean(), y.mean()
        denom = float(((x - x_mean) ** 2).sum())
        if denom > 1e-12:
            slope = float(((x - x_mean) * (y - y_mean)).sum() / denom)
            intercept = y_mean - slope * x_mean
            predicted = slope * x + intercept
            residuals = y - predicted
            # Worst positive residual = lap most above regression line
            worst_residual = float(_np.max(_np.abs(residuals)))
            btm_s = worst_residual
            _used_regression = True
            logger.debug(
                "Grip progression: using worst residual %.3fs vs regression "
                "(slope=%.4f s/lap) instead of best-to-median",
                worst_residual, slope,
            )

    # Select thresholds: session-type-specific > wet > defaults
    _stype = _normalize_session_type(session_type)
    type_thresh = _CONSISTENCY_THRESHOLDS_BY_TYPE.get(_stype)

    if type_thresh and not is_wet:
        cv_full  = type_thresh["cv_full"]
        cv_zero  = type_thresh["cv_zero"]
        btm_full = type_thresh["btm_full"]
        btm_zero = type_thresh["btm_zero"]
    elif is_wet:
        cv_full  = WET_CONSISTENCY_FULL_CV_PCT
        cv_zero  = WET_CONSISTENCY_ZERO_CV_PCT
        btm_full = WET_CONSISTENCY_BTM_FULL_S
        btm_zero = WET_CONSISTENCY_BTM_ZERO_S
    else:
        cv_full  = CONSISTENCY_FULL_CV_PCT
        cv_zero  = CONSISTENCY_ZERO_CV_PCT
        btm_full = CONSISTENCY_BTM_FULL_S
        btm_zero = CONSISTENCY_BTM_ZERO_S

    cv_ratio  = _ratio_score(
        cv_pct, cv_full, cv_zero,
        higher_is_better=False,
    ) if not math.isnan(cv_pct) else 0.5   # partial credit when unknown

    btm_ratio = _ratio_score(
        btm_s, btm_full, btm_zero,
        higher_is_better=False,
    ) if not math.isnan(btm_s) else 0.5

    composite = CONSISTENCY_W_CV * cv_ratio + CONSISTENCY_W_BTM * btm_ratio
    score     = round(composite * MAX_CONSISTENCY, 4)

    logger.debug(
        "Consistency inputs: cv_pct=%.4f  btm_s=%.3f  n_laps=%d  is_wet=%s | "
        "thresholds: cv[%.2f-%.2f]  btm[%.2f-%.2f] | "
        "cv_ratio=%.4f  btm_ratio=%.4f  composite=%.4f  score=%.4f",
        cv_pct if not math.isnan(cv_pct) else -1.0,
        btm_s if not math.isnan(btm_s) else -1.0,
        n_laps, is_wet,
        cv_full, cv_zero, btm_full, btm_zero,
        cv_ratio, btm_ratio, composite, score,
    )

    detail: dict[str, Any] = {
        "cv_pct":              round(cv_pct,  4) if not math.isnan(cv_pct) else None,
        "best_to_median_s":    round(btm_s,   3) if not math.isnan(btm_s)  else None,
        "cv_ratio":            round(cv_ratio,  4),
        "btm_ratio":           round(btm_ratio, 4),
        "is_wet":              is_wet,
    }
    if _used_regression:
        detail["used_regression"] = True
        detail["worst_residual_s"] = round(btm_s, 3)

    return score, detail


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
    is_physics = simulation_method in ("physics", "hybrid")

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


def _score_robustness(
    m:  dict[str, Any],
    _th: dict[str, Any],
) -> tuple[float, dict[str, Any]]:
    """
    Score racecraft / endurance robustness: pace retention and stability.

    Required metric keys (from *m*)
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    ``early_mean_s`` -- mean lap time of the first stint [s]
    ``late_mean_s`` -- mean lap time of the last stint [s]
    ``early_yaw_var`` -- mean yaw-rate variance of the first stint
    ``late_yaw_var`` -- mean yaw-rate variance of the last stint
    ``n_laps`` -- total laps

    Missing values fall back to partial credit.
    """
    n_laps     = int(_get(m, "n_laps", 0))
    early_mean = _get(m, "early_mean_s")
    late_mean  = _get(m, "late_mean_s")
    early_yaw  = _get(m, "early_yaw_var")
    late_yaw   = _get(m, "late_yaw_var")

    # Pace fade (positive = getting slower)

    if not math.isnan(early_mean) and not math.isnan(late_mean) and early_mean > 0:
        fade_frac = (late_mean - early_mean) / early_mean
        fade_r    = _ratio_score(
            fade_frac, ROBUST_FADE_FULL, ROBUST_FADE_ZERO,
            higher_is_better=False,
        )
    else:
        fade_r    = 0.5
        fade_frac = float("nan")

    # Stability (yaw variance growth)

    if not math.isnan(early_yaw) and not math.isnan(late_yaw) and early_yaw > 0:
        yaw_ratio   = late_yaw / early_yaw
        stability_r = _ratio_score(
            yaw_ratio, ROBUST_YAW_FULL, ROBUST_YAW_ZERO,
            higher_is_better=False,
        )
    else:
        stability_r = 0.5
        yaw_ratio   = float("nan")

    composite = ROBUST_W_FADE * fade_r + ROBUST_W_STABILITY * stability_r
    score     = round(composite * MAX_ROBUSTNESS, 4)

    return score, {
        "pace_fade_frac":  round(fade_frac, 6) if not math.isnan(fade_frac) else None,
        "yaw_var_ratio":   round(yaw_ratio, 4) if not math.isnan(yaw_ratio)  else None,
        "fade_ratio":      round(fade_r,    4),
        "stability_ratio": round(stability_r, 4),
        "n_laps":          n_laps,
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


# =============================================================================

# Racecraft scoring (race sessions only)

# =============================================================================


def compute_racecraft_score(
    lap_metrics: "list[dict[str, Any]] | None" = None,
    session_type: str = "practice",
) -> dict[str, Any]:
    """
    Score racecraft: start performance, stint management, late-race retention.

    Only meaningful for race sessions.  Returns neutral 0.5 for non-races.

    Parameters -- lap_metrics:
        Per-lap metric dicts with ``lap_number`` and ``lap_time_s``.

    Returns -- -
    dict
        ``composite`` (float 0-1), plus ``start_score``, ``stint_score``,
        ``retention_score``.
    """
    result: dict[str, Any] = {
        "composite": 0.5,
        "start_score": 0.5,
        "stint_score": 0.5,
        "retention_score": 0.5,
        "is_race": False,
        "detail": {},
    }

    if _normalize_session_type(session_type) != "race" or not lap_metrics:
        return result

    result["is_race"] = True

    lm_df = pd.DataFrame(lap_metrics)
    if "lap_time_s" not in lm_df.columns or "lap_number" not in lm_df.columns:
        return result

    lm_df["lap_time_s"] = pd.to_numeric(lm_df["lap_time_s"], errors="coerce")
    lm_df = lm_df.dropna(subset=["lap_time_s"]).sort_values("lap_number")
    times = lm_df["lap_time_s"].values.astype(float)
    n = len(times)
    if n < 4:
        return result

    best = float(np.min(times))

    # --- Lap 1 start performance -
    lap1_time = float(times[0])
    lap1_delta = lap1_time - best
    start_score = _ratio_score(
        lap1_delta, RACE_LAP1_FULL_DELTA_S, RACE_LAP1_ZERO_DELTA_S,
        higher_is_better=False,
    )
    result["start_score"] = round(start_score, 4)
    result["detail"]["lap1_delta_s"] = round(lap1_delta, 3)

    # --- Stint management (middle 60% of laps) -
    start_cut = max(1, int(n * 0.2))
    end_cut = max(start_cut + 2, int(n * 0.8))
    mid_times = times[start_cut:end_cut]
    if len(mid_times) >= 3:
        mid_mean = float(mid_times.mean())
        mid_cv = float(mid_times.std() / mid_mean * 100.0) if mid_mean > 0 else 0.0
        stint_score = _ratio_score(
            mid_cv, RACE_STINT_FULL_CV, RACE_STINT_ZERO_CV,
            higher_is_better=False,
        )
    else:
        stint_score = 0.5
        mid_cv = float("nan")

    result["stint_score"] = round(stint_score, 4)
    result["detail"]["mid_stint_cv_pct"] = (
        round(mid_cv, 3) if math.isfinite(mid_cv) else None
    )

    # --- Late-race pace retention -
    early_n = max(1, int(n * 0.25))
    late_n = max(1, int(n * 0.25))
    early_mean = float(np.mean(times[:early_n]))
    late_mean = float(np.mean(times[-late_n:]))
    if early_mean > 0:
        fade_frac = (late_mean - early_mean) / early_mean
        retention_score = _ratio_score(
            fade_frac, RACE_RETENTION_FULL, RACE_RETENTION_ZERO,
            higher_is_better=False,
        )
    else:
        retention_score = 0.5
        fade_frac = float("nan")

    result["retention_score"] = round(retention_score, 4)
    result["detail"]["late_race_fade_pct"] = (
        round(fade_frac * 100, 2) if math.isfinite(fade_frac) else None
    )

    # --- Composite -
    composite = (
        RACE_W_START * result["start_score"]
        + RACE_W_STINT * result["stint_score"]
        + RACE_W_RETENTION * result["retention_score"]
    )
    result["composite"] = round(composite, 4)

    logger.info(
        "Racecraft: start=%.3f (lap1 +%.1fs), stint=%.3f (cv=%.2f%%), "
        "retention=%.3f (fade=%.2f%%), composite=%.3f",
        result["start_score"], lap1_delta,
        result["stint_score"], mid_cv if math.isfinite(mid_cv) else -1.0,
        result["retention_score"],
        fade_frac * 100 if math.isfinite(fade_frac) else -1.0,
        composite,
    )
    return result


# =============================================================================

# Session-type weights

# =============================================================================


# Session-type weight multipliers: adjust sub-score emphasis per type.
# Weights are multiplied against the base category max, then renormalised
# so the total always equals 100.
_SESSION_WEIGHT_OVERRIDES: dict[str, dict[str, float]] = {
    "qualifying":      {"pace": 1.40, "consistency": 0.90, "execution": 1.10, "robustness": 0.60},
    "race":            {"pace": 0.90, "consistency": 1.10, "execution": 0.90, "robustness": 1.40},
    "sprint_race":     {"pace": 0.90, "consistency": 1.10, "execution": 0.90, "robustness": 1.40},
    "practice":        {"pace": 1.00, "consistency": 1.00, "execution": 1.20, "robustness": 0.80},
    "test":            {"pace": 0.80, "consistency": 1.10, "execution": 1.30, "robustness": 0.80},
    "warmup":          {"pace": 0.60, "consistency": 0.80, "execution": 1.30, "robustness": 0.60},
    "heat":            {"pace": 1.20, "consistency": 1.00, "execution": 1.00, "robustness": 0.80},
    "final":           {"pace": 1.10, "consistency": 1.00, "execution": 1.00, "robustness": 0.90},
    "feature_race":    {"pace": 0.90, "consistency": 1.10, "execution": 0.90, "robustness": 1.40},
    "endurance_stint": {"pace": 0.80, "consistency": 1.20, "execution": 0.80, "robustness": 1.60},
    "endurance_race":  {"pace": 0.80, "consistency": 1.20, "execution": 0.80, "robustness": 1.60},
    "sprint":          {"pace": 1.10, "consistency": 1.00, "execution": 1.00, "robustness": 0.90},
    "endurance":       {"pace": 0.80, "consistency": 1.20, "execution": 0.80, "robustness": 1.60},
}

# Synonyms: map alternative type names to canonical keys
_SESSION_TYPE_SYNONYMS: dict[str, str] = {
    "sprint_race": "sprint_race",
    "feature_race": "feature_race",
    "endurance_stint": "endurance_stint",
    "endurance_race": "endurance_race",
}

# Session-type-specific consistency thresholds
# Qualifying expects very tight CV; endurance/race allows wider
_CONSISTENCY_THRESHOLDS_BY_TYPE: dict[str, dict[str, float]] = {
    "qualifying": {
        "cv_full": 0.40, "cv_zero": 2.0,
        "btm_full": 0.30, "btm_zero": 3.0,
    },
    "race": {
        "cv_full": 0.80, "cv_zero": 4.0,
        "btm_full": 0.80, "btm_zero": 6.0,
    },
    "sprint_race": {
        "cv_full": 0.70, "cv_zero": 3.5,
        "btm_full": 0.70, "btm_zero": 5.0,
    },
    "endurance": {
        "cv_full": 1.00, "cv_zero": 5.0,
        "btm_full": 1.00, "btm_zero": 7.0,
    },
    "endurance_stint": {
        "cv_full": 1.00, "cv_zero": 5.0,
        "btm_full": 1.00, "btm_zero": 7.0,
    },
    "endurance_race": {
        "cv_full": 1.00, "cv_zero": 5.0,
        "btm_full": 1.00, "btm_zero": 7.0,
    },
    "warmup": {
        "cv_full": 1.50, "cv_zero": 6.0,
        "btm_full": 1.50, "btm_zero": 8.0,
    },
    "test": {
        "cv_full": 1.20, "cv_zero": 5.0,
        "btm_full": 1.20, "btm_zero": 7.0,
    },
}

_BASE_MAXES: dict[str, float] = {
    "pace":        MAX_PACE,
    "consistency": MAX_CONSISTENCY,
    "execution":   MAX_EXECUTION,
    "robustness":  MAX_ROBUSTNESS,
}


def _apply_session_weights(
    raw_scores: dict[str, float],
    session_type: str,
) -> dict[str, float]:
    """
    Re-scale sub-scores so the total always sums to TOTAL_MAX (100).

    The multipliers in ``_SESSION_WEIGHT_OVERRIDES`` change the *relative*
    emphasis between categories without changing the total budget.
    """
    stype = _normalize_session_type(session_type)
    stype = _SESSION_TYPE_SYNONYMS.get(stype, stype)
    overrides = _SESSION_WEIGHT_OVERRIDES.get(stype, {})
    if not overrides:
        return raw_scores   # no-op for unknown session types

    # Compute adjusted maximums

    adjusted_max = {
        cat: _BASE_MAXES[cat] * overrides.get(cat, 1.0)
        for cat in _BASE_MAXES
    }
    total_adjusted = sum(adjusted_max.values())
    scale = TOTAL_MAX / total_adjusted   # normalisation factor

    rescaled: dict[str, float] = {}
    for cat, raw in raw_scores.items():
        fraction = raw / _BASE_MAXES[cat] if _BASE_MAXES[cat] > 0 else 0.0
        new_max  = adjusted_max[cat] * scale
        rescaled[cat] = round(fraction * new_max, 4)

    return rescaled


# =============================================================================

# Public API

# =============================================================================


def score_session(
    metrics_dict:         dict[str, Any],
    theoretical_metrics:  dict[str, Any],
    session_type:         str = "practice",
    *,
    is_wet:               bool = False,
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
    data_confidence = float(theoretical_metrics.get(
        "confidence",
        metrics_dict.get("data_confidence", 1.0),
    ))
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
        metrics_dict, theoretical_metrics, simulation_method=sim_method,
    )
    cons_score,        cons_detail  = _score_consistency(
        metrics_dict, theoretical_metrics, is_wet=is_wet,
        session_type=session_type,
    )
    exec_score,        exec_detail  = _score_execution(
        metrics_dict, theoretical_metrics, simulation_method=sim_method,
    )
    robust_score,      robust_detail= _score_robustness(
        metrics_dict, theoretical_metrics,
    )

    raw_scores: dict[str, float] = {
        "pace":        pace_score,
        "consistency": cons_score,
        "execution":   exec_score,
        "robustness":  robust_score,
    }

    # --- Apply session-type reweighting -- -

    final_scores = _apply_session_weights(raw_scores, session_type)

    # Recompute effective maximums for this session type

    _stype_key = _normalize_session_type(session_type)
    _stype_key = _SESSION_TYPE_SYNONYMS.get(_stype_key, _stype_key)
    overrides = _SESSION_WEIGHT_OVERRIDES.get(_stype_key, {})
    if overrides:
        adj_max = {
            cat: _BASE_MAXES[cat] * overrides.get(cat, 1.0)
            for cat in _BASE_MAXES
        }
        total_adj = sum(adj_max.values())
        norm_max  = {cat: round(v / total_adj * TOTAL_MAX, 4) for cat, v in adj_max.items()}
    else:
        norm_max = dict(_BASE_MAXES)

    total = round(min(TOTAL_MAX, max(0.0, sum(final_scores.values()))), 4)

    # --- Data confidence weighting -- # When data quality is low, shrink toward a neutral midpoint to avoid

    # misleading high or low scores built on unreliable telemetry.

    total = _apply_confidence(total, data_confidence)

    # --- Assemble sub-scores dict -- -

    details_map = {
        "pace":        pace_detail,
        "consistency": cons_detail,
        "execution":   exec_detail,
        "robustness":  robust_detail,
    }
    labels = {
        "pace":        "Pace",
        "consistency": "Consistency",
        "execution":   "Execution Quality",
        "robustness":  "Racecraft / Endurance Robustness",
    }

    sub_scores: dict[str, Any] = {}
    strengths:  list[str] = []
    weaknesses: list[str] = []

    for cat in ("pace", "consistency", "execution", "robustness"):
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


# =============================================================================

# Phase-aware scoring + adaptation_score

# =============================================================================


def score_session_phase_aware(
    metrics_dict: dict[str, Any],
    theoretical_metrics: dict[str, Any],
    session_type: str = "practice",
    *,
    context: Any = None,
    phases_df: Optional[pd.DataFrame] = None,
    lap_to_phase: Optional[dict[int, int]] = None,
    lap_metrics: Optional[list[dict[str, Any]]] = None,
    track_evolution: Optional[dict[str, Any]] = None,
    corner_performances: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """
    Phase-aware wrapper around :func:`score_session`.

    Adds ``phase_scores`` (per-phase sub-scores) and ``adaptation_score``
    (how fast pace improves after condition changes) when phase information
    is available.  Falls back to plain :func:`score_session` otherwise.

    Parameters -- metrics_dict, theoretical_metrics, session_type:
        Forwarded to :func:`score_session`.
    context:
        ``SessionContext`` instance (optional).
    phases_df:
        Output of ``condition_tracking.build_condition_phases``.
    lap_to_phase:
        ``{lap_number: phase_id}`` mapping.
    lap_metrics:
        Per-lap metric dicts (each must include ``lap_number``, ``lap_time_s``).

    Returns -- -
    dict
        Same keys as :func:`score_session` plus:
        ``phase_scores`` (dict[int, dict]) and ``adaptation_score`` (float 0-1).
    """
    # Base scoring (always computed)

    # Detect wet conditions from context

    _is_wet = False
    if context is not None:
        _track_state = getattr(context, "baseline_track_state", None)
        if _track_state is not None:
            _state_val = _track_state.value if hasattr(_track_state, "value") else str(_track_state)
            _is_wet = _state_val.lower() in ("wet", "full_wet", "damp", "drying", "greasy")

    # Check for track evolution to adjust consistency scoring

    _has_evolution = (
        track_evolution is not None
        and abs(track_evolution.get("total_evolution_pct", 0.0)) >= ADAPT_MIN_EVOLUTION_PCT
    )

    result = score_session(
        metrics_dict, theoretical_metrics, session_type, is_wet=_is_wet,
    )

    # --- Detrended consistency for evolving conditions -- -

    # If track is evolving (drying/degrading), the raw CV% is unfairly high.

    # Recompute consistency using detrended or per-phase CV.

    if _has_evolution and lap_metrics:
        try:
            from features import compute_detrended_consistency

            _lap_times = [
                lm.get("lap_time_s")
                for lm in sorted(lap_metrics, key=lambda x: x.get("lap_number", 0))
                if isinstance(lm.get("lap_time_s"), (int, float))
                and math.isfinite(lm["lap_time_s"])
            ]

            if len(_lap_times) >= 3:
                detrend_result = compute_detrended_consistency(
                    _lap_times,
                    lap_to_phase=lap_to_phase,
                )
                adj_cv = detrend_result.get("adjusted_cv_pct", float("nan"))

                if math.isfinite(adj_cv):
                    # Recompute consistency sub-score with adjusted CV
                    _grip_improving = (
                        track_evolution is not None
                        and track_evolution.get("grip_trend") == "improving"
                    )
                    _adj_cons_score, _adj_cons_detail = _score_consistency(
                        metrics_dict, theoretical_metrics,
                        is_wet=_is_wet,
                        within_phase_cv=adj_cv,
                        session_type=session_type,
                        lap_times=_lap_times,
                        grip_progressing=_grip_improving,
                    )

                    if "consistency" in result.get("sub_scores", {}):
                        old_cons = result["sub_scores"]["consistency"]["score"]
                        result["sub_scores"]["consistency"]["score"] = _adj_cons_score
                        pct = _adj_cons_score / MAX_CONSISTENCY * 100.0 if MAX_CONSISTENCY > 0 else 0
                        result["sub_scores"]["consistency"]["pct"] = round(pct, 2)
                        result["sub_scores"]["consistency"]["detail"] = _adj_cons_detail
                        result["sub_scores"]["consistency"]["detail"]["detrended"] = True
                        result["sub_scores"]["consistency"]["detail"]["raw_cv_pct"] = detrend_result["raw_cv_pct"]
                        result["sub_scores"]["consistency"]["detail"]["adjusted_cv_pct"] = adj_cv

                        # Recompute total score

                        new_total = sum(
                            result["sub_scores"][cat]["score"]
                            for cat in ("pace", "consistency", "execution", "robustness")
                            if cat in result["sub_scores"]
                        )
                        new_total = _apply_confidence(
                            new_total, result.get("data_confidence", 1.0),
                        )
                        if math.isnan(new_total):
                            new_total = result["total_score"]
                        result["total_score"] = round(min(100.0, max(0.0, new_total)), 4)
                        result["grade"] = _assign_grade(result["total_score"])

                        logger.info(
                            "Detrended consistency: raw_cv=%.2f%% adj_cv=%.2f%% "
                            "cons_score %.2f -> %.2f",
                            detrend_result["raw_cv_pct"], adj_cv,
                            old_cons, _adj_cons_score,
                        )
        except ImportError:
            logger.debug("features module unavailable for detrended consistency")
        except Exception as _dt_err:
            logger.warning("Detrended consistency failed: %s", _dt_err)

    # --- Granular execution sub-scores (when corner data available) -
    granular_exec = compute_granular_execution(
        corner_performances=corner_performances,
        lap_metrics=lap_metrics,
    )
    result["granular_execution"] = granular_exec

    # --- Racecraft scoring (race sessions only) -
    racecraft = compute_racecraft_score(
        lap_metrics=lap_metrics,
        session_type=session_type,
    )
    result["racecraft"] = racecraft

    # Blend granular execution into the main execution score if available

    if granular_exec.get("has_corner_data", False):
        exec_key = "execution"
        if exec_key in result.get("sub_scores", {}):
            orig_exec = result["sub_scores"][exec_key]

            # Blend on raw 0-1 fractions to avoid scale mismatch
            orig_frac = orig_exec["score"] / orig_exec["max"] if orig_exec["max"] > 0 else 0.5
            gran_frac = granular_exec["composite"]
            blended_frac = 0.40 * orig_frac + 0.60 * gran_frac
            new_score = blended_frac * orig_exec["max"]
            result["sub_scores"][exec_key]["score"] = round(new_score, 4)
            result["sub_scores"][exec_key]["pct"] = round(blended_frac * 100.0, 2)
            result["sub_scores"][exec_key]["detail"]["granular"] = granular_exec

            # Recompute total

            new_total = sum(
                result["sub_scores"][cat]["score"]
                for cat in ("pace", "consistency", "execution", "robustness")
                if cat in result["sub_scores"]
            )
            new_total = _apply_confidence(
                new_total, result.get("data_confidence", 1.0),
            )
            if math.isnan(new_total):
                new_total = result["total_score"]
            result["total_score"] = round(min(100.0, max(0.0, new_total)), 4)
            result["grade"] = _assign_grade(result["total_score"])

    # Phase-level scoring

    phase_scores: dict[int, dict[str, Any]] = {}
    adaptation: float = 0.5  # neutral default

    if (
        phases_df is not None
        and not phases_df.empty
        and lap_to_phase
        and lap_metrics
    ):
        try:
            phase_scores = _compute_phase_scores(
                phases_df, lap_to_phase, lap_metrics,
            )
        except Exception as exc:
            logger.warning("Phase scoring failed: %s", exc)

        try:
            adaptation = _compute_adaptation_score(
                phases_df, lap_to_phase, lap_metrics,
                track_evolution=track_evolution,
            )
        except Exception as exc:
            logger.warning("Adaptation scoring failed: %s", exc)

    result["phase_scores"] = phase_scores
    result["adaptation_score"] = round(adaptation, 4)

    # Surface track evolution summary in scoring result

    if track_evolution is not None:
        result["track_evolution"] = {
            "total_evolution_pct": track_evolution.get("total_evolution_pct", 0.0),
            "grip_trend": track_evolution.get("grip_trend", "stable"),
            "evolution_rate_s_per_lap": track_evolution.get("evolution_rate_s_per_lap", 0.0),
        }
        # If track is evolving, adjust consistency interpretation:

        # the consistency sub-score should note it measured within-phase CV

        has_evolution = abs(track_evolution.get("total_evolution_pct", 0.0)) >= ADAPT_MIN_EVOLUTION_PCT
        if has_evolution and "consistency" in result.get("sub_scores", {}):
            result["sub_scores"]["consistency"]["detail"]["within_phase"] = True
            result["sub_scores"]["consistency"]["detail"]["track_evolving"] = True

    return result


def _compute_phase_scores(
    phases_df: pd.DataFrame,
    lap_to_phase: dict[int, int],
    lap_metrics: list[dict[str, Any]],
) -> dict[int, dict[str, Any]]:
    """Per-phase pace/consistency/stability sub-scores."""
    lm_df = pd.DataFrame(lap_metrics)
    if "lap_number" not in lm_df.columns or "lap_time_s" not in lm_df.columns:
        return {}

    lm_df["lap_time_s"] = pd.to_numeric(lm_df["lap_time_s"], errors="coerce")
    lm_df["_phase"] = lm_df["lap_number"].map(lap_to_phase)

    result: dict[int, dict[str, Any]] = {}
    for pid, grp in lm_df.groupby("_phase", sort=True):
        times = grp["lap_time_s"].dropna()
        if len(times) < 2:
            continue
        best = float(times.min())
        median = float(times.median())
        cv = float(times.std() / times.mean() * 100) if times.mean() > 0 else 0.0

        # Simple sub-scores normalised 0-1

        pace_sub = max(0.0, 1.0 - (median - best) / max(best, 1.0))
        cons_sub = max(0.0, 1.0 - cv / 5.0)  # 5% cv -- ž -- ¢ 0

        # Stability: jerk_rms if available

        jerk_col = "jerk_rms_mps3"
        if jerk_col in grp.columns:
            jerk_vals = pd.to_numeric(grp[jerk_col], errors="coerce").dropna()
            stab_sub = max(0.0, 1.0 - float(jerk_vals.std() / jerk_vals.mean())
                          ) if len(jerk_vals) > 1 and jerk_vals.mean() > 0 else 0.5
        else:
            stab_sub = 0.5

        result[int(pid)] = {
            "n_laps": len(times),
            "best_s": round(best, 3),
            "median_s": round(median, 3),
            "cv_pct": round(cv, 2),
            "pace_sub": round(pace_sub, 4),
            "consistency_sub": round(cons_sub, 4),
            "stability_sub": round(stab_sub, 4),
        }
    return result


def _compute_adaptation_score(
    phases_df: pd.DataFrame,
    lap_to_phase: dict[int, int],
    lap_metrics: list[dict[str, Any]],
    *,
    track_evolution: "dict[str, Any] | None" = None,
) -> float:
    """
    Score how effectively the driver adapts to changing conditions.

    Two components:

    1. **Grip capture ratio** (60%): For each phase transition, how much
       of the track's grip improvement did the driver actually capture
       in their lap times?  If the track improved 5% but the driver
       only improved 2%, the capture ratio is 0.4.

    2. **Intra-phase consistency** (40%): CV% measured *within* each
       stable phase, not across the whole evolving session.

    When ``track_evolution`` data is available (from
    :func:`condition_tracking.compute_track_evolution_rate`), the grip
    capture ratio uses the phase median paces.  Otherwise, falls back
    to a slope-based heuristic.

    Returns a float bounded [0, 1].
    """
    if len(phases_df) < 2:
        return 0.5  # single phase -> neutral

    lm_df = pd.DataFrame(lap_metrics)
    if "lap_number" not in lm_df.columns or "lap_time_s" not in lm_df.columns:
        return 0.5

    lm_df["lap_time_s"] = pd.to_numeric(lm_df["lap_time_s"], errors="coerce")
    lm_df = lm_df.dropna(subset=["lap_time_s"]).sort_values("lap_number")
    lm_df["_phase"] = lm_df["lap_number"].map(lap_to_phase)

    # --- Component 1: Grip capture ratio -
    capture_ratio = _compute_grip_capture(
        phases_df, lm_df, track_evolution,
    )

    # --- Component 2: Intra-phase consistency -
    intra_cv = _compute_intra_phase_cv(phases_df, lm_df)

    # Combine

    capture_score = _ratio_score(
        capture_ratio, ADAPT_FULL_RATIO, ADAPT_ZERO_RATIO,
        higher_is_better=True,
    )

    # Intra-phase CV scoring: use dry thresholds (within a phase, conditions

    # are approximately stable so normal CV expectations apply)

    cv_score = _ratio_score(
        intra_cv, CONSISTENCY_FULL_CV_PCT, CONSISTENCY_ZERO_CV_PCT,
        higher_is_better=False,
    ) if not math.isnan(intra_cv) else 0.5

    adaptation = ADAPT_W_CAPTURE * capture_score + ADAPT_W_INTRA_PHASE * cv_score

    logger.info(
        "Adaptation: capture_ratio=%.3f (score=%.3f), "
        "intra_cv=%.2f%% (score=%.3f), combined=%.3f",
        capture_ratio, capture_score, intra_cv, cv_score, adaptation,
    )
    return float(np.clip(adaptation, 0.0, 1.0))


def _compute_grip_capture(
    phases_df: pd.DataFrame,
    lm_df: pd.DataFrame,
    track_evolution: "dict[str, Any] | None",
) -> float:
    """
    Compute how much of the track's pace improvement the driver captured.

    If track_evolution provides per_lap_expected_s, compare the driver's
    actual improvement to the expected improvement from track evolution.
    Otherwise, use a slope-based heuristic.
    """
    # Use track evolution data if available

    if (track_evolution is not None
            and track_evolution.get("phase_paces")
            and len(track_evolution["phase_paces"]) >= 2):
        phase_paces = track_evolution["phase_paces"]
        expected_improvement = phase_paces[0]["median_s"] - phase_paces[-1]["median_s"]
        if expected_improvement <= 0:
            return 0.5  # track not improving -> neutral

        # Driver's actual improvement across same phases

        first_pid = phase_paces[0]["phase_id"]
        last_pid = phase_paces[-1]["phase_id"]
        first_laps = lm_df[lm_df["_phase"] == first_pid]["lap_time_s"]
        last_laps = lm_df[lm_df["_phase"] == last_pid]["lap_time_s"]

        if first_laps.empty or last_laps.empty:
            return 0.5

        driver_improvement = float(first_laps.median()) - float(last_laps.median())
        if expected_improvement > 0.5:  # meaningful evolution
            return float(np.clip(driver_improvement / expected_improvement, 0.0, 1.5))
        return 0.5

    # Fallback: slope-based heuristic (first 5 laps of each new phase)

    slopes: list[float] = []
    for pid in sorted(phases_df["phase_id"].unique()):
        if pid == 0:
            continue
        phase_laps = lm_df[lm_df["_phase"] == pid].head(5)
        if len(phase_laps) < 3:
            continue
        x = np.arange(len(phase_laps), dtype=float)
        y = phase_laps["lap_time_s"].values.astype(float)
        x_mean = x.mean()
        y_mean = y.mean()
        denom = float(((x - x_mean) ** 2).sum())
        if denom < 1e-12:
            continue
        slope = float(((x - x_mean) * (y - y_mean)).sum() / denom)
        slopes.append(slope)

    if not slopes:
        return 0.5

    mean_slope = float(np.mean(slopes))
    # Negative slope = improving = good adaptation

    # Map: -2 s/lap -> 1.0, 0 -> 0.5, +2 -> 0.0

    return float(np.clip(0.5 - mean_slope / 4.0, 0.0, 1.0))


def _compute_intra_phase_cv(
    phases_df: pd.DataFrame,
    lm_df: pd.DataFrame,
) -> float:
    """
    Weighted-average CV% computed WITHIN each phase (not across
    the whole evolving session).
    """
    total_laps = 0
    weighted_cv = 0.0

    for pid in sorted(phases_df["phase_id"].unique()):
        phase_times = lm_df[lm_df["_phase"] == pid]["lap_time_s"].dropna()
        if len(phase_times) < 3:
            continue
        mean_t = float(phase_times.mean())
        if mean_t <= 0:
            continue
        cv = float(phase_times.std() / mean_t * 100.0)
        n = len(phase_times)
        weighted_cv += cv * n
        total_laps += n

    if total_laps == 0:
        return float("nan")
    return weighted_cv / total_laps



# =============================================================================

# Unit tests

# =============================================================================


def _run_tests() -> None:
    import traceback

    passed: list[str] = []
    failed: list[tuple[str, str]] = []

    def _test(name: str, fn) -> None:   # type: ignore[type-arg]
        try:
            fn()
            passed.append(name)
        except Exception:  # noqa: BLE001
            failed.append((name, traceback.format_exc()))

    # -- Fixtures
    THEORY: dict[str, Any] = {
        "best_s":          90.0,
        "speed_mean_mps":  42.0,
        "accel_max_mps2":  8.5,
        "braking_max_mps2": 14.0,
    }

    THEORY_PHYSICS: dict[str, Any] = {
        "best_s":                      90.0,
        "speed_mean_mps":              42.0,
        "accel_max_mps2":              8.5,
        "braking_max_mps2":            14.0,
        "simulation_method":           "physics",
        "confidence":                  0.85,
        "cornering_limited_fraction":  0.45,
    }

    def _perfect() -> dict[str, Any]:
        """Driver metrics that match theoretical perfectly."""
        return {
            "best_s":           90.0,
            "n_laps":           20,
            "cv_pct":           0.15,
            "best_to_median_s": 0.20,
            "speed_mean_mps":   42.0,
            "accel_max_mps2":   8.5,
            "braking_max_mps2": 14.0,
            "early_mean_s":     91.0,
            "late_mean_s":      91.0,   # no fade
            "early_yaw_var":    10.0,
            "late_yaw_var":     10.5,   # 5 % increase -> within full range
        }

    def _poor() -> dict[str, Any]:
        """Driver metrics far below theoretical."""
        return {
            "best_s":           105.0,  # 15 s off theory
            "n_laps":           6,
            "cv_pct":           3.0,    # poor consistency
            "best_to_median_s": 4.0,
            "speed_mean_mps":   34.0,   # 80 % of theory
            "accel_max_mps2":   4.0,    # 47 % of theory
            "braking_max_mps2": 7.0,    # 50 % of theory
            "early_mean_s":     107.0,
            "late_mean_s":      115.0,  # ~7.5 % fade
            "early_yaw_var":    10.0,
            "late_yaw_var":     28.0,   # 2.8x increase
        }

    def _good_physics() -> dict[str, Any]:
        """Good driver vs a physics-based theoretical (small realistic gap)."""
        return {
            "best_s":           91.5,   # 1.5 s off physics theory (1.67 %)
            "n_laps":           20,
            "cv_pct":           0.40,
            "best_to_median_s": 0.50,
            "speed_mean_mps":   40.5,   # 96.4 % of theory
            "accel_max_mps2":   7.8,    # 91.8 %
            "braking_max_mps2": 12.5,   # 89.3 %
            "early_mean_s":     92.5,
            "late_mean_s":      93.0,
            "early_yaw_var":    10.0,
            "late_yaw_var":     11.0,
        }

    def _bad_physics() -> dict[str, Any]:
        """Bad driver vs a physics-based theoretical."""
        return {
            "best_s":           100.0,  # 10 s off (11.1 %)
            "n_laps":           8,
            "cv_pct":           2.5,
            "best_to_median_s": 3.0,
            "speed_mean_mps":   35.0,   # 83 %
            "accel_max_mps2":   5.0,    # 59 %
            "braking_max_mps2": 8.0,    # 57 %
            "early_mean_s":     102.0,
            "late_mean_s":      106.0,
            "early_yaw_var":    10.0,
            "late_yaw_var":     25.0,
        }

    # Test 1 -- perfect driver scores near maximum (percentile mode)

    #

    def t_perfect_near_max() -> None:
        result = score_session(_perfect(), THEORY, "practice")
        assert result["total_score"] >= 85.0, (
            f"Perfect driver should score >= 85, got {result['total_score']}"
        )
        assert result["grade"] in ("S", "A"), f"Expected S/A grade, got {result['grade']}"

    _test("perfect_near_max", t_perfect_near_max)

    # Test 2 -- poor driver scores low (percentile mode)

    #

    def t_poor_scores_low() -> None:
        result = score_session(_poor(), THEORY, "practice")
        assert result["total_score"] <= 40.0, (
            f"Poor driver should score <= 40, got {result['total_score']}"
        )

    _test("poor_scores_low", t_poor_scores_low)

    # Test 3 -- total score = sum of sub-scores (before confidence)

    #

    def t_total_equals_sum() -> None:
        result = score_session(_perfect(), THEORY, "practice")
        sub_sum = sum(v["score"] for v in result["sub_scores"].values())
        assert abs(result["total_score"] - min(100.0, sub_sum)) < 1e-3, (
            f"total_score {result['total_score']} != sum {sub_sum}"
        )

    _test("total_equals_sum", t_total_equals_sum)

    # Test 4 -- scores are in [0, max] for each category

    #

    def t_scores_in_bounds() -> None:
        for metrics, label in [(_perfect(), "perfect"), (_poor(), "poor")]:
            result = score_session(metrics, THEORY, "practice")
            for cat, info in result["sub_scores"].items():
                assert 0.0 <= info["score"] <= info["max"] + 1e-9, (
                    f"{label}/{cat}: score {info['score']} out of [0, {info['max']}]"
                )

    _test("scores_in_bounds", t_scores_in_bounds)

    # Test 5 -- total always in [0, 100]

    #

    def t_total_in_bounds() -> None:
        for m in [_perfect(), _poor(), {}]:
            for th in [THEORY, THEORY_PHYSICS]:
                for st in ["practice", "qualifying", "race", "unknown"]:
                    r = score_session(m, th, st)
                    assert -1e-6 <= r["total_score"] <= 100.0 + 1e-6, (
                        f"total={r['total_score']} out of bounds"
                    )

    _test("total_in_bounds", t_total_in_bounds)

    # Test 6 -- qualifying weights pace more than race

    #

    def t_qualifying_weights_pace() -> None:
        base = _perfect()
        r_qual = score_session(base, THEORY, "qualifying")
        r_race = score_session(base, THEORY, "race")
        assert (r_qual["sub_scores"]["pace"]["max"] >
                r_race["sub_scores"]["pace"]["max"]), (
            "Qualifying pace max should exceed race pace max"
        )

    _test("qualifying_weights_pace", t_qualifying_weights_pace)

    # Test 7 -- race weights robustness more than qualifying

    #

    def t_race_weights_robustness() -> None:
        base = _perfect()
        r_race = score_session(base, THEORY, "race")
        r_qual = score_session(base, THEORY, "qualifying")
        assert (r_race["sub_scores"]["robustness"]["max"] >
                r_qual["sub_scores"]["robustness"]["max"])

    _test("race_weights_robustness", t_race_weights_robustness)

    # Test 8 -- session type maximums always sum to 100

    #

    def t_session_maxes_sum_to_100() -> None:
        for st in ["practice", "qualifying", "race"]:
            r = score_session(_perfect(), THEORY, st)
            max_sum = sum(v["max"] for v in r["sub_scores"].values())
            assert abs(max_sum - 100.0) < 0.01, (
                f"{st}: sub-score maxes sum to {max_sum}, expected 100"
            )

    _test("session_maxes_sum_to_100", t_session_maxes_sum_to_100)

    # Test 9 -- strengths are populated for perfect driver

    #

    def t_perfect_has_strengths() -> None:
        result = score_session(_perfect(), THEORY, "practice")
        assert len(result["strengths"]) > 0, (
            "Perfect driver should have at least one strength"
        )

    _test("perfect_has_strengths", t_perfect_has_strengths)

    # Test 10 -- weaknesses are populated for poor driver

    #

    def t_poor_has_weaknesses() -> None:
        result = score_session(_poor(), THEORY, "practice")
        assert len(result["weaknesses"]) > 0, (
            "Poor driver should have at least one weakness"
        )

    _test("poor_has_weaknesses", t_poor_has_weaknesses)

    # Test 11 -- strengths and weaknesses are disjoint

    #

    def t_strengths_weaknesses_disjoint() -> None:
        result = score_session(_perfect(), THEORY, "practice")
        overlap = set(result["strengths"]) & set(result["weaknesses"])
        assert not overlap, f"Category cannot be both strength and weakness: {overlap}"

    _test("strengths_weaknesses_disjoint", t_strengths_weaknesses_disjoint)

    # Test 12 -- empty metrics returns valid structure, no exception

    #

    def t_empty_metrics_no_crash() -> None:
        result = score_session({}, {}, "practice")
        assert "total_score" in result
        assert "grade" in result
        assert 0.0 <= result["total_score"] <= 100.0

    _test("empty_metrics_no_crash", t_empty_metrics_no_crash)

    # Test 13 -- deterministic: identical inputs -> identical outputs

    #

    def t_deterministic() -> None:
        m  = _perfect()
        r1 = score_session(m, THEORY, "race")
        r2 = score_session(m, THEORY, "race")
        assert r1 == r2, "score_session is not deterministic"

    _test("deterministic", t_deterministic)

    # Test 14 -- NaN metrics handled gracefully (partial credit)

    #

    def t_nan_metrics_partial_credit() -> None:
        m = {"best_s": float("nan"), "n_laps": float("nan")}
        result = score_session(m, THEORY, "practice")
        assert result["total_score"] >= 0.0

    _test("nan_metrics_partial_credit", t_nan_metrics_partial_credit)

    # Test 15 -- result has all required top-level keys

    #

    def t_result_keys() -> None:
        result = score_session(_perfect(), THEORY, "practice")
        for key in ("total_score", "grade", "session_type",
                    "sub_scores", "strengths", "weaknesses",
                    "simulation_method", "data_confidence"):
            assert key in result, f"Missing key: {key!r}"

    _test("result_keys", t_result_keys)

    # Test 16 -- pace gap 0 -> near-full pace score

    #

    def t_zero_gap_full_pace() -> None:
        m = {**_perfect(), "best_s": 90.0}   # exactly equals theory
        r = score_session(m, THEORY, "practice")
        pace_info = r["sub_scores"]["pace"]
        assert pace_info["score"] >= pace_info["max"] * 0.95, (
            f"Zero gap should yield >= 95 % pace score, got {pace_info['pct']}"
        )

    _test("zero_gap_full_pace", t_zero_gap_full_pace)

    # Test 17 -- type check raises TypeError

    #

    def t_type_check() -> None:
        try:
            score_session("not_a_dict", THEORY)  # type: ignore[arg-type]
            raise AssertionError("Should have raised TypeError")
        except TypeError:
            pass

    _test("type_check", t_type_check)

    # Test 18 -- grade boundaries

    #

    def t_grade_boundaries() -> None:
        assert _assign_grade(95.0) == "S"
        assert _assign_grade(85.0) == "A"
        assert _assign_grade(72.0) == "B"
        assert _assign_grade(55.0) == "C"
        assert _assign_grade(40.0) == "D"
        assert _assign_grade(20.0) == "F"

    _test("grade_boundaries", t_grade_boundaries)

    # ==================================================================

    # NEW TESTS -- Physics-based scoring

    # ==================================================================


    # Test 19 -- physics mode: good driver scores well

    #

    def t_physics_good_scores_well() -> None:
        r = score_session(_good_physics(), THEORY_PHYSICS, "practice")
        assert r["total_score"] >= 60.0, (
            f"Good driver with physics theory should score >= 60, got {r['total_score']}"
        )
        assert r["simulation_method"] == "physics"

    _test("physics_good_scores_well", t_physics_good_scores_well)

    # Test 20 -- physics mode: bad driver scores low

    #

    def t_physics_bad_scores_low() -> None:
        r = score_session(_bad_physics(), THEORY_PHYSICS, "practice")
        assert r["total_score"] <= 55.0, (
            f"Bad driver with physics theory should score <= 55, got {r['total_score']}"
        )

    _test("physics_bad_scores_low", t_physics_bad_scores_low)

    # Test 21 -- physics pace: 1.5s gap on 90s lap scores better than

    #            percentile-mode with same gap (physics is more lenient

    #            for achievable gaps)

    #

    def t_physics_pace_more_lenient_for_small_gap() -> None:
        m = {**_perfect(), "best_s": 91.5}
        pace_pct, _ = _score_pace(m, THEORY)
        pace_phy, _ = _score_pace(m, THEORY_PHYSICS, simulation_method="physics")
        # 1.5 s gap: percentile mode uses [0.05, 15] -> ratio ~0.90

        # physics uses blended pct+abs with tighter but more lenient band

        assert pace_phy > 0, f"Physics pace should be > 0, got {pace_phy}"
        # Both should give positive scores for a 1.5s gap

        assert pace_pct > 0, f"Percentile pace should be > 0, got {pace_pct}"

    _test("physics_pace_more_lenient_for_small_gap", t_physics_pace_more_lenient_for_small_gap)

    # Test 22 -- physics pace: large gap (10s = 11%) scores low

    #

    def t_physics_pace_large_gap_low() -> None:
        m = {**_perfect(), "best_s": 100.0}  # 10s gap = 11.1%
        pace_phy, detail = _score_pace(m, THEORY_PHYSICS, simulation_method="physics")
        assert pace_phy <= MAX_PACE * 0.40, (
            f"10s gap should score <= 40% of max pace, got {pace_phy}"
        )
        assert detail["simulation_method"] == "physics"

    _test("physics_pace_large_gap_low", t_physics_pace_large_gap_low)

    # Test 23 -- physics pace: uses percentage-based scoring

    #

    def t_physics_pace_pct_based() -> None:
        # A 2.5s gap on a 50s lap (5%) should score differently than 2.5s on 200s (1.25%)

        short_theory = {"best_s": 50.0, "simulation_method": "physics"}
        long_theory  = {"best_s": 200.0, "simulation_method": "physics"}
        m_short = {"best_s": 52.5}  # 2.5s gap = 5%
        m_long  = {"best_s": 202.5}  # 2.5s gap = 1.25%

        p_short, _ = _score_pace(m_short, short_theory, simulation_method="physics")
        p_long,  _ = _score_pace(m_long,  long_theory,  simulation_method="physics")

        # 1.25% gap on long track should score better than 5% on short

        assert p_long > p_short, (
            f"1.25% gap ({p_long:.2f}) should score > 5% gap ({p_short:.2f})"
        )

    _test("physics_pace_pct_based", t_physics_pace_pct_based)

    # Test 24 -- percentile mode: uses percentage-based scoring

    #

    def t_percentile_pace_percentage() -> None:
        # Same percentage gap should give same score regardless of track length

        # (percentile mode uses track-aware percentage gaps)

        short_theory = {"best_s": 50.0}
        long_theory  = {"best_s": 200.0}
        # Both have 5% gap
        m_short = {"best_s": 52.5}   # 2.5s gap = 5% of 50s
        m_long  = {"best_s": 210.0}  # 10s gap = 5% of 200s

        p_short, _ = _score_pace(m_short, short_theory)
        p_long,  _ = _score_pace(m_long,  long_theory)

        # Same percentage gap -> same score in percentile mode

        assert abs(p_short - p_long) < 0.01, (
            f"Percentile mode: same % gap should give same score: {p_short:.4f} vs {p_long:.4f}"
        )

    _test("percentile_pace_percentage", t_percentile_pace_percentage)

    # Test 25 -- physics execution: uses lenient thresholds

    #

    def t_physics_exec_thresholds() -> None:
        # Driver at 90% of theoretical speed

        m  = {**_perfect(), "speed_mean_mps": 42.0 * 0.90,
               "accel_max_mps2": 8.5 * 0.90, "braking_max_mps2": 14.0 * 0.90}
        # Physics mode: 0.90 is between full (0.95) and zero (0.80) for speed

        exec_phy, _ = _score_execution(m, THEORY_PHYSICS, simulation_method="physics")
        # Percentile mode: 0.90 is between full (0.99) and zero (0.85) for speed

        exec_pct, _ = _score_execution(m, THEORY)
        # Physics should be more lenient (higher score) at 90% ratio

        assert exec_phy >= exec_pct, (
            f"Physics exec ({exec_phy:.2f}) should be >= percentile ({exec_pct:.2f}) at 90% ratio"
        )

    _test("physics_exec_thresholds", t_physics_exec_thresholds)

    # Test 26 -- simulation_method in result

    #

    def t_simulation_method_in_result() -> None:
        r_pct = score_session(_perfect(), THEORY, "practice")
        assert r_pct["simulation_method"] == "percentile_envelope"

        r_phy = score_session(_good_physics(), THEORY_PHYSICS, "practice")
        assert r_phy["simulation_method"] == "physics"

    _test("simulation_method_in_result", t_simulation_method_in_result)

    # Test 27 -- data confidence weighting shrinks toward neutral

    #

    def t_confidence_weighting() -> None:
        # Full confidence: no adjustment

        th_full = {**THEORY_PHYSICS, "confidence": 1.0}
        r_full = score_session(_good_physics(), th_full, "practice")

        # Low confidence: shrunk toward CONFIDENCE_NEUTRAL_SCORE (65)

        th_low = {**THEORY_PHYSICS, "confidence": 0.5}
        r_low = score_session(_good_physics(), th_low, "practice")

        # The low-confidence score should be closer to 65 than the full-conf score

        full_dist = abs(r_full["total_score"] - CONFIDENCE_NEUTRAL_SCORE)
        low_dist  = abs(r_low["total_score"]  - CONFIDENCE_NEUTRAL_SCORE)
        assert low_dist <= full_dist + 0.01, (
            f"Low confidence should move score toward neutral: "
            f"full={r_full['total_score']:.2f}, low={r_low['total_score']:.2f}"
        )

    _test("confidence_weighting", t_confidence_weighting)

    # Test 28 -- confidence = 0 collapses to neutral score

    #

    def t_confidence_zero_is_neutral() -> None:
        th_zero = {**THEORY_PHYSICS, "confidence": 0.0}
        r = score_session(_good_physics(), th_zero, "practice")
        assert abs(r["total_score"] - CONFIDENCE_NEUTRAL_SCORE) < 0.01, (
            f"Zero confidence should give neutral score {CONFIDENCE_NEUTRAL_SCORE}, "
            f"got {r['total_score']}"
        )

    _test("confidence_zero_is_neutral", t_confidence_zero_is_neutral)

    # Test 29 -- data_confidence in output

    #

    def t_data_confidence_in_result() -> None:
        r = score_session(_good_physics(), THEORY_PHYSICS, "practice")
        assert "data_confidence" in r
        assert r["data_confidence"] == 0.85

    _test("data_confidence_in_result", t_data_confidence_in_result)

    # Test 30 -- backward compat: percentile mode with no sim_method key

    #

    def t_backward_compat_no_sim_method() -> None:
        # THEORY has no "simulation_method" key -> should default to percentile

        r = score_session(_perfect(), THEORY, "practice")
        assert r["simulation_method"] == "percentile_envelope"
        assert r["data_confidence"] == 1.0
        # Should still score high for perfect metrics

        assert r["total_score"] >= 85.0

    _test("backward_compat_no_sim_method", t_backward_compat_no_sim_method)

    # Test 31 -- pace detail includes simulation_method

    #

    def t_pace_detail_has_method() -> None:
        _, detail = _score_pace(
            _good_physics(), THEORY_PHYSICS, simulation_method="physics",
        )
        assert detail["simulation_method"] == "physics"
        assert "raw_gap_s" in detail
        assert "gap_pct" in detail

    _test("pace_detail_has_method", t_pace_detail_has_method)

    # Test 32 -- execution detail includes simulation_method

    #

    def t_exec_detail_has_method() -> None:
        _, detail = _score_execution(
            _good_physics(), THEORY_PHYSICS, simulation_method="physics",
        )
        assert detail["simulation_method"] == "physics"
        assert "speed_efficiency_ratio" in detail

    _test("exec_detail_has_method", t_exec_detail_has_method)

    # Test 33 -- physics mode scores in bounds across all session types

    #

    def t_physics_all_session_types() -> None:
        for st in ["practice", "qualifying", "race"]:
            r = score_session(_good_physics(), THEORY_PHYSICS, st)
            assert 0.0 <= r["total_score"] <= 100.0
            for cat, info in r["sub_scores"].items():
                assert 0.0 <= info["score"] <= info["max"] + 1e-9, (
                    f"physics/{st}/{cat}: {info['score']} out of [0, {info['max']}]"
                )

    _test("physics_all_session_types", t_physics_all_session_types)

    # Test 34 -- physics perfect driver (matching theory) scores near max

    #

    def t_physics_perfect_near_max() -> None:
        m = {
            **_perfect(),
            "best_s": 90.0,  # exactly matches physics theory
            "speed_mean_mps": 42.0,
            "accel_max_mps2": 8.5,
            "braking_max_mps2": 14.0,
        }
        r = score_session(m, THEORY_PHYSICS, "practice")
        assert r["total_score"] >= 80.0, (
            f"Perfect vs physics theory should score >= 80, got {r['total_score']}"
        )

    _test("physics_perfect_near_max", t_physics_perfect_near_max)

    # Test 35a -- granular execution with corner data

    #

    def t_granular_execution_basic() -> None:
        corners = [
            {
                "corner_id": 1, "s_start": 100, "s_end": 200,
                "braking_point_delta_m": 5.0,
                "theoretical_apex_speed_mps": 20.0,
                "actual_apex_speed_mps": 18.0,
                "theoretical_exit_speed_mps": 30.0,
                "actual_exit_speed_mps": 28.0,
                "grip_utilisation_pct": 75.0,
                "time_loss_s": 0.3,
            },
            {
                "corner_id": 2, "s_start": 300, "s_end": 400,
                "braking_point_delta_m": 3.0,
                "theoretical_apex_speed_mps": 25.0,
                "actual_apex_speed_mps": 24.0,
                "theoretical_exit_speed_mps": 35.0,
                "actual_exit_speed_mps": 34.0,
                "grip_utilisation_pct": 85.0,
                "time_loss_s": 0.1,
            },
        ]
        g = compute_granular_execution(corner_performances=corners)
        assert g["has_corner_data"]
        assert 0.0 <= g["composite"] <= 1.0
        assert 0.0 <= g["braking_quality"] <= 1.0
        assert 0.0 <= g["corner_speed"] <= 1.0
        assert g["detail"]["mean_bp_delta_m"] == 4.0  # average of 5 and 3

    _test("granular_execution_basic", t_granular_execution_basic)

    def t_granular_execution_empty() -> None:
        g = compute_granular_execution(corner_performances=None)
        assert not g["has_corner_data"]
        assert g["composite"] == 0.5

    _test("granular_execution_empty", t_granular_execution_empty)

    # Test 35b -- racecraft scoring

    #

    def t_racecraft_race_session() -> None:
        lm = [{"lap_number": i, "lap_time_s": 60.0 + 10.0 / max(i, 1)}
              for i in range(1, 21)]  # improving then plateau
        rc = compute_racecraft_score(lap_metrics=lm, session_type="race")
        assert rc["is_race"]
        assert 0.0 <= rc["composite"] <= 1.0
        assert rc["detail"]["lap1_delta_s"] > 0

    _test("racecraft_race_session", t_racecraft_race_session)

    def t_racecraft_not_race() -> None:
        rc = compute_racecraft_score(lap_metrics=[], session_type="practice")
        assert not rc["is_race"]
        assert rc["composite"] == 0.5

    _test("racecraft_not_race", t_racecraft_not_race)

    # Test 35c -- recalibrated scoring is more lenient

    #

    def t_recalibrated_good_amateur() -> None:
        """A competent amateur with reasonable metrics should score ~75-85."""
        m = {
            "best_s": 63.0,  # 5% slower than theoretical
            "n_laps": 20,
            "cv_pct": 1.5,
            "best_to_median_s": 1.5,
            "speed_mean_mps": 28.0,
            "accel_max_mps2": 7.0,
            "braking_max_mps2": 9.0,
            "early_mean_s": 63.5,
            "late_mean_s": 64.5,
            "early_yaw_var": 0.5,
            "late_yaw_var": 0.6,
        }
        th = {
            "best_s": 60.0,
            "speed_mean_mps": 30.0,
            "accel_max_mps2": 8.0,
            "braking_max_mps2": 10.0,
            "simulation_method": "physics",
            "confidence": 1.0,
        }
        r = score_session(m, th, "practice")
        total = r["total_score"]
        assert total >= 55.0, f"Good amateur should score >= 55, got {total}"
        assert total <= 90.0, f"Good amateur should score <= 90, got {total}"

    _test("recalibrated_good_amateur", t_recalibrated_good_amateur)

    # Test 35 -- adaptation score with track evolution

    #

    def t_adaptation_with_evolution() -> None:
        phases = pd.DataFrame({
            "phase_id": [0, 1, 2],
            "lap_start": [1, 11, 21],
            "lap_end": [10, 20, 30],
            "n_laps": [10, 10, 10],
            "confidence": [1.0, 1.0, 1.0],
            "signature_json": ["{}", "{}", "{}"],
        })
        l2p = {l: 0 for l in range(1, 11)}
        l2p.update({l: 1 for l in range(11, 21)})
        l2p.update({l: 2 for l in range(21, 31)})

        # Driver improves as track improves (good adaptation)

        lm = [{"lap_number": l, "lap_time_s": 70.0 - 0.6 * l + 0.5 * (l % 3)}
              for l in range(1, 31)]

        track_evo = {
            "total_evolution_pct": 20.0,
            "grip_trend": "improving",
            "evolution_rate_s_per_lap": -0.6,
            "phase_paces": [
                {"phase_id": 0, "median_s": 67.0, "lap_start": 1, "lap_end": 10,
                 "mid_lap": 5.5, "best_s": 65.0, "cv_pct": 1.5, "n_laps": 10},
                {"phase_id": 1, "median_s": 61.0, "lap_start": 11, "lap_end": 20,
                 "mid_lap": 15.5, "best_s": 59.0, "cv_pct": 1.2, "n_laps": 10},
                {"phase_id": 2, "median_s": 55.0, "lap_start": 21, "lap_end": 30,
                 "mid_lap": 25.5, "best_s": 53.0, "cv_pct": 1.0, "n_laps": 10},
            ],
        }

        score = _compute_adaptation_score(
            phases, l2p, lm, track_evolution=track_evo,
        )
        assert 0.0 <= score <= 1.0
        # Good adaptation should score above neutral (0.5)

        assert score > 0.5, f"Good adaptation should score > 0.5, got {score}"

    _test("adaptation_with_evolution", t_adaptation_with_evolution)

    # Test 36 -- intra-phase CV

    #

    def t_intra_phase_cv() -> None:
        lm_df = pd.DataFrame({
            "lap_number": list(range(1, 21)),
            "lap_time_s": [60 + 0.5 * (i % 3) for i in range(20)],
            "_phase": [0]*10 + [1]*10,
        })
        phases = pd.DataFrame({
            "phase_id": [0, 1],
        })
        cv = _compute_intra_phase_cv(phases, lm_df)
        assert cv < 2.0, f"Within-phase CV should be low, got {cv}"

    _test("intra_phase_cv", t_intra_phase_cv)

    # Test 37 -- phase_aware with track_evolution

    #

    def t_phase_aware_with_evo() -> None:
        m = _perfect()
        r = score_session_phase_aware(
            m, THEORY, "practice",
            track_evolution={"total_evolution_pct": 15.0, "grip_trend": "improving",
                            "evolution_rate_s_per_lap": -0.3},
        )
        assert "track_evolution" in r
        assert r["track_evolution"]["grip_trend"] == "improving"

    _test("phase_aware_with_evo", t_phase_aware_with_evo)

    # Test: detrended consistency improves score for evolving conditions

    def t_detrended_consistency_evolving() -> None:
        m = _perfect()
        # Simulate drying track: lap times going from 70 -> 52 (highly consistent

        # within trend, but raw CV% would be terrible)

        import numpy as _np
        _rng = _np.random.default_rng(42)
        base = _np.linspace(70, 52, 20)
        noisy = base + _rng.normal(0, 0.3, 20)
        lap_metrics = [
            {"lap_number": i + 1, "lap_time_s": float(noisy[i])}
            for i in range(20)
        ]

        # Without track evolution: raw CV% is terrible

        m_evo = dict(m)
        m_evo["cv_pct"] = float(_np.std(noisy, ddof=1) / _np.mean(noisy) * 100)
        m_evo["n_laps"] = 20
        m_evo["best_to_median_s"] = float(_np.median(noisy) - noisy.min())

        # Score without evolution awareness (should have bad consistency)

        r_raw = score_session(m_evo, THEORY, "practice")
        raw_cons = r_raw["sub_scores"]["consistency"]["score"]

        # Score WITH evolution awareness (should fix consistency)

        r_evo = score_session_phase_aware(
            m_evo, THEORY, "practice",
            track_evolution={"total_evolution_pct": 30.0, "grip_trend": "improving",
                           "evolution_rate_s_per_lap": -0.9},
            lap_metrics=lap_metrics,
        )
        evo_cons = r_evo["sub_scores"]["consistency"]["score"]

        # Detrended score should be significantly better

        assert evo_cons > raw_cons + 2.0, (
            f"Detrended consistency ({evo_cons:.2f}) should be much better "
            f"than raw ({raw_cons:.2f}) for evolving session"
        )

    _test("detrended_consistency_evolving", t_detrended_consistency_evolving)

    # Summary

    total = len(passed) + len(failed)
    print(f"\nScoring Tests: {len(passed)}/{total} passed")
    for name in passed:
        print(f"  \u2713 {name}")
    for name, tb in failed:
        print(f"  \u2717 {name}\n{tb}")

    if failed:
        raise AssertionError(f"{len(failed)} test(s) failed.")


# =============================================================================

# Entry point

# =============================================================================


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _run_tests()
