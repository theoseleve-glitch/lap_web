"""Scoring helpers — shared utility functions used by all scorer modules."""
from __future__ import annotations

import logging
import math
from typing import Any

from scoring.constants import (
    CONFIDENCE_NEUTRAL_SCORE,
    GRADE_A,
    GRADE_B,
    GRADE_C,
    GRADE_D,
    GRADE_S,
)

logger = logging.getLogger(__name__)


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
