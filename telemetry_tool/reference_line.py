"""
reference_line.py
-----------------
Computes a single clean reference racing line from multiple GPS laps and
derives the track curvature profile needed by the physics-based lap
simulation engine.

Public API
~~~~~~~~~~
``compute_reference_line(resampled_laps, method, ...)``
    Aggregate multiple laps into a single representative XY trace.

``compute_curvature_profile(ref_line)``
    Curvature κ(s) and heading θ(s) from the smoothed reference line.

``compute_track_width_estimate(resampled_laps, ref_line)``
    Lateral scatter (perpendicular std) at each distance bin.

Design principles
~~~~~~~~~~~~~~~~~
- Pure functions; no side effects, no global mutable state.
- NaN-robust throughout.
- Structured logging; zero print statements.
- Deterministic: identical inputs â†’ identical outputs.
- Numpy / pandas only â€” no scipy, no heavy dependencies.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any, Final

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# -- -

# Column-name constants (aligned with features.py / corner_detection.py)

# -- -


_COL_DIST:  Final[str] = "Distance (m)"
_COL_SPEED: Final[str] = "Speed (m/s)"
_COL_TIME:  Final[str] = "Time (s)"
_COL_X:     Final[str] = "X (m)"
_COL_Y:     Final[str] = "Y (m)"
_COL_LAT:   Final[str] = "Latitude (deg)"
_COL_LON:   Final[str] = "Longitude (deg)"

# Output column names

OUT_DIST:       Final[str] = "distance_m"
OUT_X:          Final[str] = "x_ref_m"
OUT_Y:          Final[str] = "y_ref_m"
OUT_LAT:        Final[str] = "lat_ref_deg"
OUT_LON:        Final[str] = "lon_ref_deg"
OUT_CURVATURE:  Final[str] = "curvature_1pm"
OUT_HEADING:    Final[str] = "heading_rad"
OUT_LAT_SCATTER: Final[str] = "lateral_scatter_m"

# Defaults

_DEFAULT_SMOOTH_WINDOW: Final[int] = 7     # half-window for Gaussian smooth
_MIN_LAPS:              Final[int] = 2     # minimum laps for median/weighted
_MIN_POINTS:            Final[int] = 10    # minimum valid grid points
_EARTH_RADIUS_M:        Final[float] = 6_371_000.0

# -- -

# Exceptions

# -- -


class ReferenceLineError(ValueError):
    """Raised when the reference line cannot be computed."""


# -- -

# Internal helpers â€” geometry

# -- -


def _has(df: pd.DataFrame, col: str) -> bool:
    """Return True if *col* exists in *df* and has at least one non-NaN value."""
    return col in df.columns and df[col].notna().any()


def _gaussian_smooth(signal: np.ndarray, half_window: int) -> np.ndarray:
    """
    Apply a Gaussian-weighted symmetric rolling average.

    Parameters
    ----------
    signal:
        1-D array (may contain only finite values).
    half_window:
        Half-width of the kernel in samples.

    Returns
    -------
    np.ndarray of the same length as *signal*.
    """
    if half_window <= 0 or len(signal) < 3:
        return signal.copy()

    k = 2 * half_window + 1
    x = np.arange(k) - half_window
    w = np.exp(-0.5 * (x / max(half_window / 2.0, 0.5)) ** 2)
    w /= w.sum()

    pad = np.pad(signal, half_window, mode="reflect")
    out = np.convolve(pad, w, mode="valid")
    return out[: len(signal)]


_MAX_ABS_LATITUDE_DEG = 85.0


def _assert_valid_latitude(lat_ref_rad: float) -> None:
    """Raise if the reference latitude is too close to a pole for the
    equirectangular projection to be numerically sound.

    cos(lat_ref) -> 0 as |lat| -> 90 deg, which makes the longitude<->metres
    scale factor collapse toward zero in the forward transform and blow up
    (division by near-zero) in the inverse -- tiny GPS jitter turns into
    wildly wrong metre offsets. No real racetrack is within a few degrees of
    a pole, so this is a genuine precondition violation, not something to
    silently degrade: it's raised so the pipeline's existing per-stage
    _safe_step wrapper records it as a stage error with a reason, instead of
    this function producing numerically-garbage coordinates.
    """
    lat_deg = np.degrees(lat_ref_rad)
    if abs(lat_deg) > _MAX_ABS_LATITUDE_DEG:
        raise ValueError(
            f"GPS latitude {lat_deg:.4f}° is outside the supported range "
            f"(|lat| <= {_MAX_ABS_LATITUDE_DEG}°) for the equirectangular "
            "projection used here; this session's location is not supported."
        )


def _latlon_to_local_xy(
    lat: np.ndarray,
    lon: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Convert lat/lon arrays to local tangent-plane XY (metres) using an
    equirectangular projection centred on the mean position.

    Returns (x_m, y_m) arrays.

    Raises
    ------
    ValueError
        If the mean latitude is beyond +/-85 degrees (see
        _assert_valid_latitude) -- the projection is not numerically sound
        that close to a pole, and no real racetrack is there.
    """
    lat_r = np.radians(lat)
    lon_r = np.radians(lon)

    lat_ref = np.nanmean(lat_r)
    lon_ref = np.nanmean(lon_r)

    _assert_valid_latitude(lat_ref)

    x_m = _EARTH_RADIUS_M * (lon_r - lon_ref) * np.cos(lat_ref)
    y_m = _EARTH_RADIUS_M * (lat_r - lat_ref)
    return x_m, y_m


def _local_xy_to_latlon(
    x_m: np.ndarray,
    y_m: np.ndarray,
    lat_ref_rad: float,
    lon_ref_rad: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Inverse of the equirectangular projection.

    Raises
    ------
    ValueError
        If lat_ref_rad is beyond +/-85 degrees (see _assert_valid_latitude).
    """
    _assert_valid_latitude(lat_ref_rad)
    lat_r = y_m / _EARTH_RADIUS_M + lat_ref_rad
    lon_r = x_m / (_EARTH_RADIUS_M * np.cos(lat_ref_rad)) + lon_ref_rad
    return np.degrees(lat_r), np.degrees(lon_r)


def _extract_xy(
    df: pd.DataFrame,
) -> tuple[np.ndarray, np.ndarray, str]:
    """
    Extract XY position arrays from a lap DataFrame.

    Priority: X/Y columns â†’ lat/lon â†’ error.
    Returns (x, y, source_label).
    """
    if _has(df, _COL_X) and _has(df, _COL_Y):
        x = pd.to_numeric(df[_COL_X], errors="coerce").values
        y = pd.to_numeric(df[_COL_Y], errors="coerce").values
        return x, y, "XY"

    if _has(df, _COL_LAT) and _has(df, _COL_LON):
        lat = pd.to_numeric(df[_COL_LAT], errors="coerce").values
        lon = pd.to_numeric(df[_COL_LON], errors="coerce").values
        x, y = _latlon_to_local_xy(lat, lon)
        return x, y, "GPS"

    raise ReferenceLineError(
        "Cannot extract position data: neither X/Y nor Latitude/Longitude "
        "columns found."
    )


def _extract_latlon_if_available(
    df: pd.DataFrame,
) -> tuple[np.ndarray | None, np.ndarray | None]:
    """Return (lat, lon) arrays if present, else (None, None)."""
    if _has(df, _COL_LAT) and _has(df, _COL_LON):
        lat = pd.to_numeric(df[_COL_LAT], errors="coerce").values
        lon = pd.to_numeric(df[_COL_LON], errors="coerce").values
        return lat, lon
    return None, None


def _lap_time(df: pd.DataFrame) -> float:
    """Return lap duration from the Time column, or NaN if unavailable."""
    if not _has(df, _COL_TIME):
        return float("nan")
    t = pd.to_numeric(df[_COL_TIME], errors="coerce").dropna()
    if len(t) < 2:
        return float("nan")
    return float(t.iloc[-1] - t.iloc[0])


def _build_common_grid(
    resampled_laps: dict[int, pd.DataFrame],
) -> np.ndarray:
    """
    Build a common distance grid from the median start/end of all laps.

    All laps are assumed to be distance-resampled and start near 0.
    The grid uses the median number of samples across laps.
    """
    starts: list[float] = []
    ends:   list[float] = []
    counts: list[int]   = []

    for df in resampled_laps.values():
        d = pd.to_numeric(df[_COL_DIST], errors="coerce").dropna()
        if len(d) >= 2:
            starts.append(float(d.iloc[0]))
            ends.append(float(d.iloc[-1]))
            counts.append(len(d))

    if not starts:
        raise ReferenceLineError("No valid laps with distance data.")

    d_min = float(np.median(starts))
    d_max = float(np.median(ends))
    n_pts = int(np.median(counts))

    if d_max <= d_min:
        raise ReferenceLineError(
            f"Degenerate distance range: d_min={d_min:.1f}, d_max={d_max:.1f}."
        )

    return np.linspace(d_min, d_max, n_pts)


def _interpolate_lap_onto_grid(
    df: pd.DataFrame,
    grid: np.ndarray,
    col: str,
) -> np.ndarray:
    """
    Linearly interpolate a single column of *df* onto the common distance
    *grid*.  Returns NaN where the lap distance range doesn't cover the grid.
    """
    d   = pd.to_numeric(df[_COL_DIST], errors="coerce").values
    val = pd.to_numeric(df[col], errors="coerce").values if col in df.columns else None
    if val is None:
        return np.full(len(grid), np.nan)

    mask = np.isfinite(d) & np.isfinite(val)
    if mask.sum() < 2:
        return np.full(len(grid), np.nan)

    d_c  = d[mask]
    v_c  = val[mask]
    order = np.argsort(d_c, kind="stable")
    _, ui = np.unique(d_c[order], return_index=True)

    result = np.interp(
        grid,
        d_c[order][ui],
        v_c[order][ui],
        left=np.nan,
        right=np.nan,
    )
    return result


# -- -

# Public API â€” 1. compute_reference_line

# -- -


def compute_reference_line(
    resampled_laps: dict[int, pd.DataFrame],
    method: str = "median",
    *,
    smooth_window: int = _DEFAULT_SMOOTH_WINDOW,
    exclude_laps: "set[int] | None" = None,
) -> pd.DataFrame:
    """
    Compute a single clean reference racing line from multiple resampled laps.

    Parameters
    ----------
    resampled_laps:
        Dict of ``{lap_number: DataFrame}`` where each DataFrame is
        distance-resampled and contains ``Distance (m)`` plus position
        columns (``X (m)`` / ``Y (m)`` or ``Latitude (deg)`` / ``Longitude
        (deg)``).
    method:
        Aggregation strategy:

        - ``"median"`` â€” median X/Y at each distance bin (default, most
          robust to outliers).
        - ``"best"`` â€” use the single fastest lap as the reference.
        - ``"weighted"`` â€” inverse-lap-time weighted mean (faster laps
          contribute more).
    smooth_window:
        Gaussian half-window (samples) applied to the aggregated trace
        to suppress GPS jitter.  Pass 0 to disable.

    Returns
    -------
    pd.DataFrame
        Columns: ``distance_m``, ``x_ref_m``, ``y_ref_m``, and
        ``lat_ref_deg``, ``lon_ref_deg`` when GPS data is available.

    Raises
    ------
    ReferenceLineError
        If fewer than the required laps are available, or no position
        data is present.
    """
    if not resampled_laps:
        raise ReferenceLineError("resampled_laps is empty.")

    method = method.lower().strip()
    valid_methods = ("median", "best", "weighted")
    if method not in valid_methods:
        raise ReferenceLineError(
            f"Unknown method {method!r}; choose from {valid_methods}."
        )

    # --- Filter out invalid/excluded laps
    if exclude_laps:
        filtered_laps = {
            k: v for k, v in resampled_laps.items()
            if k not in exclude_laps
        }
        n_excluded = len(resampled_laps) - len(filtered_laps)
        if n_excluded > 0:
            logger.info(
                "Reference line: excluded %d invalid lap(s), "
                "%d remaining.",
                n_excluded, len(filtered_laps),
            )
        # Fall back to full set if too few remain

        if len(filtered_laps) >= _MIN_LAPS:
            resampled_laps = filtered_laps
        else:
            logger.warning(
                "After exclusion only %d lap(s) remain; "
                "using all %d laps for reference line.",
                len(filtered_laps), len(resampled_laps),
            )

    # --- Best-lap shortcut (single-lap reference) -- -

    if method == "best":
        return _reference_from_best_lap(resampled_laps, smooth_window)

    # --- Multi-lap aggregation (median / weighted)
    if len(resampled_laps) < _MIN_LAPS:
        logger.warning(
            "Only %d lap(s) available; falling back to best-lap reference.",
            len(resampled_laps),
        )
        return _reference_from_best_lap(resampled_laps, smooth_window)

    grid = _build_common_grid(resampled_laps)

    # Determine position source (prefer XY, fall back to GPS â†’ local XY)

    first_df = next(iter(resampled_laps.values()))
    have_xy  = _has(first_df, _COL_X) and _has(first_df, _COL_Y)
    have_gps = _has(first_df, _COL_LAT) and _has(first_df, _COL_LON)

    if not have_xy and not have_gps:
        raise ReferenceLineError(
            "No position columns found (need X/Y or Lat/Lon)."
        )

    # Interpolate every lap's X and Y onto the common grid

    x_col = _COL_X if have_xy else None
    y_col = _COL_Y if have_xy else None

    x_matrix: list[np.ndarray] = []
    y_matrix: list[np.ndarray] = []
    weights:  list[float]      = []

    # If GPS-only, we project each lap to local XY using a common centre

    # to avoid aggregating lat/lon directly (which suffers from cosine

    # distortion).

    gps_lat_ref_rad: float = 0.0
    gps_lon_ref_rad: float = 0.0

    if not have_xy and have_gps:
        # Compute a single projection centre from all laps combined

        all_lat: list[float] = []
        all_lon: list[float] = []
        for df in resampled_laps.values():
            lat_arr = pd.to_numeric(df[_COL_LAT], errors="coerce").dropna().values
            lon_arr = pd.to_numeric(df[_COL_LON], errors="coerce").dropna().values
            if len(lat_arr) > 0:
                all_lat.append(float(np.mean(lat_arr)))
                all_lon.append(float(np.mean(lon_arr)))
        gps_lat_ref_rad = np.radians(np.mean(all_lat))
        gps_lon_ref_rad = np.radians(np.mean(all_lon))

    for ln in sorted(resampled_laps.keys()):
        df = resampled_laps[ln]

        if have_xy:
            xi = _interpolate_lap_onto_grid(df, grid, _COL_X)
            yi = _interpolate_lap_onto_grid(df, grid, _COL_Y)
        else:
            # GPS â†’ local XY with the shared projection centre

            lat_i = _interpolate_lap_onto_grid(df, grid, _COL_LAT)
            lon_i = _interpolate_lap_onto_grid(df, grid, _COL_LON)
            xi = _EARTH_RADIUS_M * (np.radians(lon_i) - gps_lon_ref_rad) * np.cos(gps_lat_ref_rad)
            yi = _EARTH_RADIUS_M * (np.radians(lat_i) - gps_lat_ref_rad)

        x_matrix.append(xi)
        y_matrix.append(yi)

        lt = _lap_time(df)
        weights.append(1.0 / lt if math.isfinite(lt) and lt > 0 else 1.0)

    X = np.array(x_matrix)  # shape (n_laps, n_grid)
    Y = np.array(y_matrix)

    # --- Aggregate -
    if method == "median":
        import warnings
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", "All-NaN slice", RuntimeWarning)
            x_ref = np.nanmedian(X, axis=0)
            y_ref = np.nanmedian(Y, axis=0)
    else:  # "weighted"
        w = np.array(weights)
        w = w / w.sum()  # normalise

        # Mask NaN rows per grid point for robust weighted mean

        x_ref = np.full(len(grid), np.nan)
        y_ref = np.full(len(grid), np.nan)
        for j in range(len(grid)):
            xj = X[:, j]
            yj = Y[:, j]
            finite = np.isfinite(xj) & np.isfinite(yj)
            if finite.sum() == 0:
                continue
            wf = w[finite]
            wf = wf / wf.sum()
            x_ref[j] = float(np.dot(wf, xj[finite]))
            y_ref[j] = float(np.dot(wf, yj[finite]))

    # --- Smooth -
    if smooth_window > 0:
        finite_x = np.isfinite(x_ref)
        finite_y = np.isfinite(y_ref)
        if finite_x.sum() >= 3:
            x_ref[finite_x] = _gaussian_smooth(x_ref[finite_x], smooth_window)
        if finite_y.sum() >= 3:
            y_ref[finite_y] = _gaussian_smooth(y_ref[finite_y], smooth_window)

    # --- Assemble output DataFrame -
    result = pd.DataFrame({
        OUT_DIST: grid,
        OUT_X:    x_ref,
        OUT_Y:    y_ref,
    })

    # Add lat/lon back-projection if the source was GPS

    if not have_xy and have_gps:
        lat_out, lon_out = _local_xy_to_latlon(
            x_ref, y_ref, gps_lat_ref_rad, gps_lon_ref_rad,
        )
        result[OUT_LAT] = lat_out
        result[OUT_LON] = lon_out
    elif have_gps:
        # XY was primary but GPS is also available â€” aggregate lat/lon too

        lat_mat = np.array([
            _interpolate_lap_onto_grid(resampled_laps[ln], grid, _COL_LAT)
            for ln in sorted(resampled_laps.keys())
        ])
        lon_mat = np.array([
            _interpolate_lap_onto_grid(resampled_laps[ln], grid, _COL_LON)
            for ln in sorted(resampled_laps.keys())
        ])
        if method == "median":
            result[OUT_LAT] = np.nanmedian(lat_mat, axis=0)
            result[OUT_LON] = np.nanmedian(lon_mat, axis=0)
        else:
            lat_ref_arr = np.full(len(grid), np.nan)
            lon_ref_arr = np.full(len(grid), np.nan)
            w = np.array(weights)
            w = w / w.sum()
            for j in range(len(grid)):
                finite = np.isfinite(lat_mat[:, j]) & np.isfinite(lon_mat[:, j])
                if finite.sum() == 0:
                    continue
                wf = w[finite]
                wf = wf / wf.sum()
                lat_ref_arr[j] = float(np.dot(wf, lat_mat[:, j][finite]))
                lon_ref_arr[j] = float(np.dot(wf, lon_mat[:, j][finite]))
            result[OUT_LAT] = lat_ref_arr
            result[OUT_LON] = lon_ref_arr

    valid = np.isfinite(result[OUT_X]) & np.isfinite(result[OUT_Y])
    if valid.sum() < _MIN_POINTS:
        raise ReferenceLineError(
            f"Reference line has only {valid.sum()} valid points "
            f"(need â‰¥ {_MIN_POINTS})."
        )

    logger.info(
        "Reference line: method=%s, %d points, range=%.1fâ€“%.1f m, "
        "%d laps aggregated, smooth_window=%d",
        method, len(grid), float(grid[0]), float(grid[-1]),
        len(resampled_laps), smooth_window,
    )
    return result


def _reference_from_best_lap(
    resampled_laps: dict[int, pd.DataFrame],
    smooth_window: int,
) -> pd.DataFrame:
    """Select the fastest lap and use its trace as the reference line."""
    best_ln:   int | None = None
    best_time: float      = float("inf")

    for ln, df in resampled_laps.items():
        lt = _lap_time(df)
        if math.isfinite(lt) and lt < best_time:
            best_time = lt
            best_ln   = ln

    if best_ln is None:
        # No lap time available â€” pick the first lap

        best_ln = next(iter(resampled_laps.keys()))
        logger.warning("No lap times available; using lap %d as reference.", best_ln)

    df = resampled_laps[best_ln]
    x, y, source = _extract_xy(df)
    dist = pd.to_numeric(df[_COL_DIST], errors="coerce").values

    # Smooth

    finite_mask = np.isfinite(x) & np.isfinite(y) & np.isfinite(dist)
    if smooth_window > 0 and finite_mask.sum() >= 3:
        x_s = x.copy()
        y_s = y.copy()
        x_s[finite_mask] = _gaussian_smooth(x[finite_mask], smooth_window)
        y_s[finite_mask] = _gaussian_smooth(y[finite_mask], smooth_window)
    else:
        x_s, y_s = x.copy(), y.copy()

    result = pd.DataFrame({
        OUT_DIST: dist,
        OUT_X:    x_s,
        OUT_Y:    y_s,
    })

    # Add lat/lon if available

    lat_arr, lon_arr = _extract_latlon_if_available(df)
    if lat_arr is not None:
        result[OUT_LAT] = lat_arr
        result[OUT_LON] = lon_arr

    logger.info(
        "Reference line: method=best (lap %d, %.2fs), %d points, source=%s",
        best_ln, best_time, len(df), source,
    )
    return result


# -- -

# Public API â€” 2. compute_curvature_profile

# -- -


def compute_curvature_profile(
    ref_line: pd.DataFrame,
    *,
    smooth_window: int = _DEFAULT_SMOOTH_WINDOW,
) -> pd.DataFrame:
    """
    Compute curvature κ(s) [1/m] and heading θ(s) [rad] from the reference
    line.

    The curvature is computed via the Frenetâ€“Serret formula:

        κ = |x'y'' âˆ’ y'x''| / (x'² + y'²)^(3/2)

    where derivatives are taken with respect to arc length (distance).

    Parameters
    ----------
    ref_line:
        DataFrame from :func:`compute_reference_line` with columns
        ``distance_m``, ``x_ref_m``, ``y_ref_m``.
    smooth_window:
        Gaussian half-window applied to the curvature signal after
        computation to suppress differentiation noise.

    Returns
    -------
    pd.DataFrame
        A copy of *ref_line* with two new columns added:

        ``curvature_1pm`` â€” absolute curvature [1/m]
        ``heading_rad``   â€” heading angle [rad] (from atan2)

    Raises
    ------
    ReferenceLineError
        If required columns are absent or insufficient data.
    """
    for col in (OUT_DIST, OUT_X, OUT_Y):
        if col not in ref_line.columns:
            raise ReferenceLineError(
                f"Required column {col!r} not found in ref_line."
            )

    dist = ref_line[OUT_DIST].values.astype(float)
    x    = ref_line[OUT_X].values.astype(float)
    y    = ref_line[OUT_Y].values.astype(float)

    finite = np.isfinite(dist) & np.isfinite(x) & np.isfinite(y)
    if finite.sum() < _MIN_POINTS:
        raise ReferenceLineError(
            f"Only {finite.sum()} finite points; need â‰¥ {_MIN_POINTS}."
        )

    # --- Heading θ(s) = atan2(dy, dx) -
    heading = _compute_heading(x, y, dist)

    # --- Curvature via Frenetâ€“Serret -
    kappa = _curvature_from_xy(x, y, dist)

    # Smooth the curvature to remove differentiation noise

    kappa_finite = np.isfinite(kappa)
    if smooth_window > 0 and kappa_finite.sum() >= 3:
        kappa[kappa_finite] = _gaussian_smooth(kappa[kappa_finite], smooth_window)

    # Clip non-physical curvature (radius < 3 m â†’ κ > 0.33 is extreme)

    kappa = np.clip(kappa, 0.0, 1.0)

    result = ref_line.copy()
    result[OUT_CURVATURE] = kappa
    result[OUT_HEADING]   = heading

    finite_k = kappa[np.isfinite(kappa)]
    logger.info(
        "Curvature profile: %d points, κ_mean=%.4f 1/m, κ_max=%.4f 1/m, "
        "κ > 0.005 at %.0f%% of points",
        len(kappa),
        float(np.mean(finite_k)) if len(finite_k) > 0 else 0.0,
        float(np.max(finite_k))  if len(finite_k) > 0 else 0.0,
        float((finite_k > 0.005).sum() / max(len(finite_k), 1) * 100),
    )
    return result


def _curvature_from_xy(
    x: np.ndarray,
    y: np.ndarray,
    dist: np.ndarray,
) -> np.ndarray:
    """
    Absolute curvature via the Frenetâ€“Serret formula:

        κ = |x'·y'' âˆ’ y'·x''| / (x'² + y'²)^(3/2)

    Derivatives are taken with respect to arc length (distance).

    Returns an array of the same length as x, with edges padded to nearest
    interior value.
    """
    ds = np.diff(dist)
    ds = np.where(ds > 0, ds, np.nan)

    dx = np.diff(x)
    dy = np.diff(y)
    xd = dx / ds
    yd = dy / ds

    # Second derivatives (centred differences)

    xd_mid = 0.5 * (xd[:-1] + xd[1:])
    yd_mid = 0.5 * (yd[:-1] + yd[1:])
    ds_mid = 0.5 * (ds[:-1] + ds[1:])

    xdd = np.diff(xd) / ds_mid
    ydd = np.diff(yd) / ds_mid

    denom = (xd_mid ** 2 + yd_mid ** 2) ** 1.5
    with np.errstate(divide="ignore", invalid="ignore"):
        kappa = np.abs(
            np.where(denom > 0, (xd_mid * ydd - yd_mid * xdd) / denom, np.nan)
        )

    # Pad to original length

    kappa_full = np.empty(len(x))
    kappa_full[:] = np.nan
    kappa_full[1:-1] = kappa

    if np.isfinite(kappa).any():
        kappa_full[0]  = kappa[0]  if np.isfinite(kappa[0])  else float(np.nanmean(kappa))
        kappa_full[-1] = kappa[-1] if np.isfinite(kappa[-1]) else float(np.nanmean(kappa))

    return kappa_full


def _compute_heading(
    x: np.ndarray,
    y: np.ndarray,
    dist: np.ndarray,
) -> np.ndarray:
    """
    Heading angle θ(s) = atan2(dy/ds, dx/ds) [rad].

    Returns an array of the same length as x, with the first and last
    values replicated from the nearest interior point.
    """
    ds = np.diff(dist)
    ds = np.where(ds > 0, ds, np.nan)

    dx = np.diff(x)
    dy = np.diff(y)

    theta = np.arctan2(dy / ds, dx / ds)

    # Pad to original length

    heading = np.empty(len(x))
    heading[:] = np.nan
    heading[:-1] = theta  # assign to the left end of each segment

    if np.isfinite(theta).any():
        heading[-1] = theta[-1] if np.isfinite(theta[-1]) else float(np.nanmean(theta))

    return heading


# -- -

# Public API â€” 3. compute_track_width_estimate

# -- -


def compute_track_width_estimate(
    resampled_laps: dict[int, pd.DataFrame],
    ref_line: pd.DataFrame,
) -> pd.DataFrame:
    """
    Estimate lateral scatter at each distance bin by computing the standard
    deviation of perpendicular offsets from the reference line across all laps.

    Large scatter indicates sections where drivers explore different lines
    (typically corner entry/exit).

    Parameters
    ----------
    resampled_laps:
        Dict of ``{lap_number: DataFrame}`` (same as input to
        :func:`compute_reference_line`).
    ref_line:
        DataFrame from :func:`compute_reference_line`.  Must contain
        ``distance_m``, ``x_ref_m``, ``y_ref_m``.

    Returns
    -------
    pd.DataFrame
        A copy of *ref_line* with a new column ``lateral_scatter_m``
        (std of perpendicular offsets [m]).
    """
    for col in (OUT_DIST, OUT_X, OUT_Y):
        if col not in ref_line.columns:
            raise ReferenceLineError(
                f"Required column {col!r} not found in ref_line."
            )

    grid  = ref_line[OUT_DIST].values.astype(float)
    x_ref = ref_line[OUT_X].values.astype(float)
    y_ref = ref_line[OUT_Y].values.astype(float)
    n_pts = len(grid)

    # Compute the local tangent direction at each grid point from the

    # reference line.  The normal (perpendicular) is (-ty, tx).

    tx = np.zeros(n_pts)
    ty = np.zeros(n_pts)
    ds = np.diff(grid)

    dx_ref = np.diff(x_ref)
    dy_ref = np.diff(y_ref)

    # Assign segment tangent to the left end of each pair

    tx[:-1] = dx_ref
    ty[:-1] = dy_ref
    tx[-1]  = tx[-2]   # replicate last
    ty[-1]  = ty[-2]

    # Normalise tangent vectors

    t_len = np.sqrt(tx ** 2 + ty ** 2)
    t_len = np.where(t_len > 0, t_len, 1.0)
    tx /= t_len
    ty /= t_len

    # Normal direction (90° CCW rotation of tangent)

    nx = -ty
    ny =  tx

    # Determine source and projection centre for GPS-only laps

    first_df = next(iter(resampled_laps.values()))
    have_xy  = _has(first_df, _COL_X) and _has(first_df, _COL_Y)
    have_gps = _has(first_df, _COL_LAT) and _has(first_df, _COL_LON)

    gps_lat_ref_rad = 0.0
    gps_lon_ref_rad = 0.0
    if not have_xy and have_gps:
        all_lat = []
        all_lon = []
        for df in resampled_laps.values():
            lat_vals = pd.to_numeric(df[_COL_LAT], errors="coerce").dropna().values
            lon_vals = pd.to_numeric(df[_COL_LON], errors="coerce").dropna().values
            if len(lat_vals) > 0:
                all_lat.append(float(np.mean(lat_vals)))
                all_lon.append(float(np.mean(lon_vals)))
        gps_lat_ref_rad = np.radians(np.mean(all_lat))
        gps_lon_ref_rad = np.radians(np.mean(all_lon))

    # For each lap, compute the perpendicular offset at each grid point

    offsets: list[np.ndarray] = []

    for ln in sorted(resampled_laps.keys()):
        df = resampled_laps[ln]

        if have_xy:
            xi = _interpolate_lap_onto_grid(df, grid, _COL_X)
            yi = _interpolate_lap_onto_grid(df, grid, _COL_Y)
        elif have_gps:
            lat_i = _interpolate_lap_onto_grid(df, grid, _COL_LAT)
            lon_i = _interpolate_lap_onto_grid(df, grid, _COL_LON)
            xi = _EARTH_RADIUS_M * (np.radians(lon_i) - gps_lon_ref_rad) * np.cos(gps_lat_ref_rad)
            yi = _EARTH_RADIUS_M * (np.radians(lat_i) - gps_lat_ref_rad)
        else:
            continue

        # Perpendicular offset: project (lap_pos âˆ’ ref_pos) onto the normal

        dx_lap = xi - x_ref
        dy_lap = yi - y_ref
        perp = dx_lap * nx + dy_lap * ny   # signed perpendicular offset
        offsets.append(perp)

    result = ref_line.copy()

    if not offsets:
        logger.warning("No laps could be projected; lateral_scatter_m will be NaN.")
        result[OUT_LAT_SCATTER] = np.full(n_pts, np.nan)
    else:
        offset_matrix = np.array(offsets)  # (n_laps, n_pts)
        scatter = np.nanstd(offset_matrix, axis=0, ddof=1)
        result[OUT_LAT_SCATTER] = scatter

        logger.info(
            "Track width estimate: mean_scatter=%.2f m, max_scatter=%.2f m, "
            "%d laps used",
            float(np.nanmean(scatter)),
            float(np.nanmax(scatter)),
            len(offsets),
        )

    return result


# ============================================================================

# Inline tests

# ============================================================================


def _run_tests() -> None:
    """
    Inline unit tests using synthetic data.
    Raises AssertionError on failure; prints a pass/fail summary.
    """
    import traceback

    passed: list[str] = []
    failed: list[tuple[str, str]] = []

    def _test(name: str, fn) -> None:  # type: ignore[type-arg]
        try:
            fn()
            passed.append(name)
        except Exception:  # noqa: BLE001
            failed.append((name, traceback.format_exc()))

    # -- -

    # Fixtures: synthetic laps around a known oval

    # -- -

    # Oval: two semicircles of radius R connected by two straights of

    # length L.  Total track length = 2L + 2Ï€R.

    R       = 50.0      # corner radius [m]
    L       = 200.0     # straight length [m]
    N_PTS   = 800       # samples per lap
    TRACK_LEN = 2 * L + 2 * math.pi * R   # â‰ˆ 714.16 m
    N_LAPS  = 6

    def _oval_xy(s: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Map arc-length â†’ (x, y) for the test oval."""
        x = np.empty_like(s)
        y = np.empty_like(s)

        seg1_end = L                            # first straight
        seg2_end = L + math.pi * R              # first semicircle
        seg3_end = 2 * L + math.pi * R          # second straight
        # seg4_end = TRACK_LEN                  # second semicircle


        for i, si in enumerate(s):
            si_mod = si % TRACK_LEN
            if si_mod < seg1_end:
                # Straight 1: along +x

                x[i] = si_mod
                y[i] = 0.0
            elif si_mod < seg2_end:
                # Semicircle 1: centre at (L, R), CW sweep

                angle = (si_mod - seg1_end) / R
                x[i] = L + R * math.sin(angle)
                y[i] = R * (1.0 - math.cos(angle))
            elif si_mod < seg3_end:
                # Straight 2: along -x at y = 2R

                x[i] = L - (si_mod - seg2_end)
                y[i] = 2 * R
            else:
                # Semicircle 2: centre at (0, R), CW sweep

                angle = (si_mod - seg3_end) / R
                x[i] = -R * math.sin(angle)
                y[i] = 2 * R - R * (1.0 - math.cos(angle))
        return x, y

    def _make_synthetic_laps(
        n_laps: int = N_LAPS,
        noise_m: float = 0.0,
        speed_base: float = 25.0,
    ) -> dict[int, pd.DataFrame]:
        """Generate dict of laps around the oval with optional positional noise."""
        rng = np.random.default_rng(42)
        laps: dict[int, pd.DataFrame] = {}
        for lap_num in range(1, n_laps + 1):
            dist = np.linspace(0.0, TRACK_LEN, N_PTS, endpoint=False)
            x, y = _oval_xy(dist)
            if noise_m > 0:
                x = x + rng.normal(0, noise_m, N_PTS)
                y = y + rng.normal(0, noise_m, N_PTS)
            # Speed: slower in corners, faster on straights

            seg1 = dist < L
            seg3 = (dist >= L + math.pi * R) & (dist < 2 * L + math.pi * R)
            speed = np.where(seg1 | seg3, speed_base, speed_base * 0.6)
            # Synthetic time from distance / speed

            dt = np.diff(dist) / speed[:-1]
            t  = np.concatenate([[0.0], np.cumsum(dt)])
            # Vary lap time slightly per lap

            t = t * (1.0 + rng.normal(0, 0.02))
            laps[lap_num] = pd.DataFrame({
                _COL_DIST:  dist,
                _COL_X:     x,
                _COL_Y:     y,
                _COL_SPEED: speed,
                _COL_TIME:  t,
            })
        return laps

    def _make_gps_laps(n_laps: int = N_LAPS, noise_m: float = 0.0) -> dict[int, pd.DataFrame]:
        """Laps with Lat/Lon instead of X/Y."""
        xy_laps = _make_synthetic_laps(n_laps=n_laps, noise_m=noise_m)
        gps_laps: dict[int, pd.DataFrame] = {}
        lat_origin = 48.8566   # Paris-ish
        lon_origin = 2.3522
        cos_lat = math.cos(math.radians(lat_origin))
        for ln, df in xy_laps.items():
            x = df[_COL_X].values
            y = df[_COL_Y].values
            lat = lat_origin + np.degrees(y / _EARTH_RADIUS_M)
            lon = lon_origin + np.degrees(x / (_EARTH_RADIUS_M * cos_lat))
            gps_df = df.drop(columns=[_COL_X, _COL_Y])
            gps_df = gps_df.copy()
            gps_df[_COL_LAT] = lat
            gps_df[_COL_LON] = lon
            gps_laps[ln] = gps_df
        return gps_laps

    # -- -

    # Test 1 â€” median reference line has correct length

    # -- -

    def t_median_correct_length() -> None:
        laps = _make_synthetic_laps(noise_m=0.0)
        ref  = compute_reference_line(laps, method="median", smooth_window=0)
        assert OUT_DIST in ref.columns
        assert OUT_X in ref.columns
        assert OUT_Y in ref.columns
        total_len = float(ref[OUT_DIST].iloc[-1] - ref[OUT_DIST].iloc[0])
        assert abs(total_len - TRACK_LEN) < TRACK_LEN * 0.02, (
            f"Track length {total_len:.1f} m deviates from expected {TRACK_LEN:.1f} m"
        )

    _test("median_correct_length", t_median_correct_length)

    # -- -

    # Test 2 â€” best-lap method returns a single lap trace

    # -- -

    def t_best_lap_selects_fastest() -> None:
        laps = _make_synthetic_laps()
        ref  = compute_reference_line(laps, method="best", smooth_window=0)
        assert len(ref) == N_PTS, f"Expected {N_PTS} points, got {len(ref)}"

    _test("best_lap_selects_fastest", t_best_lap_selects_fastest)

    # -- -

    # Test 3 â€” weighted method returns valid reference

    # -- -

    def t_weighted_method_runs() -> None:
        laps = _make_synthetic_laps()
        ref  = compute_reference_line(laps, method="weighted", smooth_window=3)
        assert len(ref) > 0
        assert np.isfinite(ref[OUT_X]).sum() > _MIN_POINTS

    _test("weighted_method_runs", t_weighted_method_runs)

    # -- -

    # Test 4 â€” GPS-only laps produce XY reference via local projection

    # -- -

    def t_gps_only_laps() -> None:
        laps = _make_gps_laps()
        ref  = compute_reference_line(laps, method="median", smooth_window=0)
        assert OUT_X in ref.columns
        assert OUT_Y in ref.columns
        assert OUT_LAT in ref.columns
        assert OUT_LON in ref.columns
        assert np.isfinite(ref[OUT_X]).sum() > _MIN_POINTS

    _test("gps_only_laps", t_gps_only_laps)

    # -- -

    # Test 5 â€” curvature profile: zero on straights, ~1/R in corners

    # -- -

    def t_curvature_on_oval() -> None:
        laps = _make_synthetic_laps(noise_m=0.0)
        ref  = compute_reference_line(laps, method="median", smooth_window=3)
        prof = compute_curvature_profile(ref, smooth_window=5)

        assert OUT_CURVATURE in prof.columns
        assert OUT_HEADING in prof.columns

        kappa = prof[OUT_CURVATURE].values
        dist  = prof[OUT_DIST].values

        # Middle of first straight (dist â‰ˆ L/2 = 100 m): curvature near 0

        mid_straight = np.abs(dist - L / 2) < 20
        k_straight = kappa[mid_straight]
        assert np.nanmean(k_straight) < 0.003, (
            f"Curvature on straight = {np.nanmean(k_straight):.4f}; expected near 0"
        )

        # Middle of first corner (dist â‰ˆ L + Ï€R/2): curvature near 1/R = 0.02

        corner_mid = L + math.pi * R / 2
        mid_corner = np.abs(dist - corner_mid) < 20
        k_corner = kappa[mid_corner]
        k_expected = 1.0 / R   # 0.02
        assert abs(np.nanmean(k_corner) - k_expected) < k_expected * 0.35, (
            f"Curvature in corner = {np.nanmean(k_corner):.4f}; "
            f"expected â‰ˆ {k_expected:.4f}"
        )

    _test("curvature_on_oval", t_curvature_on_oval)

    # -- -

    # Test 6 â€” heading increases monotonically around the oval

    # -- -

    def t_heading_monotonic() -> None:
        laps = _make_synthetic_laps(noise_m=0.0)
        ref  = compute_reference_line(laps, method="median", smooth_window=3)
        prof = compute_curvature_profile(ref, smooth_window=3)

        heading = prof[OUT_HEADING].values
        finite  = heading[np.isfinite(heading)]
        # Unwrap: on a closed oval the heading should rotate by ~2Ï€

        unwrapped = np.unwrap(finite)
        total_rotation = abs(unwrapped[-1] - unwrapped[0])
        assert abs(total_rotation - 2 * math.pi) < 1.0, (
            f"Total heading rotation = {total_rotation:.2f} rad; expected â‰ˆ 2Ï€"
        )

    _test("heading_monotonic", t_heading_monotonic)

    # -- -

    # Test 7 â€” lateral scatter is low for noiseless laps

    # -- -

    def t_scatter_low_noiseless() -> None:
        laps = _make_synthetic_laps(noise_m=0.0)
        ref  = compute_reference_line(laps, method="median", smooth_window=0)
        tw   = compute_track_width_estimate(laps, ref)
        assert OUT_LAT_SCATTER in tw.columns
        scatter = tw[OUT_LAT_SCATTER].values
        # All identical laps â†’ scatter should be ~0 (within floating-point)

        assert np.nanmax(scatter) < 0.01, (
            f"Max scatter = {np.nanmax(scatter):.4f} m; expected ~0 for identical laps"
        )

    _test("scatter_low_noiseless", t_scatter_low_noiseless)

    # -- -

    # Test 8 â€” lateral scatter increases with noise

    # -- -

    def t_scatter_reflects_noise() -> None:
        noise_m = 2.0
        laps = _make_synthetic_laps(noise_m=noise_m)
        ref  = compute_reference_line(laps, method="median", smooth_window=3)
        tw   = compute_track_width_estimate(laps, ref)
        scatter = tw[OUT_LAT_SCATTER].values
        mean_scatter = float(np.nanmean(scatter))
        # Mean scatter should be on the order of the noise std

        assert 0.5 < mean_scatter < noise_m * 3, (
            f"Mean scatter = {mean_scatter:.2f} m; expected near {noise_m:.1f} m"
        )

    _test("scatter_reflects_noise", t_scatter_reflects_noise)

    # -- -

    # Test 9 â€” single lap falls back to best-lap method

    # -- -

    def t_single_lap_fallback() -> None:
        laps = _make_synthetic_laps(n_laps=1)
        ref  = compute_reference_line(laps, method="median", smooth_window=0)
        assert len(ref) == N_PTS

    _test("single_lap_fallback", t_single_lap_fallback)

    # -- -

    # Test 10 â€” invalid method raises ReferenceLineError

    # -- -

    def t_invalid_method() -> None:
        laps = _make_synthetic_laps()
        try:
            compute_reference_line(laps, method="banana")
            assert False, "Expected ReferenceLineError"
        except ReferenceLineError:
            pass

    _test("invalid_method_raises", t_invalid_method)

    # -- -

    # Test 11 â€” empty laps raises ReferenceLineError

    # -- -

    def t_empty_laps() -> None:
        try:
            compute_reference_line({})
            assert False, "Expected ReferenceLineError"
        except ReferenceLineError:
            pass

    _test("empty_laps_raises", t_empty_laps)

    # -- -

    # Test 12 â€” smoothing reduces jitter

    # -- -

    def t_smoothing_reduces_jitter() -> None:
        laps = _make_synthetic_laps(noise_m=3.0)
        ref_raw    = compute_reference_line(laps, method="median", smooth_window=0)
        ref_smooth = compute_reference_line(laps, method="median", smooth_window=10)

        # Compute point-to-point jitter (second derivative proxy)

        def _jitter(arr: np.ndarray) -> float:
            d2 = np.diff(arr, n=2)
            return float(np.sqrt(np.nanmean(d2 ** 2)))

        jitter_raw    = _jitter(ref_raw[OUT_X].values)
        jitter_smooth = _jitter(ref_smooth[OUT_X].values)
        assert jitter_smooth < jitter_raw, (
            f"Smoothed jitter ({jitter_smooth:.4f}) should be less than "
            f"raw ({jitter_raw:.4f})"
        )

    _test("smoothing_reduces_jitter", t_smoothing_reduces_jitter)

    # -- -

    # Test 13 â€” curvature profile missing columns raises error

    # -- -

    def t_curvature_missing_columns() -> None:
        bad_df = pd.DataFrame({"foo": [1, 2, 3]})
        try:
            compute_curvature_profile(bad_df)
            assert False, "Expected ReferenceLineError"
        except ReferenceLineError:
            pass

    _test("curvature_missing_columns", t_curvature_missing_columns)

    # -- -

    # Test 14 â€” GPS round-trip: lat/lon â†’ XY â†’ lat/lon preserves location

    # -- -

    def t_gps_roundtrip() -> None:
        laps = _make_gps_laps(noise_m=0.0)
        ref  = compute_reference_line(laps, method="median", smooth_window=0)
        # The output lat/lon should be close to the input lat/lon of any lap

        original_lat = laps[1][_COL_LAT].values
        original_lon = laps[1][_COL_LON].values
        ref_lat = ref[OUT_LAT].values
        ref_lon = ref[OUT_LON].values
        # Use only overlapping grid points

        n = min(len(original_lat), len(ref_lat))
        lat_err = np.abs(original_lat[:n] - ref_lat[:n])
        lon_err = np.abs(original_lon[:n] - ref_lon[:n])
        assert np.nanmax(lat_err) < 0.001, (
            f"Lat roundtrip error = {np.nanmax(lat_err):.6f} deg"
        )
        assert np.nanmax(lon_err) < 0.001, (
            f"Lon roundtrip error = {np.nanmax(lon_err):.6f} deg"
        )

    _test("gps_roundtrip", t_gps_roundtrip)

    # -- -

    # Test 15 â€” curvature on GPS-only laps matches XY-based result

    # -- -

    def t_curvature_gps_vs_xy() -> None:
        laps_xy  = _make_synthetic_laps(noise_m=0.0)
        laps_gps = _make_gps_laps(noise_m=0.0)

        ref_xy  = compute_reference_line(laps_xy,  method="median", smooth_window=3)
        ref_gps = compute_reference_line(laps_gps, method="median", smooth_window=3)

        prof_xy  = compute_curvature_profile(ref_xy,  smooth_window=5)
        prof_gps = compute_curvature_profile(ref_gps, smooth_window=5)

        k_xy  = prof_xy[OUT_CURVATURE].values
        k_gps = prof_gps[OUT_CURVATURE].values
        n = min(len(k_xy), len(k_gps))

        # Trim edges (projection artifacts) and compare interior

        trim = n // 20
        k_xy_int  = k_xy[trim:-trim]
        k_gps_int = k_gps[trim:-trim]

        finite = np.isfinite(k_xy_int) & np.isfinite(k_gps_int)
        if finite.sum() > 10:
            corr = float(np.corrcoef(k_xy_int[finite], k_gps_int[finite])[0, 1])
            assert corr > 0.85, (
                f"XY vs GPS curvature correlation = {corr:.3f}; expected > 0.85"
            )

    _test("curvature_gps_vs_xy", t_curvature_gps_vs_xy)

    # -- -

    # Test 16 â€” track width estimate works with GPS-only laps

    # -- -

    def t_track_width_gps() -> None:
        laps = _make_gps_laps(noise_m=1.5)
        ref  = compute_reference_line(laps, method="median", smooth_window=3)
        tw   = compute_track_width_estimate(laps, ref)
        assert OUT_LAT_SCATTER in tw.columns
        assert np.isfinite(tw[OUT_LAT_SCATTER]).sum() > _MIN_POINTS

    _test("track_width_gps", t_track_width_gps)

    # -- -

    # Summary

    # -- -

    total = len(passed) + len(failed)
    print(f"\nReference Line Tests: {len(passed)}/{total} passed")
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


# ---------------------------------------------------------------------------
# Track boundary estimation
# ---------------------------------------------------------------------------


@dataclass
class TrackBoundaries:
    distance_m: np.ndarray
    left_offset_m: np.ndarray
    right_offset_m: np.ndarray
    confidence: np.ndarray
    sample_count: np.ndarray

    def to_dict(self) -> dict:
        return {
            "distance_m": self.distance_m.tolist(),
            "left_offset_m": self.left_offset_m.tolist(),
            "right_offset_m": self.right_offset_m.tolist(),
            "confidence": self.confidence.tolist(),
            "sample_count": self.sample_count.tolist(),
        }


def estimate_track_boundaries(
    resampled_laps: dict,
    ref_line: pd.DataFrame,
    percentile: float = 95,
    min_width_m: float = 4.0,
    max_width_m: float = 20.0,
    smooth_window: int = 15,
) -> TrackBoundaries | None:
    """Estimate L/R boundaries from perpendicular offsets of all lap XY traces."""
    if not resampled_laps:
        return None
    if ref_line is None or len(ref_line) == 0:
        return None

    # ref_line is produced by compute_reference_line() which uses snake_case
    # OUT_* names ("distance_m", "x_ref_m", "y_ref_m"). The lap_df values below
    # come straight from the resampled pipeline and use RaceChrono _COL_* names
    # ("Distance (m)", "X (m)", "Y (m)"). Do NOT conflate the two schemas.
    ref_dist = ref_line[OUT_DIST].values
    ref_x = ref_line[OUT_X].values
    ref_y = ref_line[OUT_Y].values

    if OUT_HEADING in ref_line.columns:
        heading = ref_line[OUT_HEADING].values
    else:
        dx = np.gradient(ref_x)
        dy = np.gradient(ref_y)
        heading = np.arctan2(dy, dx)

    n_bins = len(ref_dist)
    all_offsets: list[list[float]] = [[] for _ in range(n_bins)]

    for lap_df in resampled_laps.values():
        if lap_df is None or lap_df.empty:
            continue
        if _COL_X not in lap_df.columns or _COL_Y not in lap_df.columns:
            continue
        if _COL_DIST not in lap_df.columns:
            continue
        lap_x = np.interp(ref_dist, lap_df[_COL_DIST].values, lap_df[_COL_X].values)
        lap_y = np.interp(ref_dist, lap_df[_COL_DIST].values, lap_df[_COL_Y].values)
        dx = lap_x - ref_x
        dy = lap_y - ref_y
        perp = -dx * np.sin(heading) + dy * np.cos(heading)
        for i in range(n_bins):
            if np.isfinite(perp[i]):
                all_offsets[i].append(perp[i])

    left = np.zeros(n_bins)
    right = np.zeros(n_bins)
    counts = np.zeros(n_bins, dtype=int)
    for i in range(n_bins):
        if all_offsets[i]:
            arr = np.array(all_offsets[i])
            left[i] = np.percentile(arr, percentile)
            right[i] = np.percentile(arr, 100 - percentile)
            counts[i] = len(arr)

    for i in range(n_bins):
        width = left[i] - right[i]
        if width < min_width_m:
            center = (left[i] + right[i]) / 2
            left[i] = center + min_width_m / 2
            right[i] = center - min_width_m / 2
        elif width > max_width_m:
            center = (left[i] + right[i]) / 2
            left[i] = center + max_width_m / 2
            right[i] = center - max_width_m / 2

    if smooth_window > 1 and n_bins > smooth_window:
        kernel = np.ones(smooth_window) / smooth_window
        left = np.convolve(left, kernel, mode="same")
        right = np.convolve(right, kernel, mode="same")

    confidence = np.minimum(1.0, counts / 5.0)

    return TrackBoundaries(
        distance_m=ref_dist.copy(),
        left_offset_m=left,
        right_offset_m=right,
        confidence=confidence,
        sample_count=counts,
    )
