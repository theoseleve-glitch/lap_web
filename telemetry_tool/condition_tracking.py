"""
condition_tracking.py
---------------------
Track evolution detection: identify when track conditions change mid-session
and label the resulting phases.

Public API
~~~~~~~~~~
``compute_grip_indicators(lap_metrics_df)``
    Derive per-lap grip / instability / braking proxy columns.

``detect_condition_changes(indicators_df, min_laps)``
    Robust z-score change detection with hysteresis.

``build_condition_phases(lap_metrics_df, change_points)``
    Assemble contiguous phases with confidence and signature.

``label_phases(phases_df, baseline, weather)``
    Heuristic labels for each phase's track state.

Design principles
~~~~~~~~~~~~~~~~~
- Pure functions; no global mutable state.
- NaN-robust: missing columns degrade gracefully.
- Deterministic: identical inputs â†’ identical outputs.
- Structured logging; zero print statements.
"""

from __future__ import annotations

import json
import logging
import math
from typing import Any, Final, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# -- -

# Column-name constants (aligned with feature_builder / features.py)

# -- -

_C_LAP:         Final[str] = "lap_number"
_C_LAP_TIME:    Final[str] = "lap_time_s"
_C_SPEED_MEAN:  Final[str] = "speed_mean_mps"
_C_BRAKING_MAX: Final[str] = "braking_max_mps2"
_C_ACCEL_RMS:   Final[str] = "accel_rms_mps2"
_C_JERK_RMS:    Final[str] = "jerk_rms_mps3"
_C_LAT_ACCEL:   Final[str] = "lat_accel_rms_mps2"
_C_LINE_LEN:    Final[str] = "line_length_m"

# Output indicator columns

_I_PACE_RES:    Final[str] = "pace_residual_s"
_I_GRIP:        Final[str] = "grip_proxy"
_I_INSTAB:      Final[str] = "instability_proxy"
_I_BRAKE:       Final[str] = "braking_proxy"

# Default z-score threshold for change detection (robust MAD-based)

_Z_THRESHOLD: Final[float] = 2.0
_HYSTERESIS_LAPS: Final[int] = 3

# Trend-based evolution detection

_TREND_MIN_LAPS: Final[int] = 10       # need >= 10 laps for trend analysis
_TREND_SIGNIFICANCE_PCT: Final[float] = 2.0  # total pace shift > 2% of mean -> significant
_TREND_SEGMENT_MIN: Final[int] = 5     # min laps per segment for piecewise fit
_EVOLUTION_SMOOTHING: Final[int] = 7   # smoothing window for evolution rate calc


# ============================================================================

# 1. compute_grip_indicators

# ============================================================================


def compute_grip_indicators(
    lap_metrics_df: pd.DataFrame,
    *,
    rolling_window: int = 9,
) -> pd.DataFrame:
    """
    Derive per-lap grip, instability, and braking proxy indicators.

    Parameters
    ----------
    lap_metrics_df:
        One row per lap.  Expected columns (all optional â€” absent columns
        produce NaN indicators):
        ``lap_number``, ``lap_time_s``, ``speed_mean_mps``,
        ``braking_max_mps2``, ``jerk_rms_mps3``, ``lat_accel_rms_mps2``.
    rolling_window:
        Window for the rolling median used to compute pace_residual.

    Returns
    -------
    pd.DataFrame
        Indexed by ``lap_number`` with columns:
        ``pace_residual_s``, ``grip_proxy``, ``instability_proxy``,
        ``braking_proxy``.
    """
    df = lap_metrics_df.copy()

    # Ensure lap_number index

    if _C_LAP in df.columns:
        df = df.set_index(_C_LAP, drop=False)
    elif df.index.name != _C_LAP:
        df.index.name = _C_LAP

    n = len(df)
    result = pd.DataFrame(index=df.index)

    # --- pace_residual_s: lap_time - rolling median -
    if _C_LAP_TIME in df.columns:
        lap_times = pd.to_numeric(df[_C_LAP_TIME], errors="coerce")
        win = min(rolling_window, max(1, n))
        rolling_med = lap_times.rolling(window=win, min_periods=1, center=True).median()
        result[_I_PACE_RES] = lap_times - rolling_med
    else:
        result[_I_PACE_RES] = np.nan

    # --- grip_proxy: normalised mean speed Ã— lateral accel -
    # Higher = more grip available

    speed = _safe_col(df, _C_SPEED_MEAN)
    lat_a = _safe_col(df, _C_LAT_ACCEL)
    if speed is not None and lat_a is not None:
        s_norm = _min_max_normalize(speed)
        l_norm = _min_max_normalize(lat_a)
        result[_I_GRIP] = (s_norm + l_norm) / 2.0
    else:
        result[_I_GRIP] = np.nan

    # --- instability_proxy: normalised jerk RMS -
    jerk = _safe_col(df, _C_JERK_RMS)
    if jerk is not None:
        result[_I_INSTAB] = _min_max_normalize(jerk)
    else:
        result[_I_INSTAB] = np.nan

    # --- braking_proxy: normalised peak braking -
    brake = _safe_col(df, _C_BRAKING_MAX)
    if brake is not None:
        result[_I_BRAKE] = _min_max_normalize(brake)
    else:
        result[_I_BRAKE] = np.nan

    result.index.name = _C_LAP
    logger.info(
        "Grip indicators: %d laps, finite pace_residual=%d, grip=%d",
        n,
        int(result[_I_PACE_RES].notna().sum()),
        int(result[_I_GRIP].notna().sum()),
    )
    return result


# ============================================================================

# 2. detect_condition_changes

# ============================================================================


def detect_condition_changes(
    indicators_df: pd.DataFrame,
    *,
    min_laps: int = 8,
    z_threshold: float = _Z_THRESHOLD,
    hysteresis: int = _HYSTERESIS_LAPS,
) -> list[int]:
    """
    Detect laps where track conditions change significantly.

    Uses robust z-scores (MAD-based) on ``pace_residual_s`` and
    ``grip_proxy``.  A change point must persist for at least
    *hysteresis* consecutive laps to be confirmed.

    Parameters
    ----------
    indicators_df:
        Output of :func:`compute_grip_indicators`.
    min_laps:
        Minimum number of laps required; returns ``[]`` if fewer.
    z_threshold:
        Robust z-score threshold for flagging a sample.
    hysteresis:
        Minimum consecutive flagged laps to confirm a change.

    Returns
    -------
    list[int]
        Lap numbers where a new phase begins (excludes the first lap).
    """
    if len(indicators_df) < min_laps:
        logger.info(
            "Condition detection skipped: %d laps < min_laps=%d.",
            len(indicators_df), min_laps,
        )
        return []

    # Combine z-scores from pace_residual and grip_proxy

    flags = np.zeros(len(indicators_df), dtype=bool)

    for col in (_I_PACE_RES, _I_GRIP):
        if col not in indicators_df.columns:
            continue
        values = pd.to_numeric(indicators_df[col], errors="coerce").values
        z = _robust_zscore(values)
        flags |= np.abs(z) > z_threshold

    # Apply hysteresis: require *hysteresis* consecutive flags

    change_laps: list[int] = []
    laps = indicators_df.index.tolist()
    run_length = 0
    change_announced = False

    for i, is_flag in enumerate(flags):
        if is_flag:
            run_length += 1
            if run_length == hysteresis and not change_announced:
                # Mark the START of the run as the change point

                start_idx = i - hysteresis + 1
                if start_idx > 0:  # exclude first lap
                    change_laps.append(int(laps[start_idx]))
                change_announced = True
        else:
            run_length = 0
            change_announced = False

    logger.info("Condition changes detected (z-score) at laps: %s", change_laps)
    return change_laps


def detect_condition_changes_combined(
    indicators_df: pd.DataFrame,
    lap_times: "list[float] | None" = None,
    *,
    min_laps: int = 8,
    z_threshold: float = _Z_THRESHOLD,
    hysteresis: int = _HYSTERESIS_LAPS,
) -> list[int]:
    """
    Combined detection: try z-score first, fall back to trend-based.

    If z-score detection finds changes, use those.  Otherwise, if
    there are enough laps, try gradual-evolution detection.  This
    ensures that both abrupt and gradual condition changes are caught.

    Returns
    -------
    list[int]
        Merged, deduplicated list of change-point lap numbers.
    """
    # Z-score detection (abrupt changes)

    z_changes = detect_condition_changes(
        indicators_df, min_laps=min_laps,
        z_threshold=z_threshold, hysteresis=hysteresis,
    )

    # Trend-based detection (gradual evolution)

    trend_changes = detect_gradual_evolution(
        indicators_df, lap_times=lap_times, min_laps=min_laps,
    )

    # Merge and deduplicate (keep changes that are >= 3 laps apart)

    all_changes = sorted(set(z_changes + trend_changes))
    if len(all_changes) <= 1:
        merged = all_changes
    else:
        merged = [all_changes[0]]
        for c in all_changes[1:]:
            if c - merged[-1] >= 3:
                merged.append(c)

    logger.info(
        "Combined detection: z=%s, trend=%s, merged=%s",
        z_changes, trend_changes, merged,
    )
    return merged


# ============================================================================

# 2b. merge_manual_changes (Phase 2 — CLI --condition-change)

# ============================================================================


def merge_manual_changes(
    auto_changes: list[int],
    manual_changes: "dict[int, str]",
) -> list[int]:
    """
    Merge user-supplied manual condition change points with auto-detected ones.

    Parameters
    ----------
    auto_changes : list[int]
        Change-point lap numbers from auto-detection.
    manual_changes : dict[int, str]
        Mapping of ``{lap_number: state_label}`` from ``--condition-change``.
        The state labels are stored but the function only needs the keys
        (lap numbers) for merging.  Labels are used later by ``label_phases``.

    Returns
    -------
    list[int]
        Merged, deduplicated, sorted list of change-point lap numbers.
    """
    manual_laps = list(manual_changes.keys())
    all_changes = sorted(set(auto_changes + manual_laps))

    # Deduplicate: keep changes >= 2 laps apart
    if len(all_changes) <= 1:
        merged = all_changes
    else:
        merged = [all_changes[0]]
        for c in all_changes[1:]:
            if c - merged[-1] >= 2:
                merged.append(c)
            else:
                # Prefer manual change point over auto-detected
                if c in manual_laps:
                    merged[-1] = c

    logger.info(
        "merge_manual_changes: auto=%s, manual=%s -> merged=%s",
        auto_changes, manual_laps, merged,
    )
    return merged


# ============================================================================

# 3. build_condition_phases

# ============================================================================


def build_condition_phases(
    lap_metrics_df: pd.DataFrame,
    change_points: list[int],
) -> pd.DataFrame:
    """
    Assemble contiguous condition phases covering all laps.

    Parameters
    ----------
    lap_metrics_df:
        One row per lap with ``lap_number``.
    change_points:
        Lap numbers where new phases begin.

    Returns
    -------
    pd.DataFrame
        Columns: ``phase_id``, ``lap_start``, ``lap_end``, ``n_laps``,
        ``confidence``, ``signature_json``.
    """
    if _C_LAP not in lap_metrics_df.columns:
        return pd.DataFrame(columns=[
            "phase_id", "lap_start", "lap_end", "n_laps",
            "confidence", "signature_json",
        ])

    all_laps = sorted(lap_metrics_df[_C_LAP].dropna().astype(int).tolist())
    if not all_laps:
        return pd.DataFrame(columns=[
            "phase_id", "lap_start", "lap_end", "n_laps",
            "confidence", "signature_json",
        ])

    # Build boundaries

    sorted_changes = sorted(set(change_points) & set(all_laps))
    boundaries = [all_laps[0]] + sorted_changes
    if boundaries[0] != all_laps[0]:
        boundaries = [all_laps[0]] + boundaries

    phases: list[dict[str, Any]] = []
    for pid, start in enumerate(boundaries):
        # End is just before the next boundary, or last lap

        if pid + 1 < len(boundaries):
            end_laps = [l for l in all_laps if start <= l < boundaries[pid + 1]]
        else:
            end_laps = [l for l in all_laps if l >= start]

        if not end_laps:
            continue

        lap_end = max(end_laps)
        n_laps = len(end_laps)

        # Compute signature: median of key metrics for laps in this phase

        phase_mask = lap_metrics_df[_C_LAP].isin(end_laps)
        phase_df = lap_metrics_df.loc[phase_mask]
        signature = _compute_phase_signature(phase_df)

        # Confidence: higher for longer phases, lower for single lap

        confidence = min(1.0, n_laps / 6.0)

        phases.append({
            "phase_id":       pid,
            "lap_start":      start,
            "lap_end":        lap_end,
            "n_laps":         n_laps,
            "confidence":     round(confidence, 3),
            "signature_json": json.dumps(signature, default=_json_default),
        })

    result = pd.DataFrame(phases)
    logger.info("Built %d condition phase(s) covering %d laps.", len(phases), len(all_laps))
    return result


# ============================================================================

# 4. label_phases

# ============================================================================


def label_phases(
    phases_df: pd.DataFrame,
    baseline: "TrackState",  # noqa: F821 (forward ref to avoid circular import)
    weather: Optional[Any] = None,
) -> pd.DataFrame:
    """
    Add ``phase_track_state`` and ``label_reason`` columns via heuristics.

    Parameters
    ----------
    phases_df:
        Output of :func:`build_condition_phases`.
    baseline:
        Starting track state from :class:`session_context.TrackState`.
    weather:
        Optional ``WeatherObs`` instance.

    Returns
    -------
    pd.DataFrame
        Input with two extra columns: ``phase_track_state``, ``label_reason``.
    """
    # Import here to avoid circular import

    from session_context import TrackState

    df = phases_df.copy()
    if df.empty:
        df["phase_track_state"] = pd.Series(dtype=str)
        df["label_reason"] = pd.Series(dtype=str)
        return df

    states: list[str] = []
    reasons: list[str] = []

    prev_state = baseline

    for _, row in df.iterrows():
        sig = _parse_signature(row.get("signature_json", "{}"))
        state, reason = _heuristic_label(prev_state, sig, weather)
        states.append(state.value)
        reasons.append(reason)
        prev_state = state

    df["phase_track_state"] = states
    df["label_reason"] = reasons
    return df


# ============================================================================

# 5. detect_gradual_evolution (trend-based)

# ============================================================================


def detect_gradual_evolution(
    indicators_df: pd.DataFrame,
    lap_times: "list[float] | None" = None,
    *,
    min_laps: int = _TREND_MIN_LAPS,
    significance_pct: float = _TREND_SIGNIFICANCE_PCT,
    segment_min: int = _TREND_SEGMENT_MIN,
) -> list[int]:
    """
    Detect gradual track evolution via piecewise linear segmentation.

    Unlike :func:`detect_condition_changes` (which finds abrupt z-score
    spikes), this function detects *smooth* trends -- e.g. a drying track
    where lap times decrease steadily over 60 laps.

    Algorithm
    ~~~~~~~~~
    1. Smooth lap times with a rolling median.
    2. Fit a global linear trend; if total shift < *significance_pct*
       of the mean, return [] (no evolution detected).
    3. Recursively split the session at the point that maximises the
       reduction in sum-of-squared residuals (binary segmentation).
    4. Stop splitting when segments have < *segment_min* laps or when
       the improvement from a split is < 5% of total variance.

    Returns
    -------
    list[int]
        Lap numbers where phase boundaries should be placed.
    """
    if len(indicators_df) < min_laps:
        return []

    # Extract lap times: prefer explicit list, else from indicators

    if lap_times is not None and len(lap_times) == len(indicators_df):
        times = np.array(lap_times, dtype=float)
    elif _I_PACE_RES in indicators_df.columns:
        # Reconstruct from pace residual + rolling median isn't possible

        # so fall back to index-based extraction

        return []
    else:
        return []

    laps = np.array(indicators_df.index.tolist(), dtype=int)
    finite_mask = np.isfinite(times)
    if finite_mask.sum() < min_laps:
        return []

    # Smooth

    win = min(7, len(times))
    smoothed = pd.Series(times).rolling(window=win, min_periods=1, center=True).median().values

    # Global trend significance check

    mean_time = float(np.nanmean(smoothed))
    if mean_time <= 0:
        return []

    n = len(smoothed)
    x = np.arange(n, dtype=float)
    slope = _linear_fit_slope(x, smoothed)
    total_shift_s = abs(slope * (n - 1))
    total_shift_pct = 100.0 * total_shift_s / mean_time

    if total_shift_pct < significance_pct:
        logger.info(
            "Gradual evolution: total shift %.1f%% < threshold %.1f%%; "
            "no evolution detected.",
            total_shift_pct, significance_pct,
        )
        return []

    logger.info(
        "Gradual evolution detected: slope=%.3f s/lap, "
        "total_shift=%.1f s (%.1f%%), %d laps.",
        slope, total_shift_s, total_shift_pct, n,
    )

    # Binary segmentation to find natural breakpoints

    change_indices = _binary_segmentation(smoothed, segment_min)

    # Convert indices to lap numbers

    change_laps = [int(laps[i]) for i in change_indices if 0 < i < n]
    logger.info("Gradual evolution breakpoints at laps: %s", change_laps)
    return change_laps


def _linear_fit_slope(x: np.ndarray, y: np.ndarray) -> float:
    """OLS slope of y vs x, NaN-safe."""
    mask = np.isfinite(y)
    if mask.sum() < 2:
        return 0.0
    xm, ym = x[mask], y[mask]
    x_mean, y_mean = xm.mean(), ym.mean()
    denom = float(((xm - x_mean) ** 2).sum())
    if denom < 1e-12:
        return 0.0
    return float(((xm - x_mean) * (ym - y_mean)).sum() / denom)


def _binary_segmentation(
    values: np.ndarray,
    min_seg: int,
    max_splits: int = 4,
) -> list[int]:
    """
    Recursive binary segmentation: find up to *max_splits* breakpoints
    that maximise reduction in sum-of-squared residuals from piecewise
    constant (mean) fit.
    """
    n = len(values)
    if n < 2 * min_seg or max_splits <= 0:
        return []

    total_ss = float(np.sum((values - np.mean(values)) ** 2))
    if total_ss < 1e-12:
        return []

    best_gain = 0.0
    best_idx = -1
    for i in range(min_seg, n - min_seg + 1):
        left = values[:i]
        right = values[i:]
        ss_left = float(np.sum((left - np.mean(left)) ** 2))
        ss_right = float(np.sum((right - np.mean(right)) ** 2))
        gain = total_ss - (ss_left + ss_right)
        if gain > best_gain:
            best_gain = gain
            best_idx = i

    # Require at least 5% variance reduction to split

    if best_idx < 0 or best_gain < 0.05 * total_ss:
        return []

    # Recurse on both sides

    left_breaks = _binary_segmentation(values[:best_idx], min_seg, max_splits - 1)
    right_breaks = _binary_segmentation(values[best_idx:], min_seg, max_splits - 1)
    right_breaks = [b + best_idx for b in right_breaks]

    return sorted(left_breaks + [best_idx] + right_breaks)


# ============================================================================

# 6. compute_track_evolution_rate

# ============================================================================


def compute_track_evolution_rate(
    phases_df: pd.DataFrame,
    lap_metrics_df: pd.DataFrame,
) -> dict[str, Any]:
    """
    Quantify track evolution across phases.

    For each phase, computes median pace, grip proxy, and the
    improvement rate relative to the first phase.

    Returns
    -------
    dict
        ``total_evolution_pct``  -- total pace improvement first->last phase [%]
        ``evolution_rate_s_per_lap`` -- average pace improvement [s/lap]
        ``grip_trend``          -- "improving" / "degrading" / "stable"
        ``phase_paces``         -- list of {phase_id, median_s, grip_proxy, ...}
        ``per_lap_expected_s``  -- list of expected lap times based on linear
                                   interpolation of phase medians (for
                                   adaptation scoring)
    """
    result: dict[str, Any] = {
        "total_evolution_pct": 0.0,
        "evolution_rate_s_per_lap": 0.0,
        "grip_trend": "stable",
        "phase_paces": [],
        "per_lap_expected_s": [],
    }

    if phases_df is None or phases_df.empty:
        return result

    col_lt = "lap_time_s"
    col_ln = "lap_number"
    if col_lt not in lap_metrics_df.columns or col_ln not in lap_metrics_df.columns:
        return result

    lm = lap_metrics_df.copy()
    lm[col_lt] = pd.to_numeric(lm[col_lt], errors="coerce")
    lm[col_ln] = pd.to_numeric(lm[col_ln], errors="coerce")

    phase_paces: list[dict[str, Any]] = []
    for _, row in phases_df.iterrows():
        pid = int(row["phase_id"])
        ls = int(row["lap_start"])
        le = int(row["lap_end"])
        mask = (lm[col_ln] >= ls) & (lm[col_ln] <= le)
        phase_times = lm.loc[mask, col_lt].dropna()
        if phase_times.empty:
            continue
        med = float(phase_times.median())
        best = float(phase_times.min())
        cv = float(phase_times.std() / phase_times.mean() * 100) if phase_times.mean() > 0 and len(phase_times) > 1 else 0.0
        mid_lap = (ls + le) / 2.0
        phase_paces.append({
            "phase_id": pid,
            "lap_start": ls,
            "lap_end": le,
            "mid_lap": mid_lap,
            "median_s": round(med, 3),
            "best_s": round(best, 3),
            "cv_pct": round(cv, 2),
            "n_laps": int(row.get("n_laps", le - ls + 1)),
        })

    if len(phase_paces) < 2:
        result["phase_paces"] = phase_paces
        return result

    # Compute evolution

    first_pace = phase_paces[0]["median_s"]
    last_pace = phase_paces[-1]["median_s"]
    if first_pace > 0:
        evo_pct = (first_pace - last_pace) / first_pace * 100.0
        total_laps = phase_paces[-1]["lap_end"] - phase_paces[0]["lap_start"]
        evo_rate = (first_pace - last_pace) / max(total_laps, 1)
    else:
        evo_pct = 0.0
        evo_rate = 0.0

    if evo_pct > 1.0:
        grip_trend = "improving"
    elif evo_pct < -1.0:
        grip_trend = "degrading"
    else:
        grip_trend = "stable"

    # Build per-lap expected pace (linear interpolation between phase midpoints)

    all_laps = sorted(lm[col_ln].dropna().astype(int).tolist())
    mid_laps = [pp["mid_lap"] for pp in phase_paces]
    mid_paces = [pp["median_s"] for pp in phase_paces]
    expected = np.interp([float(l) for l in all_laps], mid_laps, mid_paces)
    per_lap_expected = [{"lap": int(l), "expected_s": round(float(e), 3)}
                        for l, e in zip(all_laps, expected)]

    result["total_evolution_pct"] = round(evo_pct, 2)
    result["evolution_rate_s_per_lap"] = round(evo_rate, 3)
    result["grip_trend"] = grip_trend
    result["phase_paces"] = phase_paces
    result["per_lap_expected_s"] = per_lap_expected

    logger.info(
        "Track evolution: %.1f%% (%s), rate=%.3f s/lap, %d phases.",
        evo_pct, grip_trend, evo_rate, len(phase_paces),
    )
    return result


# ============================================================================

# Internal helpers

# ============================================================================


def _safe_col(df: pd.DataFrame, col: str) -> Optional[pd.Series]:
    """Return a numeric Series for *col* if present, else None."""
    if col not in df.columns:
        return None
    s = pd.to_numeric(df[col], errors="coerce")
    if s.isna().all():
        return None
    return s


def _min_max_normalize(s: pd.Series) -> pd.Series:
    """0â€“1 normalisation; returns NaN where input is NaN."""
    smin, smax = s.min(), s.max()
    if smin == smax or pd.isna(smin) or pd.isna(smax):
        return s * 0.0 + 0.5  # degenerate â†’ 0.5
    return (s - smin) / (smax - smin)


def _robust_zscore(values: np.ndarray) -> np.ndarray:
    """MAD-based robust z-score.  Returns 0 for NaN positions."""
    finite = values[np.isfinite(values)]
    if len(finite) < 3:
        return np.zeros_like(values)
    med = np.median(finite)
    mad = np.median(np.abs(finite - med))
    if mad < 1e-12:
        return np.zeros_like(values)
    scale = mad * 1.4826  # consistent with normal Ïƒ
    z = np.where(np.isfinite(values), (values - med) / scale, 0.0)
    return z


def _compute_phase_signature(phase_df: pd.DataFrame) -> dict[str, float]:
    """Compute median of key metrics for a phase."""
    sig: dict[str, float] = {}
    for col in (_C_LAP_TIME, _C_SPEED_MEAN, _C_BRAKING_MAX, _C_JERK_RMS, _C_LAT_ACCEL):
        if col in phase_df.columns:
            val = pd.to_numeric(phase_df[col], errors="coerce").median()
            sig[col] = round(float(val), 4) if not pd.isna(val) else float("nan")
    return sig


def _parse_signature(sig_json: str) -> dict[str, float]:
    """Parse a signature JSON string, returning empty dict on error."""
    try:
        return json.loads(sig_json)
    except (json.JSONDecodeError, TypeError):
        return {}


def _json_default(obj: Any) -> Any:
    """JSON serialiser fallback for numpy/pandas types."""
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return str(obj)


def _heuristic_label(
    prev_state: Any,
    signature: dict[str, float],
    weather: Optional[Any],
) -> tuple[Any, str]:
    """
    Simple heuristic: compare phase signature against previous state.

    Returns (new_state, reason_string).
    """
    from session_context import TrackState, WeatherObs

    # Check weather for rain hint

    is_raining = False
    if isinstance(weather, WeatherObs) and weather.humidity_pct is not None:
        is_raining = weather.humidity_pct > 85.0

    instab = signature.get(_C_JERK_RMS, float("nan"))
    grip_speed = signature.get(_C_SPEED_MEAN, float("nan"))
    braking = signature.get(_C_BRAKING_MAX, float("nan"))

    # If previous state was wet and instability is low â†’ drying

    if prev_state in (TrackState.WET, TrackState.FULL_WET):
        if not math.isnan(instab) and instab < 0.5:  # lower instability
            return TrackState.DRYING, "instability decreased from wet baseline"
        return prev_state, "no significant change from wet"

    # If previous was damp and instability increasing â†’ wet/greasy

    if prev_state == TrackState.DAMP:
        if is_raining:
            return TrackState.WET, "high humidity suggests rain during damp conditions"
        if not math.isnan(instab) and instab > 1.5:
            return TrackState.GREASY, "instability increased from damp baseline"
        return prev_state, "no significant change from damp"

    # If previous was green/dry and speed increasing â†’ rubbering in

    if prev_state in (TrackState.GREEN, TrackState.DRY):
        if not math.isnan(grip_speed) and not math.isnan(braking):
            return TrackState.RUBBERED, "grip indicators improving from dry/green"
        if is_raining:
            return TrackState.DAMP, "rain onset detected on dry track"
        return prev_state, "no significant change"

    if prev_state == TrackState.DRYING:
        return TrackState.DRY, "conditions continuing to improve"

    return prev_state, "no heuristic matched"


# ============================================================================

# Self-test

# ============================================================================


def _run_tests() -> None:
    import traceback as _tb

    passed: list[str] = []
    failed: list[tuple[str, str]] = []

    def _test(name: str, fn: Any) -> None:
        try:
            fn()
            passed.append(name)
        except Exception:
            failed.append((name, _tb.format_exc()))

    rng = np.random.default_rng(42)

    # --- Fixtures -
    def _make_lap_metrics(n: int = 20, trend: float = 0.0) -> pd.DataFrame:
        lap_nums = list(range(1, n + 1))
        base_time = 55.0
        return pd.DataFrame({
            _C_LAP:        lap_nums,
            _C_LAP_TIME:   [base_time + trend * i + rng.normal(0, 0.3) for i in range(n)],
            _C_SPEED_MEAN: [40.0 + rng.normal(0, 1) for _ in range(n)],
            _C_BRAKING_MAX:[14.0 + rng.normal(0, 0.5) for _ in range(n)],
            _C_JERK_RMS:   [3.0 + rng.normal(0, 0.3) for _ in range(n)],
            _C_LAT_ACCEL:  [8.0 + rng.normal(0, 0.5) for _ in range(n)],
        })

    # --- Tests -
    def t_grip_indicators_shape() -> None:
        df = _make_lap_metrics(12)
        ind = compute_grip_indicators(df)
        assert len(ind) == 12
        for col in (_I_PACE_RES, _I_GRIP, _I_INSTAB, _I_BRAKE):
            assert col in ind.columns

    _test("grip_indicators_shape", t_grip_indicators_shape)

    def t_grip_indicators_missing_cols() -> None:
        """Should return NaN columns instead of crashing."""
        df = pd.DataFrame({_C_LAP: [1, 2, 3]})
        ind = compute_grip_indicators(df)
        assert len(ind) == 3
        assert ind[_I_PACE_RES].isna().all()

    _test("grip_indicators_missing_cols", t_grip_indicators_missing_cols)

    def t_detect_no_changes_stable() -> None:
        df = _make_lap_metrics(15, trend=0.0)
        ind = compute_grip_indicators(df)
        changes = detect_condition_changes(ind)
        assert isinstance(changes, list)
        # Stable session â†’ no changes or very few

        assert len(changes) <= 1

    _test("detect_no_changes_stable", t_detect_no_changes_stable)

    def t_detect_too_few_laps() -> None:
        df = _make_lap_metrics(5)
        ind = compute_grip_indicators(df)
        changes = detect_condition_changes(ind, min_laps=8)
        assert changes == []

    _test("detect_too_few_laps", t_detect_too_few_laps)

    def t_build_phases_no_changes() -> None:
        df = _make_lap_metrics(10)
        phases = build_condition_phases(df, [])
        assert len(phases) == 1
        assert phases.iloc[0]["lap_start"] == 1
        assert phases.iloc[0]["lap_end"] == 10

    _test("build_phases_no_changes", t_build_phases_no_changes)

    def t_build_phases_with_split() -> None:
        df = _make_lap_metrics(10)
        phases = build_condition_phases(df, [5])
        assert len(phases) == 2
        assert phases.iloc[0]["lap_end"] == 4
        assert phases.iloc[1]["lap_start"] == 5

    _test("build_phases_with_split", t_build_phases_with_split)

    def t_label_phases_basic() -> None:
        from session_context import TrackState
        df = _make_lap_metrics(10)
        phases = build_condition_phases(df, [6])
        labelled = label_phases(phases, TrackState.DRY)
        assert "phase_track_state" in labelled.columns
        assert "label_reason" in labelled.columns
        assert len(labelled) == 2

    _test("label_phases_basic", t_label_phases_basic)

    def t_label_phases_empty() -> None:
        from session_context import TrackState
        empty = pd.DataFrame(columns=[
            "phase_id", "lap_start", "lap_end", "n_laps",
            "confidence", "signature_json",
        ])
        result = label_phases(empty, TrackState.DRY)
        assert "phase_track_state" in result.columns
        assert len(result) == 0

    _test("label_phases_empty", t_label_phases_empty)

    # --- Trend detection tests -

    def t_detect_gradual_evolution_drying() -> None:
        """A drying track with steadily decreasing lap times should detect phases."""
        n = 60
        lap_nums = list(range(1, n + 1))
        # Simulate drying: 70s -> 52s over 60 laps with noise

        rng2 = np.random.default_rng(99)
        times = [70.0 - 18.0 * i / (n - 1) + rng2.normal(0, 0.5) for i in range(n)]
        lm = pd.DataFrame({
            _C_LAP: lap_nums,
            _C_LAP_TIME: times,
            _C_SPEED_MEAN: [30.0 + 10.0 * i / n + rng2.normal(0, 0.3) for i in range(n)],
            _C_BRAKING_MAX: [10.0 + rng2.normal(0, 0.3) for _ in range(n)],
            _C_JERK_RMS:   [3.0 + rng2.normal(0, 0.2) for _ in range(n)],
            _C_LAT_ACCEL:  [6.0 + 3.0 * i / n + rng2.normal(0, 0.3) for i in range(n)],
        })
        ind = compute_grip_indicators(lm)
        changes = detect_gradual_evolution(ind, lap_times=times)
        assert len(changes) >= 1, (
            f"Drying track should detect at least 1 breakpoint, got {changes}"
        )

    _test("detect_gradual_evolution_drying", t_detect_gradual_evolution_drying)

    def t_combined_detection_stable() -> None:
        """Stable session should still return no/few changes."""
        df = _make_lap_metrics(20, trend=0.0)
        ind = compute_grip_indicators(df)
        times = df[_C_LAP_TIME].tolist()
        changes = detect_condition_changes_combined(ind, lap_times=times)
        assert len(changes) <= 1

    _test("combined_detection_stable", t_combined_detection_stable)

    def t_track_evolution_rate_basic() -> None:
        n = 30
        rng3 = np.random.default_rng(77)
        lm = pd.DataFrame({
            _C_LAP: list(range(1, n + 1)),
            _C_LAP_TIME: [60.0 - 8.0 * i / (n - 1) + rng3.normal(0, 0.3) for i in range(n)],
        })
        phases = build_condition_phases(lm, [11, 21])
        evo = compute_track_evolution_rate(phases, lm)
        assert evo["total_evolution_pct"] > 0, "Track was improving"
        assert evo["grip_trend"] == "improving"
        assert len(evo["phase_paces"]) == 3
        assert len(evo["per_lap_expected_s"]) == n

    _test("track_evolution_rate_basic", t_track_evolution_rate_basic)

    # -- Summary -
    total = len(passed) + len(failed)
    print(f"\nCondition Tracking Tests: {len(passed)}/{total} passed")
    for n in passed:
        print(f"  âœ“ {n}")
    for n, tb in failed:
        print(f"  âœ— {n}\n{tb}")
    if failed:
        raise AssertionError(f"{len(failed)} test(s) failed.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _run_tests()
