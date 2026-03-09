"""Consistency scorer — how repeatable is performance across laps?"""
from __future__ import annotations

import logging
import math
from typing import Any

from scoring.constants import (
    _CONSISTENCY_THRESHOLDS_BY_TYPE,
    CONSISTENCY_BTM_FULL_S,
    CONSISTENCY_BTM_ZERO_S,
    CONSISTENCY_FULL_CV_PCT,
    CONSISTENCY_W_BTM,
    CONSISTENCY_W_CV,
    CONSISTENCY_ZERO_CV_PCT,
    MAX_CONSISTENCY,
    WET_CONSISTENCY_BTM_FULL_S,
    WET_CONSISTENCY_BTM_ZERO_S,
    WET_CONSISTENCY_FULL_CV_PCT,
    WET_CONSISTENCY_ZERO_CV_PCT,
)
from scoring.helpers import _get, _normalize_session_type, _ratio_score

logger = logging.getLogger(__name__)


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
