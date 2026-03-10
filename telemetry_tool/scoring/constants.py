"""Scoring constants — weights, thresholds, and grade boundaries."""

from __future__ import annotations

from typing import Final

# =============================================================================
# WEIGHT CONSTANTS  (category maximums --  must sum to 100)
# =============================================================================

MAX_PACE:        Final[float] = 25.0
MAX_CONSISTENCY: Final[float] = 25.0
MAX_EXECUTION:   Final[float] = 20.0
MAX_ROBUSTNESS:  Final[float] = 15.0
MAX_ADAPTATION:  Final[float] = 15.0
TOTAL_MAX:       Final[float] = MAX_PACE + MAX_CONSISTENCY + MAX_EXECUTION + MAX_ROBUSTNESS + MAX_ADAPTATION  # 100.0

# =============================================================================
# PACE SCORING CONSTANTS
# =============================================================================

# Gap (seconds) -- DEPRECATED: replaced by percentage-based ENVELOPE_*_GAP_PCT
# Kept for backward compatibility; no longer used in _score_pace().
PACE_ZERO_GAP_S: Final[float] = 15.0
PACE_FULL_GAP_S: Final[float] = 0.05

# Exponent for the pace decay curve (1.0 = linear, >1 = more forgiving near peak)
PACE_DECAY_EXP:  Final[float] = 1.6

# --- Physics-based theoretical lap thresholds (achievable ideal) ---
# When the theoretical lap comes from a physics simulation, the gap is
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

# Coefficient of Variation (std/mean * 100) at which consistency score = 0
# Racing: CV > 2 % is considered poor; CV < 0.3 % is elite
CONSISTENCY_ZERO_CV_PCT:  Final[float] = 3.0
CONSISTENCY_FULL_CV_PCT:  Final[float] = 0.60

# Best-to-median gap (s) at which consistency bonus is saturated
CONSISTENCY_BTM_FULL_S:   Final[float] = 0.60
CONSISTENCY_BTM_ZERO_S:   Final[float] = 5.00

# Wet-session thresholds (wider band -- higher variability is expected)
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
EXEC_SPEED_FULL_RATIO:  Final[float] = 0.99   # 99 % = full marks
EXEC_SPEED_ZERO_RATIO:  Final[float] = 0.85   # 85 % = zero marks

# Acceleration efficiency: comparison vs theoretical accel peak ratio
EXEC_ACCEL_FULL_RATIO:  Final[float] = 0.95
EXEC_ACCEL_ZERO_RATIO:  Final[float] = 0.60

# Braking efficiency: comparison vs theoretical brake peak ratio
EXEC_BRAKE_FULL_RATIO:  Final[float] = 0.95
EXEC_BRAKE_ZERO_RATIO:  Final[float] = 0.60

# --- Physics-based execution thresholds ---
# When the theoretical lap is from a physics simulation, the reference values
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
ROBUST_FADE_FULL:  Final[float] = 0.010   # 0.5 % fade = full marks
ROBUST_FADE_ZERO:  Final[float] = 0.050   # 5 % fade = zero marks

# Stability: yaw-rate variance ratio (late laps / early laps)
ROBUST_YAW_FULL:   Final[float] = 1.10    # 10 % increase = full marks
ROBUST_YAW_ZERO:   Final[float] = 2.50    # 150 % increase = zero marks

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

# --- Adaptation V2 scoring constants (weather-aware) ---
ADAPT_V2_TRANSITION_FULL_LAPS: Final[float] = 2.0
ADAPT_V2_TRANSITION_ZERO_LAPS: Final[float] = 8.0
ADAPT_V2_TRANSITION_WEIGHT:    Final[float] = 0.40
ADAPT_V2_PHASE_PACE_FULL_PCT:  Final[float] = 3.0
ADAPT_V2_PHASE_PACE_ZERO_PCT:  Final[float] = 12.0
ADAPT_V2_PHASE_PACE_WEIGHT:    Final[float] = 0.35
ADAPT_V2_TECHNIQUE_WEIGHT:     Final[float] = 0.25
ADAPT_V2_STABLE_DEFAULT_FRAC:  Final[float] = 0.75
ADAPT_V2_DECAY_EXP:            Final[float] = 1.4

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

GRADE_S: Final[float] = 90.0
GRADE_A: Final[float] = 78.0
GRADE_B: Final[float] = 63.0
GRADE_C: Final[float] = 48.0
GRADE_D: Final[float] = 33.0
# below GRADE_D = F

# Threshold at which a sub-score is labelled a "strength" (fraction of max)
STRENGTH_THRESHOLD: Final[float] = 0.80
# Threshold at which a sub-score is labelled a "weakness" (fraction of max)
WEAKNESS_THRESHOLD: Final[float] = 0.50

# Badge tier thresholds (fraction of category max)
BADGE_TIER_BRONZE: Final[float] = 0.60
BADGE_TIER_SILVER: Final[float] = 0.75
BADGE_TIER_GOLD:   Final[float] = 0.90

# --- Data confidence weighting ---
# When data quality is low (confidence < 1.0), the total score is shrunk
# toward a neutral midpoint to avoid misleading high/low scores.
CONFIDENCE_NEUTRAL_SCORE: Final[float] = 65.0

# =============================================================================
# SESSION-TYPE CATEGORY CONFIG (suppression + emphasis)
# =============================================================================
# Replaces the old flat _SESSION_WEIGHT_OVERRIDES.
# - "suppressed": categories zeroed out, budget redistributed
# - "emphasis": multipliers on surviving categories (default 1.0)

_SESSION_CATEGORY_CONFIG: dict[str, dict] = {
    "qualifying": {
        "suppressed": {"consistency", "robustness", "adaptation"},
        "emphasis":   {"pace": 1.6, "execution": 1.4},
    },
    "race": {
        "suppressed": set(),
        "emphasis":   {"robustness": 1.4, "adaptation": 1.2},
    },
    "practice": {
        "suppressed": {"robustness"},
        "emphasis":   {"adaptation": 1.4, "execution": 1.2},
    },
    "warmup": {
        "suppressed": {"pace", "robustness"},
        "emphasis":   {"execution": 1.3, "adaptation": 1.2},
    },
    "test": {
        "suppressed": {"pace", "robustness"},
        "emphasis":   {"execution": 1.3, "consistency": 1.2},
    },
    "endurance": {
        "suppressed": set(),
        "emphasis":   {"robustness": 1.6},
    },
    "endurance_stint": {
        "suppressed": set(),
        "emphasis":   {"robustness": 1.6},
    },
    "endurance_race": {
        "suppressed": set(),
        "emphasis":   {"robustness": 1.6},
    },
    "heat": {
        "suppressed": {"consistency"},
        "emphasis":   {"pace": 1.4, "execution": 1.2},
    },
    "final": {
        "suppressed": set(),
        "emphasis":   {"pace": 1.2, "robustness": 1.1},
    },
    "sprint": {
        "suppressed": {"consistency"},
        "emphasis":   {"pace": 1.3, "execution": 1.2},
    },
    "sprint_race": {
        "suppressed": {"consistency"},
        "emphasis":   {"pace": 1.3, "execution": 1.2},
    },
    "feature_race": {
        "suppressed": set(),
        "emphasis":   {"robustness": 1.4, "adaptation": 1.2},
    },
}

# Backward compat: build _SESSION_WEIGHT_OVERRIDES from the new config
# so any code still importing it gets a reasonable dict.
_SESSION_WEIGHT_OVERRIDES: dict[str, dict[str, float]] = {}
for _stype, _cfg in _SESSION_CATEGORY_CONFIG.items():
    _w: dict[str, float] = {}
    for _cat in ("pace", "consistency", "execution", "robustness", "adaptation"):
        if _cat in _cfg["suppressed"]:
            _w[_cat] = 0.0
        else:
            _w[_cat] = _cfg["emphasis"].get(_cat, 1.0)
    _SESSION_WEIGHT_OVERRIDES[_stype] = _w

# =============================================================================
# TRACK-STATE WEIGHT MODIFIERS
# =============================================================================
# Applied multiplicatively on top of session-type weights (surviving categories).

_TRACK_STATE_MODIFIERS: dict[str, dict[str, float]] = {
    "dry":      {},
    "damp":     {"adaptation": 1.10, "robustness": 1.05, "pace": 0.95},
    "wet":      {"adaptation": 1.15, "robustness": 1.10, "pace": 0.90, "execution": 0.95},
    "full_wet": {"adaptation": 1.20, "robustness": 1.15, "pace": 0.85, "execution": 0.90},
    "drying":   {"adaptation": 1.20, "pace": 0.90},
    "greasy":   {"adaptation": 1.10, "robustness": 1.05, "pace": 0.95},
}

# =============================================================================
# DIMINISHING RETURNS CONSTANTS
# =============================================================================
# Asymptotic log curve: factor = max(floor, 1.0 - k * ln(1 + laps / L0))

DR_EXP_K:     Final[float] = 0.005    # experience decay rate
DR_EXP_L0:    Final[float] = 1000.0   # reference lap count
DR_EXP_FLOOR: Final[float] = 0.96     # per-factor floor

DR_SES_K:     Final[float] = 0.004    # session laps decay rate
DR_SES_L0:    Final[float] = 30.0     # reference (typical short session)
DR_SES_FLOOR: Final[float] = 0.96     # per-factor floor

DR_COMBINED_FLOOR: Final[float] = 0.92  # absolute floor for combined multiplier

# Synonyms: map alternative type names to canonical keys
_SESSION_TYPE_SYNONYMS: dict[str, str] = {
    "sprint_race": "sprint_race",
    "feature_race": "feature_race",
    "endurance_stint": "endurance_stint",
    "endurance_race": "endurance_race",
}

# =============================================================================
# SESSION-TYPE CONSISTENCY THRESHOLDS
# =============================================================================

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

# =============================================================================
# BASE MAXIMUMS (derived from weight constants above)
# =============================================================================

_BASE_MAXES: dict[str, float] = {
    "pace":        MAX_PACE,
    "consistency": MAX_CONSISTENCY,
    "execution":   MAX_EXECUTION,
    "robustness":  MAX_ROBUSTNESS,
    "adaptation":  MAX_ADAPTATION,
}

# =============================================================================
# Exceptions
# =============================================================================


class ScoringError(ValueError):
    """Raised when required metrics keys are absent or values are invalid."""
