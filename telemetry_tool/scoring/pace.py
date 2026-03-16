"""Pace scorer — how fast are you and how well do you build speed?

Two components blended:
1. **Gap** (60%): median-vs-best — how consistently do you hold near-peak pace?
2. **Progression** (40%): early stint → best lap — how well do you find speed
   through the session? Rewards qualifying/practice improvement.

When a valid physics-based theoretical exists, gap scoring uses that instead.
"""
from __future__ import annotations

import logging
import math
from typing import Any

from scoring.constants import (
    MAX_PACE,
    PACE_DECAY_EXP,
    PHYS_PACE_FULL_GAP_PCT,
    PHYS_PACE_FULL_GAP_S,
    PHYS_PACE_W_ABS,
    PHYS_PACE_W_PCT,
    PHYS_PACE_ZERO_GAP_PCT,
    PHYS_PACE_ZERO_GAP_S,
)
from scoring.helpers import _get, _ratio_score

logger = logging.getLogger(__name__)

# Gap component thresholds (median vs best)
_MEDIAN_FULL_GAP_PCT = 0.3    # within 0.3% of best = full marks
_MEDIAN_ZERO_GAP_PCT = 10.0   # 10% slower than best = zero

# Progression component thresholds (early stint → best)
_PROG_FULL_PCT = 5.0   # 5%+ improvement from early to best = full marks
_PROG_ZERO_PCT = 0.0   # no improvement = zero progression marks

# Blend weights
_W_GAP  = 0.60
_W_PROG = 0.40


def _score_pace(
    m:  dict[str, Any],
    th: dict[str, Any],
    *,
    simulation_method: str = "percentile_envelope",
) -> tuple[float, dict[str, Any]]:
    """
    Score pace: raw speed capability + session progression.

    Required metric keys (from *m*):
        ``best_s``           -- driver's best lap time [s]
        ``best_to_median_s`` -- gap between best and median [s]
        ``early_mean_s``     -- mean lap time first stint [s] (optional)

    Optional (from *th*):
        ``best_s``           -- theoretical best lap time [s]
    """
    driver_best = _get(m, "best_s")
    median_gap  = _get(m, "best_to_median_s")
    early_mean  = _get(m, "early_mean_s")
    theory_best = _get(th, "best_s")

    if math.isnan(driver_best) or driver_best <= 0:
        return 0.0, {"raw_gap_s": float("nan"), "gap_pct": float("nan"),
                      "method": "none"}

    # ── Gap component ─────────────────────────────────────────────
    is_physics = simulation_method in (
        "physics", "hybrid", "ocp",
        "kart_envelope_qss", "kart_envelope_casadi",
    )
    has_valid_theoretical = (
        is_physics
        and not math.isnan(theory_best)
        and theory_best > 0
        and theory_best < driver_best
    )

    if has_valid_theoretical:
        gap_s   = driver_best - theory_best
        gap_pct = 100.0 * gap_s / theory_best
        pct_ratio = _ratio_score(
            gap_pct, PHYS_PACE_FULL_GAP_PCT, PHYS_PACE_ZERO_GAP_PCT,
            higher_is_better=False, exp=PACE_DECAY_EXP,
        )
        abs_ratio = _ratio_score(
            gap_s, PHYS_PACE_FULL_GAP_S, PHYS_PACE_ZERO_GAP_S,
            higher_is_better=False, exp=PACE_DECAY_EXP,
        )
        gap_ratio = PHYS_PACE_W_PCT * pct_ratio + PHYS_PACE_W_ABS * abs_ratio
        gap_method = f"physics:{simulation_method}"
    else:
        if math.isnan(median_gap) or median_gap < 0:
            median_gap = 0.0
        gap_s   = median_gap
        gap_pct = 100.0 * gap_s / driver_best
        gap_ratio = _ratio_score(
            gap_pct, _MEDIAN_FULL_GAP_PCT, _MEDIAN_ZERO_GAP_PCT,
            higher_is_better=False, exp=PACE_DECAY_EXP,
        )
        gap_method = "median_gap"

    # ── Progression component ─────────────────────────────────────
    prog_ratio = 0.0
    prog_pct = 0.0
    if not math.isnan(early_mean) and early_mean > 0 and early_mean > driver_best:
        prog_pct = 100.0 * (early_mean - driver_best) / early_mean
        prog_ratio = _ratio_score(
            prog_pct, _PROG_FULL_PCT, _PROG_ZERO_PCT,
            higher_is_better=True, exp=1.0,
        )

    # ── Blend ─────────────────────────────────────────────────────
    blended = _W_GAP * gap_ratio + _W_PROG * prog_ratio
    score = round(blended * MAX_PACE, 4)

    return score, {
        "raw_gap_s":      round(gap_s, 3),
        "gap_pct":        round(gap_pct, 4),
        "gap_ratio":      round(gap_ratio, 4),
        "prog_pct":       round(prog_pct, 4),
        "prog_ratio":     round(prog_ratio, 4),
        "method":         gap_method,
    }
