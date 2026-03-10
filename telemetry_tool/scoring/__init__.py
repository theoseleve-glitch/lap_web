"""
scoring
~~~~~~~
Modular session performance scoring.

Backward-compatible re-exports so that existing code using
``from scoring import score_session`` continues to work.
"""
# _compute_phase_scores is in adaptation module for grouping
from scoring.adaptation import (
    _compute_adaptation_score,
    _compute_grip_capture,
    _compute_intra_phase_cv,
    _compute_phase_scores,
    _score_adaptation_v2,
)
from scoring.badges import evaluate_badges
from scoring.consistency import _score_consistency
from scoring.constants import *  # noqa: F401,F403 — all constants
from scoring.constants import (
    _CONSISTENCY_THRESHOLDS_BY_TYPE,
    _SESSION_CATEGORY_CONFIG,
    _SESSION_TYPE_SYNONYMS,
    _SESSION_WEIGHT_OVERRIDES,
    _TRACK_STATE_MODIFIERS,
    ScoringError,
)
from scoring.execution import (
    _score_execution,
    compute_granular_execution,
    enhance_execution_with_controls,
)
from scoring.helpers import (
    _apply_confidence,
    _assign_grade,
    _clamp01,
    _get,
    _normalize_session_type,
    _ratio_score,
)
from scoring.pace import _score_pace
from scoring.phase_aware import score_session_phase_aware
from scoring.racecraft import compute_racecraft_score
from scoring.robustness import _score_robustness
from scoring.scorer import _apply_adaptive_weights, _apply_session_weights, score_session

__all__ = [
    # Public API
    "score_session",
    "score_session_phase_aware",
    "evaluate_badges",
    "compute_granular_execution",
    "enhance_execution_with_controls",
    "compute_racecraft_score",
    "ScoringError",
    # Constants (re-exported via wildcard)
    "MAX_PACE",
    "MAX_CONSISTENCY",
    "MAX_EXECUTION",
    "MAX_ROBUSTNESS",
    "MAX_ADAPTATION",
    "TOTAL_MAX",
    # Internal (used by tests)
    "_score_pace",
    "_score_consistency",
    "_score_execution",
    "_score_robustness",
    "_score_adaptation_v2",
    "_ratio_score",
    "_apply_session_weights",
    "_apply_adaptive_weights",
    "_SESSION_WEIGHT_OVERRIDES",
    "_SESSION_CATEGORY_CONFIG",
    "_TRACK_STATE_MODIFIERS",
    "_CONSISTENCY_THRESHOLDS_BY_TYPE",
]
