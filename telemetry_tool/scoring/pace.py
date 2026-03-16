"""Pace scorer — how well does the driver maintain speed across the session?

Pace measures the gap between the driver's best lap and their median lap.
A small gap means the driver sustains near-peak speed throughout the session.
A large gap means the driver had one fast lap but their typical pace drops off.

When a valid physics-based theoretical exists (theoretical faster than actual),
the theoretical is used as the reference instead of the driver's own best.
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

# Thresholds for median-vs-best scoring
_MEDIAN_FULL_GAP_PCT = 1.0   # within 1% of best = full marks
_MEDIAN_ZERO_GAP_PCT = 8.0   # 8% slower than best = zero


def _score_pace(
    m:  dict[str, Any],
    th: dict[str, Any],
    *,
    simulation_method: str = "percentile_envelope",
) -> tuple[float, dict[str, Any]]:
    """
    Score pace: how well does the driver maintain speed across the session?

    Primary method (always available):
        Compare median lap time vs best lap time.  A tight gap means the
        driver sustains near-peak speed throughout the session.

    Physics override (when valid theoretical exists):
        When a physics/OCP theoretical lap is available AND faster than the
        driver's best (i.e. it's a genuinely challenging target), use the
        blended percentage+absolute gap scoring against the theoretical.

    Required metric keys
    ~~~~~~~~~~~~~~~~~~~~
    ``best_s``           -- driver's best lap time [s]  (from *m*)
    ``best_to_median_s`` -- gap between best and median [s]  (from *m*)
    ``best_s``           -- theoretical best lap time [s]  (from *th*, optional)
    """
    driver_best = _get(m, "best_s")
    median_gap  = _get(m, "best_to_median_s")
    theory_best = _get(th, "best_s")

    if math.isnan(driver_best) or driver_best <= 0:
        logger.debug("Pace: missing or invalid best_s; returning 0.")
        return 0.0, {"raw_gap_s": float("nan"), "gap_pct": float("nan"),
                      "method": "none"}

    # ── Check if a valid physics theoretical exists ─────────────
    is_physics = simulation_method in (
        "physics", "hybrid", "ocp",
        "kart_envelope_qss", "kart_envelope_casadi",
    )
    has_valid_theoretical = (
        is_physics
        and not math.isnan(theory_best)
        and theory_best > 0
        and theory_best < driver_best  # theoretical must be FASTER
    )

    if has_valid_theoretical:
        # ── Physics-based: best vs challenging theoretical ──────
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
        ratio = PHYS_PACE_W_PCT * pct_ratio + PHYS_PACE_W_ABS * abs_ratio
        method = f"physics:{simulation_method}"
    else:
        # ── Median-based: how well does pace hold across session ─
        if math.isnan(median_gap) or median_gap < 0:
            median_gap = 0.0

        gap_s   = median_gap
        gap_pct = 100.0 * gap_s / driver_best

        ratio = _ratio_score(
            gap_pct, _MEDIAN_FULL_GAP_PCT, _MEDIAN_ZERO_GAP_PCT,
            higher_is_better=False, exp=PACE_DECAY_EXP,
        )
        method = "median_gap"

    score = round(ratio * MAX_PACE, 4)

    return score, {
        "raw_gap_s": round(gap_s, 3),
        "gap_pct":   round(gap_pct, 4),
        "method":    method,
    }
