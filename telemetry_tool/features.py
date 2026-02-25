"""
features.py
-----------
Modular, typed feature-extraction functions for motorsport telemetry.

Each function accepts a pandas DataFrame (or Series/list for aggregate
functions) and returns a plain dict so results can be easily serialised,
logged, or assembled into a feature matrix for ML.

Functions
~~~~~~~~~
``compute_lap_time(lap_df)``
    Scalar lap duration from the time column.

``compute_consistency_metrics(lap_times)``
    Std deviation and best-to-median gap across multiple lap times.

``compute_speed_profile_features(resampled_lap)``
    Min / max / mean / p10 / p90 speed, and speed-below-threshold fraction.

``compute_accel_features(resampled_lap)``
    Max acceleration, max braking, RMS longitudinal accel, and jerk metrics.

``compute_line_length(lap_df)``
    Total arc length driven, computed via haversine (GPS) or Euclidean (XY).

Design principles
~~~~~~~~~~~~~~~~~
- Modular: every function is independently usable.
- Numpy / pandas only â€” no scipy, no plotting.
- Type hints throughout.
- All functions are NaN-robust: channels with insufficient valid data return
  NaN rather than crashing.
- No side effects, no global state, no print statements.
"""

from __future__ import annotations

import logging
from typing import Any, Final

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# -- -

# Column-name constants

# -- -


_COL_TIME:  Final[str] = "Time (s)"
_COL_SPEED: Final[str] = "Speed (m/s)"
_COL_DIST:  Final[str] = "Distance (m)"
_COL_LAT:   Final[str] = "Latitude (deg)"
_COL_LON:   Final[str] = "Longitude (deg)"
_COL_X:     Final[str] = "X (m)"
_COL_Y:     Final[str] = "Y (m)"
_COL_LONG:  Final[str] = "accel_long_mps2"   # internal standardised name
_COL_LAT_A: Final[str] = "accel_lat_mps2"    # internal standardised name

# Speed below which a sample counts as "slow" for the stuck fraction metric

_SLOW_SPEED_THRESHOLD_MPS: Final[float] = 5.0

# -- -

# Exceptions

# -- -


class FeatureExtractionError(ValueError):
    """Raised when a required column is missing or data is structurally invalid."""


# -- -

# Internal helpers

# -- -


def _get_numeric(df: pd.DataFrame, col: str) -> np.ndarray:
    """Return a finite-values-only numpy array for *col*, or empty array."""
    if col not in df.columns:
        return np.array([], dtype=float)
    vals = pd.to_numeric(df[col], errors="coerce").values
    return vals[np.isfinite(vals)]


def _safe_stat(values: np.ndarray, fn) -> float:  # type: ignore[type-arg]
    """Apply *fn* to *values*; return NaN if fewer than 2 finite values."""
    if len(values) < 2:
        return float("nan")
    return float(fn(values))


def _require_column(df: pd.DataFrame, col: str) -> None:
    if col not in df.columns:
        raise FeatureExtractionError(
            f"Required column {col!r} not found. "
            f"Available: {list(df.columns)}"
        )


# -- -

# 1. Lap time

# -- -


def compute_lap_time(lap_df: pd.DataFrame) -> dict[str, Any]:
    """
    Compute the duration of a single lap.

    Parameters
    ----------
    lap_df:
        Single-lap telemetry DataFrame containing ``Time (s)``.

    Returns
    -------
    dict with keys:
        ``lap_time_s``   â€“ float â€“ duration in seconds (NaN if unavailable)
        ``t_start_s``    â€“ float â€“ session time at lap start
        ``t_end_s``      â€“ float â€“ session time at lap end
        ``sample_count`` â€“ int   â€“ number of rows in the lap
    """
    sample_count = len(lap_df)

    if _COL_TIME not in lap_df.columns:
        logger.warning("Column %r absent; lap_time_s will be NaN.", _COL_TIME)
        return {
            "lap_time_s":   float("nan"),
            "t_start_s":    float("nan"),
            "t_end_s":      float("nan"),
            "sample_count": sample_count,
        }

    t = pd.to_numeric(lap_df[_COL_TIME], errors="coerce").dropna()

    if len(t) < 2:
        return {
            "lap_time_s":   float("nan"),
            "t_start_s":    float(t.iloc[0]) if len(t) == 1 else float("nan"),
            "t_end_s":      float(t.iloc[0]) if len(t) == 1 else float("nan"),
            "sample_count": sample_count,
        }

    return {
        "lap_time_s":   round(float(t.max() - t.min()), 3),
        "t_start_s":    round(float(t.min()),            3),
        "t_end_s":      round(float(t.max()),            3),
        "sample_count": sample_count,
    }


# -- -

# 2. Consistency metrics

# -- -


def compute_consistency_metrics(
    lap_times: list[float] | pd.Series | np.ndarray,
    *,
    min_laps: int = 2,
) -> dict[str, Any]:
    """
    Compute cross-lap consistency metrics from a collection of lap durations.

    Parameters
    ----------
    lap_times:
        Iterable of lap times in seconds.  NaN values are silently removed.
    min_laps:
        Minimum number of valid laps required to compute meaningful statistics.
        Below this count, metrics are NaN.  Default: 2.

    Returns
    -------
    dict with keys:
        ``n_laps``          â€“ int   â€“ number of valid laps used
        ``best_s``          â€“ float â€“ fastest lap time
        ``worst_s``         â€“ float â€“ slowest lap time
        ``mean_s``          â€“ float â€“ mean lap time
        ``median_s``        â€“ float â€“ median lap time
        ``std_s``           â€“ float â€“ standard deviation of lap times
        ``cv_pct``          â€“ float â€“ coefficient of variation (std/mean Ã— 100)
        ``best_to_median_s``â€“ float â€“ gap between best and median lap time
        ``best_to_mean_s``  â€“ float â€“ gap between best and mean lap time
    """
    arr = np.asarray(lap_times, dtype=float)
    arr = arr[np.isfinite(arr)]
    n   = len(arr)

    if n < min_laps:
        logger.debug(
            "Only %d valid lap(s); consistency metrics require â‰¥ %d.", n, min_laps
        )
        return {
            "n_laps":           n,
            "best_s":           float(arr.min()) if n == 1 else float("nan"),
            "worst_s":          float(arr.max()) if n == 1 else float("nan"),
            "mean_s":           float("nan"),
            "median_s":         float("nan"),
            "std_s":            float("nan"),
            "cv_pct":           float("nan"),
            "best_to_median_s": float("nan"),
            "best_to_mean_s":   float("nan"),
        }

    best   = float(arr.min())
    worst  = float(arr.max())
    mean   = float(arr.mean())
    median = float(np.median(arr))
    std    = float(arr.std(ddof=1))
    cv     = (std / mean * 100.0) if mean > 0 else float("nan")

    return {
        "n_laps":           n,
        "best_s":           round(best,          3),
        "worst_s":          round(worst,         3),
        "mean_s":           round(mean,          3),
        "median_s":         round(median,        3),
        "std_s":            round(std,           3),
        "cv_pct":           round(cv,            4),
        "best_to_median_s": round(median - best, 3),
        "best_to_mean_s":   round(mean   - best, 3),
    }


# -- -

# 2b. Detrended consistency (for evolving conditions)

# -- -


def compute_detrended_consistency(
    lap_times: list[float] | pd.Series | np.ndarray,
    *,
    lap_to_phase: dict[int, int] | None = None,
    min_laps: int = 2,
) -> dict[str, Any]:
    """
    Compute consistency metrics that account for evolving track conditions.

    On a drying track, lap times naturally decrease from ~70s to ~52s.
    Raw CV% would be huge even if the driver is perfectly consistent
    *within* each condition phase.  This function provides two
    complementary approaches:

    1. **Detrended CV**: Fit a linear trend through lap times, then
       measure CV of the *residuals* around that trend.
    2. **Per-phase CV**: If ``lap_to_phase`` is provided, compute CV
       within each phase and return a lap-count-weighted average.

    The final ``adjusted_cv_pct`` is the minimum of the two (most
    favourable for the driver), since both capture the same insight:
    the driver is consistent relative to evolving conditions.

    Parameters
    ----------
    lap_times:
        Iterable of lap times in seconds.
    lap_to_phase:
        ``{lap_index: phase_id}`` mapping from condition_tracking.
    min_laps:
        Minimum laps required per phase.

    Returns
    -------
    dict with keys:
        ``detrended_cv_pct``   -- CV of residuals around linear fit
        ``per_phase_cv_pct``   -- lap-weighted mean of per-phase CVs
        ``adjusted_cv_pct``    -- min(detrended, per_phase) [best estimate]
        ``detrended_std_s``    -- std of residuals (seconds)
        ``n_phases``           -- number of phases with enough data
        ``raw_cv_pct``         -- original un-adjusted CV for reference
    """
    arr = np.asarray(lap_times, dtype=float)
    arr = arr[np.isfinite(arr)]
    n = len(arr)

    nan_result = {
        "detrended_cv_pct": float("nan"),
        "per_phase_cv_pct": float("nan"),
        "adjusted_cv_pct":  float("nan"),
        "detrended_std_s":  float("nan"),
        "n_phases":         0,
        "raw_cv_pct":       float("nan"),
    }

    if n < min_laps:
        return nan_result

    raw_mean = float(arr.mean())
    raw_std  = float(arr.std(ddof=1))
    raw_cv   = (raw_std / raw_mean * 100.0) if raw_mean > 0 else float("nan")

    # --- 1. Detrended CV: fit linear trend, measure residuals -- -

    x = np.arange(n, dtype=float)
    try:
        coeffs = np.polyfit(x, arr, 1)  # [slope, intercept]
        trend = np.polyval(coeffs, x)
        residuals = arr - trend
        res_std = float(residuals.std(ddof=1)) if n > 2 else raw_std
        # CV of residuals relative to the mean lap time

        detrended_cv = (res_std / raw_mean * 100.0) if raw_mean > 0 else raw_cv
    except (np.linalg.LinAlgError, ValueError):
        detrended_cv = raw_cv
        res_std = raw_std

    # --- 2. Per-phase CV: weighted average of within-phase CVs -- -

    per_phase_cv = float("nan")
    n_phases = 0

    if lap_to_phase is not None:
        phase_groups: dict[int, list[float]] = {}
        for i in range(n):
            # lap_to_phase keys may be 0-indexed or lap-number indexed

            pid = lap_to_phase.get(i)
            if pid is None:
                # Try 1-indexed

                pid = lap_to_phase.get(i + 1)
            if pid is not None:
                phase_groups.setdefault(pid, []).append(arr[i])

        phase_cvs: list[tuple[int, float]] = []  # (n_laps, cv)
        for pid, times in phase_groups.items():
            if len(times) < min_laps:
                continue
            t = np.array(times)
            mu = float(t.mean())
            sd = float(t.std(ddof=1))
            if mu > 0:
                phase_cvs.append((len(times), sd / mu * 100.0))

        n_phases = len(phase_cvs)

        if n_phases > 0:
            total_laps = sum(n_l for n_l, _ in phase_cvs)
            if total_laps > 0:
                per_phase_cv = sum(n_l * cv for n_l, cv in phase_cvs) / total_laps

    # --- 3. Adjusted CV: best of both approaches -
    candidates = [c for c in (detrended_cv, per_phase_cv) if np.isfinite(c)]
    adjusted_cv = min(candidates) if candidates else raw_cv

    logger.info(
        "Detrended consistency: raw_cv=%.3f%%  detrended=%.3f%%  "
        "per_phase=%.3f%%  adjusted=%.3f%%  n_phases=%d",
        raw_cv,
        detrended_cv,
        per_phase_cv if np.isfinite(per_phase_cv) else -1.0,
        adjusted_cv,
        n_phases,
    )

    return {
        "detrended_cv_pct": round(detrended_cv, 4),
        "per_phase_cv_pct": round(per_phase_cv, 4) if np.isfinite(per_phase_cv) else float("nan"),
        "adjusted_cv_pct":  round(adjusted_cv, 4),
        "detrended_std_s":  round(res_std, 4),
        "n_phases":         n_phases,
        "raw_cv_pct":       round(raw_cv, 4),
    }


# -- -

# 3. Speed profile features

# -- -


def compute_speed_profile_features(
    resampled_lap: pd.DataFrame,
    *,
    slow_threshold_mps: float = _SLOW_SPEED_THRESHOLD_MPS,
) -> dict[str, Any]:
    """
    Extract speed profile statistics from a distance-resampled lap.

    Parameters
    ----------
    resampled_lap:
        Distance-resampled DataFrame (output of ``resampling.py``).
        Must contain ``Speed (m/s)``.
    slow_threshold_mps:
        Speed below which a sample is counted as "slow" (e.g. corner apex).
        Default: 5.0 m/s.

    Returns
    -------
    dict with keys:
        ``speed_min_mps``      â€“ float â€“ minimum speed
        ``speed_max_mps``      â€“ float â€“ maximum speed
        ``speed_mean_mps``     â€“ float â€“ mean speed
        ``speed_median_mps``   â€“ float â€“ median speed
        ``speed_std_mps``      â€“ float â€“ std deviation of speed
        ``speed_p10_mps``      â€“ float â€“ 10th percentile (slow corner speed proxy)
        ``speed_p90_mps``      â€“ float â€“ 90th percentile (straight speed proxy)
        ``slow_fraction``      â€“ float â€“ fraction of samples below *slow_threshold_mps*
        ``speed_range_mps``    â€“ float â€“ max âˆ’ min
        ``sample_count``       â€“ int
    """
    spd = _get_numeric(resampled_lap, _COL_SPEED)

    if len(spd) < 2:
        logger.warning("Insufficient speed data (%d valid samples).", len(spd))
        return {k: float("nan") for k in (
            "speed_min_mps", "speed_max_mps", "speed_mean_mps", "speed_median_mps",
            "speed_std_mps", "speed_p10_mps", "speed_p90_mps",
            "slow_fraction", "speed_range_mps",
        )} | {"sample_count": len(resampled_lap)}

    slow_frac = float((spd < slow_threshold_mps).sum()) / len(spd)

    return {
        "speed_min_mps":    round(float(spd.min()),                        3),
        "speed_max_mps":    round(float(spd.max()),                        3),
        "speed_mean_mps":   round(float(spd.mean()),                       3),
        "speed_median_mps": round(float(np.median(spd)),                   3),
        "speed_std_mps":    round(float(spd.std(ddof=1)) if len(spd) > 1 else float("nan"), 3),
        "speed_p10_mps":    round(float(np.percentile(spd, 10)),           3),
        "speed_p90_mps":    round(float(np.percentile(spd, 90)),           3),
        "slow_fraction":    round(slow_frac,                               4),
        "speed_range_mps":  round(float(spd.max() - spd.min()),            3),
        "sample_count":     len(resampled_lap),
    }


# -- -

# 4. Acceleration features

# -- -


def compute_accel_features(
    resampled_lap: pd.DataFrame,
    *,
    jerk_window: int = 3,
) -> dict[str, Any]:
    """
    Extract longitudinal acceleration and jerk features.

    If ``accel_long_mps2`` is absent, the function falls back to computing
    acceleration numerically from ``Speed (m/s)`` vs ``Distance (m)``.

    Parameters
    ----------
    resampled_lap:
        Distance-resampled DataFrame.
    jerk_window:
        Half-window (samples) used for Gaussian smoothing of the acceleration
        signal before computing its derivative (jerk).  Pass 1 to disable.

    Returns
    -------
    dict with keys:
        ``accel_max_mps2``       â€“ float â€“ peak positive longitudinal accel
        ``accel_rms_mps2``       â€“ float â€“ RMS longitudinal accel
        ``braking_max_mps2``     â€“ float â€“ peak deceleration (positive value)
        ``jerk_max_mps3``        â€“ float â€“ peak positive jerk
        ``jerk_min_mps3``        â€“ float â€“ peak negative jerk (most abrupt brake)
        ``jerk_rms_mps3``        â€“ float â€“ RMS jerk (smoothness proxy)
        ``lat_accel_max_mps2``   â€“ float â€“ peak lateral accel magnitude (if available)
        ``lat_accel_rms_mps2``   â€“ float â€“ RMS lateral accel (if available)
        ``sample_count``         â€“ int
    """
    # --- Longitudinal acceleration source -- -

    if _COL_LONG in resampled_lap.columns and (
        pd.to_numeric(resampled_lap[_COL_LONG], errors="coerce").notna().any()
    ):
        long_raw = pd.to_numeric(resampled_lap[_COL_LONG], errors="coerce").values
    elif _COL_SPEED in resampled_lap.columns and _COL_DIST in resampled_lap.columns:
        spd  = pd.to_numeric(resampled_lap[_COL_SPEED], errors="coerce").values
        dist = pd.to_numeric(resampled_lap[_COL_DIST],  errors="coerce").values
        ds   = np.diff(dist)
        ds   = np.where((ds > 0) & np.isfinite(ds), ds, np.nan)
        dv   = np.diff(np.where(np.isfinite(spd), spd, np.nan))
        a    = dv / ds
        long_raw = np.concatenate([[np.nan], a])
    else:
        long_raw = np.full(len(resampled_lap), np.nan)

    long_vals = long_raw[np.isfinite(long_raw)]

    # --- Jerk (d/ds of smoothed acceleration) -- -

    jerk_rms = jerk_max = jerk_min = float("nan")
    if len(long_vals) >= max(4, 2 * jerk_window + 1):
        # Smooth acceleration before differentiation to reduce noise amplification

        smoothed = _gaussian_smooth_1d(long_vals, jerk_window)
        # Jerk units: m/s³ when distance is uniform; adequate proxy

        jerk     = np.diff(smoothed)
        jerk_rms = float(np.sqrt(np.mean(jerk ** 2)))
        jerk_max = float(jerk.max())
        jerk_min = float(jerk.min())

    # --- Lateral acceleration (optional)
    lat_vals = _get_numeric(resampled_lap, _COL_LAT_A)

    def _nn(v: float) -> float:
        return round(v, 4) if np.isfinite(v) else float("nan")

    return {
        "accel_max_mps2":     _nn(float(long_vals[long_vals > 0].max()) if (long_vals > 0).any() else float("nan")),
        "accel_rms_mps2":     _nn(_safe_stat(long_vals, lambda v: np.sqrt(np.mean(v**2)))),
        "braking_max_mps2":   _nn(float(np.abs(long_vals[long_vals < 0]).max()) if (long_vals < 0).any() else float("nan")),
        "jerk_max_mps3":      _nn(jerk_max),
        "jerk_min_mps3":      _nn(jerk_min),
        "jerk_rms_mps3":      _nn(jerk_rms),
        "lat_accel_max_mps2": _nn(float(np.abs(lat_vals).max()) if len(lat_vals) > 0 else float("nan")),
        "lat_accel_rms_mps2": _nn(_safe_stat(lat_vals, lambda v: np.sqrt(np.mean(v**2)))),
        "sample_count":       len(resampled_lap),
    }


# -- -

# 5. Line length

# -- -


def compute_line_length(lap_df: pd.DataFrame) -> dict[str, Any]:
    """
    Compute the total arc length driven in a single lap.

    Source priority
    ~~~~~~~~~~~~~~~
    1. ``Distance (m)`` column  â€“ span = max âˆ’ min (most accurate).
    2. XY position columns      â€“ Euclidean sum of point-to-point steps.
    3. GPS lat/lon columns      â€“ Haversine sum.

    Parameters
    ----------
    lap_df:
        Single-lap telemetry DataFrame.

    Returns
    -------
    dict with keys:
        ``line_length_m`` â€“ float â€“ total driven distance in metres
        ``source``        â€“ str   â€“ which data source was used
        ``sample_count``  â€“ int
    """
    n = len(lap_df)

    # Source 1 â€“ Distance column

    if _COL_DIST in lap_df.columns:
        d = pd.to_numeric(lap_df[_COL_DIST], errors="coerce").dropna()
        if len(d) >= 2:
            length = float(d.max() - d.min())
            return {
                "line_length_m": round(length, 2),
                "source":        "Distance (m)",
                "sample_count":  n,
            }

    # Source 2 â€“ XY Euclidean

    if _COL_X in lap_df.columns and _COL_Y in lap_df.columns:
        x = pd.to_numeric(lap_df[_COL_X], errors="coerce").values
        y = pd.to_numeric(lap_df[_COL_Y], errors="coerce").values
        mask = np.isfinite(x) & np.isfinite(y)
        if mask.sum() >= 2:
            dx = np.diff(x[mask]); dy = np.diff(y[mask])
            length = float(np.sqrt(dx**2 + dy**2).sum())
            return {
                "line_length_m": round(length, 2),
                "source":        "XY Euclidean",
                "sample_count":  n,
            }

    # Source 3 â€“ GPS Haversine

    if _COL_LAT in lap_df.columns and _COL_LON in lap_df.columns:
        lat = pd.to_numeric(lap_df[_COL_LAT], errors="coerce").values
        lon = pd.to_numeric(lap_df[_COL_LON], errors="coerce").values
        mask = np.isfinite(lat) & np.isfinite(lon)
        if mask.sum() >= 2:
            length = _haversine_sum(lat[mask], lon[mask])
            return {
                "line_length_m": round(length, 2),
                "source":        "GPS haversine",
                "sample_count":  n,
            }

    logger.warning("No valid distance source found; line_length_m will be NaN.")
    return {"line_length_m": float("nan"), "source": "none", "sample_count": n}


# -- -

# Private numeric helpers

# -- -


def _haversine_sum(lat: np.ndarray, lon: np.ndarray) -> float:
    """Sum of point-to-point great-circle distances (metres)."""
    R     = 6_371_000.0
    lat_r = np.radians(lat); lon_r = np.radians(lon)
    dlat  = np.diff(lat_r);  dlon  = np.diff(lon_r)
    a     = np.sin(dlat / 2)**2 + np.cos(lat_r[:-1]) * np.cos(lat_r[1:]) * np.sin(dlon / 2)**2
    return float(2 * R * np.arcsin(np.sqrt(np.clip(a, 0, 1))).sum())


def _gaussian_smooth_1d(signal: np.ndarray, half_window: int) -> np.ndarray:
    """Apply a Gaussian-weighted rolling average to a 1-D array."""
    if half_window <= 1 or len(signal) < 3:
        return signal.copy()
    k = 2 * half_window + 1
    x = np.arange(k) - half_window
    w = np.exp(-0.5 * (x / max(half_window / 2.0, 0.5)) ** 2)
    w /= w.sum()
    padded = np.pad(signal, half_window, mode="reflect")
    out    = np.convolve(padded, w, mode="valid")
    return out[:len(signal)]


# -- -

# Unit tests

# -- -


def _run_tests() -> None:
    import traceback

    passed: list[str] = []
    failed: list[tuple[str, str]] = []

    def _test(name: str, fn) -> None:   # type: ignore[type-arg]
        try:
            fn()
            passed.append(name)
        except Exception:   # noqa: BLE001
            failed.append((name, traceback.format_exc()))

    rng = np.random.default_rng(42)
    N   = 500
    dist_arr = np.linspace(0.0, 4500.0, N)
    time_arr = np.linspace(0.0, 95.0,   N)
    spd_arr  = 30.0 + 20.0 * np.sin(2 * np.pi * dist_arr / 4500.0)
    accel_arr = np.gradient(spd_arr, dist_arr)

    def _base_df() -> pd.DataFrame:
        return pd.DataFrame({
            _COL_TIME:  time_arr,
            _COL_DIST:  dist_arr,
            _COL_SPEED: spd_arr,
            _COL_LONG:  accel_arr,
        })

    #
    # compute_lap_time

    #
    def t_lap_time_correct() -> None:
        feat = compute_lap_time(_base_df())
        np.testing.assert_allclose(feat["lap_time_s"], 95.0, rtol=1e-3)
        assert feat["sample_count"] == N

    _test("lap_time_correct", t_lap_time_correct)

    def t_lap_time_missing_col() -> None:
        df   = pd.DataFrame({"Speed (m/s)": [10.0, 20.0]})
        feat = compute_lap_time(df)
        assert np.isnan(feat["lap_time_s"])

    _test("lap_time_missing_col", t_lap_time_missing_col)

    def t_lap_time_single_row() -> None:
        df   = pd.DataFrame({_COL_TIME: [42.0], _COL_SPEED: [30.0]})
        feat = compute_lap_time(df)
        assert np.isnan(feat["lap_time_s"])

    _test("lap_time_single_row", t_lap_time_single_row)

    #
    # compute_consistency_metrics

    #
    def t_consistency_std_correct() -> None:
        times = [90.0, 90.5, 89.8, 91.2, 90.3]
        feat  = compute_consistency_metrics(times)
        expected_std = round(float(np.array(times).std(ddof=1)), 3)
        np.testing.assert_allclose(feat["std_s"], expected_std, rtol=1e-6)

    _test("consistency_std_correct", t_consistency_std_correct)

    def t_consistency_best_to_median() -> None:
        times = [90.0, 90.5, 89.8, 91.2, 90.3]
        feat  = compute_consistency_metrics(times)
        assert feat["best_to_median_s"] >= 0, "Best-to-median should be â‰¥ 0"
        expected = float(np.median(times) - min(times))
        np.testing.assert_allclose(feat["best_to_median_s"], expected, rtol=1e-6)

    _test("consistency_best_to_median", t_consistency_best_to_median)

    def t_consistency_nan_stripped() -> None:
        times = [90.0, float("nan"), 89.5, float("nan"), 91.0]
        feat  = compute_consistency_metrics(times)
        assert feat["n_laps"] == 3, f"Expected 3 valid laps, got {feat['n_laps']}"

    _test("consistency_nan_stripped", t_consistency_nan_stripped)

    def t_consistency_single_lap() -> None:
        feat = compute_consistency_metrics([92.3])
        assert np.isnan(feat["std_s"])
        assert feat["n_laps"] == 1

    _test("consistency_single_lap", t_consistency_single_lap)

    def t_consistency_cv_correct() -> None:
        times = [100.0, 100.0, 100.0]   # zero variance â†’ cv=0
        feat  = compute_consistency_metrics(times)
        np.testing.assert_allclose(feat["cv_pct"], 0.0, atol=1e-9)

    _test("consistency_cv_zero_variance", t_consistency_cv_correct)

    #
    # compute_speed_profile_features

    #
    def t_speed_min_max() -> None:
        df   = _base_df()
        feat = compute_speed_profile_features(df)
        np.testing.assert_allclose(feat["speed_min_mps"], round(float(spd_arr.min()), 3), rtol=1e-6)
        np.testing.assert_allclose(feat["speed_max_mps"], round(float(spd_arr.max()), 3), rtol=1e-6)

    _test("speed_min_max", t_speed_min_max)

    def t_speed_mean_correct() -> None:
        df   = _base_df()
        feat = compute_speed_profile_features(df)
        np.testing.assert_allclose(feat["speed_mean_mps"], spd_arr.mean(), rtol=1e-4)

    _test("speed_mean_correct", t_speed_mean_correct)

    def t_speed_percentiles_ordered() -> None:
        df   = _base_df()
        feat = compute_speed_profile_features(df)
        assert feat["speed_p10_mps"] <= feat["speed_median_mps"] <= feat["speed_p90_mps"]

    _test("speed_percentiles_ordered", t_speed_percentiles_ordered)

    def t_speed_slow_fraction_bounds() -> None:
        df   = _base_df()
        feat = compute_speed_profile_features(df)
        assert 0.0 <= feat["slow_fraction"] <= 1.0

    _test("speed_slow_fraction_bounds", t_speed_slow_fraction_bounds)

    def t_speed_range() -> None:
        df   = _base_df()
        feat = compute_speed_profile_features(df)
        expected = round(float(spd_arr.max() - spd_arr.min()), 3)
        np.testing.assert_allclose(feat["speed_range_mps"], expected, rtol=1e-5)

    _test("speed_range", t_speed_range)

    def t_speed_missing_col_returns_nan() -> None:
        df   = pd.DataFrame({_COL_DIST: dist_arr})
        feat = compute_speed_profile_features(df)
        assert np.isnan(feat["speed_min_mps"])

    _test("speed_missing_col_returns_nan", t_speed_missing_col_returns_nan)

    #
    # compute_accel_features

    #
    def t_accel_max_positive() -> None:
        feat = compute_accel_features(_base_df())
        assert feat["accel_max_mps2"] >= 0, "Max accel should be non-negative"

    _test("accel_max_positive", t_accel_max_positive)

    def t_braking_max_positive() -> None:
        feat = compute_accel_features(_base_df())
        assert feat["braking_max_mps2"] >= 0, "Max braking should be non-negative"

    _test("braking_max_positive", t_braking_max_positive)

    def t_accel_fallback_from_speed() -> None:
        df = pd.DataFrame({
            _COL_DIST:  dist_arr,
            _COL_SPEED: spd_arr,
            # no accel_long_mps2

        })
        feat = compute_accel_features(df)
        assert np.isfinite(feat["accel_rms_mps2"]), "Fallback accel should be finite"

    _test("accel_fallback_from_speed", t_accel_fallback_from_speed)

    def t_jerk_rms_positive() -> None:
        feat = compute_accel_features(_base_df())
        assert np.isfinite(feat["jerk_rms_mps3"])
        assert feat["jerk_rms_mps3"] >= 0

    _test("jerk_rms_positive", t_jerk_rms_positive)

    def t_jerk_min_le_max() -> None:
        feat = compute_accel_features(_base_df())
        assert feat["jerk_min_mps3"] <= feat["jerk_max_mps3"]

    _test("jerk_min_le_max", t_jerk_min_le_max)

    def t_lat_accel_nan_when_absent() -> None:
        feat = compute_accel_features(_base_df())   # no lat accel column
        assert np.isnan(feat["lat_accel_max_mps2"])

    _test("lat_accel_nan_when_absent", t_lat_accel_nan_when_absent)

    def t_lat_accel_present() -> None:
        df = _base_df()
        df[_COL_LAT_A] = np.sin(2 * np.pi * dist_arr / 4500.0) * 10.0
        feat = compute_accel_features(df)
        assert np.isfinite(feat["lat_accel_max_mps2"])
        assert np.isfinite(feat["lat_accel_rms_mps2"])
        assert feat["lat_accel_max_mps2"] > 0

    _test("lat_accel_present", t_lat_accel_present)

    #
    # compute_line_length

    #
    def t_line_length_from_distance_col() -> None:
        df   = _base_df()
        feat = compute_line_length(df)
        np.testing.assert_allclose(feat["line_length_m"], 4500.0, rtol=1e-5)
        assert feat["source"] == "Distance (m)"

    _test("line_length_from_distance_col", t_line_length_from_distance_col)

    def t_line_length_from_xy() -> None:
        # Straight 100 m track in XY

        x = np.linspace(0, 100, 50); y = np.zeros(50)
        df = pd.DataFrame({_COL_X: x, _COL_Y: y})
        feat = compute_line_length(df)
        np.testing.assert_allclose(feat["line_length_m"], 100.0, rtol=1e-5)
        assert feat["source"] == "XY Euclidean"

    _test("line_length_from_xy", t_line_length_from_xy)

    def t_line_length_from_gps() -> None:
        # ~1 deg longitude at 50 deg N â‰ˆ 71.7 km

        lat = np.full(50, 50.0)
        lon = np.linspace(0.0, 1.0, 50)
        df  = pd.DataFrame({_COL_LAT: lat, _COL_LON: lon})
        feat = compute_line_length(df)
        assert feat["source"] == "GPS haversine"
        # Rough check: 1 deg lon at 50 N â‰ˆ 71 700 m

        assert 70_000 < feat["line_length_m"] < 73_000, feat["line_length_m"]

    _test("line_length_from_gps", t_line_length_from_gps)

    def t_line_length_no_source_returns_nan() -> None:
        df   = pd.DataFrame({"Time (s)": [0.0, 1.0]})
        feat = compute_line_length(df)
        assert np.isnan(feat["line_length_m"])
        assert feat["source"] == "none"

    _test("line_length_no_source_returns_nan", t_line_length_no_source_returns_nan)

    #
    # Return type guarantees

    #
    def t_all_functions_return_dict() -> None:
        df = _base_df()
        for fn, arg in [
            (compute_lap_time,            df),
            (compute_speed_profile_features, df),
            (compute_accel_features,      df),
            (compute_line_length,         df),
        ]:
            result = fn(arg)
            assert isinstance(result, dict), f"{fn.__name__} must return a dict"
        assert isinstance(compute_consistency_metrics([90.0, 91.0]), dict)

    _test("all_functions_return_dict", t_all_functions_return_dict)

    #
    # Test: detrended consistency - evolving conditions

    #
    def t_detrended_steady() -> None:
        # Steady conditions: detrended CV should be similar to raw CV

        lt = [90.0, 90.5, 89.8, 90.2, 91.0, 89.5, 90.1]
        result = compute_detrended_consistency(lt)
        assert np.isfinite(result["detrended_cv_pct"])
        assert np.isfinite(result["adjusted_cv_pct"])
        # In steady conditions, detrended CV ~ raw CV

        assert abs(result["detrended_cv_pct"] - result["raw_cv_pct"]) < 1.0

    _test("detrended_steady", t_detrended_steady)

    def t_detrended_evolving() -> None:
        # Drying track: laps go 70 -> 52 over 20 laps, but each lap is

        # only +/-0.3s from the trend line (very consistent within phase)

        rng = np.random.default_rng(42)
        base = np.linspace(70, 52, 20)
        lt = (base + rng.normal(0, 0.3, 20)).tolist()
        result = compute_detrended_consistency(lt)
        raw = result["raw_cv_pct"]
        detrended = result["detrended_cv_pct"]
        # Raw CV should be huge (> 5%) because of the 70->52 spread

        assert raw > 5.0, f"Raw CV should be large, got {raw}"
        # Detrended CV should be tiny (< 1%) since residuals are small

        assert detrended < 1.0, f"Detrended CV should be small, got {detrended}"
        # Adjusted should use the detrended (better) value

        assert result["adjusted_cv_pct"] < 1.0

    _test("detrended_evolving", t_detrended_evolving)

    def t_detrended_per_phase() -> None:
        # Two distinct phases: laps 0-4 at 70s, laps 5-9 at 52s

        rng = np.random.default_rng(7)
        lt = list(70.0 + rng.normal(0, 0.2, 5)) + list(52.0 + rng.normal(0, 0.2, 5))
        phase_map = {i: 0 for i in range(5)}
        phase_map.update({i: 1 for i in range(5, 10)})
        result = compute_detrended_consistency(lt, lap_to_phase=phase_map)
        assert result["n_phases"] == 2
        # Per-phase CV should be very small (each phase is tight)

        assert np.isfinite(result["per_phase_cv_pct"])
        assert result["per_phase_cv_pct"] < 1.0
        # Adjusted should be small

        assert result["adjusted_cv_pct"] < 1.0

    _test("detrended_per_phase", t_detrended_per_phase)

    def t_detrended_insufficient() -> None:
        result = compute_detrended_consistency([90.0])
        assert np.isnan(result["adjusted_cv_pct"])

    _test("detrended_insufficient", t_detrended_insufficient)

    #
    # Summary

    #
    total = len(passed) + len(failed)
    print(f"\nFeature Extraction Tests: {len(passed)}/{total} passed")
    for name in passed:
        print(f"  âœ“ {name}")
    for name, tb in failed:
        print(f"  âœ— {name}\n{tb}")

    if failed:
        raise AssertionError(f"{len(failed)} test(s) failed.")


# -- -

# Entry point

# -- -


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _run_tests()