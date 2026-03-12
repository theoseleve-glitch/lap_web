"""Pace scorer — how close is the driver's best lap to the theoretical reference?"""
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

    is_physics = simulation_method in (
        "physics", "hybrid", "ocp",
        "kart_envelope_qss", "kart_envelope_casadi",
    )

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
