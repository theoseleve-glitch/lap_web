"""Racecraft scorer — start performance, stint management, late-race retention."""
from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np
import pandas as pd

from scoring.constants import (
    RACE_LAP1_FULL_DELTA_S,
    RACE_LAP1_ZERO_DELTA_S,
    RACE_RETENTION_FULL,
    RACE_RETENTION_ZERO,
    RACE_STINT_FULL_CV,
    RACE_STINT_ZERO_CV,
    RACE_W_RETENTION,
    RACE_W_START,
    RACE_W_STINT,
)
from scoring.helpers import _normalize_session_type, _ratio_score

logger = logging.getLogger(__name__)


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
