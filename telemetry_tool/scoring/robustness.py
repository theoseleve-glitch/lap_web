"""Robustness scorer — pace retention and stability over a stint."""
from __future__ import annotations

import logging
import math
from typing import Any

from scoring.constants import (
    MAX_ROBUSTNESS,
    ROBUST_FADE_FULL,
    ROBUST_FADE_ZERO,
    ROBUST_W_FADE,
    ROBUST_W_STABILITY,
    ROBUST_YAW_FULL,
    ROBUST_YAW_ZERO,
)
from scoring.helpers import _get, _ratio_score

logger = logging.getLogger(__name__)


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
        stability_basis = "measured"
    else:
        stability_r = 0.5
        yaw_ratio   = float("nan")
        stability_basis = "neutral_no_yaw"

    composite = ROBUST_W_FADE * fade_r + ROBUST_W_STABILITY * stability_r
    score     = round(composite * MAX_ROBUSTNESS, 4)

    return score, {
        "pace_fade_frac":  round(fade_frac, 6) if not math.isnan(fade_frac) else None,
        "yaw_var_ratio":   round(yaw_ratio, 4) if not math.isnan(yaw_ratio)  else None,
        "fade_ratio":      round(fade_r,    4),
        "stability_ratio": round(stability_r, 4),
        "stability_basis": stability_basis,
        "n_laps":          n_laps,
    }
