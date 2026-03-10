"""
Stage 13 — Scoring + Coaching
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Steps 13, 13b–13d: session scoring (phase-aware or standard fallback),
coaching guide generation, evidence-based coaching V2, and practice
plan / drill generation.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np
import pandas as pd

from pipeline.helpers import lazy_import

logger = logging.getLogger(__name__)


# ── Step 13: Score session ─────────────────────────────────────────────


def run_score(
    consistency: Optional[dict[str, Any]],
    robustness: Optional[dict[str, Any]],
    lap_metrics: Optional[list[dict[str, Any]]],
    excluded_laps: frozenset[int],
    theo_metrics: dict[str, Any],
    meta: dict[str, Any],
    *,
    context: Any = None,
    phases_df: Optional[pd.DataFrame] = None,
    lap_to_phase: Optional[dict[int, int]] = None,
    track_evolution: Any = None,
    corner_performances: Optional[list[dict[str, Any]]] = None,
    weather_timeline: Optional[pd.DataFrame] = None,
    corner_coaching: Optional[list[dict[str, Any]]] = None,
    progressive_physics: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Score session.

    Prefers the phase-aware scorer (``score_session_phase_aware``) if
    available, otherwise falls back to the standard ``score_session``.

    Returns
    -------
    dict
        Score result with total_score, sub-scores, letter grades, etc.

    Raises
    ------
    ImportError
        If the ``scoring`` module is unavailable.
    """
    score_mod = lazy_import("scoring")
    if score_mod is None:
        raise ImportError("scoring unavailable")

    m: dict[str, Any] = {}
    if consistency:
        m.update(consistency)
    if robustness:
        m.update(robustness)
    if lap_metrics:
        # Filter out excluded laps so invalid data doesn't distort averages
        valid_metrics = [
            lm for lm in lap_metrics if lm.get("lap_number") not in excluded_laps
        ]
        src = valid_metrics if valid_metrics else lap_metrics
        speeds = [lm.get("speed_mean_mps", float("nan")) for lm in src]
        accels = [lm.get("accel_max_mps2", float("nan")) for lm in src]
        brakes = [lm.get("braking_max_mps2", float("nan")) for lm in src]
        m["speed_mean_mps"] = float(np.nanmean(speeds)) if speeds else float("nan")
        m["accel_max_mps2"] = float(np.nanmax(accels)) if accels and not all(np.isnan(v) for v in accels) else float("nan")
        m["braking_max_mps2"] = float(np.nanmax(brakes)) if brakes and not all(np.isnan(v) for v in brakes) else float("nan")

    # Phase-aware scoring (preferred)
    if hasattr(score_mod, "score_session_phase_aware"):
        return score_mod.score_session_phase_aware(
            m,
            theo_metrics,
            meta.get("session_type", "practice"),
            context=context,
            phases_df=phases_df,
            lap_to_phase=lap_to_phase,
            lap_metrics=lap_metrics,
            track_evolution=track_evolution,
            corner_performances=corner_performances,
            weather_timeline=weather_timeline,
            driver_total_laps=int(meta.get("driver_total_laps", 0) or 0),
            corner_coaching=corner_coaching,
            progressive_physics=progressive_physics,
        )

    # Standard fallback — detect wet + track state from context
    is_wet = False
    track_state = meta.get("track_state", "dry")
    if context is not None:
        ts = getattr(context, "baseline_track_state", None)
        if ts is not None:
            sv = ts.value if hasattr(ts, "value") else str(ts)
            is_wet = sv.lower() in ("wet", "full_wet", "damp", "drying", "greasy")
            track_state = sv.lower()

    return score_mod.score_session(
        m,
        theo_metrics,
        meta.get("session_type", "practice"),
        is_wet=is_wet,
        track_state=track_state,
        driver_total_laps=int(meta.get("driver_total_laps", 0) or 0),
        corner_coaching=corner_coaching,
        progressive_physics=progressive_physics,
    )


# ── Step 13b: Coaching guide ──────────────────────────────────────────


def run_coaching_guide(
    corner_performances: Optional[list[dict[str, Any]]],
    lap_metrics: Optional[list[dict[str, Any]]],
    score_result: Optional[dict[str, Any]],
    track_evolution: Any,
    meta: dict[str, Any],
    *,
    distance_quality: Any = None,
) -> Optional[dict[str, Any]]:
    """Generate coaching guide.

    Returns a dict with ``focus_areas`` and recommendations, or ``None``
    if the debrief engine is unavailable or distance quality is degraded.
    """
    # Gate on distance quality
    if (
        distance_quality is not None
        and hasattr(distance_quality, "gate_advanced")
        and distance_quality.gate_advanced
    ):
        logger.warning("Coaching guide SKIPPED: distance quality gate active.")
        return None

    de_mod = lazy_import("debrief_engine")
    if de_mod is None or not hasattr(de_mod, "generate_coaching_guide"):
        return None

    result = de_mod.generate_coaching_guide(
        corner_performances=corner_performances,
        lap_metrics=lap_metrics,
        score_result=score_result,
        track_evolution=track_evolution,
        session_type=meta.get("session_type", "practice"),
    )
    if result:
        n_focus = len(result.get("focus_areas", []))
        logger.info("Coaching guide: %d focus areas", n_focus)
    return result


# ── Step 13c: Coaching V2 ─────────────────────────────────────────────


def run_coaching_v2(
    corner_performances: Optional[list[dict[str, Any]]],
    corner_timelines: list[dict[str, Any]],
    corners: list[dict[str, Any]],
    *,
    data_quality: Any = None,
    distance_quality: Any = None,
) -> Any:
    """Generate coaching V2 (evidence-based, confidence-gated).

    Returns the coaching result object, or ``None`` if unavailable
    or distance quality is degraded.
    """
    # Gate on distance quality
    if (
        distance_quality is not None
        and hasattr(distance_quality, "gate_advanced")
        and distance_quality.gate_advanced
    ):
        return None

    ca_mod = lazy_import("corner_analysis")
    if ca_mod is None or not hasattr(ca_mod, "generate_coaching_v2"):
        return None
    if not corner_performances:
        return None

    dq_score = getattr(data_quality, "overall_confidence", 1.0) if data_quality else 1.0

    return ca_mod.generate_coaching_v2(
        corner_performances,
        corner_timelines=corner_timelines,
        corners=corners,
        data_quality=dq_score,
    )


# ── Step 13d: Practice plan + drills ──────────────────────────────────


def run_practice_plan(
    coaching_v2: Any,
    enriched_df: Optional[pd.DataFrame],
) -> Any:
    """Generate practice plan + drills from coaching V2.

    Returns the plan result object, or ``None`` if the drills module
    is unavailable or no coaching data exists.
    """
    drills_mod = lazy_import("drills")
    if drills_mod is None or not hasattr(drills_mod, "generate_practice_plan"):
        return None

    if not coaching_v2:
        return None

    available_channels = (
        list(enriched_df.columns) if enriched_df is not None else []
    )
    return drills_mod.generate_practice_plan(coaching_v2, available_channels)
