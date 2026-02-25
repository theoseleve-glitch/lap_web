"""
deltas.py
---------
Lap-to-lap time delta analysis with segment-level cause classification.

Pipeline
~~~~~~~~
1. ``compute_cumulative_time(resampled_lap)``
   Integrate speed over uniform distance grid to produce elapsed time at
   each distance sample — independent of the raw time column.

2. ``compute_delta_curve(reference_lap, comparison_lap)``
   Subtract cumulative time curves on a shared distance grid.  Positive
   delta means the comparison lap is slower than the reference.

3. ``segment_time_loss(delta_curve, n_segments)``
   Divide the delta curve into *n_segments* equal-distance bands and
   compute the net time gained / lost in each.

4. ``classify_time_loss_cause(reference_lap, comparison_lap)``
   For each segment, run five heuristic tests and return the most likely
   cause of any time loss.

Cause heuristics
~~~~~~~~~~~~~~~~
Each heuristic compares the per-segment means (or extremes) of the
comparison lap against the reference:

  entry_loss        – comparison entry speed (first quartile of segment)
                      is lower than reference
  mid_corner_loss   – comparison minimum speed in segment is lower
  exit_loss         – comparison post-apex acceleration (last quartile) is lower
  instability       – comparison yaw-rate variance in segment is higher
  line_inefficiency – comparison path length (Euclidean or GPS sum) in
                      segment is longer
  on_pace           – none of the above triggers

Multiple causes may be present; the one with the largest magnitude is
returned as ``likely_cause``.  If no cause can be determined (missing data)
the string ``"undetermined"`` is used.

Design principles
~~~~~~~~~~~~~~~~~
- Deterministic: identical inputs → identical outputs.
- All thresholds are keyword arguments with physically motivated defaults.
- NaN-robust: missing channels degrade gracefully to ``"undetermined"``.
- No mutation of input DataFrames.
- Structured logging only; zero print statements.
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


_COL_DIST:   Final[str] = "Distance (m)"
_COL_TIME:   Final[str] = "Time (s)"
_COL_SPEED:  Final[str] = "Speed (m/s)"
_COL_YAW:    Final[str] = "yaw_rate_dps"
_COL_YAW_RC: Final[str] = "Yaw rate (deg/s)"
_COL_LONG:   Final[str] = "accel_long_mps2"
_COL_LAT:    Final[str] = "Latitude (deg)"
_COL_LON:    Final[str] = "Longitude (deg)"
_COL_X:      Final[str] = "X (m)"
_COL_Y:      Final[str] = "Y (m)"

# -- -

# Default thresholds (all overridable via keyword arguments)

# -- -


_DEFAULT_N_SEGMENTS:     Final[int]   = 20
_DEFAULT_ENTRY_THRESH:   Final[float] = 0.02   # fraction of segment that is "entry"
_DEFAULT_EXIT_THRESH:    Final[float] = 0.02   # fraction of segment that is "exit" (from end)
_DEFAULT_SPEED_TOL:      Final[float] = 0.50   # m/s — differences below this are noise
_DEFAULT_ACCEL_TOL:      Final[float] = 0.10   # m/s² — accel differences below this are noise
_DEFAULT_YAW_VAR_RATIO:  Final[float] = 1.20   # comparison yaw variance must exceed ref × this
_DEFAULT_LINE_LEN_RATIO: Final[float] = 1.005  # comparison path length must exceed ref × this


# -- -

# Exceptions

# -- -


class DeltaError(ValueError):
    """Raised when inputs are incompatible or required columns are absent."""


# -- -

# Internal helpers

# -- -


def _get_finite(df: pd.DataFrame, col: str) -> np.ndarray:
    """Return a finite-only numpy array for *col*, or empty array."""
    if col not in df.columns:
        return np.array([], dtype=float)
    vals = pd.to_numeric(df[col], errors="coerce").values
    return vals[np.isfinite(vals)]


def _col_values(df: pd.DataFrame, col: str) -> np.ndarray:
    """Return numpy array for *col* with NaN preserved (no filtering)."""
    if col not in df.columns:
        return np.full(len(df), np.nan)
    return pd.to_numeric(df[col], errors="coerce").values


def _interpolate_to_grid(
    df: pd.DataFrame,
    col: str,
    new_dist: np.ndarray,
) -> np.ndarray:
    """
    Interpolate *col* from *df* onto *new_dist*.

    Uses the ``Distance (m)`` column of *df* as the x-axis.  Clamps at
    boundaries (no extrapolation).
    """
    dist = _col_values(df, _COL_DIST)
    vals = _col_values(df, col)

    # Remove NaN from both arrays jointly

    mask = np.isfinite(dist) & np.isfinite(vals)
    if mask.sum() < 2:
        return np.full(len(new_dist), np.nan)

    d_clean = dist[mask]; v_clean = vals[mask]
    order   = np.argsort(d_clean, kind="stable")
    d_s, v_s = d_clean[order], v_clean[order]
    # Dedup

    _, ui = np.unique(d_s, return_index=True)
    return np.interp(new_dist, d_s[ui], v_s[ui])


def _path_length_segment(df: pd.DataFrame, mask: np.ndarray) -> float:
    """
    Compute Euclidean (XY) or haversine (GPS) path length for the rows
    selected by boolean *mask*.  Returns NaN if no position data available.
    """
    sub = df[mask]
    if len(sub) < 2:
        return float("nan")

    if _COL_X in sub.columns and _COL_Y in sub.columns:
        x = pd.to_numeric(sub[_COL_X], errors="coerce").dropna().values
        y = pd.to_numeric(sub[_COL_Y], errors="coerce").dropna().values
        n = min(len(x), len(y))
        if n >= 2:
            return float(np.sqrt(np.diff(x[:n])**2 + np.diff(y[:n])**2).sum())

    if _COL_LAT in sub.columns and _COL_LON in sub.columns:
        lat = pd.to_numeric(sub[_COL_LAT], errors="coerce").dropna().values
        lon = pd.to_numeric(sub[_COL_LON], errors="coerce").dropna().values
        n   = min(len(lat), len(lon))
        if n >= 2:
            return _haversine_sum(lat[:n], lon[:n])

    return float("nan")


def _haversine_sum(lat: np.ndarray, lon: np.ndarray) -> float:
    R = 6_371_000.0
    lr = np.radians(lat); or_ = np.radians(lon)
    a  = np.sin(np.diff(lr)/2)**2 + np.cos(lr[:-1]) * np.cos(lr[1:]) * np.sin(np.diff(or_)/2)**2
    return float(2 * R * np.arcsin(np.sqrt(np.clip(a, 0, 1))).sum())


def _segment_slice(dist_grid: np.ndarray, seg_idx: int, n_segments: int) -> slice:
    """Return the index slice for segment *seg_idx* of the shared distance grid."""
    n = len(dist_grid)
    step = n / n_segments
    start = int(round(seg_idx * step))
    end   = int(round((seg_idx + 1) * step))
    return slice(start, min(end, n))


def _safe_mean(arr: np.ndarray) -> float:
    finite = arr[np.isfinite(arr)]
    return float(finite.mean()) if len(finite) > 0 else float("nan")


def _safe_min(arr: np.ndarray) -> float:
    finite = arr[np.isfinite(arr)]
    return float(finite.min()) if len(finite) > 0 else float("nan")


def _safe_var(arr: np.ndarray) -> float:
    finite = arr[np.isfinite(arr)]
    return float(finite.var()) if len(finite) > 1 else float("nan")


# -- -

# 1. Cumulative time

# -- -


def compute_cumulative_time(resampled_lap: pd.DataFrame) -> pd.DataFrame:
    """
    Compute elapsed time at each distance sample by integrating speed.

    ``t(s) = ∫₀ˢ (1 / v(s')) ds'``   (trapezoidal rule)

    This is distance-independent of the raw time column and works correctly
    even when the input is a distance-resampled lap (uniform Δs grid).

    Parameters
    ----------
    resampled_lap:
        Distance-resampled DataFrame.  Must contain ``Distance (m)`` and
        ``Speed (m/s)``.

    Returns
    -------
    pd.DataFrame
        Copy of *resampled_lap* with an additional column
        ``cumulative_time_s`` (elapsed time from the first sample).

    Raises
    ------
    DeltaError
        If ``Distance (m)`` or ``Speed (m/s)`` is absent.
    """
    for col in (_COL_DIST, _COL_SPEED):
        if col not in resampled_lap.columns:
            raise DeltaError(f"Required column {col!r} absent from lap DataFrame.")

    dist  = _col_values(resampled_lap, _COL_DIST)
    speed = _col_values(resampled_lap, _COL_SPEED)

    # Guard against zero / negative speed to avoid division by zero

    spd_safe = np.where((speed > 0) & np.isfinite(speed), speed, np.nan)
    inv_v    = np.where(np.isfinite(spd_safe), 1.0 / spd_safe, 0.0)

    ds          = np.diff(dist)
    # Trapezoidal: dt[i] = (inv_v[i] + inv_v[i+1]) / 2 * ds[i]

    dt          = 0.5 * (inv_v[:-1] + inv_v[1:]) * np.abs(ds)
    cum_time    = np.concatenate([[0.0], np.cumsum(dt)])

    result = resampled_lap.copy()
    result["cumulative_time_s"] = cum_time
    return result


# -- -

# 2. Delta curve

# -- -


def compute_delta_curve(
    reference_lap:   pd.DataFrame,
    comparison_lap:  pd.DataFrame,
    *,
    n_grid: int = 1000,
) -> pd.DataFrame:
    """
    Compute the time-delta curve between two laps on a shared distance grid.

    Both laps are interpolated onto a common ``n_grid``-point distance axis
    spanning the shorter of the two laps.  Positive delta means the
    comparison lap is *slower* than the reference.

    Parameters
    ----------
    reference_lap:
        Baseline lap DataFrame (distance-resampled).
    comparison_lap:
        Lap to compare against the reference.
    n_grid:
        Number of grid points for the shared distance axis.  Default: 1000.

    Returns
    -------
    pd.DataFrame
        Columns:
          ``distance_m``       – shared grid
          ``delta_s``          – time delta (comparison − reference) in seconds
          ``ref_cum_time_s``   – reference cumulative time
          ``comp_cum_time_s``  – comparison cumulative time

    Raises
    ------
    DeltaError
        If either lap lacks ``Distance (m)`` or ``Speed (m/s)``.
    """
    for lap, name in ((reference_lap, "reference"), (comparison_lap, "comparison")):
        for col in (_COL_DIST, _COL_SPEED):
            if col not in lap.columns:
                raise DeltaError(
                    f"Column {col!r} absent from {name} lap."
                )

    ref_with_t  = compute_cumulative_time(reference_lap)
    comp_with_t = compute_cumulative_time(comparison_lap)

    # Shared distance grid: [max of both mins, min of both maxes]

    d_min = max(
        float(pd.to_numeric(reference_lap[_COL_DIST],  errors="coerce").min()),
        float(pd.to_numeric(comparison_lap[_COL_DIST], errors="coerce").min()),
    )
    d_max = min(
        float(pd.to_numeric(reference_lap[_COL_DIST],  errors="coerce").max()),
        float(pd.to_numeric(comparison_lap[_COL_DIST], errors="coerce").max()),
    )

    if d_max <= d_min:
        raise DeltaError(
            f"No overlapping distance range between laps "
            f"(ref: {d_min:.1f}–{d_max:.1f} m)."
        )

    grid = np.linspace(d_min, d_max, n_grid)

    ref_time  = _interpolate_to_grid(ref_with_t,  "cumulative_time_s", grid)
    comp_time = _interpolate_to_grid(comp_with_t, "cumulative_time_s", grid)
    delta     = comp_time - ref_time

    logger.debug(
        "Delta curve: d=%.1f–%.1f m  final_delta=%.3f s  grid=%d pts",
        d_min, d_max, float(np.nansum(np.where(np.isfinite(delta), delta, 0.0))),
        n_grid,
    )

    return pd.DataFrame({
        "distance_m":      grid,
        "delta_s":         delta,
        "ref_cum_time_s":  ref_time,
        "comp_cum_time_s": comp_time,
    })


# -- -

# 3. Segment time loss

# -- -


def segment_time_loss(
    delta_curve: pd.DataFrame,
    n_segments:  int = _DEFAULT_N_SEGMENTS,
) -> list[dict[str, Any]]:
    """
    Divide the delta curve into equal-distance segments and compute the net
    time gained or lost in each.

    Parameters
    ----------
    delta_curve:
        DataFrame returned by :func:`compute_delta_curve`.
    n_segments:
        Number of equal-distance bands.  Default: 20.

    Returns
    -------
    list[dict]  with keys:
        ``segment``       – int   – 1-based segment number
        ``s_start_m``     – float – distance at start of segment
        ``s_end_m``       – float – distance at end of segment
        ``time_loss_ms``  – float – positive = comparison slower (ms)
        ``cum_delta_ms``  – float – cumulative delta at segment end (ms)
    """
    if "distance_m" not in delta_curve.columns or "delta_s" not in delta_curve.columns:
        raise DeltaError(
            "delta_curve must contain 'distance_m' and 'delta_s' columns."
        )

    dist  = delta_curve["distance_m"].values
    delta = delta_curve["delta_s"].values
    n     = len(dist)

    results: list[dict[str, Any]] = []

    for seg in range(n_segments):
        sl    = _segment_slice(dist, seg, n_segments)
        d_seg = dist[sl]
        t_seg = delta[sl]

        if len(d_seg) < 2:
            # Emit a zero-valued placeholder so every lap always has
            # exactly *n_segments* entries – avoids ragged arrays that
            # break numpy in the heatmap renderer.
            d_total = dist[-1] - dist[0] if n > 1 else 0.0
            seg_width = d_total / n_segments
            results.append({
                "segment":      seg + 1,
                "s_start_m":    round(float(dist[0] + seg * seg_width), 2),
                "s_end_m":      round(float(dist[0] + (seg + 1) * seg_width), 2),
                "time_loss_ms": 0.0,
                "cum_delta_ms": 0.0,
            })
            continue

        # Time loss in this segment = delta at end − delta at start

        # (both relative to the start of the lap)

        t_start_val = t_seg[0]  if np.isfinite(t_seg[0])  else 0.0
        t_end_val   = t_seg[-1] if np.isfinite(t_seg[-1]) else t_start_val
        time_loss_s = float(t_end_val - t_start_val)

        cum_at_end  = float(t_end_val)

        results.append({
            "segment":      seg + 1,
            "s_start_m":    round(float(d_seg[0]),    2),
            "s_end_m":      round(float(d_seg[-1]),   2),
            "time_loss_ms": round(time_loss_s * 1000, 2),
            "cum_delta_ms": round(cum_at_end  * 1000, 2),
        })

    logger.info(
        "Segment time loss: %d segments, total loss = %.1f ms",
        len(results),
        sum(r["time_loss_ms"] for r in results),
    )
    return results


# -- -

# 4. Cause classification

# -- -


def classify_time_loss_cause(
    reference_lap:   pd.DataFrame,
    comparison_lap:  pd.DataFrame,
    *,
    n_segments:          int   = _DEFAULT_N_SEGMENTS,
    n_grid:              int   = 1000,
    speed_tolerance_mps: float = _DEFAULT_SPEED_TOL,
    accel_tolerance:     float = _DEFAULT_ACCEL_TOL,
    yaw_var_ratio:       float = _DEFAULT_YAW_VAR_RATIO,
    line_len_ratio:      float = _DEFAULT_LINE_LEN_RATIO,
    entry_fraction:      float = _DEFAULT_ENTRY_THRESH,
    exit_fraction:       float = _DEFAULT_EXIT_THRESH,
) -> list[dict[str, Any]]:
    """
    For each distance segment, diagnose the most likely cause of any time
    loss or gain between *comparison_lap* and *reference_lap*.

    Cause heuristics (each tested independently, largest-magnitude wins)
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    entry_loss        – mean speed in the first *entry_fraction* of the
                        segment is lower in comparison than reference
    mid_corner_loss   – minimum speed in the segment is lower in comparison
    exit_loss         – mean longitudinal acceleration in the last
                        *exit_fraction* of the segment is lower in comparison
    instability       – yaw-rate variance in the segment is higher in
                        comparison by factor ≥ *yaw_var_ratio*
    line_inefficiency – path length in the segment is longer by factor
                        ≥ *line_len_ratio*
    on_pace           – no heuristic triggered (comparison ≈ reference)
    undetermined      – the relevant channel is absent from one or both laps

    Parameters
    ----------
    reference_lap / comparison_lap:
        Distance-resampled DataFrames.
    n_segments:
        Number of distance segments.  Default: 20.
    n_grid:
        Grid resolution for the shared distance axis.  Default: 1000.
    speed_tolerance_mps / accel_tolerance:
        Minimum signal difference to register as a meaningful delta.
    yaw_var_ratio / line_len_ratio:
        Ratio thresholds for instability and line-length heuristics.
    entry_fraction / exit_fraction:
        Fraction of each segment considered "entry" / "exit" respectively.

    Returns
    -------
    list[dict]  with keys:
        ``segment``       – int
        ``s_start_m``     – float
        ``s_end_m``       – float
        ``time_loss_ms``  – float – from :func:`segment_time_loss`
        ``likely_cause``  – str
        ``cause_details`` – dict  – per-heuristic scores for diagnostics
    """
    # Compute delta curve and segment losses

    delta_curve = compute_delta_curve(reference_lap, comparison_lap, n_grid=n_grid)
    seg_losses  = segment_time_loss(delta_curve, n_segments=n_segments)

    grid = delta_curve["distance_m"].values

    # Interpolate channels onto the shared grid once

    def _interp(df: pd.DataFrame, col: str) -> np.ndarray:
        return _interpolate_to_grid(df, col, grid)

    ref_speed  = _interp(reference_lap,  _COL_SPEED)
    comp_speed = _interp(comparison_lap, _COL_SPEED)

    # Yaw rate: prefer internal name, fall back to raw

    _yaw_col = (
        _COL_YAW    if _COL_YAW    in reference_lap.columns else
        _COL_YAW_RC if _COL_YAW_RC in reference_lap.columns else
        None
    )
    ref_yaw  = _interp(reference_lap,  _yaw_col) if _yaw_col else np.full(len(grid), np.nan)
    comp_yaw = _interp(comparison_lap, _yaw_col) if (
        _yaw_col and _yaw_col in comparison_lap.columns
    ) else np.full(len(grid), np.nan)

    # Longitudinal acceleration (optional)

    ref_accel  = _interp(reference_lap,  _COL_LONG) if _COL_LONG in reference_lap.columns  else np.full(len(grid), np.nan)
    comp_accel = _interp(comparison_lap, _COL_LONG) if _COL_LONG in comparison_lap.columns else np.full(len(grid), np.nan)

    # Build a distance-to-row-index map for raw lap path-length lookup

    def _dist_mask(df: pd.DataFrame, s_start: float, s_end: float) -> np.ndarray:
        d = pd.to_numeric(df[_COL_DIST], errors="coerce").values if _COL_DIST in df.columns else np.arange(len(df), dtype=float)
        return (d >= s_start) & (d <= s_end)

    results: list[dict[str, Any]] = []

    for seg_info in seg_losses:
        seg_num   = seg_info["segment"]
        sl        = _segment_slice(grid, seg_num - 1, n_segments)
        s_start   = seg_info["s_start_m"]
        s_end     = seg_info["s_end_m"]
        seg_len   = max(1, sl.stop - sl.start)

        # Entry / exit index boundaries within the segment

        n_entry   = max(1, int(seg_len * entry_fraction))
        n_exit    = max(1, int(seg_len * exit_fraction))
        entry_sl  = slice(sl.start, sl.start + n_entry)
        exit_sl   = slice(sl.stop  - n_exit, sl.stop)

        details: dict[str, Any] = {}
        scored:  dict[str, float] = {}   # cause → magnitude of deficit

        # -- 1. Entry loss
        ref_entry_spd  = _safe_mean(ref_speed[entry_sl])
        comp_entry_spd = _safe_mean(comp_speed[entry_sl])
        if np.isfinite(ref_entry_spd) and np.isfinite(comp_entry_spd):
            diff = ref_entry_spd - comp_entry_spd
            details["entry_speed_diff_mps"] = round(diff, 3)
            if diff > speed_tolerance_mps:
                scored["entry_loss"] = diff
        else:
            details["entry_speed_diff_mps"] = None

        # -- 2. Mid-corner loss -- -

        ref_min_spd  = _safe_min(ref_speed[sl])
        comp_min_spd = _safe_min(comp_speed[sl])
        if np.isfinite(ref_min_spd) and np.isfinite(comp_min_spd):
            diff = ref_min_spd - comp_min_spd
            details["min_speed_diff_mps"] = round(diff, 3)
            if diff > speed_tolerance_mps:
                scored["mid_corner_loss"] = diff
        else:
            details["min_speed_diff_mps"] = None

        # -- 3. Exit loss -- -

        ref_exit_accel  = _safe_mean(ref_accel[exit_sl])
        comp_exit_accel = _safe_mean(comp_accel[exit_sl])
        if np.isfinite(ref_exit_accel) and np.isfinite(comp_exit_accel):
            diff = ref_exit_accel - comp_exit_accel
            details["exit_accel_diff_mps2"] = round(diff, 4)
            if diff > accel_tolerance:
                scored["exit_loss"] = diff
        else:
            details["exit_accel_diff_mps2"] = None

        # -- 4. Instability -- -

        ref_yaw_var  = _safe_var(ref_yaw[sl])
        comp_yaw_var = _safe_var(comp_yaw[sl])
        if np.isfinite(ref_yaw_var) and np.isfinite(comp_yaw_var) and ref_yaw_var > 0:
            ratio = comp_yaw_var / ref_yaw_var
            details["yaw_var_ratio"] = round(ratio, 4)
            if ratio >= yaw_var_ratio:
                scored["instability"] = ratio - 1.0
        else:
            details["yaw_var_ratio"] = None

        # -- 5. Line inefficiency -- -

        ref_mask  = _dist_mask(reference_lap,  s_start, s_end)
        comp_mask = _dist_mask(comparison_lap, s_start, s_end)
        ref_len   = _path_length_segment(reference_lap,  ref_mask)
        comp_len  = _path_length_segment(comparison_lap, comp_mask)
        if np.isfinite(ref_len) and np.isfinite(comp_len) and ref_len > 0:
            ratio = comp_len / ref_len
            details["line_length_ratio"] = round(ratio, 6)
            if ratio >= line_len_ratio:
                scored["line_inefficiency"] = ratio - 1.0
        else:
            details["line_length_ratio"] = None

        # -- Determine likely cause -- -

        if not scored:
            # Check if any heuristic was undetermined

            undetermined = any(v is None for v in details.values())
            likely_cause = "undetermined" if undetermined else "on_pace"
        else:
            likely_cause = max(scored, key=scored.__getitem__)

        results.append({
            "segment":       seg_num,
            "s_start_m":     s_start,
            "s_end_m":       s_end,
            "time_loss_ms":  seg_info["time_loss_ms"],
            "likely_cause":  likely_cause,
            "cause_details": details,
        })

    logger.info(
        "Cause classification: %d segments, causes: %s",
        len(results),
        {r["likely_cause"] for r in results},
    )
    return results


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

    N    = 1000
    dist = np.linspace(0.0, 4500.0, N)
    # Sinusoidal speed profile: 20–60 m/s

    spd_ref  = 40.0 + 20.0 * np.sin(2 * np.pi * dist / 4500.0)
    # Reference lap

    REF = pd.DataFrame({_COL_DIST: dist, _COL_SPEED: spd_ref})

    def _lap(speed_scale: float = 1.0,
             yaw_noise:   float = 0.0,
             extra_cols:  dict | None = None) -> pd.DataFrame:
        spd = spd_ref * speed_scale + np.random.default_rng(0).normal(0, 0.1, N)
        d = {_COL_DIST: dist, _COL_SPEED: spd}
        if extra_cols:
            d.update(extra_cols)
        return pd.DataFrame(d)

    #
    # compute_cumulative_time

    #
    def t_cum_time_column_added() -> None:
        out = compute_cumulative_time(REF)
        assert "cumulative_time_s" in out.columns
        assert len(out) == N

    _test("cum_time_column_added", t_cum_time_column_added)

    def t_cum_time_starts_at_zero() -> None:
        out = compute_cumulative_time(REF)
        assert out["cumulative_time_s"].iloc[0] == 0.0

    _test("cum_time_starts_at_zero", t_cum_time_starts_at_zero)

    def t_cum_time_monotone_increasing() -> None:
        out = compute_cumulative_time(REF)
        diffs = np.diff(out["cumulative_time_s"].values)
        assert (diffs >= 0).all(), "Cumulative time must be non-decreasing"

    _test("cum_time_monotone_increasing", t_cum_time_monotone_increasing)

    def t_cum_time_physically_correct() -> None:
        # Constant 40 m/s over 4000 m → 100 s

        const_df = pd.DataFrame({
            _COL_DIST:  np.linspace(0, 4000, 400),
            _COL_SPEED: np.full(400, 40.0),
        })
        out = compute_cumulative_time(const_df)
        np.testing.assert_allclose(
            out["cumulative_time_s"].iloc[-1], 100.0, rtol=1e-3
        )

    _test("cum_time_physically_correct", t_cum_time_physically_correct)

    def t_cum_time_missing_col_raises() -> None:
        df = pd.DataFrame({_COL_SPEED: [10.0, 20.0]})
        try:
            compute_cumulative_time(df)
            raise AssertionError("Should have raised DeltaError")
        except DeltaError:
            pass

    _test("cum_time_missing_col_raises", t_cum_time_missing_col_raises)

    def t_cum_time_no_mutation() -> None:
        df   = REF.copy()
        cols_before = set(df.columns)
        compute_cumulative_time(df)
        assert set(df.columns) == cols_before

    _test("cum_time_no_mutation", t_cum_time_no_mutation)

    #
    # compute_delta_curve

    #
    def t_delta_curve_same_lap_is_zero() -> None:
        dc = compute_delta_curve(REF, REF)
        np.testing.assert_allclose(dc["delta_s"].values, 0.0, atol=1e-9)

    _test("delta_curve_same_lap_zero", t_delta_curve_same_lap_is_zero)

    def t_delta_curve_slower_lap_positive_delta() -> None:
        slow_lap = _lap(speed_scale=0.95)  # 5 % slower everywhere
        dc = compute_delta_curve(REF, slow_lap)
        # Final cumulative delta should be positive (comparison is slower)

        assert float(dc["delta_s"].iloc[-1]) > 0, (
            "Slower comparison lap should produce positive final delta"
        )

    _test("delta_curve_slower_positive", t_delta_curve_slower_lap_positive_delta)

    def t_delta_curve_faster_lap_negative_delta() -> None:
        fast_lap = _lap(speed_scale=1.05)
        dc = compute_delta_curve(REF, fast_lap)
        assert float(dc["delta_s"].iloc[-1]) < 0

    _test("delta_curve_faster_negative", t_delta_curve_faster_lap_negative_delta)

    def t_delta_curve_output_columns() -> None:
        dc = compute_delta_curve(REF, _lap())
        for col in ("distance_m", "delta_s", "ref_cum_time_s", "comp_cum_time_s"):
            assert col in dc.columns, f"Missing column: {col}"

    _test("delta_curve_output_columns", t_delta_curve_output_columns)

    def t_delta_curve_grid_length() -> None:
        dc = compute_delta_curve(REF, _lap(), n_grid=500)
        assert len(dc) == 500

    _test("delta_curve_grid_length", t_delta_curve_grid_length)

    #
    # segment_time_loss

    #
    def t_segment_count_correct() -> None:
        dc  = compute_delta_curve(REF, _lap(speed_scale=0.98))
        seg = segment_time_loss(dc, n_segments=20)
        assert len(seg) == 20, f"Expected 20 segments, got {len(seg)}"

    _test("segment_count_correct", t_segment_count_correct)

    def t_segment_ids_sequential() -> None:
        dc  = compute_delta_curve(REF, _lap())
        seg = segment_time_loss(dc, n_segments=10)
        ids = [s["segment"] for s in seg]
        assert ids == list(range(1, len(seg) + 1))

    _test("segment_ids_sequential", t_segment_ids_sequential)

    def t_segment_total_loss_consistent() -> None:
        slow = _lap(speed_scale=0.97)
        dc   = compute_delta_curve(REF, slow)
        seg  = segment_time_loss(dc, n_segments=20)
        total_from_segments = sum(s["time_loss_ms"] for s in seg) / 1000.0
        final_delta = float(dc["delta_s"].iloc[-1])
        # Both should give the same total (within rounding)

        np.testing.assert_allclose(
            total_from_segments, final_delta, rtol=0.05,
            err_msg="Sum of segment losses should match final delta"
        )

    _test("segment_total_loss_consistent", t_segment_total_loss_consistent)

    def t_segment_extents_monotone() -> None:
        dc  = compute_delta_curve(REF, _lap())
        seg = segment_time_loss(dc, n_segments=15)
        starts = [s["s_start_m"] for s in seg]
        ends   = [s["s_end_m"]   for s in seg]
        assert starts == sorted(starts)
        assert ends   == sorted(ends)

    _test("segment_extents_monotone", t_segment_extents_monotone)

    #
    # classify_time_loss_cause

    #
    def t_cause_classification_keys() -> None:
        comp = _lap(speed_scale=0.97)
        out  = classify_time_loss_cause(REF, comp)
        for r in out:
            for k in ("segment", "s_start_m", "s_end_m", "time_loss_ms",
                      "likely_cause", "cause_details"):
                assert k in r, f"Missing key {k!r} in result"

    _test("cause_keys_present", t_cause_classification_keys)

    def t_cause_on_pace_when_identical() -> None:
        out = classify_time_loss_cause(REF, REF, n_segments=5)
        for r in out:
            assert r["likely_cause"] in ("on_pace", "undetermined"), (
                f"Identical laps should be on_pace, got {r['likely_cause']}"
            )

    _test("cause_on_pace_identical", t_cause_on_pace_when_identical)

    def t_entry_loss_detected() -> None:
        # Slow entry: lower speed in the first part of every segment

        spd_slow_entry = spd_ref.copy()
        # Drop speed in first 10 % of every 20-segment band

        for i in range(20):
            sl = _segment_slice(dist, i, 20)
            n_entry = max(1, int((sl.stop - sl.start) * 0.1))
            spd_slow_entry[sl.start: sl.start + n_entry] *= 0.80
        comp = pd.DataFrame({_COL_DIST: dist, _COL_SPEED: spd_slow_entry})
        out  = classify_time_loss_cause(REF, comp, n_segments=10,
                                        speed_tolerance_mps=0.2)
        causes = [r["likely_cause"] for r in out]
        assert "entry_loss" in causes, f"Expected entry_loss in {causes}"

    _test("entry_loss_detected", t_entry_loss_detected)

    def t_mid_corner_loss_detected() -> None:
        # Uniformly lower speed (lower min speed everywhere)

        comp = _lap(speed_scale=0.90)
        out  = classify_time_loss_cause(REF, comp, n_segments=10,
                                        speed_tolerance_mps=0.2)
        causes = [r["likely_cause"] for r in out]
        assert any(c in ("mid_corner_loss", "entry_loss") for c in causes), (
            f"Expected speed-related cause, got {causes}"
        )

    _test("mid_corner_loss_detected", t_mid_corner_loss_detected)

    def t_instability_detected() -> None:
        # Reference has small yaw noise; comparison has 10× more variance.

        # ref_yaw must be non-zero so the variance ratio is defined.

        rng = np.random.default_rng(7)
        yaw_ref   = rng.normal(0, 2.0,  N)   # small baseline noise
        yaw_noisy = rng.normal(0, 20.0, N)   # 10× noisier
        comp = pd.DataFrame({
            _COL_DIST:  dist,
            _COL_SPEED: spd_ref,
            _COL_YAW:   yaw_noisy,
        })
        ref_with_yaw = pd.DataFrame({
            _COL_DIST:  dist,
            _COL_SPEED: spd_ref,
            _COL_YAW:   yaw_ref,
        })
        out = classify_time_loss_cause(ref_with_yaw, comp, n_segments=5,
                                       yaw_var_ratio=1.1)
        causes = [r["likely_cause"] for r in out]
        assert "instability" in causes, f"Expected instability in {causes}"

    _test("instability_detected", t_instability_detected)

    def t_deterministic() -> None:
        comp = _lap(speed_scale=0.97)
        r1 = classify_time_loss_cause(REF, comp, n_segments=10)
        r2 = classify_time_loss_cause(REF, comp, n_segments=10)
        assert r1 == r2, "classify_time_loss_cause is not deterministic"

    _test("deterministic", t_deterministic)

    def t_no_mutation() -> None:
        ref  = REF.copy(); comp = _lap()
        cols_ref  = set(ref.columns); n_ref  = len(ref)
        cols_comp = set(comp.columns); n_comp = len(comp)
        classify_time_loss_cause(ref, comp)
        assert set(ref.columns)  == cols_ref  and len(ref)  == n_ref
        assert set(comp.columns) == cols_comp and len(comp) == n_comp

    _test("no_mutation", t_no_mutation)

    #
    # Summary

    #
    total = len(passed) + len(failed)
    print(f"\nDelta Analysis Tests: {len(passed)}/{total} passed")
    for name in passed:
        print(f"  ✓ {name}")
    for name, tb in failed:
        print(f"  ✗ {name}\n{tb}")

    if failed:
        raise AssertionError(f"{len(failed)} test(s) failed.")


# -- -

# Entry point

# -- -


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _run_tests()