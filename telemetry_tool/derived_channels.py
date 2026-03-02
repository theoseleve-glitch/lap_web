"""
derived_channels.py
-------------------
Computes derived telemetry channels when the primary sensor channels are
absent from a RaceChrono CSV export.

Derived channels
~~~~~~~~~~~~~~~~
accel_long_mps2
    Longitudinal acceleration in m/s^2.
    Source priority:
      1. "Longitudinal acceleration (G) *calc"  (raw sensor, converted G->m/s^2)
      2. dv/dt from "Speed (m/s)" (numerical differentiation + optional smoothing)

accel_lat_mps2
    Lateral acceleration in m/s^2.
    Source priority:
      1. "Lateral acceleration (G) *calc"       (raw sensor, converted G->m/s^2)
      2. Cross-product of velocity vector derived from X/Y position + speed

yaw_rate_dps
    Yaw rate in degrees per second.
    Source priority:
      1. "Yaw rate (deg/s)"                     (direct sensor channel)
      2. d(bearing)/dt with 0-360 deg wrap handling

Design principles
~~~~~~~~~~~~~~~~~
- Automatic channel detection: each function inspects the DataFrame's columns
  and selects the best available source without caller configuration.
- Non-destructive: returns a new DataFrame; the input is never mutated.
- Noise control: numerical derivatives are optionally smoothed with a
  Gaussian-weighted rolling window before differentiation.
- Physical plausibility: results are clipped to realistic motorsport limits
  to prevent NaN/Inf pollution from propagating downstream.
- No print statements; structured logging only.
- Zero side effects at import time.
"""

from __future__ import annotations

import logging
from typing import Final

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# -- -

# Physical constants

# -- -


_G_TO_MPS2: Final[float] = 9.80665   # 1 g in m/s^2

# -- -

# Clip limits (remove physically impossible values caused by GPS artefacts)

# -- -


_MAX_LONG_ACCEL_MPS2: Final[float] = 50.0    # +/-5 g ~= extreme braking/accel
_MAX_LAT_ACCEL_MPS2:  Final[float] = 50.0    # +/-5 g
_MAX_YAW_RATE_DPS:    Final[float] = 1000.0  # deg/s -- covers full-lock spins

# -- -

# Column-name constants (raw RaceChrono + internal)

# -- -


# Raw RaceChrono names

_RAW_LONG_G:   Final[str] = "Longitudinal acceleration (G) *calc"
_RAW_LAT_G:    Final[str] = "Lateral acceleration (G) *calc"
_RAW_YAW_DPS:  Final[str] = "Yaw rate (deg/s)"
_RAW_SPEED:    Final[str] = "Speed (m/s)"
_RAW_BEARING:  Final[str] = "Bearing (deg)"
_RAW_X:        Final[str] = "X (m)"
_RAW_Y:        Final[str] = "Y (m)"
_RAW_TIME:     Final[str] = "Time (s)"

# Altitude column candidates (RaceChrono varies between versions)

_RAW_ALT_CANDIDATES: Final[tuple[str, ...]] = (
    "Altitude (m)",
    "altitude_m",
    "GPS Altitude (m)",
    "GPS altitude (m)",
    "Altitude",
)

_RAW_DIST: Final[str] = "Distance (m)"

# Internal standardised output names

OUT_LONG:       Final[str] = "accel_long_mps2"
OUT_LAT:        Final[str] = "accel_lat_mps2"
OUT_YAW:        Final[str] = "yaw_rate_dps"
OUT_COMBINED_G: Final[str] = "combined_g"
OUT_DIST:       Final[str] = "Distance (m)"
OUT_GRADE_PCT:  Final[str] = "grade_pct"
OUT_BANK_DEG:   Final[str] = "bank_angle_deg"

# Limits for new channels

_MAX_GRADE_PCT:     Final[float] = 30.0    # +/-30% grade ~= +/-17 deg
_MAX_BANK_ANGLE_DEG: Final[float] = 15.0   # +/-15 deg banking
_MIN_SPEED_MPS:     Final[float] = 1.0     # curvature unreliable below this
_MIN_CURVATURE:     Final[float] = 0.005   # 1/m -- only estimate banking in corners


# -- -

# Exceptions

# -- -


class DerivedChannelError(RuntimeError):
    """Raised when no valid source is available to compute a channel."""


# -- -

# Internal numerical helpers

# -- -


def _has(df: pd.DataFrame, col: str) -> bool:
    """Return True if *col* exists and has at least one non-NaN value."""
    return col in df.columns and df[col].notna().any()


def _safe_dt(df: pd.DataFrame) -> pd.Series:
    """
    Return a Series of time deltas (Deltat in seconds) aligned with df.index.

    Uses ``_RAW_TIME`` if present, otherwise falls back to a uniform 1-sample
    spacing.  Zeros in Deltat are replaced with NaN to avoid division-by-zero.
    """
    if _has(df, _RAW_TIME):
        dt = df[_RAW_TIME].diff()
    else:
        dt = pd.Series(np.ones(len(df)), index=df.index)
        logger.debug("'%s' not found; assuming uniform 1 s sample spacing for dt.", _RAW_TIME)

    dt = dt.where(dt > 0, np.nan)   # reject zero and negative deltas
    return dt


def _smooth(series: pd.Series, window: int) -> pd.Series:
    """
    Apply a Gaussian-weighted rolling average to *series*.

    A window of 1 (or less) is a no-op so callers can pass
    ``smoothing_window=1`` to disable smoothing without branching.

    Parameters
    ----------
    series:
        Numeric Series to smooth.
    window:
        Half-window size in samples.  The full Gaussian kernel spans
        ``2 * window + 1`` samples, centred on each point.
    """
    if window <= 1:
        return series
    kernel_size = 2 * window + 1
    # Gaussian weights -- std = window / 2 gives ~95 % weight within the window

    x   = np.arange(kernel_size) - window
    w   = np.exp(-0.5 * (x / (window / 2)) ** 2)
    w  /= w.sum()
    # convolve via rolling; use 'reflect' padding to avoid edge NaN creep

    padded = pd.concat([
        series.iloc[:window][::-1],
        series,
        series.iloc[-window:][::-1],
    ])
    rolled = (
        padded
        .rolling(kernel_size, center=True, min_periods=1)
        .apply(lambda v: float(np.dot(v, w[:len(v)] / w[:len(v)].sum())), raw=True)
    )
    return rolled.iloc[window: window + len(series)].reset_index(drop=True)


def _wrap_delta_deg(delta: pd.Series) -> pd.Series:
    """
    Map angular deltas to the range (-180, +180] to handle the 0/360
    discontinuity in compass bearings.

    A car turning continuously clockwise from 350 deg -> 10 deg produces a raw
    delta of -340 deg; the wrapped value is +20 deg, correctly representing a
    20 deg rightward turn.
    """
    return ((delta + 180.0) % 360.0) - 180.0


# -- -

# Public API

# -- -


def compute_longitudinal_accel(
    df: pd.DataFrame,
    *,
    smoothing_window: int = 3,
    correct_for_slope: bool = False,
) -> pd.DataFrame:
    """
    Add ``accel_long_mps2`` (longitudinal acceleration, m/s^2) to *df*.

    Source selection
    ~~~~~~~~~~~~~~~~
    1. If ``"Longitudinal acceleration (G) *calc"`` is present and non-empty,
       multiply by *g* (9.80665 m/s^2).
    2. Otherwise differentiate ``"Speed (m/s)"`` with respect to
       ``"Time (s)"``.  Speed is smoothed before differentiation to reduce
       noise amplification.

    Parameters
    ----------
    df:
        Input telemetry DataFrame (must contain at least one valid source).
    smoothing_window:
        Half-width (samples) of the Gaussian pre-smoothing kernel applied to
        speed before differentiation.  Pass 1 to disable.  Default: 3.

    Returns
    -------
    pd.DataFrame
        Copy of *df* with ``accel_long_mps2`` column appended or overwritten.

    Raises
    ------
    DerivedChannelError
        If neither source column is available.
    """
    result = df.copy()

    if _has(df, OUT_LONG):
        logger.info("accel_long: internal channel '%s' already present; skipping.", OUT_LONG)
        return result

    if _has(df, _RAW_LONG_G):
        logger.info("accel_long: using raw sensor channel '%s'.", _RAW_LONG_G)
        accel = pd.to_numeric(df[_RAW_LONG_G], errors="coerce") * _G_TO_MPS2

    elif _has(df, _RAW_SPEED):
        logger.info(
            "accel_long: '%s' absent -- computing dv/dt from '%s' "
            "(smoothing_window=%d).",
            _RAW_LONG_G, _RAW_SPEED, smoothing_window,
        )
        speed   = pd.to_numeric(df[_RAW_SPEED], errors="coerce").reset_index(drop=True)
        speed_s = _smooth(speed, smoothing_window)
        dt      = _safe_dt(result).reset_index(drop=True)
        accel   = speed_s.diff() / dt

    else:
        raise DerivedChannelError(
            f"Cannot compute '{OUT_LONG}': neither '{_RAW_LONG_G}' "
            f"nor '{_RAW_SPEED}' found in DataFrame."
        )

    # --- Optional slope correction -
    if correct_for_slope and _has(df, _RAW_LONG_G):
        grade = compute_elevation_profile(df, smoothing_window=15)
        finite_grade = grade.notna() & (grade.abs() > 0.01)
        if finite_grade.any():
            grade_rad = np.arctan(grade.values / 100.0)
            gravity_component = _G_TO_MPS2 * np.sin(grade_rad)
            accel = accel - gravity_component
            logger.info(
                "accel_long: slope correction applied (max grade=%.1f%%, "
                "max gravity component=%.2f m/s^2).",
                float(grade.abs().max()),
                float(np.nanmax(np.abs(gravity_component))),
            )

    result[OUT_LONG] = (
        accel
        .clip(-_MAX_LONG_ACCEL_MPS2, _MAX_LONG_ACCEL_MPS2)
        .values
    )
    logger.debug(
        "accel_long_mps2: min=%.3f  max=%.3f  NaN=%d",
        result[OUT_LONG].min(), result[OUT_LONG].max(), result[OUT_LONG].isna().sum(),
    )
    return result


def compute_lateral_accel_from_xy(
    df: pd.DataFrame,
    *,
    smoothing_window: int = 3,
) -> pd.DataFrame:
    """
    Add ``accel_lat_mps2`` (lateral acceleration, m/s^2) to *df*.

    Source selection
    ~~~~~~~~~~~~~~~~
    1. If ``"Lateral acceleration (G) *calc"`` is present and non-empty,
       multiply by *g*.
    2. Otherwise derive from XY position:

       Lateral acceleration = centripetal = v^2 x kappa  where curvature
       kappa = ( Y -  ) / (^2 + ^2)^(3/2) is computed from smoothed
       positional derivatives.

    Sign convention: positive = rightward (as seen from driver's seat),
    matching RaceChrono's own convention.

    Parameters
    ----------
    df:
        Input telemetry DataFrame.
    smoothing_window:
        Gaussian pre-smoothing half-window applied to X/Y before
        differentiation.  Pass 1 to disable.

    Returns
    -------
    pd.DataFrame
        Copy of *df* with ``accel_lat_mps2`` appended or overwritten.

    Raises
    ------
    DerivedChannelError
        If neither source is available.
    """
    result = df.copy()

    if _has(df, OUT_LAT):
        logger.info("accel_lat: internal channel '%s' already present; skipping.", OUT_LAT)
        return result

    if _has(df, _RAW_LAT_G):
        logger.info("accel_lat: using raw sensor channel '%s'.", _RAW_LAT_G)
        accel = pd.to_numeric(df[_RAW_LAT_G], errors="coerce") * _G_TO_MPS2

    elif _has(df, _RAW_X) and _has(df, _RAW_Y):
        logger.info(
            "accel_lat: '%s' absent -- computing curvature from X/Y "
            "(smoothing_window=%d).",
            _RAW_LAT_G, smoothing_window,
        )
        dt = _safe_dt(result).reset_index(drop=True)

        x = _smooth(
            pd.to_numeric(df[_RAW_X], errors="coerce").reset_index(drop=True),
            smoothing_window,
        )
        y = _smooth(
            pd.to_numeric(df[_RAW_Y], errors="coerce").reset_index(drop=True),
            smoothing_window,
        )

        # First derivatives (velocity components)

        xd = x.diff() / dt
        yd = y.diff() / dt

        # Second derivatives (acceleration components)

        xdd = xd.diff() / dt
        ydd = yd.diff() / dt

        # Signed curvature kappa = (x_doty - x_ddot) / (x_dot^2 + ^2)^(3/2)

        denom = (xd**2 + yd**2) ** 1.5
        denom = denom.where(denom > 1e-6, other=np.nan)   # stationary point guard
        kappa = (xd * ydd - yd * xdd) / denom

        # Speed derived from the same smoothed XY to stay consistent with kappa
        speed = np.sqrt(xd**2 + yd**2)

        accel = kappa * speed**2

    else:
        raise DerivedChannelError(
            f"Cannot compute '{OUT_LAT}': neither '{_RAW_LAT_G}' "
            f"nor ('{_RAW_X}' + '{_RAW_Y}') found in DataFrame."
        )

    result[OUT_LAT] = (
        accel
        .clip(-_MAX_LAT_ACCEL_MPS2, _MAX_LAT_ACCEL_MPS2)
        .values
    )
    logger.debug(
        "accel_lat_mps2: min=%.3f  max=%.3f  NaN=%d",
        result[OUT_LAT].min(), result[OUT_LAT].max(), result[OUT_LAT].isna().sum(),
    )
    return result


def compute_yaw_rate_from_heading(
    df: pd.DataFrame,
    *,
    smoothing_window: int = 3,
) -> pd.DataFrame:
    """
    Add ``yaw_rate_dps`` (yaw rate in degrees per second) to *df*.

    Source selection
    ~~~~~~~~~~~~~~~~
    1. If ``"Yaw rate (deg/s)"`` is present and non-empty, copy it directly.
    2. Otherwise differentiate ``"Bearing (deg)"`` with respect to time,
       handling the 0 deg/360 deg wrap with :func:`_wrap_delta_deg`.

    Parameters
    ----------
    df:
        Input telemetry DataFrame.
    smoothing_window:
        Gaussian pre-smoothing half-window applied to bearing before
        differentiation.  Pass 1 to disable.

    Returns
    -------
    pd.DataFrame
        Copy of *df* with ``yaw_rate_dps`` appended or overwritten.

    Raises
    ------
    DerivedChannelError
        If neither source is available.
    """
    result = df.copy()

    if _has(df, OUT_YAW):
        logger.info("yaw_rate: internal channel '%s' already present; skipping.", OUT_YAW)
        return result

    if _has(df, _RAW_YAW_DPS):
        logger.info("yaw_rate: using raw sensor channel '%s'.", _RAW_YAW_DPS)
        yaw = pd.to_numeric(df[_RAW_YAW_DPS], errors="coerce")

    elif _has(df, _RAW_BEARING):
        logger.info(
            "yaw_rate: '%s' absent -- computing d(bearing)/dt from '%s' "
            "(smoothing_window=%d).",
            _RAW_YAW_DPS, _RAW_BEARING, smoothing_window,
        )
        bearing = pd.to_numeric(df[_RAW_BEARING], errors="coerce").reset_index(drop=True)
        dt      = _safe_dt(result).reset_index(drop=True)

        # Compute raw deltas and wrap to [-180, 180] BEFORE smoothing
        # to avoid the 0/360 boundary corruption that Gaussian smoothing
        # would introduce on raw circular bearing values.
        raw_delta = _wrap_delta_deg(bearing.diff())
        smoothed_delta = _smooth(raw_delta, smoothing_window)
        yaw       = smoothed_delta / dt

        # Speed gate: stationary GPS produces random bearing jumps -> garbage yaw
        if _has(df, _RAW_SPEED):
            speed = pd.to_numeric(df[_RAW_SPEED], errors="coerce").reset_index(drop=True)
            yaw = yaw.where(speed >= _MIN_SPEED_MPS, 0.0)

    else:
        raise DerivedChannelError(
            f"Cannot compute '{OUT_YAW}': neither '{_RAW_YAW_DPS}' "
            f"nor '{_RAW_BEARING}' found in DataFrame."
        )

    result[OUT_YAW] = (
        yaw
        .clip(-_MAX_YAW_RATE_DPS, _MAX_YAW_RATE_DPS)
        .values
    )
    logger.debug(
        "yaw_rate_dps: min=%.3f  max=%.3f  NaN=%d",
        result[OUT_YAW].min(), result[OUT_YAW].max(), result[OUT_YAW].isna().sum(),
    )
    return result


def compute_combined_g(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add ``combined_g`` (total G-force magnitude) to *df*.

    Computes ``sqrt(lat_g^2 + long_g^2)`` where ``lat_g`` and ``long_g``
    are obtained from the raw lateral / longitudinal G sensor columns,
    converted to G units.  If the raw G columns are absent but the
    internal m/s^2 channels exist, those are converted back to G.

    Parameters
    ----------
    df:
        Input telemetry DataFrame.  Must contain at least one pair of
        lateral + longitudinal acceleration columns.

    Returns
    -------
    pd.DataFrame
        Copy of *df* with ``combined_g`` column appended or overwritten.

    Raises
    ------
    DerivedChannelError
        If neither lateral nor longitudinal acceleration data is available.
    """
    result = df.copy()

    # --- Lateral G ---
    if _has(df, _RAW_LAT_G):
        lat_g = pd.to_numeric(df[_RAW_LAT_G], errors="coerce")
    elif _has(df, OUT_LAT):
        lat_g = pd.to_numeric(df[OUT_LAT], errors="coerce") / _G_TO_MPS2
    else:
        raise DerivedChannelError(
            f"Cannot compute '{OUT_COMBINED_G}': no lateral acceleration "
            f"column ('{_RAW_LAT_G}' or '{OUT_LAT}') found."
        )

    # --- Longitudinal G ---
    if _has(df, _RAW_LONG_G):
        long_g = pd.to_numeric(df[_RAW_LONG_G], errors="coerce")
    elif _has(df, OUT_LONG):
        long_g = pd.to_numeric(df[OUT_LONG], errors="coerce") / _G_TO_MPS2
    else:
        raise DerivedChannelError(
            f"Cannot compute '{OUT_COMBINED_G}': no longitudinal acceleration "
            f"column ('{_RAW_LONG_G}' or '{OUT_LONG}') found."
        )

    combined = np.sqrt(lat_g**2 + long_g**2)
    result[OUT_COMBINED_G] = combined.values

    logger.debug(
        "combined_g: min=%.3f  max=%.3f  NaN=%d",
        result[OUT_COMBINED_G].min(),
        result[OUT_COMBINED_G].max(),
        result[OUT_COMBINED_G].isna().sum(),
    )
    return result


def compute_distance(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add ``Distance (m)`` to *df* when it does not already exist.

    Synthesises the distance channel from ``cumsum(speed * dt)`` using
    ``"Speed (m/s)"`` and ``"Time (s)"``.  If the column already exists
    in *df*, the DataFrame is returned unchanged (as a copy).

    Parameters
    ----------
    df:
        Input telemetry DataFrame.

    Returns
    -------
    pd.DataFrame
        Copy of *df* with ``Distance (m)`` column present.

    Raises
    ------
    DerivedChannelError
        If the column is absent and neither speed nor time data is
        available to synthesise it.
    """
    result = df.copy()

    if _has(result, OUT_DIST):
        logger.debug("compute_distance: '%s' already exists; skipping.", OUT_DIST)
        return result

    if not _has(df, _RAW_SPEED):
        raise DerivedChannelError(
            f"Cannot compute '{OUT_DIST}': '{_RAW_SPEED}' not found."
        )

    speed = pd.to_numeric(df[_RAW_SPEED], errors="coerce").reset_index(drop=True)
    dt = _safe_dt(result).reset_index(drop=True)

    increments = (speed * dt).fillna(0.0)
    dist = increments.cumsum()

    result[OUT_DIST] = dist.values

    logger.debug(
        "distance: total=%.1f m, NaN=%d",
        float(dist.iloc[-1]) if len(dist) > 0 else 0.0,
        result[OUT_DIST].isna().sum(),
    )
    return result


# -- -

# Internal helpers -- elevation / banking

# -- -


def _find_altitude_col(df: pd.DataFrame) -> str | None:
    """Return the first matching altitude column name, or None."""
    for candidate in _RAW_ALT_CANDIDATES:
        if _has(df, candidate):
            return candidate
    return None


def _gaussian_smooth_arr(signal: np.ndarray, half_window: int) -> np.ndarray:
    """
    Gaussian-weighted 1-D smoothing on a numpy array.

    NaN values are ignored (filled by interpolation before smoothing, then
    re-masked).  Returns array of same length.
    """
    if half_window <= 1 or len(signal) < 3:
        return signal.copy()

    # Interpolate over NaN gaps for smooth convolution

    finite = np.isfinite(signal)
    if finite.sum() < 2:
        return signal.copy()

    working = signal.copy()
    if not finite.all():
        working[~finite] = np.interp(
            np.where(~finite)[0], np.where(finite)[0], signal[finite],
        )

    k = 2 * half_window + 1
    x = np.arange(k) - half_window
    w = np.exp(-0.5 * (x / max(half_window / 2.0, 0.5)) ** 2)
    w /= w.sum()

    padded = np.pad(working, half_window, mode="reflect")
    out = np.convolve(padded, w, mode="valid")[: len(signal)]

    # Re-mask original NaN positions
    out[~finite] = np.nan

    return out


# -- -

# Public API -- Elevation profile

# -- -


def compute_elevation_profile(
    df: pd.DataFrame,
    *,
    smoothing_window: int = 15,
) -> pd.Series:
    """
    Compute road gradient (grade) from altitude data.

    If an altitude column is present, it is heavily smoothed (GPS altitude
    is noisy) and then differentiated with respect to distance to yield the
    gradient as a percentage: ``grade_pct = 100 x dz / ds``.

    If no altitude data is found, a flat-track assumption is applied
    (all-zeros) with a log warning.

    Parameters
    ----------
    df:
        Input telemetry DataFrame.  Should contain a distance column
        (``"Distance (m)"``) and optionally an altitude column.
    smoothing_window:
        Gaussian half-window (samples) for altitude smoothing.  GPS altitude
        noise is typically +/-5--20 m; a large window (15--25) is needed.

    Returns
    -------
    pd.Series
        Gradient in percent (``grade_pct``), aligned with *df*'s index.
        Positive = uphill, negative = downhill.
    """
    alt_col = _find_altitude_col(df)

    if alt_col is None:
        logger.warning(
            "No altitude column found (tried %s); assuming flat track "
            "(grade_pct = 0).",
            [c for c in _RAW_ALT_CANDIDATES],
        )
        return pd.Series(np.zeros(len(df)), index=df.index, name=OUT_GRADE_PCT)

    logger.info("elevation: using column '%s'.", alt_col)
    alt = pd.to_numeric(df[alt_col], errors="coerce").values.astype(float)

    # Heavy smoothing to suppress GPS altitude noise

    alt_smooth = _gaussian_smooth_arr(alt, smoothing_window)

    # Compute gradient dz/ds

    if _has(df, _RAW_DIST):
        dist = pd.to_numeric(df[_RAW_DIST], errors="coerce").values.astype(float)
    elif _has(df, _RAW_TIME) and _has(df, _RAW_SPEED):
        # Reconstruct distance from speed x dt

        speed = pd.to_numeric(df[_RAW_SPEED], errors="coerce").values
        dt = np.diff(pd.to_numeric(df[_RAW_TIME], errors="coerce").values)
        dist = np.concatenate([[0.0], np.cumsum(speed[:-1] * dt)])
        logger.debug("elevation: distance reconstructed from speed x dt.")
    else:
        logger.warning(
            "No distance column found; cannot compute gradient. "
            "Returning zeros."
        )
        return pd.Series(np.zeros(len(df)), index=df.index, name=OUT_GRADE_PCT)

    ds = np.diff(dist)
    ds = np.where((ds > 0) & np.isfinite(ds), ds, np.nan)
    dz = np.diff(alt_smooth)

    with np.errstate(divide="ignore", invalid="ignore"):
        grade_frac = np.where(np.isfinite(ds) & (ds > 0), dz / ds, 0.0)

    grade_pct = np.concatenate([[grade_frac[0] if len(grade_frac) > 0 else 0.0],
                                 grade_frac]) * 100.0

    # Clip to physical limits

    grade_pct = np.clip(grade_pct, -_MAX_GRADE_PCT, _MAX_GRADE_PCT)

    # Light smoothing on the gradient itself to remove differentiation noise

    if len(grade_pct) >= 5:
        grade_pct = _gaussian_smooth_arr(grade_pct, min(smoothing_window // 2, 5))

    result = pd.Series(grade_pct, index=df.index, name=OUT_GRADE_PCT)

    logger.info(
        "elevation: grade_pct range [%.1f%%, %.1f%%], mean=%.2f%%",
        float(np.nanmin(grade_pct)), float(np.nanmax(grade_pct)),
        float(np.nanmean(grade_pct)),
    )
    return result


# -- -

# Public API -- Bank angle estimate

# -- -


def compute_bank_angle_estimate(
    df: pd.DataFrame,
    *,
    smoothing_window: int = 5,
) -> pd.Series:
    """
    Estimate track banking angle from the residual between measured lateral
    acceleration and expected centripetal acceleration.

    On a banked corner the lateral accelerometer reads:

        a_lat_measured = v^2 * kappa - g * sin(theta_bank)

    Rearranging:

        theta_bank ~= arcsin((v^2 * kappa - a_lat_measured) / g)

    The estimate is only meaningful in corners where curvature is above a
    threshold; on straights the result is NaN.

    Parameters
    ----------
    df:
        Input telemetry DataFrame.  Must contain ``"Speed (m/s)"``.
        Lateral acceleration must be available (``accel_lat_mps2`` or
        raw sensor).  Curvature is derived from yaw rate or XY position.
    smoothing_window:
        Half-window for smoothing the bank angle estimate.

    Returns
    -------
    pd.Series
        Bank angle in degrees, aligned with *df*'s index.
        Positive = banked towards centre (left turn banked left).
        NaN on straights (curvature < threshold).
    """
    n = len(df)

    # --- Speed -
    if not _has(df, _RAW_SPEED):
        logger.warning("bank_angle: no speed data; returning NaN.")
        return pd.Series(np.full(n, np.nan), index=df.index, name=OUT_BANK_DEG)

    speed = pd.to_numeric(df[_RAW_SPEED], errors="coerce").values.astype(float)

    # --- Lateral accel (measured) -
    if _has(df, OUT_LAT):
        a_lat_meas = pd.to_numeric(df[OUT_LAT], errors="coerce").values.astype(float)
    elif _has(df, _RAW_LAT_G):
        a_lat_meas = pd.to_numeric(df[_RAW_LAT_G], errors="coerce").values * _G_TO_MPS2
    else:
        logger.warning("bank_angle: no lateral accel data; returning NaN.")
        return pd.Series(np.full(n, np.nan), index=df.index, name=OUT_BANK_DEG)

    # --- Curvature kappa [1/m] -
    curvature = _compute_curvature_for_banking(df, speed)
    if curvature is None:
        logger.warning("bank_angle: cannot compute curvature; returning NaN.")
        return pd.Series(np.full(n, np.nan), index=df.index, name=OUT_BANK_DEG)

    # --- Compute bank angle -
    # Expected centripetal accel (unsigned): v^2 * kappa

    a_centripetal = speed ** 2 * np.abs(curvature)

    # Residual: what the accelerometer "should" read minus what it reads

    # On a banked track: a_lat_meas ~= a_centripetal - g*sin(bank)

    # So: g*sin(bank) ~= a_centripetal - |a_lat_meas|

    residual = a_centripetal - np.abs(a_lat_meas)

    with np.errstate(divide="ignore", invalid="ignore"):
        sin_bank = np.clip(residual / _G_TO_MPS2, -1.0, 1.0)
        bank_rad = np.arcsin(sin_bank)

    bank_deg = np.degrees(bank_rad)

    # Mask straights (curvature below threshold) -- banking meaningless there

    straight_mask = np.abs(curvature) < _MIN_CURVATURE
    bank_deg[straight_mask] = np.nan

    # Mask low speed (curvature/accel unreliable)

    bank_deg[speed < _MIN_SPEED_MPS] = np.nan

    # Clip to physical range

    bank_deg = np.clip(bank_deg, -_MAX_BANK_ANGLE_DEG, _MAX_BANK_ANGLE_DEG)

    # Smooth to reduce noise

    finite = np.isfinite(bank_deg)
    if finite.sum() >= 5 and smoothing_window > 1:
        # Smooth only the finite sections

        bank_deg_smooth = bank_deg.copy()
        bank_deg_smooth[finite] = _gaussian_smooth_arr(
            bank_deg[finite], smoothing_window,
        )
        bank_deg = bank_deg_smooth

    result = pd.Series(bank_deg, index=df.index, name=OUT_BANK_DEG)

    finite_vals = bank_deg[np.isfinite(bank_deg)]
    if len(finite_vals) > 0:
        logger.info(
            "bank_angle: range [%.1f deg, %.1f deg], mean=%.2f deg, "
            "%d/%d points estimated (%.0f%% in corners).",
            float(np.min(finite_vals)), float(np.max(finite_vals)),
            float(np.mean(finite_vals)),
            len(finite_vals), n,
            len(finite_vals) / max(n, 1) * 100,
        )
    else:
        logger.info("bank_angle: no corner sections found; all NaN.")

    return result


def _compute_curvature_for_banking(
    df: pd.DataFrame,
    speed: np.ndarray,
) -> np.ndarray | None:
    """
    Compute curvature [1/m] for bank angle estimation.

    Priority: yaw_rate / speed > XY position.
    Returns None if no suitable source is available.
    """
    n = len(df)
    _COL_YAW_INT = "yaw_rate_dps"      # internal standardised
    _COL_YAW_RAW = "Yaw rate (deg/s)"  # raw RaceChrono

    # Source 1: yaw rate (internal or raw) + speed

    yaw_col = None
    if _has(df, _COL_YAW_INT):
        yaw_col = _COL_YAW_INT
    elif _has(df, _COL_YAW_RAW):
        yaw_col = _COL_YAW_RAW

    if yaw_col is not None:
        yaw_dps = pd.to_numeric(df[yaw_col], errors="coerce").values.astype(float)
        yaw_rps = np.radians(yaw_dps)
        with np.errstate(divide="ignore", invalid="ignore"):
            curvature = np.where(
                speed >= _MIN_SPEED_MPS,
                yaw_rps / speed,
                0.0,
            )
        return curvature

    # Source 2: XY position

    if _has(df, _RAW_X) and _has(df, _RAW_Y):
        x = pd.to_numeric(df[_RAW_X], errors="coerce").values.astype(float)
        y = pd.to_numeric(df[_RAW_Y], errors="coerce").values.astype(float)
        if _has(df, _RAW_DIST):
            dist = pd.to_numeric(df[_RAW_DIST], errors="coerce").values.astype(float)
        else:
            dist = np.arange(n, dtype=float)

        ds = np.diff(dist)
        ds = np.where(ds > 0, ds, np.nan)
        dx = np.diff(x); dy = np.diff(y)
        with np.errstate(divide="ignore", invalid="ignore"):
            xd = dx / ds; yd = dy / ds
            xd_mid = 0.5 * (xd[:-1] + xd[1:])
            yd_mid = 0.5 * (yd[:-1] + yd[1:])
            ds_mid = 0.5 * (ds[:-1] + ds[1:])
            xdd = np.diff(xd) / ds_mid
            ydd = np.diff(yd) / ds_mid
            denom = (xd_mid ** 2 + yd_mid ** 2) ** 1.5
            kappa = np.where(
                denom > 0, (xd_mid * ydd - yd_mid * xdd) / denom, 0.0,
            )
        # Pad to original length

        curvature = np.zeros(n)
        if len(kappa) > 0:
            curvature[1:-1] = kappa
            curvature[0] = kappa[0] if len(kappa) > 0 else 0.0
            curvature[-1] = kappa[-1] if len(kappa) > 0 else 0.0
        return curvature

    return None


# -- -

# Unit tests

# -- -


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
        except Exception:   # noqa: BLE001
            failed.append((name, traceback.format_exc()))

    N = 50
    t = np.linspace(0.0, 5.0, N)
    dt_val = t[1] - t[0]

    # -- -

    # Test 1 -- longitudinal accel from raw G sensor

    # -- -

    def t_long_from_g() -> None:
        g_values = np.full(N, 0.5)   # 0.5 g constant
        df = pd.DataFrame({
            _RAW_TIME: t,
            _RAW_LONG_G: g_values,
        })
        out = compute_longitudinal_accel(df, smoothing_window=1)
        assert OUT_LONG in out.columns
        expected = 0.5 * _G_TO_MPS2
        np.testing.assert_allclose(
            out[OUT_LONG].dropna().values, expected, rtol=1e-6,
            err_msg="G conversion incorrect"
        )

    _test("long_accel_from_g", t_long_from_g)

    # -- -

    # Test 2 -- longitudinal accel via dv/dt when G channel absent

    # -- -

    def t_long_from_speed() -> None:
        # Constant acceleration: v = a*t -> dv/dt = a

        a_true = 5.0
        speed  = a_true * t
        df = pd.DataFrame({_RAW_TIME: t, _RAW_SPEED: speed})
        out = compute_longitudinal_accel(df, smoothing_window=1)
        # First sample is NaN (diff), compare interior

        interior = out[OUT_LONG].iloc[2:-2].dropna()
        np.testing.assert_allclose(
            interior.values, a_true, atol=0.2,
            err_msg="dv/dt accel should be ~5 m/s^2"
        )

    _test("long_accel_from_speed", t_long_from_speed)

    # -- -

    # Test 3 -- smoothing reduces noise in dv/dt

    # -- -

    def t_long_smoothing_reduces_noise() -> None:
        rng   = np.random.default_rng(42)
        a_true = 3.0
        noise  = rng.normal(0, 2.0, N)
        speed  = a_true * t + noise
        df = pd.DataFrame({_RAW_TIME: t, _RAW_SPEED: speed})

        out_raw    = compute_longitudinal_accel(df, smoothing_window=1)
        out_smooth = compute_longitudinal_accel(df, smoothing_window=5)

        std_raw    = out_raw[OUT_LONG].std()
        std_smooth = out_smooth[OUT_LONG].std()
        assert std_smooth < std_raw, (
            f"Smoothing should reduce std: raw={std_raw:.3f}, smooth={std_smooth:.3f}"
        )

    _test("long_smoothing_reduces_noise", t_long_smoothing_reduces_noise)

    # -- -

    # Test 4 -- longitudinal accel: DerivedChannelError when no source

    # -- -

    def t_long_no_source() -> None:
        df = pd.DataFrame({"irrelevant": [1, 2, 3]})
        try:
            compute_longitudinal_accel(df)
            raise AssertionError("Should have raised DerivedChannelError")
        except DerivedChannelError:
            pass

    _test("long_no_source_raises", t_long_no_source)

    # -- -

    # Test 5 -- lateral accel from raw G sensor

    # -- -

    def t_lat_from_g() -> None:
        g_values = np.full(N, -0.8)   # 0.8 g left
        df = pd.DataFrame({_RAW_TIME: t, _RAW_LAT_G: g_values})
        out = compute_lateral_accel_from_xy(df, smoothing_window=1)
        assert OUT_LAT in out.columns
        expected = -0.8 * _G_TO_MPS2
        np.testing.assert_allclose(
            out[OUT_LAT].dropna().values, expected, rtol=1e-6,
        )

    _test("lat_accel_from_g", t_lat_from_g)

    # -- -

    # Test 6 -- lateral accel from circular X/Y motion

    # -- -

    def t_lat_from_xy() -> None:
        # Uniform circular motion: radius R, angular velocity omega

        R      = 50.0    # metres
        omega  = 0.4     # rad/s
        x      = R * np.cos(omega * t)
        y      = R * np.sin(omega * t)
        v      = R * omega   # constant speed (m/s)
        # Expected centripetal acceleration = v^2/R

        a_expected = v**2 / R

        df = pd.DataFrame({
            _RAW_TIME: t, _RAW_X: x, _RAW_Y: y, _RAW_SPEED: np.full(N, v),
        })
        out = compute_lateral_accel_from_xy(df, smoothing_window=3)
        # Exclude first/last few samples affected by edge effects

        interior = out[OUT_LAT].iloc[5:-5].dropna()
        np.testing.assert_allclose(
            np.abs(interior.values), a_expected, rtol=0.15,
            err_msg=f"Centripetal accel expected ~= {a_expected:.2f} m/s^2"
        )

    _test("lat_accel_from_xy_circle", t_lat_from_xy)

    # -- -

    # Test 7 -- lateral accel: DerivedChannelError when no source

    # -- -

    def t_lat_no_source() -> None:
        df = pd.DataFrame({"irrelevant": [1, 2, 3]})
        try:
            compute_lateral_accel_from_xy(df)
            raise AssertionError("Should have raised DerivedChannelError")
        except DerivedChannelError:
            pass

    _test("lat_no_source_raises", t_lat_no_source)

    # -- -

    # Test 8 -- yaw rate from raw sensor

    # -- -

    def t_yaw_from_sensor() -> None:
        yaw_values = np.full(N, 45.0)
        df = pd.DataFrame({_RAW_TIME: t, _RAW_YAW_DPS: yaw_values})
        out = compute_yaw_rate_from_heading(df)
        assert OUT_YAW in out.columns
        np.testing.assert_allclose(
            out[OUT_YAW].dropna().values, 45.0, rtol=1e-6,
        )

    _test("yaw_from_sensor", t_yaw_from_sensor)

    # -- -

    # Test 9 -- yaw rate from bearing (no wrap crossing)

    # -- -

    def t_yaw_from_bearing_no_wrap() -> None:
        # Linear bearing: 0 deg -> 90 deg over 5 s -> 18 deg/s

        bearing = np.linspace(0.0, 90.0, N)
        df = pd.DataFrame({_RAW_TIME: t, _RAW_BEARING: bearing})
        out = compute_yaw_rate_from_heading(df, smoothing_window=1)
        interior = out[OUT_YAW].iloc[2:-2].dropna()
        # Rate = 90 / 5 = 18 deg/s

        np.testing.assert_allclose(
            interior.values, 18.0, atol=1.0,
            err_msg="Yaw rate from monotone bearing should be ~18 deg/s"
        )

    _test("yaw_from_bearing_no_wrap", t_yaw_from_bearing_no_wrap)

    # -- -

    # Test 10 -- yaw rate: 0/360 wrap handled correctly

    # -- -

    def t_yaw_wrap_handling() -> None:
        # Bearing crosses 360 deg -> 0 deg -> should give a small positive rate

        N_w = 10
        t_w = np.arange(N_w, dtype=float)
        bearing = np.array([355.0, 357.0, 359.0, 1.0, 3.0, 5.0, 7.0, 9.0, 11.0, 13.0])
        df = pd.DataFrame({_RAW_TIME: t_w, _RAW_BEARING: bearing})
        out = compute_yaw_rate_from_heading(df, smoothing_window=1)
        interior = out[OUT_YAW].iloc[2:-2].dropna()
        # Rate ~= +2 deg / 1 s = +2 deg/s; must be positive (right turn), never ~-358

        assert (interior > 0).all(), (
            f"Wrap not handled: got {interior.values}"
        )
        assert (interior < 10).all(), (
            f"Rate implausibly large: got {interior.values}"
        )

    _test("yaw_wrap_360_handled", t_yaw_wrap_handling)

    # -- -

    # Test 11 -- yaw rate: DerivedChannelError when no source

    # -- -

    def t_yaw_no_source() -> None:
        df = pd.DataFrame({"irrelevant": [1.0, 2.0]})
        try:
            compute_yaw_rate_from_heading(df)
            raise AssertionError("Should have raised DerivedChannelError")
        except DerivedChannelError:
            pass

    _test("yaw_no_source_raises", t_yaw_no_source)

    # -- -

    # Test 12 -- clip limits prevent Inf/extreme values

    # -- -

    def t_clip_limits() -> None:
        df = pd.DataFrame({
            _RAW_TIME:    np.linspace(0, 1, 5),
            _RAW_LONG_G:  [0.1, 0.2, 999.0, 0.2, 0.1],   # 999 g spike
            _RAW_LAT_G:   [0.0, 0.0, -888.0, 0.0, 0.0],
            _RAW_YAW_DPS: [0.0, 0.0, 5000.0, 0.0, 0.0],
        })
        out = compute_longitudinal_accel(df)
        out = compute_lateral_accel_from_xy(out)
        out = compute_yaw_rate_from_heading(out)

        assert out[OUT_LONG].abs().max() <= _MAX_LONG_ACCEL_MPS2, "Long accel not clipped"
        assert out[OUT_LAT].abs().max()  <= _MAX_LAT_ACCEL_MPS2,  "Lat accel not clipped"
        assert out[OUT_YAW].abs().max()  <= _MAX_YAW_RATE_DPS,    "Yaw rate not clipped"

    _test("clip_limits_applied", t_clip_limits)

    # -- -

    # Test 13 -- input DataFrame is not mutated

    # -- -

    def t_no_mutation() -> None:
        df = pd.DataFrame({
            _RAW_TIME:    t,
            _RAW_SPEED:   np.ones(N) * 20.0,
            _RAW_BEARING: np.linspace(0, 360, N),
        })
        cols_before = set(df.columns)
        _ = compute_longitudinal_accel(df)
        _ = compute_yaw_rate_from_heading(df)
        assert set(df.columns) == cols_before, "Input DataFrame was mutated"

    _test("no_input_mutation", t_no_mutation)

    # -- -

    # Test 14 -- G channel takes priority over speed channel

    # -- -

    def t_g_channel_priority() -> None:
        # G channel says 1 g; speed-based would give ~0 (constant speed)

        df = pd.DataFrame({
            _RAW_TIME:    t,
            _RAW_LONG_G:  np.full(N, 1.0),
            _RAW_SPEED:   np.full(N, 30.0),   # constant -> dv/dt ~= 0
        })
        out = compute_longitudinal_accel(df, smoothing_window=1)
        np.testing.assert_allclose(
            out[OUT_LONG].dropna().values, _G_TO_MPS2, rtol=1e-6,
            err_msg="G channel should take priority over speed"
        )

    _test("g_channel_priority", t_g_channel_priority)

    # -- -

    # Test 15 -- elevation profile from altitude column

    # -- -

    def t_elevation_from_altitude() -> None:
        N_e = 200
        dist = np.linspace(0, 1000, N_e)
        # Hill: altitude rises 50 m over 500 m then descends

        alt = 50.0 * np.sin(dist / 1000 * np.pi)
        df = pd.DataFrame({
            _RAW_DIST:  dist,
            _RAW_TIME:  np.linspace(0, 50, N_e),
            "Altitude (m)": alt,
        })
        grade = compute_elevation_profile(df, smoothing_window=5)
        assert grade.name == OUT_GRADE_PCT
        assert len(grade) == N_e
        # At the midpoint (dist=500), the sine is flat -> grade ~= 0

        mid = grade.iloc[N_e // 2]
        assert abs(mid) < 3.0, f"Grade at midpoint should be ~0, got {mid:.2f}%"
        # At the start, the gradient is steepest: dz/ds = 50pi/1000 ~= 15.7%

        # After smoothing it will be lower, but still positive

        early = grade.iloc[5:20].mean()
        assert early > 3.0, f"Early grade should be positive (uphill), got {early:.2f}%"

    _test("elevation_from_altitude", t_elevation_from_altitude)

    # -- -

    # Test 16 -- elevation profile: no altitude column -> zeros

    # -- -

    def t_elevation_no_altitude() -> None:
        df = pd.DataFrame({
            _RAW_DIST: np.linspace(0, 500, 100),
            _RAW_TIME: np.linspace(0, 25, 100),
        })
        grade = compute_elevation_profile(df)
        assert (grade == 0.0).all(), "No altitude -> should be all zeros"

    _test("elevation_no_altitude_zeros", t_elevation_no_altitude)

    # -- -

    # Test 17 -- elevation with different altitude column names

    # -- -

    def t_elevation_alt_column_names() -> None:
        for col_name in ("GPS Altitude (m)", "altitude_m"):
            df = pd.DataFrame({
                _RAW_DIST: np.linspace(0, 100, 50),
                _RAW_TIME: np.linspace(0, 5, 50),
                col_name:  np.linspace(100, 110, 50),  # 10m rise over 100m = 10%
            })
            grade = compute_elevation_profile(df, smoothing_window=3)
            mean_grade = grade.mean()
            assert 5.0 < mean_grade < 15.0, (
                f"Column '{col_name}': mean grade={mean_grade:.1f}%, expected ~10%"
            )

    _test("elevation_alt_column_names", t_elevation_alt_column_names)

    # -- -

    # Test 18 -- elevation profile: flat track -> zero grade

    # -- -

    def t_elevation_flat_track() -> None:
        df = pd.DataFrame({
            _RAW_DIST:      np.linspace(0, 500, 100),
            _RAW_TIME:      np.linspace(0, 25, 100),
            "Altitude (m)": np.full(100, 42.0),  # constant altitude
        })
        grade = compute_elevation_profile(df, smoothing_window=5)
        assert np.abs(grade).max() < 0.1, (
            f"Flat track grade should be ~0, got max={grade.abs().max():.3f}%"
        )

    _test("elevation_flat_track_zero", t_elevation_flat_track)

    # -- -

    # Test 19 -- bank angle: flat track -> NaN or ~0

    # -- -

    def t_bank_angle_flat_track() -> None:
        # Circular motion on a flat track: a_lat_measured = v^2/R exactly

        N_b = 200
        R = 50.0
        omega = 0.5  # rad/s
        t_b = np.linspace(0, 2 * np.pi / omega, N_b)
        speed_val = R * omega  # 25 m/s
        yaw_dps = np.degrees(omega) * np.ones(N_b)
        # Lateral accel = v^2/R (exactly centripetal -- no banking)

        a_lat = np.full(N_b, speed_val ** 2 / R)

        df = pd.DataFrame({
            _RAW_TIME:  t_b,
            _RAW_SPEED: np.full(N_b, speed_val),
            OUT_LAT:    a_lat,
            OUT_YAW:    yaw_dps,
        })
        bank = compute_bank_angle_estimate(df, smoothing_window=3)
        # On a flat track, residual is ~0 -> bank angle ~0

        finite = bank.dropna()
        if len(finite) > 0:
            assert finite.abs().mean() < 3.0, (
                f"Flat track bank should be ~0 deg, got mean={finite.mean():.2f} deg"
            )

    _test("bank_angle_flat_track", t_bank_angle_flat_track)

    # -- -

    # Test 20 -- bank angle: banked corner -> detects positive banking

    # -- -

    def t_bank_angle_banked_corner() -> None:
        N_b = 200
        R = 50.0
        omega = 0.5
        speed_val = R * omega  # 25 m/s
        bank_true_deg = 10.0
        yaw_dps = np.degrees(omega) * np.ones(N_b)

        # With banking, the accelerometer reads less than expected:

        # a_lat_meas = v^2/R - g*sin(bank)

        a_centripetal = speed_val ** 2 / R
        a_lat_meas = a_centripetal - _G_TO_MPS2 * np.sin(np.radians(bank_true_deg))

        df = pd.DataFrame({
            _RAW_TIME:  np.linspace(0, 10, N_b),
            _RAW_SPEED: np.full(N_b, speed_val),
            OUT_LAT:    np.full(N_b, a_lat_meas),
            OUT_YAW:    yaw_dps,
        })
        bank = compute_bank_angle_estimate(df, smoothing_window=3)
        finite = bank.dropna()
        assert len(finite) > 0, "Should have estimated banking in corner"
        mean_bank = float(finite.mean())
        assert abs(mean_bank - bank_true_deg) < 3.0, (
            f"Estimated bank={mean_bank:.1f} deg; expected ~={bank_true_deg} deg"
        )

    _test("bank_angle_banked_corner", t_bank_angle_banked_corner)

    # -- -

    # Test 21 -- bank angle: no speed -> NaN

    # -- -

    def t_bank_angle_no_speed() -> None:
        df = pd.DataFrame({"irrelevant": [1, 2, 3]})
        bank = compute_bank_angle_estimate(df)
        assert bank.isna().all()

    _test("bank_angle_no_speed_nan", t_bank_angle_no_speed)

    # -- -

    # Test 22 -- bank angle: straights return NaN

    # -- -

    def t_bank_angle_straights_nan() -> None:
        N_b = 100
        df = pd.DataFrame({
            _RAW_TIME:  np.linspace(0, 10, N_b),
            _RAW_SPEED: np.full(N_b, 30.0),
            OUT_LAT:    np.zeros(N_b),
            OUT_YAW:    np.zeros(N_b),  # no yaw -> straight line
        })
        bank = compute_bank_angle_estimate(df)
        assert bank.isna().all(), "Straights should be NaN"

    _test("bank_angle_straights_nan", t_bank_angle_straights_nan)

    # -- -

    # Test 23 -- slope correction: uphill reduces measured accel

    # -- -

    def t_slope_correction() -> None:
        N_s = 100
        grade_pct = 10.0  # 10% grade ~= 5.7 deg
        alt = np.linspace(0, 50, N_s)  # 50m rise over 500m = 10%
        dist = np.linspace(0, 500, N_s)
        a_true = 3.0  # m/s^2 true acceleration
        # Accelerometer reads: a_true + g*sin(atan(grade/100))

        grade_rad = np.arctan(grade_pct / 100.0)
        a_measured_g = (a_true + _G_TO_MPS2 * np.sin(grade_rad)) / _G_TO_MPS2

        df = pd.DataFrame({
            _RAW_TIME:     np.linspace(0, 25, N_s),
            _RAW_DIST:     dist,
            _RAW_LONG_G:   np.full(N_s, a_measured_g),
            "Altitude (m)": alt,
        })

        # Without correction: should read ~a_measured

        out_raw = compute_longitudinal_accel(df, smoothing_window=1, correct_for_slope=False)
        a_raw_mean = out_raw[OUT_LONG].dropna().mean()
        a_measured_mps2 = a_measured_g * _G_TO_MPS2
        np.testing.assert_allclose(
            a_raw_mean, a_measured_mps2, rtol=0.01,
            err_msg="Uncorrected accel should match raw G sensor"
        )

        # With correction: should be closer to a_true

        out_corr = compute_longitudinal_accel(df, smoothing_window=1, correct_for_slope=True)
        a_corr_mean = out_corr[OUT_LONG].dropna().iloc[5:-5].mean()
        # Allow some tolerance due to smoothing

        assert abs(a_corr_mean - a_true) < abs(a_raw_mean - a_true), (
            f"Corrected accel ({a_corr_mean:.2f}) should be closer to true "
            f"({a_true:.2f}) than raw ({a_raw_mean:.2f})"
        )

    _test("slope_correction", t_slope_correction)

    # -- -

    # Test 24 -- slope correction off by default (backward compat)

    # -- -

    def t_slope_correction_default_off() -> None:
        N_s = 50
        df = pd.DataFrame({
            _RAW_TIME:      np.linspace(0, 5, N_s),
            _RAW_DIST:      np.linspace(0, 250, N_s),
            _RAW_LONG_G:    np.full(N_s, 1.0),
            "Altitude (m)": np.linspace(0, 25, N_s),  # 10% grade
        })
        out = compute_longitudinal_accel(df, smoothing_window=1)
        # Default (no correction) -> should still be 1g

        np.testing.assert_allclose(
            out[OUT_LONG].dropna().values, _G_TO_MPS2, rtol=1e-3,
        )

    _test("slope_correction_default_off", t_slope_correction_default_off)

    # -- -

    # Test 25 -- bank angle clipped to +/-15 deg

    # -- -

    def t_bank_angle_clipping() -> None:
        N_b = 100
        # Set up an extreme residual that would give > 15 deg bank

        speed_val = 30.0
        R = 40.0
        yaw_dps = np.degrees(speed_val / R) * np.ones(N_b)
        a_centripetal = speed_val ** 2 / R
        # Make accel much lower than expected -> very high "bank"

        a_lat_meas = a_centripetal - _G_TO_MPS2 * np.sin(np.radians(25.0))

        df = pd.DataFrame({
            _RAW_TIME:  np.linspace(0, 5, N_b),
            _RAW_SPEED: np.full(N_b, speed_val),
            OUT_LAT:    np.full(N_b, a_lat_meas),
            OUT_YAW:    yaw_dps,
        })
        bank = compute_bank_angle_estimate(df)
        finite = bank.dropna()
        if len(finite) > 0:
            assert finite.max() <= _MAX_BANK_ANGLE_DEG + 0.01, (
                f"Bank angle {finite.max():.1f} deg exceeds +/-{_MAX_BANK_ANGLE_DEG} deg limit"
            )

    _test("bank_angle_clipping", t_bank_angle_clipping)

    # -- -

    # Summary

    # -- -

    total = len(passed) + len(failed)
    print(f"\nDerived Channels Tests: {len(passed)}/{total} passed")
    for name in passed:
        print(f"  OK {name}")
    for name, tb in failed:
        print(f"  FAIL {name}\n{tb}")

    if failed:
        raise AssertionError(f"{len(failed)} test(s) failed.")


# -- -

# Entry point

# -- -


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _run_tests()