"""Phase-aware scoring — adds per-phase sub-scores and adaptation when available."""
from __future__ import annotations

import logging
import math
from typing import Any, Optional

import pandas as pd

from scoring.adaptation import (
    _compute_adaptation_score,
    _compute_phase_scores,
    _score_adaptation_v2,
)
from scoring.consistency import _score_consistency
from scoring.constants import (
    ADAPT_MIN_EVOLUTION_PCT,
    ADAPT_V2_STABLE_DEFAULT_FRAC,
    MAX_ADAPTATION,
    MAX_CONSISTENCY,
)
from scoring.execution import compute_granular_execution
from scoring.helpers import _apply_confidence, _assign_grade
from scoring.racecraft import compute_racecraft_score
from scoring.scorer import score_session

logger = logging.getLogger(__name__)


def score_session_phase_aware(
    metrics_dict: dict[str, Any],
    theoretical_metrics: dict[str, Any],
    session_type: str = "practice",
    *,
    context: Any = None,
    phases_df: Optional[pd.DataFrame] = None,
    lap_to_phase: Optional[dict[int, int]] = None,
    lap_metrics: Optional[list[dict[str, Any]]] = None,
    track_evolution: Optional[dict[str, Any]] = None,
    corner_performances: Optional[list[dict[str, Any]]] = None,
    weather_timeline: Optional[pd.DataFrame] = None,
    driver_total_laps: int = 0,
    corner_coaching: Optional[list[dict[str, Any]]] = None,
    progressive_physics: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """
    Phase-aware wrapper around :func:`score_session`.

    Adds ``phase_scores`` (per-phase sub-scores) and ``adaptation_score``
    (how fast pace improves after condition changes) when phase information
    is available.  Falls back to plain :func:`score_session` otherwise.

    Parameters -- metrics_dict, theoretical_metrics, session_type:
        Forwarded to :func:`score_session`.
    context:
        ``SessionContext`` instance (optional).
    phases_df:
        Output of ``condition_tracking.build_condition_phases``.
    lap_to_phase:
        ``{lap_number: phase_id}`` mapping.
    lap_metrics:
        Per-lap metric dicts (each must include ``lap_number``, ``lap_time_s``).

    Returns -- -
    dict
        Same keys as :func:`score_session` plus:
        ``phase_scores`` (dict[int, dict]) and ``adaptation_score`` (float 0-1).
    """
    # Base scoring (always computed)

    # Detect wet conditions from context

    _is_wet = False
    _track_state_str = "dry"
    if context is not None:
        _track_state = getattr(context, "baseline_track_state", None)
        if _track_state is not None:
            _state_val = _track_state.value if hasattr(_track_state, "value") else str(_track_state)
            _track_state_str = _state_val.lower()
            _is_wet = _track_state_str in ("wet", "full_wet", "damp", "drying", "greasy")

    # Check for track evolution to adjust consistency scoring

    _has_evolution = (
        track_evolution is not None
        and abs(track_evolution.get("total_evolution_pct", 0.0)) >= ADAPT_MIN_EVOLUTION_PCT
    )

    result = score_session(
        metrics_dict, theoretical_metrics, session_type,
        is_wet=_is_wet,
        track_state=_track_state_str,
        driver_total_laps=driver_total_laps,
        corner_coaching=corner_coaching,
        progressive_physics=progressive_physics,
    )

    # --- Detrended consistency for evolving conditions -- -

    # If track is evolving (drying/degrading), the raw CV% is unfairly high.

    # Recompute consistency using detrended or per-phase CV.

    if _has_evolution and lap_metrics:
        try:
            from features import compute_detrended_consistency

            _lap_times: list[float] = [
                float(lm["lap_time_s"])
                for lm in sorted(lap_metrics, key=lambda x: x.get("lap_number", 0))
                if isinstance(lm.get("lap_time_s"), (int, float))
                and math.isfinite(lm["lap_time_s"])
            ]

            if len(_lap_times) >= 3:
                detrend_result = compute_detrended_consistency(
                    _lap_times,
                    lap_to_phase=lap_to_phase,
                )
                adj_cv = detrend_result.get("adjusted_cv_pct", float("nan"))

                if math.isfinite(adj_cv):
                    # Recompute consistency sub-score with adjusted CV
                    _grip_improving = (
                        track_evolution is not None
                        and track_evolution.get("grip_trend") == "improving"
                    )
                    _adj_cons_score, _adj_cons_detail = _score_consistency(
                        metrics_dict, theoretical_metrics,
                        is_wet=_is_wet,
                        within_phase_cv=adj_cv,
                        session_type=session_type,
                        lap_times=[float(t) for t in _lap_times],
                        grip_progressing=_grip_improving,
                    )

                    if "consistency" in result.get("sub_scores", {}):
                        old_cons = result["sub_scores"]["consistency"]["score"]
                        # Only apply detrended score if it actually helps the driver
                        if _adj_cons_score <= old_cons:
                            logger.info(
                                "Detrended consistency %.2f <= raw %.2f; keeping raw score",
                                _adj_cons_score, old_cons,
                            )
                        else:
                            result["sub_scores"]["consistency"]["score"] = _adj_cons_score
                            pct = _adj_cons_score / MAX_CONSISTENCY * 100.0 if MAX_CONSISTENCY > 0 else 0
                            result["sub_scores"]["consistency"]["pct"] = round(pct, 2)
                            result["sub_scores"]["consistency"]["detail"] = _adj_cons_detail
                            result["sub_scores"]["consistency"]["detail"]["detrended"] = True
                            result["sub_scores"]["consistency"]["detail"]["raw_cv_pct"] = detrend_result["raw_cv_pct"]
                            result["sub_scores"]["consistency"]["detail"]["adjusted_cv_pct"] = adj_cv

                            # Recompute total score

                            new_total = sum(
                                result["sub_scores"][cat]["score"]
                                for cat in ("pace", "consistency", "execution", "robustness", "adaptation")
                                if cat in result["sub_scores"]
                            )
                            new_total = _apply_confidence(
                                new_total, result.get("data_confidence", 1.0),
                            )
                            if math.isnan(new_total):
                                new_total = result["total_score"]
                            result["total_score"] = round(min(100.0, max(0.0, new_total)), 4)
                            result["grade"] = _assign_grade(result["total_score"])

                            logger.info(
                                "Detrended consistency: raw_cv=%.2f%% adj_cv=%.2f%% "
                                "cons_score %.2f -> %.2f",
                                detrend_result["raw_cv_pct"], adj_cv,
                                old_cons, _adj_cons_score,
                            )
        except ImportError:
            logger.debug("features module unavailable for detrended consistency")
        except Exception as _dt_err:
            logger.warning("Detrended consistency failed: %s", _dt_err)

    # --- Granular execution sub-scores (when corner data available) -
    granular_exec = compute_granular_execution(
        corner_performances=corner_performances,
        lap_metrics=lap_metrics,
    )
    result["granular_execution"] = granular_exec

    # --- Racecraft scoring (race sessions only) -
    racecraft = compute_racecraft_score(
        lap_metrics=lap_metrics,
        session_type=session_type,
    )
    result["racecraft"] = racecraft

    # Blend granular execution into the main execution score if available

    if granular_exec.get("has_corner_data", False):
        exec_key = "execution"
        if exec_key in result.get("sub_scores", {}):
            orig_exec = result["sub_scores"][exec_key]

            # Blend on raw 0-1 fractions to avoid scale mismatch
            orig_frac = orig_exec["score"] / orig_exec["max"] if orig_exec["max"] > 0 else 0.5
            gran_frac = granular_exec["composite"]
            blended_frac = 0.40 * orig_frac + 0.60 * gran_frac
            new_score = blended_frac * orig_exec["max"]
            result["sub_scores"][exec_key]["score"] = round(new_score, 4)
            result["sub_scores"][exec_key]["pct"] = round(blended_frac * 100.0, 2)
            result["sub_scores"][exec_key]["detail"]["granular"] = granular_exec

            # Recompute total

            new_total = sum(
                result["sub_scores"][cat]["score"]
                for cat in ("pace", "consistency", "execution", "robustness", "adaptation")
                if cat in result["sub_scores"]
            )
            new_total = _apply_confidence(
                new_total, result.get("data_confidence", 1.0),
            )
            if math.isnan(new_total):
                new_total = result["total_score"]
            result["total_score"] = round(min(100.0, max(0.0, new_total)), 4)
            result["grade"] = _assign_grade(result["total_score"])

    # Phase-level scoring

    phase_scores: dict[int, dict[str, Any]] = {}
    adaptation: float = 0.5  # neutral default

    if (
        phases_df is not None
        and not phases_df.empty
        and lap_to_phase
        and lap_metrics
    ):
        try:
            phase_scores = _compute_phase_scores(
                phases_df, lap_to_phase, lap_metrics,
            )
        except Exception as exc:
            logger.warning("Phase scoring failed: %s", exc)

        try:
            adaptation = _compute_adaptation_score(
                phases_df, lap_to_phase, lap_metrics,
                track_evolution=track_evolution,
            )
        except Exception as exc:
            logger.warning("Adaptation scoring failed: %s", exc)

    result["phase_scores"] = phase_scores
    result["adaptation_score"] = round(adaptation, 4)

    # --- Adaptation V2: weather-aware sub-score -
    # Compute the weighted adaptation sub-score and inject into sub_scores.
    theory_best = theoretical_metrics.get("best_s", None)
    try:
        adapt_v2_score = _score_adaptation_v2(
            lap_metrics=lap_metrics or [],
            weather_timeline=weather_timeline,
            theory_best=float(theory_best) if theory_best is not None else None,
        )
    except Exception as exc:
        logger.warning("Adaptation V2 scoring failed: %s", exc)
        adapt_v2_score = round(MAX_ADAPTATION * ADAPT_V2_STABLE_DEFAULT_FRAC, 4)

    if "adaptation" in result.get("sub_scores", {}):
        result["sub_scores"]["adaptation"]["score"] = round(adapt_v2_score, 4)
        mx = result["sub_scores"]["adaptation"]["max"]
        frac = adapt_v2_score / mx if mx > 0 else 0.0
        result["sub_scores"]["adaptation"]["pct"] = round(frac * 100, 2)
        result["sub_scores"]["adaptation"]["detail"] = {"source": "adaptation_v2"}

    # Recompute total with real adaptation score
    new_total = sum(
        result["sub_scores"][cat]["score"]
        for cat in ("pace", "consistency", "execution", "robustness", "adaptation")
        if cat in result["sub_scores"]
    )
    new_total = _apply_confidence(
        new_total, result.get("data_confidence", 1.0),
    )
    if math.isnan(new_total):
        new_total = result["total_score"]
    result["total_score"] = round(min(100.0, max(0.0, new_total)), 4)
    result["grade"] = _assign_grade(result["total_score"])

    # Surface track evolution summary in scoring result

    if track_evolution is not None:
        result["track_evolution"] = {
            "total_evolution_pct": track_evolution.get("total_evolution_pct", 0.0),
            "grip_trend": track_evolution.get("grip_trend", "stable"),
            "evolution_rate_s_per_lap": track_evolution.get("evolution_rate_s_per_lap", 0.0),
        }
        # If track is evolving, adjust consistency interpretation:

        # the consistency sub-score should note it measured within-phase CV

        has_evolution = abs(track_evolution.get("total_evolution_pct", 0.0)) >= ADAPT_MIN_EVOLUTION_PCT
        if has_evolution and "consistency" in result.get("sub_scores", {}):
            result["sub_scores"]["consistency"]["detail"]["within_phase"] = True
            result["sub_scores"]["consistency"]["detail"]["track_evolving"] = True

    return result
