"""
driver_profile.py
-----------------
Cross-session driver profiling for motorsport telemetry analysis.

Aggregates data from multiple sessions into a single driver profile that
captures long-term tendencies, not just per-session snapshots.

Public API
~~~~~~~~~~
``generate_driver_profile(driver_name, all_sessions_data)``
    Compute a comprehensive driver profile from one or more sessions.

Profile dimensions
~~~~~~~~~~~~~~~~~~
  Pace delta           Average gap (seconds) to the theoretical reference.
  Consistency rating   Aggregate repeatability across and within sessions.
  Aggression index     How hard the driver brakes (peak / frequency of spikes).
  Smoothness index     Inverse jerk intensity -- lower jerk = smoother inputs.
  Improvement trend    Directional change in pace over chronological sessions.

Input contract
~~~~~~~~~~~~~~
``all_sessions_data`` is a list of session dicts.  Each dict may contain:

  Required (at least one session must have these):
    ``metrics``              -- dict from ``features.compute_*`` functions
    ``theoretical_metrics``  -- dict from theoretical-lap reference

  Optional (enrich the profile when present):
    ``resampled_laps``       -- list[pd.DataFrame] of distance-resampled laps
    ``score_result``         -- dict from ``scoring.score_session()``
    ``session_id``           -- str  (for traceability)
    ``session_date``         -- str  ISO-8601 date, used for trend ordering

Missing keys degrade individual metrics to NaN -- the profile never crashes.

Design principles
~~~~~~~~~~~~~~~~~
- Modular: each sub-metric has its own internal function.
- Numpy / pandas only -- no scipy, no plotting.
- NaN-robust: absent data degrades gracefully; never crashes.
- No side effects, no global state, no print statements.
- Deterministic: identical inputs -> identical outputs.
- Returns plain dict (JSON-serialisable).
- All thresholds are module-level ``Final`` constants.
"""

from __future__ import annotations

import logging
import math
import traceback
from typing import Any, Final

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# -- -

# Column-name constants  (mirror the rest of the pipeline)

# -- -


_COL_SPEED: Final[str] = "Speed (m/s)"
_COL_DIST:  Final[str] = "Distance (m)"
_COL_LONG:  Final[str] = "accel_long_mps2"

# -- -

# Metric-key constants  (keys expected in metrics / theoretical dicts)

# -- -


_K_BEST_S:          Final[str] = "best_s"
_K_MEAN_S:          Final[str] = "mean_s"
_K_CV_PCT:          Final[str] = "cv_pct"
_K_STD_S:           Final[str] = "std_s"
_K_N_LAPS:          Final[str] = "n_laps"
_K_BRAKING_MAX:     Final[str] = "braking_max_mps2"
_K_ACCEL_MAX:       Final[str] = "accel_max_mps2"
_K_JERK_RMS:        Final[str] = "jerk_rms_mps3"
_K_JERK_MAX:        Final[str] = "jerk_max_mps3"
_K_JERK_MIN:        Final[str] = "jerk_min_mps3"
_K_SPEED_MEAN:      Final[str] = "speed_mean_mps"

# -- -

# Aggression index thresholds

# -- -


#: Braking magnitude (m/s^2) at or above which a sample is a "braking spike"

BRAKING_SPIKE_THRESHOLD_MPS2: Final[float] = 8.0

#: Aggression index is normalised so that this peak braking maps to 1.0

AGGRESSION_REF_BRAKING_MPS2:  Final[float] = 15.0

#: Weight split: peak braking vs spike frequency

AGGRESSION_W_PEAK:  Final[float] = 0.60
AGGRESSION_W_FREQ:  Final[float] = 0.40

# -- -

# Smoothness index thresholds

# -- -


#: Jerk RMS (m/s^3) at which smoothness = 0.0  (very jerky)

SMOOTHNESS_ZERO_JERK_RMS: Final[float] = 50.0

#: Jerk RMS (m/s^3) at which smoothness = 1.0  (silky)

SMOOTHNESS_FULL_JERK_RMS: Final[float] = 5.0

# -- -

# Consistency rating thresholds

# -- -


#: Cross-session CV% below which consistency = 1.0

CONSISTENCY_FULL_CV_PCT: Final[float] = 0.30

#: Cross-session CV% above which consistency = 0.0

CONSISTENCY_ZERO_CV_PCT: Final[float] = 3.0

# -- -

# Improvement trend: minimum sessions required

# -- -


TREND_MIN_SESSIONS: Final[int] = 3

# -- -

# Exceptions

# -- -



class DriverProfileError(ValueError):
    """Raised when inputs are structurally invalid (not merely incomplete)."""


# -- -

# Internal helpers

# -- -


def _clamp01(x: float) -> float:
    """Clamp *x* to [0.0, 1.0]."""
    return max(0.0, min(1.0, x))


def _get(d: dict[str, Any], key: str, default: float = float("nan")) -> float:
    """Safely retrieve a float from *d*; return *default* if absent or NaN."""
    v = d.get(key, default)
    try:
        f = float(v)
        return default if math.isnan(f) else f
    except (TypeError, ValueError):
        return default


def _finite_array(values: list[float]) -> np.ndarray:
    """Convert to array and strip NaN / Inf."""
    arr = np.asarray(values, dtype=float)
    return arr[np.isfinite(arr)]


def _get_numeric_col(df: pd.DataFrame, col: str) -> np.ndarray:
    """Return finite-values-only numpy array for *col*, or empty array."""
    if col not in df.columns:
        return np.array([], dtype=float)
    vals = pd.to_numeric(df[col], errors="coerce").values
    return vals[np.isfinite(vals)]


# -- -

# 1. Pace delta to theoretical

# -- -


def _compute_pace_delta(
    sessions: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Average gap between driver's best lap and theoretical, across sessions.

    Returns
    -------
    dict with keys:
        ``mean_delta_s``        -- mean gap to theoretical [s]
        ``median_delta_s``      -- median gap [s]
        ``best_delta_s``        -- smallest gap achieved (best session)
        ``worst_delta_s``       -- largest gap (worst session)
        ``n_sessions_scored``   -- sessions contributing to the metric
        ``per_session_deltas``  -- list of per-session deltas [s]
    """
    deltas: list[float] = []

    for sess in sessions:
        m  = sess.get("metrics", {})
        th = sess.get("theoretical_metrics", {})
        driver_best = _get(m,  _K_BEST_S)
        theory_best = _get(th, _K_BEST_S)

        if math.isnan(driver_best) or math.isnan(theory_best) or theory_best <= 0:
            continue

        deltas.append(driver_best - theory_best)

    arr = _finite_array(deltas)
    n   = len(arr)

    if n == 0:
        logger.debug("Pace delta: no valid sessions.")
        return {
            "mean_delta_s":       float("nan"),
            "median_delta_s":     float("nan"),
            "best_delta_s":       float("nan"),
            "worst_delta_s":      float("nan"),
            "n_sessions_scored":  0,
            "per_session_deltas": [],
        }

    return {
        "mean_delta_s":       round(float(arr.mean()), 3),
        "median_delta_s":     round(float(np.median(arr)), 3),
        "best_delta_s":       round(float(arr.min()), 3),
        "worst_delta_s":      round(float(arr.max()), 3),
        "n_sessions_scored":  n,
        "per_session_deltas": [round(float(d), 3) for d in arr],
    }


# -- -

# 2. Consistency rating

# -- -


def _compute_consistency_rating(
    sessions: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Aggregate consistency from intra-session CV% values and cross-session
    best-lap-time variability.

    Two components, averaged:
      - Intra-session: mean CV% across sessions (lower is better).
      - Cross-session: CV% of per-session best laps (lower is better).

    Returns
    -------
    dict with keys:
        ``rating``                -- float in [0.0, 1.0] (1 = perfectly consistent)
        ``intra_session_cv_pct``  -- mean intra-session CV%
        ``cross_session_cv_pct``  -- CV% of best laps across sessions
        ``n_sessions``            -- sessions contributing
    """
    intra_cvs:  list[float] = []
    best_times: list[float] = []

    for sess in sessions:
        m = sess.get("metrics", {})
        cv = _get(m, _K_CV_PCT)
        if not math.isnan(cv):
            intra_cvs.append(cv)

        best = _get(m, _K_BEST_S)
        if not math.isnan(best) and best > 0:
            best_times.append(best)

    intra_arr = _finite_array(intra_cvs)
    best_arr  = _finite_array(best_times)

    # Intra-session component

    if len(intra_arr) > 0:
        mean_intra_cv = float(intra_arr.mean())
        intra_score = _clamp01(
            (CONSISTENCY_ZERO_CV_PCT - mean_intra_cv)
            / (CONSISTENCY_ZERO_CV_PCT - CONSISTENCY_FULL_CV_PCT)
        )
    else:
        mean_intra_cv = float("nan")
        intra_score   = float("nan")

    # Cross-session component

    if len(best_arr) >= 2:
        cross_cv = float(best_arr.std(ddof=1) / best_arr.mean() * 100.0)
        cross_score = _clamp01(
            (CONSISTENCY_ZERO_CV_PCT - cross_cv)
            / (CONSISTENCY_ZERO_CV_PCT - CONSISTENCY_FULL_CV_PCT)
        )
    else:
        cross_cv    = float("nan")
        cross_score = float("nan")

    # Combine: use whichever components are available

    components = [s for s in (intra_score, cross_score) if not math.isnan(s)]
    rating = round(float(np.mean(components)), 4) if components else float("nan")

    return {
        "rating":               rating,
        "intra_session_cv_pct": round(mean_intra_cv, 4) if not math.isnan(mean_intra_cv) else None,
        "cross_session_cv_pct": round(cross_cv, 4) if not math.isnan(cross_cv) else None,
        "n_sessions":           len(intra_arr) + len(best_arr),
    }


# -- -

# 3. Aggression index

# -- -


def _compute_aggression_index(
    sessions: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Quantify braking aggressiveness from peak braking values and, when
    resampled laps are available, braking spike frequency.

    Two weighted components:
      - Peak braking magnitude (normalised to a reference maximum).
      - Braking spike frequency (fraction of samples exceeding threshold).

    Returns
    -------
    dict with keys:
        ``index``                 -- float in [0.0, 1.0] (1 = maximally aggressive)
        ``mean_peak_braking_mps2``-- mean peak braking across sessions
        ``spike_fraction``        -- fraction of braking samples that are spikes
        ``n_sessions``            -- sessions contributing
    """
    peak_braking_vals: list[float] = []
    total_brake_samples = 0
    total_spike_samples = 0

    for sess in sessions:
        # Peak braking from pre-computed metrics

        m = sess.get("metrics", {})
        bmax = _get(m, _K_BRAKING_MAX)
        if not math.isnan(bmax):
            peak_braking_vals.append(bmax)

        # Spike frequency from raw resampled laps (if available)

        for lap_df in sess.get("resampled_laps", []):
            accel = _get_numeric_col(lap_df, _COL_LONG)
            if len(accel) == 0:
                continue
            braking = accel[accel < 0]
            n_brake = len(braking)
            if n_brake == 0:
                continue
            total_brake_samples += n_brake
            total_spike_samples += int((np.abs(braking) >= BRAKING_SPIKE_THRESHOLD_MPS2).sum())

    peak_arr = _finite_array(peak_braking_vals)

    # Peak component

    if len(peak_arr) > 0:
        mean_peak = float(peak_arr.mean())
        peak_score = _clamp01(mean_peak / AGGRESSION_REF_BRAKING_MPS2)
    else:
        mean_peak  = float("nan")
        peak_score = float("nan")

    # Spike frequency component

    if total_brake_samples > 0:
        spike_frac  = total_spike_samples / total_brake_samples
        freq_score  = _clamp01(spike_frac / 0.30)  # 30 % spike rate -> 1.0
    else:
        spike_frac = float("nan")
        freq_score = float("nan")

    # Combine available components

    if not math.isnan(peak_score) and not math.isnan(freq_score):
        index = round(
            AGGRESSION_W_PEAK * peak_score + AGGRESSION_W_FREQ * freq_score, 4
        )
    elif not math.isnan(peak_score):
        index = round(peak_score, 4)
    elif not math.isnan(freq_score):
        index = round(freq_score, 4)
    else:
        index = float("nan")

    return {
        "index":                   index,
        "mean_peak_braking_mps2":  round(mean_peak, 3) if not math.isnan(mean_peak) else None,
        "spike_fraction":          round(spike_frac, 4) if not math.isnan(spike_frac) else None,
        "n_sessions":              len(peak_arr),
    }


# -- -

# 4. Smoothness index

# -- -


def _compute_smoothness_index(
    sessions: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Quantify driver smoothness from jerk (rate of change of acceleration).

    Lower jerk RMS -> smoother driving -> higher smoothness index.

    When resampled laps are available, jerk is recomputed from the
    longitudinal acceleration channel for accuracy.  Otherwise the
    pre-computed ``jerk_rms_mps3`` from metrics is used.

    Returns
    -------
    dict with keys:
        ``index``           -- float in [0.0, 1.0] (1 = very smooth)
        ``mean_jerk_rms``   -- mean jerk RMS across all data [m/s^3]
        ``jerk_p95``        -- 95th percentile of absolute jerk (peak harshness)
        ``n_sessions``      -- sessions contributing
    """
    jerk_rms_vals: list[float] = []
    all_jerk_abs:  list[float] = []

    for sess in sessions:
        session_jerk_computed = False

        # Prefer recomputing from resampled laps for accuracy

        for lap_df in sess.get("resampled_laps", []):
            accel = _get_numeric_col(lap_df, _COL_LONG)
            if len(accel) < 4:
                continue
            jerk = np.diff(accel)
            jerk_rms_vals.append(float(np.sqrt(np.mean(jerk ** 2))))
            all_jerk_abs.extend(np.abs(jerk).tolist())
            session_jerk_computed = True

        # Fall back to pre-computed metrics

        if not session_jerk_computed:
            m = sess.get("metrics", {})
            jrms = _get(m, _K_JERK_RMS)
            if not math.isnan(jrms):
                jerk_rms_vals.append(jrms)

    rms_arr = _finite_array(jerk_rms_vals)

    if len(rms_arr) == 0:
        logger.debug("Smoothness: no jerk data available.")
        return {
            "index":         float("nan"),
            "mean_jerk_rms": None,
            "jerk_p95":      None,
            "n_sessions":    0,
        }

    mean_rms = float(rms_arr.mean())
    index = _clamp01(
        (SMOOTHNESS_ZERO_JERK_RMS - mean_rms)
        / (SMOOTHNESS_ZERO_JERK_RMS - SMOOTHNESS_FULL_JERK_RMS)
    )

    jerk_abs_arr = _finite_array(all_jerk_abs)
    jerk_p95 = float(np.percentile(jerk_abs_arr, 95)) if len(jerk_abs_arr) > 0 else None

    return {
        "index":         round(index, 4),
        "mean_jerk_rms": round(mean_rms, 3),
        "jerk_p95":      round(jerk_p95, 3) if jerk_p95 is not None else None,
        "n_sessions":    len(rms_arr),
    }


# -- -

# 5. Improvement trend

# -- -


def _compute_improvement_trend(
    sessions: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Fit a linear trend to per-session best lap times ordered chronologically.

    Uses ``session_date`` for ordering when present; otherwise preserves list
    order (assumed chronological).

    The slope is in seconds-per-session.  Negative slope = getting faster.

    Returns
    -------
    dict with keys:
        ``slope_s_per_session``   -- float (negative = improving)
        ``total_improvement_s``   -- float (first-session best - last-session best)
        ``total_improvement_pct`` -- float (improvement as % of first-session best)
        ``r_squared``             -- float -- goodness of fit [0, 1]
        ``n_sessions``            -- int   -- sessions used for the fit
        ``trend_label``           -- str   -- "improving" | "stable" | "declining"
    """
    # Pair each session with its ordering key and best time

    entries: list[tuple[str, float]] = []
    for i, sess in enumerate(sessions):
        m = sess.get("metrics", {})
        best = _get(m, _K_BEST_S)
        if math.isnan(best) or best <= 0:
            continue
        date_key = sess.get("session_date", f"{i:06d}")
        entries.append((date_key, best))

    # Sort by date key (ISO-8601 strings sort lexicographically)

    entries.sort(key=lambda t: t[0])
    n = len(entries)

    if n < TREND_MIN_SESSIONS:
        logger.debug("Improvement trend: only %d session(s); need >= %d.", n, TREND_MIN_SESSIONS)
        return {
            "slope_s_per_session":   float("nan"),
            "total_improvement_s":   float("nan"),
            "total_improvement_pct": float("nan"),
            "r_squared":             float("nan"),
            "n_sessions":            n,
            "trend_label":           "insufficient_data",
        }

    y = np.array([e[1] for e in entries], dtype=float)
    x = np.arange(n, dtype=float)

    # Least-squares linear fit: y = slope * x + intercept

    x_mean = x.mean()
    y_mean = y.mean()
    ss_xy  = float(((x - x_mean) * (y - y_mean)).sum())
    ss_xx  = float(((x - x_mean) ** 2).sum())

    if ss_xx == 0:
        slope     = 0.0
        intercept = y_mean
    else:
        slope     = ss_xy / ss_xx
        intercept = y_mean - slope * x_mean

    # R^2

    y_pred = slope * x + intercept
    ss_res = float(((y - y_pred) ** 2).sum())
    ss_tot = float(((y - y_mean) ** 2).sum())
    r_sq   = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else float("nan")

    total_imp     = float(y[0] - y[-1])   # positive = got faster
    total_imp_pct = (total_imp / y[0] * 100.0) if y[0] > 0 else float("nan")

    # Label: "improving" if slope is meaningfully negative

    if slope < -0.05:
        label = "improving"
    elif slope > 0.05:
        label = "declining"
    else:
        label = "stable"

    return {
        "slope_s_per_session":   round(float(slope), 4),
        "total_improvement_s":   round(total_imp, 3),
        "total_improvement_pct": round(total_imp_pct, 3) if not math.isnan(total_imp_pct) else None,
        "r_squared":             round(float(r_sq), 4) if not math.isnan(r_sq) else None,
        "n_sessions":            n,
        "trend_label":           label,
    }


# -- -

# Public API

# -- -


def generate_driver_profile(
    driver_name: str,
    all_sessions_data: list[dict[str, Any]],
    *,
    context: Any = None,
    phases_df: "pd.DataFrame | None" = None,
    lap_to_phase: "dict[int, int] | None" = None,
    lap_metrics: "list[dict[str, Any]] | None" = None,
) -> dict[str, Any]:
    """
    Build a comprehensive driver profile from one or more sessions.

    Parameters
    ----------
    driver_name:
        Human-readable driver identifier (carried through for traceability).

    all_sessions_data:
        List of session dicts.  Each dict may contain:

        ``metrics``              -- dict (from ``features.compute_*`` outputs,
                                   merged).  Expected keys include ``best_s``,
                                   ``cv_pct``, ``braking_max_mps2``,
                                   ``jerk_rms_mps3``, etc.
        ``theoretical_metrics``  -- dict (same key namespace as ``metrics``;
                                   from the theoretical lap reference).
        ``resampled_laps``       -- list[pd.DataFrame] of distance-resampled
                                   laps (enriches aggression and smoothness).
        ``score_result``         -- dict (output of ``scoring.score_session``).
        ``session_id``           -- str  (optional identifier).
        ``session_date``         -- str  (ISO-8601, used for trend ordering).

        All keys are optional.  Missing data degrades individual metrics to
        NaN rather than raising an exception.

    Returns
    -------
    dict
        JSON-serialisable profile with keys:

        ``driver_name``        -- str
        ``n_sessions``         -- int
        ``pace_delta``         -- dict  (see ``_compute_pace_delta``)
        ``consistency``        -- dict  (see ``_compute_consistency_rating``)
        ``aggression``         -- dict  (see ``_compute_aggression_index``)
        ``smoothness``         -- dict  (see ``_compute_smoothness_index``)
        ``improvement_trend``  -- dict  (see ``_compute_improvement_trend``)
        ``session_ids``        -- list[str | None]
        ``summary``            -- dict  with headline numbers

    Raises
    ------
    TypeError
        If *driver_name* is not a string or *all_sessions_data* is not a list.
    DriverProfileError
        If *all_sessions_data* is empty.
    """
    # -- Input validation
    if not isinstance(driver_name, str):
        raise TypeError(
            f"driver_name must be a str, got {type(driver_name).__name__!r}."
        )
    if not isinstance(all_sessions_data, list):
        raise TypeError(
            f"all_sessions_data must be a list, got "
            f"{type(all_sessions_data).__name__!r}."
        )
    if len(all_sessions_data) == 0:
        raise DriverProfileError("all_sessions_data must contain at least one session.")

    logger.info(
        "Generating driver profile for %r across %d session(s).",
        driver_name, len(all_sessions_data),
    )

    # -- Compute each dimension
    pace        = _compute_pace_delta(all_sessions_data)
    consistency = _compute_consistency_rating(all_sessions_data)
    aggression  = _compute_aggression_index(all_sessions_data)
    smoothness  = _compute_smoothness_index(all_sessions_data)
    trend       = _compute_improvement_trend(all_sessions_data)

    # -- Collect session IDs for traceability
    session_ids = [
        sess.get("session_id") for sess in all_sessions_data
    ]

    # -- Aggregate scores if available -- -

    total_scores: list[float] = []
    for sess in all_sessions_data:
        sr = sess.get("score_result", {})
        ts = _get(sr, "total_score") if isinstance(sr, dict) else float("nan")
        if not math.isnan(ts):
            total_scores.append(ts)

    score_arr = _finite_array(total_scores)
    mean_score = round(float(score_arr.mean()), 2) if len(score_arr) > 0 else None

    # -- Build summary -- -

    summary: dict[str, Any] = {
        "mean_pace_delta_s":   pace.get("mean_delta_s"),
        "consistency_rating":  consistency.get("rating"),
        "aggression_index":    aggression.get("index"),
        "smoothness_index":    smoothness.get("index"),
        "trend_label":         trend.get("trend_label"),
        "mean_session_score":  mean_score,
    }

    profile: dict[str, Any] = {
        "driver_name":        driver_name,
        "n_sessions":         len(all_sessions_data),
        "pace_delta":         pace,
        "consistency":        consistency,
        "aggression":         aggression,
        "smoothness":         smoothness,
        "improvement_trend":  trend,
        "session_ids":        session_ids,
        "summary":            summary,
    }

    # -- Phase-aware stats (optional) -- -

    phase_stats: dict[str, Any] = {}
    if (
        phases_df is not None
        and not phases_df.empty
        and lap_to_phase
        and lap_metrics
    ):
        try:
            phase_stats = _compute_phase_stats(
                phases_df, lap_to_phase, lap_metrics,
            )
        except Exception as exc:
            logger.warning("Phase stats failed: %s", exc)

    profile["phase_stats"] = phase_stats

    # -- Wet-skill proxy (optional) -- -

    wet_skill: Optional[float] = None
    if context is not None:
        try:
            wet_skill = _compute_wet_skill_proxy(
                context, all_sessions_data,
            )
        except Exception as exc:
            logger.warning("Wet-skill proxy failed: %s", exc)

    profile["wet_skill_proxy"] = wet_skill

    logger.info(
        "Profile for %r: pace_delta=%.3f s, consistency=%.2f, "
        "aggression=%.2f, smoothness=%.2f, trend=%s",
        driver_name,
        pace.get("mean_delta_s", float("nan")),
        consistency.get("rating", float("nan")),
        aggression.get("index", float("nan")),
        smoothness.get("index", float("nan")),
        trend.get("trend_label", "?"),
    )

    return profile


# ===========================================================================

# Phase-aware helpers

# ===========================================================================


def _compute_phase_stats(
    phases_df: "pd.DataFrame",
    lap_to_phase: dict[int, int],
    lap_metrics: list[dict[str, Any]],
) -> dict[str, Any]:
    """Per-phase pace_delta and consistency."""
    import pandas as _pd

    lm_df = _pd.DataFrame(lap_metrics)
    if "lap_number" not in lm_df.columns or "lap_time_s" not in lm_df.columns:
        return {}

    lm_df["lap_time_s"] = _pd.to_numeric(lm_df["lap_time_s"], errors="coerce")
    lm_df["_phase"] = lm_df["lap_number"].map(lap_to_phase)

    result: dict[str, Any] = {}
    for pid, grp in lm_df.groupby("_phase", sort=True):
        times = grp["lap_time_s"].dropna()
        if len(times) < 2:
            continue
        best = float(times.min())
        median = float(times.median())
        cv = float(times.std() / times.mean() * 100) if times.mean() > 0 else 0.0
        result[int(pid)] = {
            "pace_delta_s": round(median - best, 3),
            "consistency_cv_pct": round(cv, 2),
            "n_laps": len(times),
        }
    return result


def _compute_wet_skill_proxy(
    context: Any,
    all_sessions_data: list[dict[str, Any]],
) -> Optional[float]:
    """
    Ratio of theoretical pace to best lap; higher = better wet skill.

    Only computed when baseline_track_state is wet/damp/greasy/full_wet.
    """
    try:
        from session_context import TrackState
    except ImportError:
        return None

    tstate = getattr(context, "baseline_track_state", None)
    wet_states = {TrackState.WET, TrackState.DAMP, TrackState.GREASY,
                  TrackState.FULL_WET, TrackState.DRYING}
    if tstate not in wet_states:
        return None

    for sess in all_sessions_data:
        metrics = sess.get("metrics", {})
        theo = sess.get("theoretical_metrics", {})
        best_s = metrics.get("best_s", float("nan"))
        theo_s = theo.get("lap_time_s", float("nan"))
        if math.isfinite(best_s) and math.isfinite(theo_s) and theo_s > 0:
            ratio = theo_s / best_s
            return round(min(1.0, max(0.0, ratio)), 4)
    return None


# ===========================================================================

# Inline tests

# ===========================================================================


def _run_tests() -> None:
    """Self-contained test suite -- run with ``python driver_profile.py``."""

    passed: list[str] = []
    failed: list[tuple[str, str]] = []

    def _test(name: str, fn) -> None:  # type: ignore[type-arg]
        try:
            fn()
            passed.append(name)
        except Exception:
            failed.append((name, traceback.format_exc()))

    # -- Helpers: synthetic sessions

    def _make_session(
        best_s: float = 90.0,
        cv_pct: float = 0.8,
        braking_max: float = 12.0,
        jerk_rms: float = 20.0,
        n_laps: int = 10,
        theory_best: float = 88.0,
        session_date: str | None = None,
        session_id: str | None = None,
        resampled_laps: list[pd.DataFrame] | None = None,
    ) -> dict[str, Any]:
        m: dict[str, Any] = {
            _K_BEST_S:      best_s,
            _K_MEAN_S:      best_s + 1.5,
            _K_CV_PCT:      cv_pct,
            _K_STD_S:       cv_pct / 100.0 * best_s,
            _K_N_LAPS:      n_laps,
            _K_BRAKING_MAX: braking_max,
            _K_ACCEL_MAX:   6.0,
            _K_JERK_RMS:    jerk_rms,
            _K_JERK_MAX:    30.0,
            _K_JERK_MIN:    -35.0,
            _K_SPEED_MEAN:  45.0,
        }
        th: dict[str, Any] = {
            _K_BEST_S:      theory_best,
            _K_SPEED_MEAN:  48.0,
            _K_ACCEL_MAX:   7.0,
            _K_BRAKING_MAX: 14.0,
        }
        sess: dict[str, Any] = {
            "metrics": m,
            "theoretical_metrics": th,
        }
        if session_date:
            sess["session_date"] = session_date
        if session_id:
            sess["session_id"] = session_id
        if resampled_laps is not None:
            sess["resampled_laps"] = resampled_laps
        return sess

    def _make_resampled_lap(n: int = 200) -> pd.DataFrame:
        dist  = np.linspace(0, 4500, n)
        speed = 30.0 + 20.0 * np.sin(2 * np.pi * dist / 4500.0)
        accel = np.gradient(speed, dist) * speed
        return pd.DataFrame({
            _COL_DIST:  dist,
            _COL_SPEED: speed,
            _COL_LONG:  accel,
        })

    #
    # Test 1 -- return type is a dict with all required keys

    #
    def t_return_type_and_keys() -> None:
        sessions = [_make_session()]
        result = generate_driver_profile("TestDriver", sessions)
        assert isinstance(result, dict), "Must return a dict"
        for key in ("driver_name", "n_sessions", "pace_delta",
                    "consistency", "aggression", "smoothness",
                    "improvement_trend", "session_ids", "summary"):
            assert key in result, f"Missing key: {key!r}"

    _test("return_type_and_keys", t_return_type_and_keys)

    #
    # Test 2 -- driver name carried through

    #
    def t_driver_name() -> None:
        result = generate_driver_profile("Alice", [_make_session()])
        assert result["driver_name"] == "Alice"

    _test("driver_name", t_driver_name)

    #
    # Test 3 -- pace delta computed correctly

    #
    def t_pace_delta() -> None:
        sess = _make_session(best_s=92.0, theory_best=90.0)
        result = generate_driver_profile("X", [sess])
        pd_info = result["pace_delta"]
        np.testing.assert_allclose(pd_info["mean_delta_s"], 2.0, atol=1e-3)
        assert pd_info["n_sessions_scored"] == 1

    _test("pace_delta", t_pace_delta)

    #
    # Test 4 -- consistency rating in [0, 1]

    #
    def t_consistency_bounds() -> None:
        sessions = [_make_session(cv_pct=0.5), _make_session(cv_pct=1.0)]
        result = generate_driver_profile("X", sessions)
        rating = result["consistency"]["rating"]
        assert 0.0 <= rating <= 1.0, f"Rating out of bounds: {rating}"

    _test("consistency_bounds", t_consistency_bounds)

    #
    # Test 5 -- aggression index in [0, 1]

    #
    def t_aggression_bounds() -> None:
        result = generate_driver_profile("X", [_make_session(braking_max=10.0)])
        idx = result["aggression"]["index"]
        assert 0.0 <= idx <= 1.0, f"Aggression index out of bounds: {idx}"

    _test("aggression_bounds", t_aggression_bounds)

    #
    # Test 6 -- smoothness index in [0, 1]

    #
    def t_smoothness_bounds() -> None:
        result = generate_driver_profile("X", [_make_session(jerk_rms=15.0)])
        idx = result["smoothness"]["index"]
        assert 0.0 <= idx <= 1.0, f"Smoothness index out of bounds: {idx}"

    _test("smoothness_bounds", t_smoothness_bounds)

    #
    # Test 7 -- low jerk -> high smoothness

    #
    def t_smoothness_low_jerk() -> None:
        smooth = generate_driver_profile("X", [_make_session(jerk_rms=6.0)])
        rough  = generate_driver_profile("X", [_make_session(jerk_rms=40.0)])
        assert smooth["smoothness"]["index"] > rough["smoothness"]["index"]

    _test("smoothness_low_jerk_beats_high", t_smoothness_low_jerk)

    #
    # Test 8 -- improvement trend with 5 improving sessions

    #
    def t_improvement_trend_improving() -> None:
        sessions = [
            _make_session(best_s=95.0 - i * 1.5, session_date=f"2024-0{i+1}-01")
            for i in range(5)
        ]
        result = generate_driver_profile("X", sessions)
        trend = result["improvement_trend"]
        assert trend["slope_s_per_session"] < 0, "Should have negative slope"
        assert trend["trend_label"] == "improving"
        assert trend["n_sessions"] == 5

    _test("improvement_trend_improving", t_improvement_trend_improving)

    #
    # Test 9 -- insufficient sessions for trend

    #
    def t_trend_insufficient() -> None:
        result = generate_driver_profile("X", [_make_session()])
        assert result["improvement_trend"]["trend_label"] == "insufficient_data"

    _test("trend_insufficient", t_trend_insufficient)

    #
    # Test 10 -- empty metrics degrade gracefully

    #
    def t_empty_metrics_no_crash() -> None:
        result = generate_driver_profile("X", [{"metrics": {}, "theoretical_metrics": {}}])
        assert isinstance(result, dict)
        assert result["n_sessions"] == 1

    _test("empty_metrics_no_crash", t_empty_metrics_no_crash)

    #
    # Test 11 -- NaN metrics handled without crash

    #
    def t_nan_metrics() -> None:
        sess = _make_session()
        sess["metrics"] = {k: float("nan") for k in sess["metrics"]}
        result = generate_driver_profile("X", [sess])
        assert isinstance(result, dict)

    _test("nan_metrics", t_nan_metrics)

    #
    # Test 12 -- resampled laps enrich aggression

    #
    def t_aggression_with_laps() -> None:
        lap = _make_resampled_lap()
        sess = _make_session(resampled_laps=[lap])
        result = generate_driver_profile("X", [sess])
        assert result["aggression"]["index"] is not None

    _test("aggression_with_laps", t_aggression_with_laps)

    #
    # Test 13 -- resampled laps enrich smoothness

    #
    def t_smoothness_with_laps() -> None:
        lap = _make_resampled_lap()
        sess = _make_session(resampled_laps=[lap])
        result = generate_driver_profile("X", [sess])
        assert result["smoothness"]["index"] is not None
        assert not math.isnan(result["smoothness"]["index"])

    _test("smoothness_with_laps", t_smoothness_with_laps)

    #
    # Test 14 -- deterministic output

    #
    def t_deterministic() -> None:
        import json
        sessions = [
            _make_session(session_date="2024-01-01", best_s=91.0),
            _make_session(session_date="2024-02-01", best_s=90.0),
            _make_session(session_date="2024-03-01", best_s=89.5),
        ]
        r1 = generate_driver_profile("X", sessions)
        r2 = generate_driver_profile("X", sessions)
        # Use JSON roundtrip: NaN is not JSON-serialisable, so if any NaN

        # leaks it will be caught here too.  json.dumps converts to string

        # for reliable equality comparison.

        s1 = json.dumps(r1, sort_keys=True)
        s2 = json.dumps(r2, sort_keys=True)
        assert s1 == s2, "Output must be deterministic"

    _test("deterministic", t_deterministic)

    #
    # Test 15 -- TypeError on bad inputs

    #
    def t_type_errors() -> None:
        try:
            generate_driver_profile(123, [])  # type: ignore[arg-type]
            raise AssertionError("Should have raised TypeError")
        except TypeError:
            pass

        try:
            generate_driver_profile("X", "not_a_list")  # type: ignore[arg-type]
            raise AssertionError("Should have raised TypeError")
        except TypeError:
            pass

    _test("type_errors", t_type_errors)

    #
    # Test 16 -- DriverProfileError on empty sessions list

    #
    def t_empty_sessions_error() -> None:
        try:
            generate_driver_profile("X", [])
            raise AssertionError("Should have raised DriverProfileError")
        except DriverProfileError:
            pass

    _test("empty_sessions_error", t_empty_sessions_error)

    #
    # Test 17 -- JSON serialisability

    #
    def t_json_serialisable() -> None:
        import json
        sessions = [
            _make_session(session_date="2024-01-01", session_id="s1",
                          resampled_laps=[_make_resampled_lap()]),
            _make_session(session_date="2024-02-01", session_id="s2", best_s=89.0),
            _make_session(session_date="2024-03-01", session_id="s3", best_s=88.5),
        ]
        result = generate_driver_profile("TestDriver", sessions)
        serialised = json.dumps(result)
        roundtrip  = json.loads(serialised)
        assert roundtrip["driver_name"] == "TestDriver"

    _test("json_serialisable", t_json_serialisable)

    #
    # Test 18 -- summary contains headline keys

    #
    def t_summary_keys() -> None:
        result = generate_driver_profile("X", [_make_session()])
        for key in ("mean_pace_delta_s", "consistency_rating",
                    "aggression_index", "smoothness_index", "trend_label"):
            assert key in result["summary"], f"Summary missing key: {key!r}"

    _test("summary_keys", t_summary_keys)

    #
    # Test 19 -- multi-session aggregation produces valid deltas list

    #
    def t_multi_session_deltas() -> None:
        sessions = [
            _make_session(best_s=91.0, session_date="2024-01-01"),
            _make_session(best_s=90.0, session_date="2024-02-01"),
            _make_session(best_s=89.5, session_date="2024-03-01"),
        ]
        result = generate_driver_profile("X", sessions)
        deltas = result["pace_delta"]["per_session_deltas"]
        assert len(deltas) == 3
        assert all(isinstance(d, float) for d in deltas)

    _test("multi_session_deltas", t_multi_session_deltas)

    #
    # Test 20 -- high braking -> higher aggression than low braking

    #
    def t_aggression_ordering() -> None:
        gentle = generate_driver_profile("X", [_make_session(braking_max=5.0)])
        hard   = generate_driver_profile("X", [_make_session(braking_max=14.0)])
        assert hard["aggression"]["index"] > gentle["aggression"]["index"]

    _test("aggression_ordering", t_aggression_ordering)

    #
    # Summary

    #
    total = len(passed) + len(failed)
    print(f"\nDriver Profile Tests: {len(passed)}/{total} passed")
    for name in passed:
        print(f"  \u2713 {name}")
    for name, tb in failed:
        print(f"  \u2717 {name}\n{tb}")

    if failed:
        raise AssertionError(f"{len(failed)} test(s) failed.")


# -- -

# Entry point

# -- -


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _run_tests()