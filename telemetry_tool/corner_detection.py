"""
corner_detection.py
-------------------
Identifies corner segments within a resampled telemetry lap.

Algorithm
~~~~~~~~~
1. Compute absolute curvature from yaw_rate / speed (falls back to
   positional curvature if yaw_rate is unavailable).
2. Smooth the curvature signal with a Gaussian-weighted rolling window to
   suppress GPS/IMU noise.
3. Detect peaks in the smoothed curvature above ``curvature_threshold``.
4. Expand each peak outward until curvature drops below
   ``expansion_threshold`` (defaults to ``curvature_threshold x 0.5``),
   giving a region that naturally captures the entry and exit of the corner.
5. Merge regions that are closer than ``merge_gap_m`` apart to avoid
   over-segmenting chicanes.
6. Discard regions shorter than ``min_corner_length_m``.

Output
~~~~~~
A list of dicts:
    [{"corner_id": int, "s_start": float, "s_end": float,
      "s_apex": float, "direction": "L" | "R"}, ...]

where ``s_start`` / ``s_end`` are positions in metres along the lap,
``s_apex`` is the point of maximum curvature within the corner, and
``direction`` is ``"L"`` (left) or ``"R"`` (right) based on the sign of
the dominant curvature.

Design principles
~~~~~~~~~~~~~~~~~
- Deterministic: identical input always produces identical output.
- Works with reconstructed yaw_rate (from bearing derivative) because
  smoothing is applied before thresholding.
- All thresholds are keyword arguments with documented physical defaults.
- Structured logging only; zero print statements.
- No mutation of the input DataFrame.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Final

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# -- -

# Column-name constants

# -- -


_COL_DIST:   Final[str] = "Distance (m)"
_COL_YAW:    Final[str] = "yaw_rate_dps"          # internal standardised name
_COL_YAW_RC: Final[str] = "Yaw rate (deg/s)"       # raw RaceChrono name
_COL_SPEED:  Final[str] = "Speed (m/s)"
_COL_X:      Final[str] = "X (m)"
_COL_Y:      Final[str] = "Y (m)"

# Synthetic output column written into the returned DataFrame (optional use).

COL_CURVATURE: Final[str] = "curvature_1pm"    # 1/metres

# -- -

# Default thresholds

# -- -


_DEFAULT_CURV_THRESH:   Final[float] = 0.01    # 1/m  ~= radius < 100 m
_DEFAULT_MIN_LENGTH_M:  Final[float] = 20.0    # metres -- ignore micro-bumps
_DEFAULT_SMOOTH_WINDOW: Final[int]   = 15      # samples (half-window)
_DEFAULT_EXPAND_RATIO:  Final[float] = 0.50    # expansion threshold = peak_thresh x ratio
_DEFAULT_MERGE_GAP_M:   Final[float] = 30.0    # metres -- merge corners closer than this
_MIN_SPEED_MPS:         Final[float] = 3.0     # below this speed curvature is unreliable (~10.8 km/h)

# -- -

# Exceptions

# -- -


class CornerDetectionError(ValueError):
    """Raised when required input columns are absent or data is insufficient."""


# -- -

# Internal data structure

# -- -


@dataclass
class CornerRegion:
    """Internal mutable representation of a corner before final output."""
    idx_start: int
    idx_end:   int
    wrapped:   bool = False    # True if the region wraps around start/finish

    def length_m(self, dist: np.ndarray) -> float:
        if self.wrapped:
            # Region goes from idx_start (near end) to end of lap, then from
            # start of lap to idx_end (near start).
            return float(
                (dist[-1] - dist[self.idx_start])
                + (dist[self.idx_end] - dist[0])
            )
        return float(dist[self.idx_end] - dist[self.idx_start])

    def s_start(self, dist: np.ndarray) -> float:
        return float(dist[self.idx_start])

    def s_end(self, dist: np.ndarray) -> float:
        return float(dist[self.idx_end])


# -- -

# Internal helpers

# -- -


def _has(df: pd.DataFrame, col: str) -> bool:
    return col in df.columns and df[col].notna().any()


def _gaussian_smooth(signal: np.ndarray, half_window: int) -> np.ndarray:
    """
    Apply a Gaussian-weighted symmetric rolling average.

    Parameters
    ----------
    signal:
        1-D array to smooth.  May contain finite values only (NaN-free).
    half_window:
        Half-width of the kernel in samples.  Full kernel spans
        ``2 * half_window + 1`` samples.

    Returns
    -------
    np.ndarray of the same length as *signal*.
    """
    if half_window <= 0 or len(signal) < 3:
        return signal.copy()

    k   = 2 * half_window + 1
    x   = np.arange(k) - half_window
    w   = np.exp(-0.5 * (x / max(half_window / 2.0, 0.5)) ** 2)
    w  /= w.sum()

    # Pad with mirror reflection to minimise edge effects

    pad = np.pad(signal, half_window, mode="reflect")
    out = np.convolve(pad, w, mode="valid")
    # Trim to original length (convolve result length = len(pad) - len(w) + 1)

    return out[:len(signal)]


def _curvature_from_yaw_speed(
    yaw_dps: np.ndarray,
    speed_mps: np.ndarray,
) -> np.ndarray:
    """
    kappa = omega / v     [1/m]   (signed -- positive = left, negative = right)

    where omega is yaw rate (deg/s -> rad/s) and v is speed (m/s).
    Samples where speed < _MIN_SPEED_MPS are set to NaN.

    The sign is preserved so that downstream code can determine turn direction.
    """
    yaw_rps = np.radians(yaw_dps)
    with np.errstate(divide="ignore", invalid="ignore"):
        curv = np.where(speed_mps >= _MIN_SPEED_MPS, yaw_rps / speed_mps, np.nan)
    return curv


def _curvature_from_xy(
    x: np.ndarray,
    y: np.ndarray,
    dist: np.ndarray,
) -> np.ndarray:
    """
    Signed curvature via the Frenet-Serret formula on XY position.

    kappa = (x_doty - x_ddot) / (x_dot^2 + ^2)^(3/2)

    Derivatives are taken with respect to arc length (distance) for
    stability across non-uniform grids.
    """
    ds = np.diff(dist)
    ds = np.where(ds > 0, ds, np.nan)

    dx = np.diff(x); dy = np.diff(y)
    xd = dx / ds;    yd = dy / ds

    # Second derivatives

    xd_mid = 0.5 * (xd[:-1] + xd[1:])
    yd_mid = 0.5 * (yd[:-1] + yd[1:])
    ds_mid = 0.5 * (ds[:-1] + ds[1:])

    xdd = np.diff(xd) / ds_mid
    ydd = np.diff(yd) / ds_mid

    denom = (xd_mid**2 + yd_mid**2) ** 1.5
    with np.errstate(divide="ignore", invalid="ignore"):
        kappa = np.where(denom > 0, (xd_mid * ydd - yd_mid * xdd) / denom, np.nan)

    # Align to original length by padding edges with nearest value

    kappa_full    = np.empty(len(x))
    kappa_full[:] = np.nan
    kappa_full[1:-1] = kappa
    # Fill edge NaNs with nearest interior value

    if np.isfinite(kappa).any():
        kappa_full[0]  = kappa[0]  if np.isfinite(kappa[0])  else np.nanmean(kappa)
        kappa_full[-1] = kappa[-1] if np.isfinite(kappa[-1]) else np.nanmean(kappa)
    return kappa_full


def _interpolate_short_nans(arr: np.ndarray, max_gap: int = 10) -> np.ndarray:
    """
    Linearly interpolate NaN stretches shorter than *max_gap* samples.

    Longer NaN stretches are left as NaN so downstream code can handle them
    explicitly rather than treating them as artificial zero-curvature straights.

    Parameters
    ----------
    arr:
        1-D array that may contain NaN values.
    max_gap:
        Maximum consecutive NaN run length to interpolate.  Runs longer than
        this are left untouched.

    Returns
    -------
    np.ndarray with short NaN gaps filled by linear interpolation.
    """
    out = arr.copy()
    finite = np.isfinite(out)
    if finite.all() or not finite.any():
        return out

    # Identify contiguous NaN runs
    nan_mask = ~finite
    # Label runs: diff of the mask gives start/end transitions
    changes = np.diff(nan_mask.astype(np.int8))
    starts = np.where(changes == 1)[0] + 1   # index where NaN begins
    ends   = np.where(changes == -1)[0] + 1  # index where NaN ends (first finite)

    # Handle edge cases: NaN at the very start or very end
    if nan_mask[0]:
        starts = np.concatenate(([0], starts))
    if nan_mask[-1]:
        ends = np.concatenate((ends, [len(out)]))

    for s, e in zip(starts, ends):
        gap_len = e - s
        if gap_len > max_gap:
            continue  # leave long gaps as NaN
        # Find boundary values for interpolation
        left_val  = out[s - 1] if s > 0 else np.nan
        right_val = out[e]     if e < len(out) else np.nan
        if np.isfinite(left_val) and np.isfinite(right_val):
            out[s:e] = np.linspace(left_val, right_val, gap_len + 2)[1:-1]
        elif np.isfinite(left_val):
            out[s:e] = left_val
        elif np.isfinite(right_val):
            out[s:e] = right_val
        # else: both boundaries are NaN -> leave as NaN

    return out


def _compute_curvature(df: pd.DataFrame) -> np.ndarray:
    """
    Compute signed curvature [1/m] using the best available channel.

    The sign encodes turn direction (positive = left, negative = right for
    yaw-rate sources; cross-product sign for XY sources).

    Priority: yaw_rate + speed  >  raw yaw_rate channel + speed  >  X/Y.
    """
    speed = (
        pd.to_numeric(df[_COL_SPEED], errors="coerce").fillna(0).values
        if _has(df, _COL_SPEED) else np.zeros(len(df))
    )
    dist = pd.to_numeric(df[_COL_DIST], errors="coerce").values

    # Source 1 -- internal yaw_rate_dps

    if _has(df, _COL_YAW):
        yaw = pd.to_numeric(df[_COL_YAW], errors="coerce").values
        logger.debug("Curvature source: yaw_rate_dps")
        return _curvature_from_yaw_speed(yaw, speed)

    # Source 2 -- raw RaceChrono yaw_rate

    if _has(df, _COL_YAW_RC):
        yaw = pd.to_numeric(df[_COL_YAW_RC], errors="coerce").values
        logger.debug("Curvature source: Yaw rate (deg/s)")
        return _curvature_from_yaw_speed(yaw, speed)

    # Source 3 -- XY position

    if _has(df, _COL_X) and _has(df, _COL_Y):
        x = pd.to_numeric(df[_COL_X], errors="coerce").values
        y = pd.to_numeric(df[_COL_Y], errors="coerce").values
        logger.debug("Curvature source: X/Y position")
        return _curvature_from_xy(x, y, dist)

    raise CornerDetectionError(
        "Cannot compute curvature: none of "
        f"({_COL_YAW!r}, {_COL_YAW_RC!r}, ({_COL_X!r}+{_COL_Y!r})) "
        "found in DataFrame."
    )


def _find_peaks(
    signal: np.ndarray,
    threshold: float,
    min_separation: int,
) -> list[int]:
    """
    Return indices of local maxima above *threshold* with at least
    *min_separation* samples between consecutive peaks.

    Uses a simple left-right comparison to keep the function deterministic
    and dependency-free.
    """
    n      = len(signal)
    peaks  = []
    i      = 1

    while i < n - 1:
        if signal[i] > threshold and signal[i] >= signal[i - 1] and signal[i] >= signal[i + 1]:
            # Is this the highest point in a +/-min_separation neighbourhood?

            lo = max(0,     i - min_separation)
            hi = min(n - 1, i + min_separation)
            if signal[i] >= np.max(signal[lo: hi + 1]) - 1e-12:
                peaks.append(i)
                i += min_separation   # skip ahead to enforce separation
                continue
        i += 1

    return peaks


def _expand_peak(
    idx_peak:  int,
    signal:    np.ndarray,
    threshold: float,
) -> CornerRegion:
    """
    Walk outward from *idx_peak* until *signal* drops below *threshold*,
    returning the resulting index range.
    """
    n    = len(signal)
    left = idx_peak
    while left > 0 and signal[left - 1] >= threshold:
        left -= 1

    right = idx_peak
    while right < n - 1 and signal[right + 1] >= threshold:
        right += 1

    return CornerRegion(idx_start=left, idx_end=right)


def _merge_regions(
    regions:    list[CornerRegion],
    dist:       np.ndarray,
    merge_gap_m: float,
) -> list[CornerRegion]:
    """
    Merge adjacent regions whose gap is smaller than *merge_gap_m*.

    Operates on sorted regions (guaranteed by peak order).
    """
    if not regions:
        return []

    merged = [CornerRegion(regions[0].idx_start, regions[0].idx_end)]

    for r in regions[1:]:
        gap = float(dist[r.idx_start] - dist[merged[-1].idx_end])
        if gap < merge_gap_m:
            merged[-1].idx_end = r.idx_end
        else:
            merged.append(CornerRegion(r.idx_start, r.idx_end))

    return merged


# -- -

# Public API

# -- -


def detect_corners(
    resampled_lap: pd.DataFrame,
    curvature_threshold:  float | None = None,
    min_corner_length_m:  float = _DEFAULT_MIN_LENGTH_M,
    *,
    smooth_window:        int   = _DEFAULT_SMOOTH_WINDOW,
    expand_ratio:         float = _DEFAULT_EXPAND_RATIO,
    merge_gap_m:          float = _DEFAULT_MERGE_GAP_M,
    min_peak_separation_m: float = 15.0,
    adaptive_percentile:  float = 85.0,
    adaptive_min_corners: int   = 4,
) -> list[dict]:
    """
    Detect corner segments in a distance-resampled telemetry lap.

    Parameters
    ----------
    resampled_lap:
        Distance-resampled DataFrame (output of ``resampling.resample_lap``).
        Must contain ``Distance (m)`` and at least one curvature source.
    curvature_threshold:
        Minimum curvature [1/m] for a peak to be considered a corner.
        Default 0.01 ~= radius < 100 m.
    min_corner_length_m:
        Minimum arc length [m] of a retained corner region.  Shorter regions
        are discarded.  Default: 20 m.
    smooth_window:
        Half-window (samples) of Gaussian pre-smoothing.  Increase for noisy
        reconstructed yaw.  Default: 15.
    expand_ratio:
        The expansion threshold = ``curvature_threshold x expand_ratio``.
        Controls how far the corner extends beyond the peak.  Default: 0.5.
    merge_gap_m:
        Two corner regions separated by less than this gap are merged into one
        (handles chicanes / linked corners).  Default: 30 m.
    min_peak_separation_m:
        Minimum arc distance between two distinct peaks.  Prevents the same
        physical corner registering multiple peaks.  Default: 15 m.
    adaptive_percentile:
        When *curvature_threshold* is ``None`` (adaptive mode), the threshold
        is derived from this percentile of the smoothed curvature.
        Default: 85.0.
    adaptive_min_corners:
        In adaptive mode, if fewer than this many corners are detected the
        threshold is relaxed by 40 % and retried once.  Default: 4.

    Returns
    -------
    list of dict
        ``[{"corner_id": int, "s_start": float, "s_end": float,
        "s_apex": float, "direction": "L"|"R"}, ...]``
        sorted by ``s_start``.  Empty list if no corners detected.
        ``s_apex`` is the distance of the maximum-curvature point.
        ``direction`` is ``"L"`` (left) or ``"R"`` (right).

    Raises
    ------
    TypeError
        If *resampled_lap* is not a pandas DataFrame.
    CornerDetectionError
        If ``Distance (m)`` is absent or no curvature source is available.
    """
    if not isinstance(resampled_lap, pd.DataFrame):
        raise TypeError(
            f"detect_corners() expects a pandas DataFrame, "
            f"got {type(resampled_lap).__name__!r}."
        )
    if _COL_DIST not in resampled_lap.columns:
        raise CornerDetectionError(
            f"Required column {_COL_DIST!r} not found."
        )

    dist = pd.to_numeric(resampled_lap[_COL_DIST], errors="coerce").values
    n    = len(dist)

    if n < 3:
        logger.warning("Lap has fewer than 3 samples; returning empty corner list.")
        return []

    # 1 -- Compute raw (signed) curvature

    curv_signed_raw = _compute_curvature(resampled_lap)

    # 1a -- Handle NaN stretches: interpolate short gaps (< 10 samples),
    #        keep NaN for longer gaps so they are not treated as straights.

    curv_signed = _interpolate_short_nans(curv_signed_raw, max_gap=10)

    # For peak detection / thresholding we use absolute curvature.
    # Signed curvature is preserved separately for direction determination.

    curv_raw = np.abs(curv_signed)
    # Replace any remaining NaN (long gaps) with 0.0 for smoothing only;
    # these regions will naturally have low curvature and not generate peaks.
    nan_mask = ~np.isfinite(curv_raw)
    curv_raw_for_smooth = np.where(nan_mask, 0.0, curv_raw)

    # 1b -- Scale smoothing to track length (shorter tracks need less smoothing)

    lap_length = float(dist[-1] - dist[0]) if n > 1 else 0.0
    if lap_length > 0 and lap_length < 1500:
        # Short tracks (karts): reduce smoothing proportionally

        effective_smooth = max(3, int(smooth_window * lap_length / 3000))
    else:
        effective_smooth = smooth_window

    # 2 -- Smooth (absolute curvature, with long-NaN regions zeroed for
    #       convolution stability; those regions stay below any reasonable
    #       threshold and will not produce false corners).

    curv_smooth = _gaussian_smooth(curv_raw_for_smooth, effective_smooth)

    # 2b -- Adaptive threshold: derive from curvature percentile if None

    _is_adaptive = curvature_threshold is None
    if _is_adaptive:
        pos_curv = curv_smooth[curv_smooth > 0]
        if len(pos_curv) > 10:
            curvature_threshold = float(np.percentile(pos_curv, adaptive_percentile))
            curvature_threshold = max(curvature_threshold, 0.002)  # floor: R ~ 500 m
        else:
            curvature_threshold = _DEFAULT_CURV_THRESH
        logger.info(
            "Adaptive curvature threshold: %.5f 1/m (p%.0f of %d positive samples, "
            "smooth_window=%d).",
            curvature_threshold, adaptive_percentile, len(pos_curv),
            effective_smooth,
        )

    # 2c -- Scale merge_gap to track length to avoid over-merging on short tracks

    effective_merge_gap = merge_gap_m
    if lap_length > 0 and lap_length < 2000:
        effective_merge_gap = min(merge_gap_m, lap_length / 30.0)

    # 3 -- Detect peaks

    # Convert min_peak_separation_m to samples using median distance step

    d_step     = float(np.nanmedian(np.diff(dist)))
    min_sep_samples = max(1, int(min_peak_separation_m / d_step)) if d_step > 0 else 5

    peaks = _find_peaks(curv_smooth, curvature_threshold, min_sep_samples)

    if not peaks:
        if _is_adaptive and curvature_threshold > 0.003:
            relaxed = curvature_threshold * 0.5
            logger.warning(
                "Adaptive mode: 0 corners at threshold %.5f; retrying at %.5f.",
                curvature_threshold, relaxed,
            )
            return detect_corners(
                resampled_lap, curvature_threshold=relaxed,
                min_corner_length_m=min(min_corner_length_m, 10.0),
                smooth_window=max(3, effective_smooth // 2),
                expand_ratio=expand_ratio,
                merge_gap_m=effective_merge_gap,
                min_peak_separation_m=min_peak_separation_m,
                adaptive_percentile=adaptive_percentile,
                adaptive_min_corners=adaptive_min_corners,
            )
        logger.info("No corners detected (threshold=%.4f 1/m).", curvature_threshold)
        return []

    # 4 -- Expand each peak into a region

    expand_threshold = curvature_threshold * expand_ratio
    regions: list[CornerRegion] = [
        _expand_peak(p, curv_smooth, expand_threshold)
        for p in peaks
    ]

    # 5 -- Merge close regions (chicanes / linked sequences)

    regions = _merge_regions(regions, dist, effective_merge_gap)

    # 6 -- Filter by minimum length

    regions = [r for r in regions if r.length_m(dist) >= min_corner_length_m]

    # 6b -- Wrap-around merge for closed circuits: if the first and last
    #        regions are within merge_gap_m of each other (accounting for
    #        the lap circumference), merge them into one wrapped region.

    if len(regions) >= 2:
        lap_circumference = float(dist[-1] - dist[0])
        gap_wrap = (
            (dist[regions[0].idx_start] - dist[0])       # first region offset from start
            + (dist[-1] - dist[regions[-1].idx_end])      # last region offset from end
        )
        if gap_wrap < effective_merge_gap and lap_circumference > 0:
            # Merge: the last region absorbs the first region, wrapping around
            # the start/finish line.  idx_start stays at the last region's start
            # (near end of lap), idx_end becomes the first region's end (near
            # start of lap).  The `wrapped` flag tells length_m() to compute
            # the distance correctly across the boundary.
            merged_region = CornerRegion(
                idx_start=regions[-1].idx_start,
                idx_end=regions[0].idx_end,
                wrapped=True,
            )
            regions = regions[1:-1]   # drop old first and last
            regions.append(merged_region)
            # Re-filter: the merged region might be shorter than min length
            # (unlikely but safe)
            regions = [r for r in regions if r.length_m(dist) >= min_corner_length_m]
            logger.debug("Wrap-around merge applied (gap=%.1f m).", gap_wrap)

    # 7 -- Build output (with apex and direction)

    def _corner_dict(cid: int, r: CornerRegion) -> dict:
        """Build one corner output dict including apex and direction."""
        s_start_val = round(r.s_start(dist), 2)
        s_end_val   = round(r.s_end(dist),   2)

        if r.wrapped:
            # Wrapped region: indices go [idx_start..end] + [0..idx_end]
            region_curv   = np.concatenate([
                curv_smooth[r.idx_start:],
                curv_smooth[: r.idx_end + 1],
            ])
            region_signed_arr = np.concatenate([
                curv_signed[r.idx_start:],
                curv_signed[: r.idx_end + 1],
            ])
            apex_local = int(np.argmax(region_curv))
            tail_len   = len(curv_smooth) - r.idx_start
            if apex_local < tail_len:
                apex_idx = r.idx_start + apex_local
            else:
                apex_idx = apex_local - tail_len
        else:
            region_curv   = curv_smooth[r.idx_start : r.idx_end + 1]
            region_signed_arr = curv_signed[r.idx_start : r.idx_end + 1]
            apex_local = int(np.argmax(region_curv))
            apex_idx   = r.idx_start + apex_local

        s_apex_val = round(float(dist[apex_idx]), 2)

        # Direction: determined by the sign of the *signed* curvature in
        # the region.  We use the mean signed curvature (after NaN-safe
        # interpolation) so that a chicane that nets left is labelled "L".
        finite_signed = region_signed_arr[np.isfinite(region_signed_arr)]
        if len(finite_signed) > 0:
            direction = "L" if float(np.mean(finite_signed)) >= 0 else "R"
        else:
            direction = "L"   # fallback (shouldn't happen)

        return {
            "corner_id": cid + 1,
            "s_start":   s_start_val,
            "s_end":     s_end_val,
            "s_apex":    s_apex_val,
            "direction": direction,
        }

    corners = [_corner_dict(cid, r) for cid, r in enumerate(regions)]

    # 7b -- Adaptive retry: relax threshold if too few corners

    if _is_adaptive and len(corners) < adaptive_min_corners and curvature_threshold > 0.003:
        relaxed = curvature_threshold * 0.5
        logger.warning(
            "Adaptive mode: only %d corner(s) at threshold %.5f "
            "(min=%d); retrying at %.5f with reduced smoothing.",
            len(corners), curvature_threshold, adaptive_min_corners, relaxed,
        )
        return detect_corners(
            resampled_lap, curvature_threshold=relaxed,
            min_corner_length_m=min(min_corner_length_m, 10.0),
            smooth_window=max(3, effective_smooth // 2),
            expand_ratio=expand_ratio,
            merge_gap_m=effective_merge_gap,
            min_peak_separation_m=min_peak_separation_m,
            adaptive_percentile=adaptive_percentile,
            adaptive_min_corners=adaptive_min_corners,
        )

    logger.info(
        "Detected %d corner(s)  [threshold=%.4f 1/m, min_length=%.1f m%s].",
        len(corners), curvature_threshold, min_corner_length_m,
        ", adaptive" if _is_adaptive else "",
    )
    return corners


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

    # -- -

    # Fixture: synthetic lap with N_CORNERS evenly-spaced sine peaks

    # -- -

    N_POINTS     = 1000
    LAP_LENGTH_M = 3000.0
    N_CORNERS    = 4           # corners placed at quarters of the lap
    PEAK_CURV    = 0.04        # 1/m at corner apex (radius ~= 25 m)
    STRAIGHT_SPD = 40.0        # m/s on straights

    def _synthetic_lap(
        n_corners: int = N_CORNERS,
        peak_curv: float = PEAK_CURV,
        add_noise: bool  = False,
        speed_zero_fraction: float = 0.0,
    ) -> pd.DataFrame:
        """
        Build a resampled-style lap DataFrame with sinusoidal curvature bumps.

        The yaw rate is reconstructed from curvature x speed so the function
        can be tested with the reconstructed-yaw pathway.
        """
        dist  = np.linspace(0.0, LAP_LENGTH_M, N_POINTS)
        speed = np.full(N_POINTS, STRAIGHT_SPD)

        # Curvature: N sine bumps, each centred at equidistant positions

        curv = np.zeros(N_POINTS)
        corner_positions = [LAP_LENGTH_M * (i + 0.5) / n_corners
                            for i in range(n_corners)]
        bump_half_width = LAP_LENGTH_M / (n_corners * 4)    # bump occupies 1/4 corner slot

        for pos in corner_positions:
            window = np.abs(dist - pos) <= bump_half_width
            phase  = (dist[window] - pos) / bump_half_width * np.pi
            curv[window] = peak_curv * (1 + np.cos(phase)) / 2

        # Yaw rate [deg/s] from curvature x speed

        yaw_dps = np.degrees(curv * speed)   # kappa =  / v  ->   = kappa*v

        if add_noise:
            rng = np.random.default_rng(0)
            yaw_dps = yaw_dps + rng.normal(0, np.degrees(PEAK_CURV) * STRAIGHT_SPD * 0.05,
                                           N_POINTS)

        if speed_zero_fraction > 0:
            n_zero = int(N_POINTS * speed_zero_fraction)
            speed[:n_zero] = 0.0
            yaw_dps[:n_zero] = np.nan

        return pd.DataFrame({
            _COL_DIST:  dist,
            _COL_SPEED: speed,
            _COL_YAW:   yaw_dps,
        })

    # -- -

    # Test 1 -- correct number of corners detected on clean signal

    # -- -

    def t_correct_corner_count() -> None:
        df      = _synthetic_lap()
        corners = detect_corners(df, curvature_threshold=0.005,
                                 min_corner_length_m=10.0, smooth_window=5)
        assert len(corners) == N_CORNERS, (
            f"Expected {N_CORNERS} corners, got {len(corners)}: {corners}"
        )

    _test("correct_corner_count", t_correct_corner_count)

    # -- -

    # Test 2 -- corner IDs are sequential from 1

    # -- -

    def t_sequential_ids() -> None:
        df      = _synthetic_lap()
        corners = detect_corners(df, curvature_threshold=0.005,
                                 min_corner_length_m=10.0, smooth_window=5)
        ids = [c["corner_id"] for c in corners]
        assert ids == list(range(1, len(corners) + 1)), f"Non-sequential IDs: {ids}"

    _test("sequential_ids", t_sequential_ids)

    # -- -

    # Test 3 -- corners are in ascending distance order

    # -- -

    def t_ascending_order() -> None:
        df      = _synthetic_lap()
        corners = detect_corners(df, curvature_threshold=0.005,
                                 min_corner_length_m=10.0, smooth_window=5)
        starts = [c["s_start"] for c in corners]
        assert starts == sorted(starts), f"Corners not in ascending order: {starts}"

    _test("ascending_order", t_ascending_order)

    # -- -

    # Test 4 -- s_end > s_start for all corners

    # -- -

    def t_valid_extents() -> None:
        df      = _synthetic_lap()
        corners = detect_corners(df, curvature_threshold=0.005,
                                 min_corner_length_m=10.0, smooth_window=5)
        for c in corners:
            assert c["s_end"] > c["s_start"], (
                f"Corner {c['corner_id']}: s_end <= s_start"
            )

    _test("valid_extents", t_valid_extents)

    # -- -

    # Test 5 -- corner apexes are near the expected sine peak positions

    # -- -

    def t_apex_positions_correct() -> None:
        df      = _synthetic_lap()
        corners = detect_corners(df, curvature_threshold=0.005,
                                 min_corner_length_m=10.0, smooth_window=5)
        expected_apexes = [
            LAP_LENGTH_M * (i + 0.5) / N_CORNERS for i in range(N_CORNERS)
        ]
        for corner, expected in zip(corners, expected_apexes):
            apex = (corner["s_start"] + corner["s_end"]) / 2
            err  = abs(apex - expected)
            assert err < LAP_LENGTH_M * 0.10, (
                f"Apex {apex:.1f} m deviates {err:.1f} m from expected {expected:.1f} m"
            )

    _test("apex_positions_correct", t_apex_positions_correct)

    # -- -

    # Test 6 -- noisy (reconstructed) yaw rate still finds all corners

    # -- -

    def t_noisy_yaw_rate() -> None:
        df      = _synthetic_lap(add_noise=True)
        corners = detect_corners(df, curvature_threshold=0.005,
                                 min_corner_length_m=10.0, smooth_window=25)
        assert len(corners) == N_CORNERS, (
            f"Noisy yaw: expected {N_CORNERS} corners, got {len(corners)}"
        )

    _test("noisy_yaw_rate", t_noisy_yaw_rate)

    # -- -

    # Test 7 -- threshold too high -> no corners detected

    # -- -

    def t_high_threshold_no_corners() -> None:
        df      = _synthetic_lap()
        corners = detect_corners(df, curvature_threshold=1.0)   # 1/m is extreme
        assert corners == [], f"Expected no corners, got {corners}"

    _test("high_threshold_no_corners", t_high_threshold_no_corners)

    # -- -

    # Test 8 -- min_corner_length_m filters out short regions

    # -- -

    def t_min_length_filter() -> None:
        # With a very large min length, all corners should be filtered out

        df      = _synthetic_lap()
        corners = detect_corners(df, curvature_threshold=0.005,
                                 min_corner_length_m=5000.0)
        assert corners == [], (
            f"min_length=5000 m should filter everything, got {corners}"
        )

    _test("min_length_filter", t_min_length_filter)

    # -- -

    # Test 9 -- merge_gap_m merges two close peaks into one corner

    # -- -

    def t_chicane_merged() -> None:
        # Two peaks 80 m apart on a track long enough (3000 m) to avoid the
        # short-track merge_gap scaling.
        # merge_gap_m=100 (> 80 m) -> merges into one;
        # merge_gap_m=30  (< 80 m) -> keeps two.

        n_pts = 3000
        dist  = np.linspace(0.0, 3000.0, n_pts)
        speed = np.full(n_pts, 30.0)
        curv  = np.zeros(n_pts)

        for pos in (1400.0, 1480.0):
            w = np.abs(dist - pos) <= 8.0
            phase = (dist[w] - pos) / 8.0 * np.pi
            curv[w] = np.maximum(curv[w], 0.04 * (1 + np.cos(phase)) / 2)
        yaw = np.degrees(curv * speed)
        df  = pd.DataFrame({_COL_DIST: dist, _COL_SPEED: speed, _COL_YAW: yaw})

        corners_merged = detect_corners(df, curvature_threshold=0.005,
                                        min_corner_length_m=5.0,
                                        smooth_window=5, merge_gap_m=100.0)
        corners_split  = detect_corners(df, curvature_threshold=0.005,
                                        min_corner_length_m=5.0,
                                        smooth_window=5, merge_gap_m=30.0)
        assert len(corners_merged) < len(corners_split), (
            f"merge_gap_m=100 should produce fewer corners than merge_gap_m=30, "
            f"got {len(corners_merged)} vs {len(corners_split)}"
        )

    _test("chicane_merged", t_chicane_merged)

    # -- -

    # Test 10 -- XY fallback: corners detected from position data only

    # -- -

    def t_xy_fallback() -> None:
        # Build a lap with circular arcs replacing yaw_rate

        n    = 500
        dist = np.linspace(0.0, 2000.0, n)
        t    = np.linspace(0.0, 60.0,   n)
        R    = 50.0    # tight corner radius
        x    = R * np.cos(2 * np.pi * t / 60.0)
        y    = R * np.sin(2 * np.pi * t / 60.0)
        df   = pd.DataFrame({_COL_DIST: dist, _COL_X: x, _COL_Y: y})
        # Full circular arc -> should be detected as one long corner

        corners = detect_corners(df, curvature_threshold=0.005,
                                 min_corner_length_m=10.0, smooth_window=10)
        assert len(corners) >= 1, "XY fallback should detect at least one corner"

    _test("xy_fallback", t_xy_fallback)

    # -- -

    # Test 11 -- determinism: two identical calls give identical output

    # -- -

    def t_deterministic() -> None:
        df = _synthetic_lap(add_noise=True)
        r1 = detect_corners(df, curvature_threshold=0.005,
                            min_corner_length_m=10.0, smooth_window=15)
        r2 = detect_corners(df, curvature_threshold=0.005,
                            min_corner_length_m=10.0, smooth_window=15)
        assert r1 == r2, "Repeated calls must return identical results"

    _test("deterministic", t_deterministic)

    # -- -

    # Test 12 -- missing distance column raises CornerDetectionError

    # -- -

    def t_missing_distance_raises() -> None:
        df = pd.DataFrame({_COL_SPEED: [10.0, 20.0], _COL_YAW: [5.0, 10.0]})
        try:
            detect_corners(df)
            raise AssertionError("Should have raised CornerDetectionError")
        except CornerDetectionError:
            pass

    _test("missing_distance_raises", t_missing_distance_raises)

    # -- -

    # Test 13 -- no curvature source raises CornerDetectionError

    # -- -

    def t_no_curvature_source_raises() -> None:
        df = pd.DataFrame({_COL_DIST: [0.0, 100.0, 200.0]})
        try:
            detect_corners(df)
            raise AssertionError("Should have raised CornerDetectionError")
        except CornerDetectionError:
            pass

    _test("no_curvature_source_raises", t_no_curvature_source_raises)

    # -- -

    # Test 14 -- input DataFrame is not mutated

    # -- -

    def t_no_mutation() -> None:
        df      = _synthetic_lap()
        cols_before = set(df.columns)
        n_before    = len(df)
        detect_corners(df, curvature_threshold=0.005, min_corner_length_m=10.0)
        assert set(df.columns) == cols_before, "Input columns were mutated"
        assert len(df) == n_before,            "Input row count was mutated"

    _test("no_mutation", t_no_mutation)

    # -- -

    # Test 15 -- zero speed samples do not crash (NaN guard)

    # -- -

    def t_zero_speed_samples() -> None:
        df      = _synthetic_lap(speed_zero_fraction=0.10)
        corners = detect_corners(df, curvature_threshold=0.005,
                                 min_corner_length_m=10.0, smooth_window=10)
        # Should still find the synthetic corners (they're in the high-speed section)

        assert len(corners) > 0, "Should still detect corners despite zero-speed prefix"

    _test("zero_speed_samples", t_zero_speed_samples)

    # -- -

    # Test 16 -- all corner lengths >= min_corner_length_m

    # -- -

    def t_all_corners_satisfy_min_length() -> None:
        min_len = 30.0
        df      = _synthetic_lap()
        corners = detect_corners(df, curvature_threshold=0.005,
                                 min_corner_length_m=min_len, smooth_window=5)
        for c in corners:
            length = c["s_end"] - c["s_start"]
            assert length >= min_len, (
                f"Corner {c['corner_id']} length {length:.1f} m < min {min_len} m"
            )

    _test("all_corners_satisfy_min_length", t_all_corners_satisfy_min_length)

    # -- -

    # Test 17 -- s_apex is present and within [s_start, s_end]

    # -- -

    def t_apex_within_bounds() -> None:
        df      = _synthetic_lap()
        corners = detect_corners(df, curvature_threshold=0.005,
                                 min_corner_length_m=10.0, smooth_window=5)
        for c in corners:
            assert "s_apex" in c, f"Corner {c['corner_id']} missing 's_apex'"
            assert c["s_start"] <= c["s_apex"] <= c["s_end"], (
                f"Corner {c['corner_id']}: s_apex {c['s_apex']} not in "
                f"[{c['s_start']}, {c['s_end']}]"
            )

    _test("apex_within_bounds", t_apex_within_bounds)

    # -- -

    # Test 18 -- direction field is present and valid

    # -- -

    def t_direction_field() -> None:
        df      = _synthetic_lap()
        corners = detect_corners(df, curvature_threshold=0.005,
                                 min_corner_length_m=10.0, smooth_window=5)
        for c in corners:
            assert "direction" in c, f"Corner {c['corner_id']} missing 'direction'"
            assert c["direction"] in ("L", "R"), (
                f"Corner {c['corner_id']}: direction {c['direction']!r} not L/R"
            )

    _test("direction_field", t_direction_field)

    # -- -

    # Test 19 -- wrap-around merge: corner straddling start/finish merges

    # -- -

    def t_wrap_around_merge() -> None:
        # Build a lap where a corner straddles the start/finish line:
        # curvature bump at the very start and very end, with small gap.
        n_pts = 3000
        dist  = np.linspace(0.0, 3000.0, n_pts)
        speed = np.full(n_pts, 30.0)
        curv  = np.zeros(n_pts)

        # Wide bump at end of lap (centred at s=2960, half-width=40 m)
        for pos in (2960.0, 40.0):
            w = np.abs(dist - pos) <= 40.0
            phase = (dist[w] - pos) / 40.0 * np.pi
            curv[w] = np.maximum(curv[w], 0.04 * (1 + np.cos(phase)) / 2)

        # Clear corner in the middle
        w_mid = np.abs(dist - 1500.0) <= 40.0
        phase_mid = (dist[w_mid] - 1500.0) / 40.0 * np.pi
        curv[w_mid] = 0.04 * (1 + np.cos(phase_mid)) / 2

        yaw = np.degrees(curv * speed)
        df  = pd.DataFrame({_COL_DIST: dist, _COL_SPEED: speed, _COL_YAW: yaw})

        corners = detect_corners(df, curvature_threshold=0.005,
                                 min_corner_length_m=5.0,
                                 smooth_window=3, merge_gap_m=100.0)
        # The start/end peaks should merge into one corner, plus the middle one = 2 total.
        # Without wrap-around we'd get 3 corners (start, middle, end).
        assert len(corners) == 2, (
            f"Expected 2 corners (1 wrap-around + 1 middle), got {len(corners)}: {corners}"
        )

    _test("wrap_around_merge", t_wrap_around_merge)

    # -- -

    # Test 20 -- NaN interpolation: short NaN gaps are interpolated, not zeroed

    # -- -

    def t_nan_interpolation() -> None:
        df  = _synthetic_lap()
        # Insert a short NaN gap (5 samples) inside a corner region
        yaw = df[_COL_YAW].values.copy()
        # Corner is near s=375 (first corner apex); pick samples near there
        idx = 120   # roughly near first corner
        yaw[idx:idx + 5] = np.nan
        df2 = df.copy()
        df2[_COL_YAW] = yaw
        corners = detect_corners(df2, curvature_threshold=0.005,
                                 min_corner_length_m=10.0, smooth_window=5)
        # Should still detect all corners despite the short NaN gap
        assert len(corners) == N_CORNERS, (
            f"Short NaN gap: expected {N_CORNERS} corners, got {len(corners)}"
        )

    _test("nan_interpolation", t_nan_interpolation)

    # -- -

    # Summary

    # -- -

    total = len(passed) + len(failed)
    print(f"\nCorner Detection Tests: {len(passed)}/{total} passed")
    for name in passed:
        print(f"  OK {name}")
    for name, tb in failed:
        print(f"  FAIL {name}\n{tb}")

    if failed:
        raise AssertionError(f"{len(failed)} test(s) failed.")


# -- -

# Entry point

# -- -


# =============================================================================
# Corner Taxonomy
# =============================================================================

def classify_corner_type(
    corner: dict,
    lap_df: pd.DataFrame,
) -> str:
    """
    Classify a corner as hairpin/medium/fast/kink based on curvature, length, speed.

    Returns one of: "hairpin", "medium", "fast", "kink", "chicane", "compound_member", "setup"
    """
    s_start = float(corner.get("s_start", 0))
    s_end = float(corner.get("s_end", 0))
    corner_length = s_end - s_start

    if corner_length <= 0:
        return "medium"

    # Get speed and curvature within corner
    dist_col = "Distance (m)"
    speed_col = "Speed (m/s)"

    if dist_col not in lap_df.columns or speed_col not in lap_df.columns:
        return "medium"

    dist = lap_df[dist_col].values.astype(float)
    speed = lap_df[speed_col].values.astype(float)

    mask = (dist >= s_start) & (dist <= s_end)
    if mask.sum() < 3:
        return "medium"

    corner_speed = speed[mask]
    finite = np.isfinite(corner_speed)
    if finite.sum() == 0:
        return "medium"

    min_speed_mps = float(np.min(corner_speed[finite]))
    min_speed_kmh = min_speed_mps * 3.6

    # Get approach speed (before corner)
    approach_mask = (dist >= max(0, s_start - 30)) & (dist < s_start)
    if approach_mask.sum() > 0:
        approach_speed = float(np.nanmean(speed[approach_mask]))
    else:
        approach_speed = float(np.nanmean(corner_speed[finite]))

    speed_loss_pct = (1.0 - min_speed_mps / max(approach_speed, 1.0)) * 100 if approach_speed > 0 else 0

    # Get mean yaw rate as curvature proxy
    mean_yaw = 0.0
    if "yaw_rate_dps" in lap_df.columns:
        yaw = np.abs(lap_df["yaw_rate_dps"].values.astype(float))
        corner_yaw = yaw[mask]
        yaw_finite = np.isfinite(corner_yaw)
        if yaw_finite.sum() > 0:
            mean_yaw = float(np.nanmean(corner_yaw[yaw_finite]))

    # Classification rules
    # Kink: very short, very low speed loss, low curvature
    if corner_length < 40 and speed_loss_pct < 12 and mean_yaw < 8:
        return "kink"

    # Hairpin: short, very slow, high curvature
    if min_speed_kmh < 45 and corner_length < 80 and (mean_yaw > 15 or speed_loss_pct > 50):
        return "hairpin"

    # Fast: long, high speed, low curvature
    if min_speed_kmh > 70 and corner_length > 60 and mean_yaw < 10:
        return "fast"

    # Medium: everything else
    return "medium"


def classify_corner_types(
    corners: list[dict],
    lap_df: pd.DataFrame,
) -> None:
    """Classify all corners in-place, adding 'corner_type' field."""
    for corner in corners:
        corner["corner_type"] = classify_corner_type(corner, lap_df)


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _run_tests()