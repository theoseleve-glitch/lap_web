"""
friction_model.py -- -
Builds a vehicle grip model (friction ellipse) from actual telemetry
g-force data.  The model captures the combined-grip relationship between
longitudinal and lateral acceleration as a function of speed, and is the
primary physics constraint for the lap-time simulation engine.

Public API
~~~~~~~~~~
``FrictionCircle``
    Dataclass storing the speed-dependent grip envelope with methods for
    querying available grip under combined loading.

``build_friction_model(resampled_laps, ...)``
    Construct a FrictionCircle from telemetry data.

``estimate_grip_scaling(friction_model, conditions)``
    Scale grip limits for wet / damp conditions.

``plot_gg_diagram(friction_model, speed_bin)``
    Return data for g-g diagram visualisation.

Physics
~~~~~~~
The friction ellipse models combined grip as:

    (a_x / a_x_max)^p + (a_y / a_y_max)^p ≤ 1.0

At corner apex (a_x ≈ 0):  full lateral grip → v_max = sqrt(a_y_max / κ)
Under combined braking/cornering:  reduced lateral grip budget.

Design principles
~~~~~~~~~~~~~~~~~
- Pure functions; no side effects, no global mutable state.
- NaN-robust throughout.
- Structured logging; zero print statements.
- Deterministic: identical inputs  --  identical outputs.
- Numpy / pandas only  — no scipy.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Final

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# -- -

# Column-name constants (aligned with derived_channels.py / features.py)

# -- -


_COL_SPEED:     Final[str] = "Speed (m/s)"
_COL_ACCEL_L:   Final[str] = "accel_long_mps2"
_COL_ACCEL_LAT: Final[str] = "accel_lat_mps2"
_COL_DIST:      Final[str] = "Distance (m)"
_COL_YAW:       Final[str] = "yaw_rate_dps"
_COL_YAW_RC:    Final[str] = "Yaw rate (deg/s)"

# Physical constants

_G: Final[float] = 9.80665

# Defaults

_DEFAULT_SPEED_BINS:     Final[int]   = 20
_DEFAULT_PERCENTILE:     Final[float] = 95.0
_DEFAULT_MIN_SAMPLES:    Final[int]   = 10
_DEFAULT_ELLIPSE_EXP:    Final[float] = 2.0
_KART_ELLIPSE_EXP:       Final[float] = 1.6    # Kart slicks have squarer combined grip
_DEFAULT_SMOOTH_WINDOW:  Final[int]   = 3
_DEFAULT_TRACTION_PCTL:  Final[float] = 98.0   # traction-specific percentile (higher for noisy GPS data)
_MIN_SPEED_MPS:          Final[float] = 1.0   # ignore data below this speed
_MAX_PHYSICAL_ACCEL:     Final[float] = 50.0   # m/s²  — clip sensor outliers

# Condition grip scaling factors (from motorsport literature)

_GRIP_SCALING: Final[dict[str, float]] = {
    "dry":      1.00,
    "damp":     0.85,
    "greasy":   0.80,
    "wet":      0.70,
    "full_wet": 0.60,
    "drying":   0.80,
}

# Kart-specific traction floor: even a rental kart can sustain ~0.45g traction.
# GPS-derived acceleration is noisy and conservative percentiles underestimate
# traction on karts by 10-30%.  This floor prevents the sim from producing
# absurd times.  Raised from 0.35g to 0.45g based on empirical GPS correction.
_KART_TRACTION_FLOOR_MPS2: Final[float] = 0.45 * _G   # 0.45g in m/s^2
_KART_LATERAL_FLOOR_MPS2:  Final[float] = 0.60 * _G   # 0.60g in m/s^2

# GPS correction factor: GPS-derived accelerations on karts (10-25Hz) read
# 10-30% lower than actual due to smoothing, sampling rate, and noise.
# Apply this multiplier to the extracted friction envelopes.
_GPS_GRIP_CORRECTION: Final[float] = 1.20  # 20% boost to compensate GPS under-read

# -- -

# Exceptions

# -- -


class FrictionModelError(ValueError):
    """Raised when the friction model cannot be built."""


# -- -

# Internal helpers

# -- -


def _has(df: pd.DataFrame, col: str) -> bool:
    return col in df.columns and df[col].notna().any()


def _gaussian_smooth(signal: np.ndarray, half_window: int) -> np.ndarray:
    """Gaussian-weighted 1-D rolling average."""
    if half_window <= 0 or len(signal) < 3:
        return signal.copy()
    k = 2 * half_window + 1
    x = np.arange(k) - half_window
    w = np.exp(-0.5 * (x / max(half_window / 2.0, 0.5)) ** 2)
    w /= w.sum()
    padded = np.pad(signal, half_window, mode="reflect")
    out = np.convolve(padded, w, mode="valid")
    return out[: len(signal)]


def _safe_percentile(values: np.ndarray, pct: float) -> float:
    """Percentile of finite values; NaN if < 2 finite."""
    finite = values[np.isfinite(values)]
    return float(np.percentile(finite, pct)) if len(finite) >= 2 else float("nan")


def _interp_fill(v_grid: np.ndarray, values: np.ndarray) -> np.ndarray:
    """Linearly interpolate NaN gaps in *values* defined on *v_grid*."""
    finite = np.isfinite(values)
    if finite.sum() < 2:
        return values.copy()
    result = values.copy()
    nans = ~finite
    if nans.any():
        result[nans] = np.interp(
            np.where(nans)[0],
            np.where(finite)[0],
            values[finite],
        )
    return result


def _extract_accel_triplets(
    resampled_laps: dict[int, pd.DataFrame],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Collect all (speed, a_long, a_lat) triplets across all laps.

    If longitudinal or lateral accel channels are absent, attempts to derive
    them from speed and yaw rate.

    Returns (speeds, a_long, a_lat)  — 1-D arrays with NaN rows removed.
    """
    all_speed: list[np.ndarray] = []
    all_along: list[np.ndarray] = []
    all_alat:  list[np.ndarray] = []

    for ln, df in sorted(resampled_laps.items()):
        if not _has(df, _COL_SPEED):
            continue

        speed = pd.to_numeric(df[_COL_SPEED], errors="coerce").values

        # --- Longitudinal accel -
        if _has(df, _COL_ACCEL_L):
            a_long = pd.to_numeric(df[_COL_ACCEL_L], errors="coerce").values
        elif _has(df, _COL_SPEED) and _has(df, _COL_DIST):
            # Derive from dv/ds * v (distance-domain derivative)

            dist = pd.to_numeric(df[_COL_DIST], errors="coerce").values
            ds = np.diff(dist)
            ds = np.where((ds > 0) & np.isfinite(ds), ds, np.nan)
            dv = np.diff(np.where(np.isfinite(speed), speed, np.nan))
            a_long = np.concatenate([[np.nan], dv / ds * speed[1:]])
        else:
            a_long = np.full(len(df), np.nan)

        # --- Lateral accel -
        if _has(df, _COL_ACCEL_LAT):
            a_lat = pd.to_numeric(df[_COL_ACCEL_LAT], errors="coerce").values
        elif _has(df, _COL_SPEED):
            # Derive from v * yaw_rate

            yaw_col = _COL_YAW if _has(df, _COL_YAW) else (
                _COL_YAW_RC if _has(df, _COL_YAW_RC) else None
            )
            if yaw_col is not None:
                yaw = pd.to_numeric(df[yaw_col], errors="coerce").values
                a_lat = speed * np.radians(yaw)  # v  --  deg
            else:
                a_lat = np.full(len(df), np.nan)
        else:
            a_lat = np.full(len(df), np.nan)

        all_speed.append(speed)
        all_along.append(a_long)
        all_alat.append(a_lat)

    if not all_speed:
        raise FrictionModelError("No valid laps with speed data.")

    speeds = np.concatenate(all_speed)
    a_long = np.concatenate(all_along)
    a_lat  = np.concatenate(all_alat)

    # Clip to physical limits

    a_long = np.clip(a_long, -_MAX_PHYSICAL_ACCEL, _MAX_PHYSICAL_ACCEL)
    a_lat  = np.clip(a_lat,  -_MAX_PHYSICAL_ACCEL, _MAX_PHYSICAL_ACCEL)

    # Filter: must have finite speed, a_long, a_lat, and speed above minimum

    mask = (
        np.isfinite(speeds) & np.isfinite(a_long) & np.isfinite(a_lat) &
        (speeds >= _MIN_SPEED_MPS)
    )
    logger.info(
        "Extracted %d valid (speed, a_long, a_lat) triplets from %d laps "
        "(%d total samples, %d filtered).",
        int(mask.sum()), len(resampled_laps),
        len(speeds), len(speeds) - int(mask.sum()),
    )
    return speeds[mask], a_long[mask], a_lat[mask]


# -- -

# FrictionCircle dataclass

# -- -


@dataclass
class FrictionCircle:
    """
    Speed-dependent friction ellipse model.

    Stores the vehicle's grip envelope and provides methods to query
    available grip under combined longitudinal/lateral loading.

    The combined grip model is:

        (a_x / a_x_max)^p + (a_y / a_y_max)^p  ≤ 1.0

    where a_x_max and a_y_max are speed-dependent grip limits and *p* is
    the ellipse shape exponent.

    Attributes -- v_grid : np.ndarray
        Speed knots [m/s].
    traction_vals : np.ndarray
        Max traction acceleration (a_x > 0) at each knot [m/s²].
    braking_vals : np.ndarray
        Max braking deceleration (positive) at each knot [m/s²].
    lateral_vals : np.ndarray
        Max lateral acceleration (|a_y|) at each knot [m/s²].
    exponent : float
        Friction ellipse shape exponent (2.0 = true ellipse).
    exponent_source : str
        "fitted" if `exponent` was estimated from boundary data, "hint" if
        it is the unfitted default/hint value.
    """

    v_grid:        np.ndarray
    traction_vals: np.ndarray
    braking_vals:  np.ndarray
    lateral_vals:  np.ndarray
    exponent:      float = _DEFAULT_ELLIPSE_EXP
    # "fitted" when _fit_ellipse_exponent had enough boundary samples to
    # actually fit p; "hint" when it silently fell back to the default.
    # In-memory only -- this object is never persisted, so no migration.
    exponent_source: str = "hint"

    # Interpolators (built post-init)

    _traction_fn: Any = field(init=False, repr=False, default=None)
    _braking_fn:  Any = field(init=False, repr=False, default=None)
    _lateral_fn:  Any = field(init=False, repr=False, default=None)

    def __post_init__(self) -> None:
        self._build_interpolators()

    def _build_interpolators(self) -> None:
        """Build piecewise-linear interpolators from the grid arrays."""
        def _make_fn(vals: np.ndarray) -> Any:
            mask = np.isfinite(vals)
            if mask.sum() < 2:
                # Constant fallback using the single finite value or a safe default

                c = float(np.nanmean(vals)) if mask.any() else _G
                return lambda v, _c=c: np.full_like(np.asarray(v, dtype=float), _c)
            vg = self.v_grid[mask]
            yg = vals[mask]
            return lambda v, _vg=vg, _yg=yg: np.interp(
                np.asarray(v, dtype=float), _vg, _yg
            )

        self._traction_fn = _make_fn(self.traction_vals)
        self._braking_fn  = _make_fn(self.braking_vals)
        self._lateral_fn  = _make_fn(self.lateral_vals)

    # --- Query methods -

    def traction_max(self, speed: float | np.ndarray) -> np.ndarray:
        """Max traction acceleration [m/s²] at *speed* [m/s]."""
        return self._traction_fn(speed)

    def braking_max(self, speed: float | np.ndarray) -> np.ndarray:
        """Max braking deceleration [m/s²] (positive) at *speed* [m/s]."""
        return self._braking_fn(speed)

    def lateral_max(self, speed: float | np.ndarray) -> np.ndarray:
        """Max lateral acceleration [m/s²] at *speed* [m/s]."""
        return self._lateral_fn(speed)

    def max_lateral_accel(
        self, speed: float, longitudinal_accel: float = 0.0,
    ) -> float:
        """
        Available lateral acceleration given current speed and longitudinal
        loading.

        Uses the friction ellipse equation:
            a_y_avail = a_y_max  -- · (1 -- |a_x / a_x_max|^p)^(1/p)
        """
        a_y_max = float(self.lateral_max(speed))
        if longitudinal_accel == 0.0:
            return a_y_max

        if longitudinal_accel > 0:
            a_x_max = float(self.traction_max(speed))
        else:
            a_x_max = float(self.braking_max(speed))

        if a_x_max <= 0:
            return a_y_max

        p = self.exponent
        ratio = min(abs(longitudinal_accel) / a_x_max, 1.0)
        return a_y_max * max(0.0, (1.0 - ratio ** p)) ** (1.0 / p)

    def max_longitudinal_accel(
        self, speed: float, lateral_accel: float = 0.0, *, braking: bool = False,
    ) -> float:
        """
        Available longitudinal acceleration (or braking) given lateral load.

        Parameters -- speed : float
            Current speed [m/s].
        lateral_accel : float
            Current lateral acceleration [m/s²] (absolute value used).
        braking : bool
            If True, return braking capacity; else traction capacity.
        """
        a_x_max = float(
            self.braking_max(speed) if braking else self.traction_max(speed)
        )
        a_y_max = float(self.lateral_max(speed))

        if lateral_accel == 0.0 or a_y_max <= 0:
            return a_x_max

        p = self.exponent
        ratio = min(abs(lateral_accel) / a_y_max, 1.0)
        return a_x_max * max(0.0, (1.0 - ratio ** p)) ** (1.0 / p)

    def max_cornering_speed(
        self, curvature: float, longitudinal_accel: float = 0.0,
    ) -> float:
        """
        Maximum speed [m/s] through a corner of given curvature.

        Uses a_lat = v² κ and the friction ellipse constraint.

        Parameters -- curvature : float
            Path curvature [1/m].  Zero or negative  --  returns infinity.
        longitudinal_accel : float
            Simultaneous longitudinal acceleration [m/s²].

        Returns -- -
        float
            Maximum cornering speed [m/s].
        """
        if curvature <= 0.0:
            return float("inf")

        # Iterative solve: v_max depends on grip at that speed, which may

        # depend on speed (downforce).  3 iterations suffice for convergence.

        # Initial guess using grip at low speed

        a_lat_avail = self.max_lateral_accel(5.0, longitudinal_accel)
        if a_lat_avail <= 0:
            return 0.0

        v = math.sqrt(a_lat_avail / curvature)

        for _ in range(5):
            a_lat_avail = self.max_lateral_accel(v, longitudinal_accel)
            if a_lat_avail <= 0:
                return 0.0
            v_new = math.sqrt(a_lat_avail / curvature)
            if abs(v_new - v) < 0.01:
                break
            v = v_new

        return v

    # --- Serialisation -

    def to_dict(self) -> dict[str, Any]:
        return {
            "v_grid":        self.v_grid.tolist(),
            "traction_vals": self.traction_vals.tolist(),
            "braking_vals":  self.braking_vals.tolist(),
            "lateral_vals":  self.lateral_vals.tolist(),
            "exponent":      self.exponent,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> FrictionCircle:
        return cls(
            v_grid=np.array(d["v_grid"], dtype=float),
            traction_vals=np.array(d["traction_vals"], dtype=float),
            braking_vals=np.array(d["braking_vals"], dtype=float),
            lateral_vals=np.array(d["lateral_vals"], dtype=float),
            exponent=d.get("exponent", _DEFAULT_ELLIPSE_EXP),
        )

    def scaled(self, factor: float) -> FrictionCircle:
        """Return a new FrictionCircle with all grip limits scaled by *factor*."""
        return FrictionCircle(
            v_grid=self.v_grid.copy(),
            traction_vals=self.traction_vals * factor,
            braking_vals=self.braking_vals * factor,
            lateral_vals=self.lateral_vals * factor,
            exponent=self.exponent,
            exponent_source=self.exponent_source,
        )


# -- -

# Public API  --  build_friction_model

# -- -


def build_friction_model(
    resampled_laps: dict[int, pd.DataFrame],
    *,
    speed_bins: int = _DEFAULT_SPEED_BINS,
    percentile: float = _DEFAULT_PERCENTILE,
    traction_percentile: float | None = None,
    min_samples_per_bin: int = _DEFAULT_MIN_SAMPLES,
    smooth_window: int = _DEFAULT_SMOOTH_WINDOW,
    exponent: float = _DEFAULT_ELLIPSE_EXP,
    kart_traction_floor: bool = False,
) -> FrictionCircle:
    """
    Build a speed-dependent friction ellipse model from telemetry data.

    Collects all (speed, a_long, a_lat) observations across laps, bins by
    speed, and extracts the percentile-boundary grip limits in each bin.
    Traction (a_x > 0) and braking (a_x < 0) are fitted independently to
    capture asymmetry.

    Parameters -- resampled_laps:
        Dict of ``{lap_number: DataFrame}`` with columns including
        ``Speed (m/s)`` and derived accel channels.
    speed_bins:
        Number of velocity bins to divide the speed range into.
    percentile:
        Percentile of the acceleration distribution to use as the grip
        boundary (e.g. 95 = top 5% of observed g-force).
    traction_percentile:
        Separate percentile for traction (acceleration) extraction.
        If None, defaults to ``_DEFAULT_TRACTION_PCTL`` (98).  Use a
        high value (98-99) for karts where GPS-derived acceleration is
        noisy and conservative percentiles underestimate traction.
    min_samples_per_bin:
        Minimum observations in a speed bin for a valid estimate.
    smooth_window:
        Gaussian half-window for smoothing the grip profiles.
    exponent:
        Friction ellipse shape exponent (2.0 = true ellipse).
    kart_traction_floor:
        If True, clamp traction values to a minimum of 0.35g.  This
        prevents absurdly low traction from producing unrealistic sim
        times on karts where GPS noise floors the acceleration readings.

    Returns -- -
    FrictionCircle

    Raises -- FrictionModelError
        If insufficient data is available.
    """
    # Resolve traction-specific percentile

    trac_pct = traction_percentile if traction_percentile is not None else _DEFAULT_TRACTION_PCTL

    speeds, a_long, a_lat = _extract_accel_triplets(resampled_laps)

    if len(speeds) < min_samples_per_bin:
        raise FrictionModelError(
            f"Only {len(speeds)} valid samples; need  ≥ {min_samples_per_bin}."
        )

    # Build velocity grid

    v_min = max(float(np.percentile(speeds, 1)), _MIN_SPEED_MPS)
    v_max = float(np.percentile(speeds, 99))
    if v_max <= v_min:
        v_max = v_min + 1.0
    v_grid = np.linspace(v_min, v_max, speed_bins)
    v_step = v_grid[1] - v_grid[0] if len(v_grid) > 1 else 1.0

    # Assign each observation to its nearest velocity bin

    bin_indices = np.clip(
        ((speeds - v_min) / v_step).astype(int), 0, speed_bins - 1
    )

    # Per-bin accumulation

    traction_bins: list[list[float]] = [[] for _ in range(speed_bins)]
    braking_bins:  list[list[float]] = [[] for _ in range(speed_bins)]
    lateral_bins:  list[list[float]] = [[] for _ in range(speed_bins)]

    for bi, ax, ay in zip(bin_indices, a_long, a_lat):
        lateral_bins[bi].append(abs(float(ay)))
        if ax > 0:
            traction_bins[bi].append(float(ax))
        elif ax < 0:
            braking_bins[bi].append(abs(float(ax)))

    # Extract percentile for each bin

    # Traction uses a separate (typically higher) percentile because

    # GPS-derived longitudinal acceleration is noisier and more conservative

    # than lateral acceleration, especially on karts.

    traction_env = np.array([
        _safe_percentile(np.array(b), trac_pct)
        if len(b) >= min_samples_per_bin else float("nan")
        for b in traction_bins
    ])
    braking_env = np.array([
        _safe_percentile(np.array(b), percentile)
        if len(b) >= min_samples_per_bin else float("nan")
        for b in braking_bins
    ])
    lateral_env = np.array([
        _safe_percentile(np.array(b), percentile)
        if len(b) >= min_samples_per_bin else float("nan")
        for b in lateral_bins
    ])

    # Interpolate NaN gaps

    traction_env = _interp_fill(v_grid, traction_env)
    braking_env  = _interp_fill(v_grid, braking_env)
    lateral_env  = _interp_fill(v_grid, lateral_env)

    # Clip to physical limits ( ≤ 5g)

    traction_env = np.clip(traction_env, 0.0, _MAX_PHYSICAL_ACCEL)
    braking_env  = np.clip(braking_env,  0.0, _MAX_PHYSICAL_ACCEL)
    lateral_env  = np.clip(lateral_env,  0.0, _MAX_PHYSICAL_ACCEL)

    # Smooth

    if smooth_window > 0:
        for env in (traction_env, braking_env, lateral_env):
            finite = np.isfinite(env)
            if finite.sum() >= 3:
                env[finite] = _gaussian_smooth(env[finite], smooth_window)

    # Ensure no NaN or zero values (minimum floor of 0.5 m/s²)

    _FLOOR = 0.5
    traction_env = np.where(np.isfinite(traction_env) & (traction_env > 0),
                            traction_env, _FLOOR)
    braking_env  = np.where(np.isfinite(braking_env) & (braking_env > 0),
                            braking_env, _FLOOR)
    lateral_env  = np.where(np.isfinite(lateral_env) & (lateral_env > 0),
                            lateral_env, _FLOOR)

    # GPS grip correction: GPS-derived accelerations systematically under-read
    # actual grip by 10-30% due to smoothing, low sample rate, and noise.
    # Apply the correction factor to all envelopes before flooring.
    if kart_traction_floor:
        logger.info(
            "Applying GPS grip correction factor %.2f to all envelopes.",
            _GPS_GRIP_CORRECTION,
        )
        traction_env *= _GPS_GRIP_CORRECTION
        braking_env  *= _GPS_GRIP_CORRECTION
        lateral_env  *= _GPS_GRIP_CORRECTION

    # Kart traction floor: clamp traction to a minimum of 0.45g.
    # GPS-derived acceleration on karts is noisy and the percentile extraction
    # yields values like 0.16-0.25g which are unrealistically low.  Even a
    # heavy 4T kart can sustain 0.45-0.55g traction on dry asphalt.

    if kart_traction_floor:
        n_clamped = int((traction_env < _KART_TRACTION_FLOOR_MPS2).sum())
        if n_clamped > 0:
            logger.info(
                "Kart traction floor: clamping %d/%d bins from "
                "%.2f-%.2f m/s^2 to floor %.2f m/s^2 (%.2fg).",
                n_clamped, len(traction_env),
                float(np.min(traction_env)), float(np.max(traction_env)),
                _KART_TRACTION_FLOOR_MPS2, _KART_TRACTION_FLOOR_MPS2 / _G,
            )
        traction_env = np.maximum(traction_env, _KART_TRACTION_FLOOR_MPS2)

        # Kart lateral grip floor: GPS-derived lateral accel can read 0.05g

        # when yaw rate is unreliable. Even a wet kart sustains > 0.5g lateral.

        n_lat_clamped = int((lateral_env < _KART_LATERAL_FLOOR_MPS2).sum())
        if n_lat_clamped > 0:
            logger.info(
                "Kart lateral floor: clamping %d/%d bins from "
                "%.2f-%.2f m/s^2 to floor %.2f m/s^2 (%.2fg).",
                n_lat_clamped, len(lateral_env),
                float(np.min(lateral_env)), float(np.max(lateral_env)),
                _KART_LATERAL_FLOOR_MPS2, _KART_LATERAL_FLOOR_MPS2 / _G,
            )
        lateral_env = np.maximum(lateral_env, _KART_LATERAL_FLOOR_MPS2)

    # Fit ellipse exponent from data.
    # For karts, use a squarer ellipse (p=1.6) as the default hint.
    exp_hint = _KART_ELLIPSE_EXP if kart_traction_floor else exponent
    fitted_exp, exp_source = _fit_ellipse_exponent(
        speeds, a_long, a_lat, v_grid,
        traction_env, braking_env, lateral_env,
        exponent_hint=exp_hint,
    )

    model = FrictionCircle(
        v_grid=v_grid,
        traction_vals=traction_env,
        braking_vals=braking_env,
        lateral_vals=lateral_env,
        exponent=fitted_exp,
        exponent_source=exp_source,
    )

    logger.info(
        "Friction model: %d speed bins [%.1f -- %.1f m/s], "
        "traction=%.1f -- %.1f m/s², braking=%.1f -- %.1f m/s², "
        "lateral=%.1f -- %.1f m/s², exponent=%.2f",
        speed_bins, float(v_grid[0]), float(v_grid[-1]),
        float(np.min(traction_env)), float(np.max(traction_env)),
        float(np.min(braking_env)),  float(np.max(braking_env)),
        float(np.min(lateral_env)),  float(np.max(lateral_env)),
        fitted_exp,
    )
    return model


def _fit_ellipse_exponent(
    speeds: np.ndarray,
    a_long: np.ndarray,
    a_lat: np.ndarray,
    v_grid: np.ndarray,
    traction_env: np.ndarray,
    braking_env: np.ndarray,
    lateral_env: np.ndarray,
    *,
    exponent_hint: float = 2.0,
) -> tuple[float, str]:
    """
    Estimate the ellipse shape exponent *p* from data by testing which
    exponent best describes the observed boundary.

    Samples near the boundary (total g > 80% of max) are used.  The exponent
    that minimises the residual (a_x/a_x_max)^p + (a_y/a_y_max)^p -- 1 for
    boundary points is selected from a grid [1.2, 1.4, ..., 3.0].

    Falls back to *exponent_hint* if insufficient boundary data.

    Returns
    -------
    tuple[float, str]
        The exponent value, and its source: "fitted" if the grid search
        ran on enough boundary samples, "hint" if it fell back to
        *exponent_hint* unchanged.
    """
    # Interpolate limits at each sample's speed

    a_x_max = np.interp(speeds, v_grid, traction_env)
    a_b_max = np.interp(speeds, v_grid, braking_env)
    a_y_max = np.interp(speeds, v_grid, lateral_env)

    # Use braking limit for negative a_long

    a_long_max = np.where(a_long >= 0, a_x_max, a_b_max)

    # Normalised accelerations

    with np.errstate(divide="ignore", invalid="ignore"):
        rx = np.abs(a_long) / np.where(a_long_max > 0, a_long_max, 1.0)
        ry = np.abs(a_lat)  / np.where(a_y_max > 0,   a_y_max,   1.0)

    # Total utilisation

    total_g = np.sqrt(a_long ** 2 + a_lat ** 2)
    max_g   = np.sqrt(a_long_max ** 2 + a_y_max ** 2)
    with np.errstate(divide="ignore", invalid="ignore"):
        utilisation = total_g / np.where(max_g > 0, max_g, 1.0)

    # Select boundary samples (high utilisation, both axes active)

    boundary = (
        np.isfinite(rx) & np.isfinite(ry) &
        (utilisation > 0.70) &
        (rx > 0.1) & (ry > 0.1) &
        (rx <= 1.5) & (ry <= 1.5)
    )

    n_boundary = int(boundary.sum())
    if n_boundary < 20:
        logger.debug(
            "Only %d boundary samples for exponent fit; using hint=%.2f",
            n_boundary, exponent_hint,
        )
        return exponent_hint, "hint"

    rx_b = rx[boundary]
    ry_b = ry[boundary]

    # Grid search for best exponent

    candidates = np.arange(1.2, 3.05, 0.2)
    best_p = exponent_hint
    best_err = float("inf")

    for p in candidates:
        residuals = rx_b ** p + ry_b ** p - 1.0
        # We want boundary points to be close to 1.0

        mse = float(np.mean(residuals ** 2))
        if mse < best_err:
            best_err = mse
            best_p = float(p)

    logger.debug(
        "Ellipse exponent fit: p=%.1f (from %d boundary samples, MSE=%.4f)",
        best_p, n_boundary, best_err,
    )
    return best_p, "fitted"


# -- -

# Public API  --  estimate_grip_scaling

# -- -


def estimate_grip_scaling(
    friction_model: FrictionCircle,
    conditions: str = "dry",
) -> FrictionCircle:
    """
    Scale the friction model for track surface conditions.

    Parameters -- friction_model:
        Base friction model (typically built from data already reflecting
        the session conditions).
    conditions:
        One of ``"dry"``, ``"damp"``, ``"greasy"``, ``"wet"``,
        ``"full_wet"``, ``"drying"``.

    Returns -- -
    FrictionCircle
        A new model with scaled grip limits.
    """
    key = conditions.lower().strip().replace(" ", "_")
    factor = _GRIP_SCALING.get(key, 1.0)

    if factor == 1.0 and key not in _GRIP_SCALING:
        logger.warning(
            "Unknown condition %r; applying no scaling. "
            "Known: %s", conditions, list(_GRIP_SCALING.keys()),
        )

    if factor == 1.0:
        return friction_model

    logger.info(
        "Scaling grip for %r: factor=%.2f", conditions, factor,
    )
    return friction_model.scaled(factor)


# -- -

# Public API -- apply_kart_traction_floor

# -- -


def apply_kart_traction_floor(
    friction_model: FrictionCircle,
    floor_g: float = 0.35,
    lateral_floor_g: float = 0.50,
) -> FrictionCircle:
    """
    Clamp traction and lateral values in the friction model to minimum floors.

    Kart GPS telemetry produces noisy acceleration readings.
    The percentile-based extraction can yield traction values as low as
    0.16-0.25g, which is unrealistically conservative -- even a heavy 4T
    kart on worn tyres can sustain 0.35-0.5g traction on dry asphalt.
    Lateral grip can read as low as 0.05g when GPS yaw rate is unreliable,
    but even a wet kart sustains > 0.5g lateral.

    Parameters -- friction_model:
        The friction model to correct.
    floor_g:
        Minimum traction in g-units.  Default: 0.35g.
    lateral_floor_g:
        Minimum lateral grip in g-units.  Default: 0.50g.

    Returns -- -
    FrictionCircle
        New model with traction and lateral clamped to floors.
    """
    floor_mps2 = floor_g * _G
    lat_floor_mps2 = lateral_floor_g * _G
    trac = friction_model.traction_vals
    lat = friction_model.lateral_vals

    needs_trac = not np.all(trac >= floor_mps2)
    needs_lat = not np.all(lat >= lat_floor_mps2)

    if not needs_trac and not needs_lat:
        return friction_model

    if needs_trac:
        n_clamped = int((trac < floor_mps2).sum())
        logger.info(
            "Kart traction floor: clamping %d/%d bins to >= %.2fg (%.2f m/s^2).",
            n_clamped, len(trac), floor_g, floor_mps2,
        )

    if needs_lat:
        n_lat_clamped = int((lat < lat_floor_mps2).sum())
        logger.info(
            "Kart lateral floor: clamping %d/%d bins to >= %.2fg (%.2f m/s^2).",
            n_lat_clamped, len(lat), lateral_floor_g, lat_floor_mps2,
        )

    return FrictionCircle(
        v_grid=friction_model.v_grid.copy(),
        traction_vals=np.maximum(trac.copy(), floor_mps2),
        braking_vals=friction_model.braking_vals.copy(),
        lateral_vals=np.maximum(lat.copy(), lat_floor_mps2),
        exponent=friction_model.exponent,
        exponent_source=friction_model.exponent_source,
    )


# -- -

# Public API  --  plot_gg_diagram

# -- -


def plot_gg_diagram(
    friction_model: FrictionCircle,
    speed_bin: float | None = None,
) -> dict[str, Any]:
    """
    Return data for a g-g diagram visualisation.

    Parameters -- friction_model:
        The fitted friction model.
    speed_bin:
        If specified, show the ellipse boundary for this speed [m/s].
        If None, show boundaries for all speed bins.

    Returns -- -
    dict with keys:
        ``speed_bins``      — list of speed values used [m/s]
        ``ellipses``        — list of dicts, each with keys:
            ``speed_mps``    — float
            ``traction``     — float, max traction [m/s²]
            ``braking``      — float, max braking [m/s²]
            ``lateral``      — float, max lateral [m/s²]
            ``boundary_x``   — list of float, a_long points on the ellipse
            ``boundary_y``   — list of float, a_lat points on the ellipse
        ``exponent``        — float, fitted ellipse exponent
    """
    p = friction_model.exponent
    theta = np.linspace(0, 2 * math.pi, 72)

    if speed_bin is not None:
        speeds = [speed_bin]
    else:
        speeds = friction_model.v_grid.tolist()

    ellipses: list[dict[str, Any]] = []

    for v in speeds:
        a_trac = float(friction_model.traction_max(v))
        a_brak = float(friction_model.braking_max(v))
        a_lat  = float(friction_model.lateral_max(v))

        # Parametric ellipse boundary

        bx: list[float] = []
        by: list[float] = []
        for t in theta:
            cos_t = math.cos(t)
            sin_t = math.sin(t)
            # Scale to asymmetric traction/braking

            a_x_max = a_trac if cos_t >= 0 else a_brak
            # Points on the superellipse: |x/a|^p + |y/b|^p = 1

            # Parametric: x = a -- ·sign(cos) -- ·|cos|^(2/p), y = b -- ·sign(sin) -- ·|sin|^(2/p)

            inv_p = 2.0 / p
            bx.append(a_x_max * math.copysign(abs(cos_t) ** inv_p, cos_t))
            by.append(a_lat   * math.copysign(abs(sin_t) ** inv_p, sin_t))

        ellipses.append({
            "speed_mps":  v,
            "traction":   a_trac,
            "braking":    a_brak,
            "lateral":    a_lat,
            "boundary_x": bx,
            "boundary_y": by,
        })

    return {
        "speed_bins": speeds,
        "ellipses":   ellipses,
        "exponent":   p,
    }


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

    # Fixtures: synthetic laps around a circle with known grip limits

    # -- -

    # Circle: radius R, constant speed v, a_lat = v²/R

    # The vehicle has a_lat_max = MU_LAT * g, a_trac = MU_TRAC * g,

    # a_brake = MU_BRAKE * g

    RADIUS      = 50.0
    MU_LAT      = 1.2       # lateral friction coefficient [g]
    MU_TRAC     = 0.8       # traction friction coefficient [g]
    MU_BRAKE    = 1.5       # braking friction coefficient [g]
    A_LAT_MAX   = MU_LAT * _G      # 11.77 m/s²
    A_TRAC_MAX  = MU_TRAC * _G     # 7.85 m/s²
    A_BRAKE_MAX = MU_BRAKE * _G    # 14.71 m/s²
    V_CORNER    = math.sqrt(A_LAT_MAX * RADIUS)  # ~24.26 m/s
    N_PTS       = 500
    N_LAPS      = 8
    TRACK_LEN   = 2 * math.pi * RADIUS  # ~314.16 m

    def _make_circular_laps(
        n_laps: int = N_LAPS,
        noise_g: float = 0.05,
    ) -> dict[int, pd.DataFrame]:
        """
        Generate laps with g-forces that saturate the known friction limits.

        Each lap has sections of:
        - Pure cornering (at corner speed)
        - Acceleration out of "corners" (using traction grip)
        - Braking into "corners" (using braking grip)
        - Combined braking+cornering (tests the ellipse)
        """
        rng = np.random.default_rng(42)
        laps: dict[int, pd.DataFrame] = {}

        for lap_num in range(1, n_laps + 1):
            dist = np.linspace(0, TRACK_LEN, N_PTS, endpoint=False)

            # Divide track into 4 zones

            zone_len = TRACK_LEN / 4
            zone = (dist / zone_len).astype(int) % 4

            speed = np.full(N_PTS, V_CORNER)
            a_long = np.zeros(N_PTS)
            a_lat = np.zeros(N_PTS)

            # Zone 0: pure cornering  --  push to the limit

            mask0 = zone == 0
            a_lat[mask0] = A_LAT_MAX * (0.90 + 0.10 * rng.random(mask0.sum()))

            # Zone 1: acceleration (variable traction use) + some lateral

            mask1 = zone == 1
            n1 = mask1.sum()
            speed[mask1] = V_CORNER * (1.0 + np.linspace(0, 0.3, n1))
            a_long[mask1] = A_TRAC_MAX * (0.75 + 0.25 * rng.random(n1))
            a_lat[mask1] = A_LAT_MAX * 0.3 * rng.random(n1)

            # Zone 2: cornering near the limit

            mask2 = zone == 2
            a_lat[mask2] = A_LAT_MAX * (0.85 + 0.15 * rng.random(mask2.sum()))

            # Zone 3: heavy braking + cornering (combined)

            mask3 = zone == 3
            n3 = mask3.sum()
            speed[mask3] = V_CORNER * (1.3 - np.linspace(0, 0.3, n3))
            a_long[mask3] = -A_BRAKE_MAX * (0.65 + 0.35 * rng.random(n3))
            a_lat[mask3] = A_LAT_MAX * (0.3 + 0.4 * rng.random(n3))

            # Add noise

            a_long += rng.normal(0, noise_g * _G, N_PTS)
            a_lat  += rng.normal(0, noise_g * _G, N_PTS)

            # Synthetic time

            dt = np.diff(dist) / np.maximum(speed[:-1], 1.0)
            t = np.concatenate([[0.0], np.cumsum(dt)])

            laps[lap_num] = pd.DataFrame({
                _COL_DIST:      dist,
                _COL_SPEED:     speed,
                _COL_ACCEL_L:   a_long,
                _COL_ACCEL_LAT: a_lat,
                "Time (s)":     t,
            })
        return laps

    # -- -

    # Test 1  --  model builds without error

    # -- -

    def t_build_succeeds() -> None:
        laps = _make_circular_laps()
        model = build_friction_model(laps, speed_bins=10, percentile=95.0)
        assert isinstance(model, FrictionCircle)
        assert len(model.v_grid) == 10

    _test("build_succeeds", t_build_succeeds)

    # -- -

    # Test 2  --  lateral grip recovery within 20% of known value

    # -- -

    def t_lateral_grip_recovery() -> None:
        laps = _make_circular_laps()
        # Use p99 to capture the physical limit (p95 intentionally leaves

        # headroom  --  in real data not all samples are at the grip limit).

        model = build_friction_model(laps, speed_bins=10, percentile=99.0)
        # Query at the corner speed

        a_lat_est = float(model.lateral_max(V_CORNER))
        err_pct = abs(a_lat_est - A_LAT_MAX) / A_LAT_MAX * 100
        assert err_pct < 20, (
            f"Lateral grip = {a_lat_est:.2f} m/s²; expected  ≈ {A_LAT_MAX:.2f} "
            f"(error {err_pct:.1f}%)"
        )

    _test("lateral_grip_recovery", t_lateral_grip_recovery)

    # -- -

    # Test 3  --  traction grip recovery within 25%

    # -- -

    def t_traction_grip_recovery() -> None:
        laps = _make_circular_laps()
        model = build_friction_model(laps, speed_bins=10, percentile=99.0)
        a_trac_est = float(model.traction_max(V_CORNER * 1.1))
        err_pct = abs(a_trac_est - A_TRAC_MAX) / A_TRAC_MAX * 100
        assert err_pct < 25, (
            f"Traction grip = {a_trac_est:.2f} m/s²; expected  ≈ {A_TRAC_MAX:.2f} "
            f"(error {err_pct:.1f}%)"
        )

    _test("traction_grip_recovery", t_traction_grip_recovery)

    # -- -

    # Test 4  --  braking grip recovery within 25%

    # -- -

    def t_braking_grip_recovery() -> None:
        laps = _make_circular_laps()
        model = build_friction_model(laps, speed_bins=10, percentile=99.0)
        a_brake_est = float(model.braking_max(V_CORNER * 1.1))
        err_pct = abs(a_brake_est - A_BRAKE_MAX) / A_BRAKE_MAX * 100
        assert err_pct < 25, (
            f"Braking grip = {a_brake_est:.2f} m/s²; expected  ≈ {A_BRAKE_MAX:.2f} "
            f"(error {err_pct:.1f}%)"
        )

    _test("braking_grip_recovery", t_braking_grip_recovery)

    # -- -

    # Test 5  --  braking > traction (asymmetry preserved)

    # -- -

    def t_asymmetry_preserved() -> None:
        laps = _make_circular_laps()
        model = build_friction_model(laps, speed_bins=10, percentile=95.0)
        a_trac = float(model.traction_max(V_CORNER))
        a_brake = float(model.braking_max(V_CORNER))
        assert a_brake > a_trac, (
            f"Expected braking ({a_brake:.2f}) > traction ({a_trac:.2f})"
        )

    _test("asymmetry_preserved", t_asymmetry_preserved)

    # -- -

    # Test 6  --  combined grip: lateral reduced under braking

    # -- -

    def t_combined_grip_reduction() -> None:
        laps = _make_circular_laps()
        model = build_friction_model(laps, speed_bins=10, percentile=95.0)
        a_lat_pure = model.max_lateral_accel(V_CORNER, 0.0)
        a_lat_braking = model.max_lateral_accel(V_CORNER, -5.0)
        assert a_lat_braking < a_lat_pure, (
            f"Under braking: lateral={a_lat_braking:.2f} should be < "
            f"pure={a_lat_pure:.2f}"
        )

    _test("combined_grip_reduction", t_combined_grip_reduction)

    # -- -

    # Test 7  --  combined grip: traction reduced under cornering

    # -- -

    def t_combined_traction_reduction() -> None:
        laps = _make_circular_laps()
        model = build_friction_model(laps, speed_bins=10, percentile=95.0)
        a_trac_pure = model.max_longitudinal_accel(V_CORNER, 0.0)
        a_trac_corner = model.max_longitudinal_accel(V_CORNER, 5.0)
        assert a_trac_corner < a_trac_pure, (
            f"Under cornering: traction={a_trac_corner:.2f} should be < "
            f"pure={a_trac_pure:.2f}"
        )

    _test("combined_traction_reduction", t_combined_traction_reduction)

    # -- -

    # Test 8  --  max_cornering_speed on known circle

    # -- -

    def t_max_cornering_speed() -> None:
        laps = _make_circular_laps()
        model = build_friction_model(laps, speed_bins=10, percentile=95.0)
        kappa = 1.0 / RADIUS
        v_max = model.max_cornering_speed(kappa)
        v_expected = V_CORNER
        err_pct = abs(v_max - v_expected) / v_expected * 100
        assert err_pct < 20, (
            f"v_max = {v_max:.2f} m/s; expected  ≈ {v_expected:.2f} "
            f"(error {err_pct:.1f}%)"
        )

    _test("max_cornering_speed", t_max_cornering_speed)

    # -- -

    # Test 9  --  zero curvature  --  infinite speed

    # -- -

    def t_zero_curvature_infinite() -> None:
        laps = _make_circular_laps()
        model = build_friction_model(laps, speed_bins=10, percentile=95.0)
        v = model.max_cornering_speed(0.0)
        assert v == float("inf"), f"Expected inf, got {v}"

    _test("zero_curvature_infinite", t_zero_curvature_infinite)

    # -- -

    # Test 10  --  wet scaling reduces grip

    # -- -

    def t_wet_scaling() -> None:
        laps = _make_circular_laps()
        model = build_friction_model(laps, speed_bins=10, percentile=95.0)
        wet_model = estimate_grip_scaling(model, "wet")
        # Wet grip should be 70% of dry

        a_dry = float(model.lateral_max(V_CORNER))
        a_wet = float(wet_model.lateral_max(V_CORNER))
        ratio = a_wet / a_dry
        assert abs(ratio - 0.70) < 0.02, (
            f"Wet/dry ratio = {ratio:.3f}; expected 0.70"
        )

    _test("wet_scaling", t_wet_scaling)

    # -- -

    # Test 11  --  damp scaling factor

    # -- -

    def t_damp_scaling() -> None:
        laps = _make_circular_laps()
        model = build_friction_model(laps, speed_bins=10, percentile=95.0)
        damp = estimate_grip_scaling(model, "damp")
        ratio = float(damp.lateral_max(20.0)) / float(model.lateral_max(20.0))
        assert abs(ratio - 0.85) < 0.02, f"Damp ratio = {ratio:.3f}"

    _test("damp_scaling", t_damp_scaling)

    # -- -

    # Test 12  --  dry scaling is identity

    # -- -

    def t_dry_no_change() -> None:
        laps = _make_circular_laps()
        model = build_friction_model(laps, speed_bins=10, percentile=95.0)
        dry = estimate_grip_scaling(model, "dry")
        # Should be the same object (no scaling applied)

        assert dry is model

    _test("dry_no_change", t_dry_no_change)

    # -- -

    # Test 13  --  serialisation round-trip

    # -- -

    def t_serialisation() -> None:
        laps = _make_circular_laps()
        model = build_friction_model(laps, speed_bins=10, percentile=95.0)
        d = model.to_dict()
        restored = FrictionCircle.from_dict(d)
        np.testing.assert_allclose(
            restored.v_grid, model.v_grid, atol=1e-6,
        )
        np.testing.assert_allclose(
            restored.lateral_vals, model.lateral_vals, atol=1e-6,
        )
        assert restored.exponent == model.exponent

    _test("serialisation_roundtrip", t_serialisation)

    # -- -

    # Test 14  --  plot_gg_diagram returns valid data

    # -- -

    def t_gg_diagram() -> None:
        laps = _make_circular_laps()
        model = build_friction_model(laps, speed_bins=10, percentile=95.0)
        data = plot_gg_diagram(model, speed_bin=V_CORNER)
        assert "ellipses" in data
        assert len(data["ellipses"]) == 1
        e = data["ellipses"][0]
        assert len(e["boundary_x"]) == 72
        assert len(e["boundary_y"]) == 72
        # Boundary should roughly match our known limits

        max_bx = max(e["boundary_x"])
        max_by = max(e["boundary_y"])
        assert max_bx > 0
        assert max_by > 0

    _test("gg_diagram", t_gg_diagram)

    # -- -

    # Test 15  --  plot_gg_diagram all bins

    # -- -

    def t_gg_diagram_all_bins() -> None:
        laps = _make_circular_laps()
        model = build_friction_model(laps, speed_bins=10, percentile=95.0)
        data = plot_gg_diagram(model)
        assert len(data["ellipses"]) == 10

    _test("gg_diagram_all_bins", t_gg_diagram_all_bins)

    # -- -

    # Test 16  --  empty laps raises error

    # -- -

    def t_empty_laps() -> None:
        try:
            build_friction_model({})
            assert False, "Expected FrictionModelError"
        except FrictionModelError:
            pass

    _test("empty_laps_raises", t_empty_laps)

    # -- -

    # Test 17  --  max_cornering_speed reduced under braking

    # -- -

    def t_cornering_speed_reduced_under_braking() -> None:
        laps = _make_circular_laps()
        model = build_friction_model(laps, speed_bins=10, percentile=95.0)
        kappa = 1.0 / RADIUS
        v_pure = model.max_cornering_speed(kappa, 0.0)
        v_braking = model.max_cornering_speed(kappa, -3.0)
        assert v_braking < v_pure, (
            f"Under braking: v={v_braking:.2f} should be < pure={v_pure:.2f}"
        )

    _test("cornering_speed_reduced_under_braking", t_cornering_speed_reduced_under_braking)

    # -- -

    # Test 18  --  derived accel from speed + yaw_rate (no direct accel cols)

    # -- -

    def t_derived_accel_fallback() -> None:
        """Build model when only Speed and yaw_rate are available."""
        rng = np.random.default_rng(99)
        laps: dict[int, pd.DataFrame] = {}
        for ln in range(1, 5):
            n = 300
            dist = np.linspace(0, 600, n)
            speed = 20.0 + 5.0 * np.sin(dist / 600 * 2 * math.pi)
            # yaw_rate = v --  deg = v/R in deg/s

            omega_dps = np.degrees(speed / RADIUS)
            omega_dps += rng.normal(0, 2.0, n)
            laps[ln] = pd.DataFrame({
                _COL_DIST: dist,
                _COL_SPEED: speed,
                _COL_YAW: omega_dps,
                "Time (s)": np.linspace(0, 30, n),
            })
        model = build_friction_model(laps, speed_bins=8, percentile=90.0,
                                     min_samples_per_bin=5)
        assert isinstance(model, FrictionCircle)
        a_lat = float(model.lateral_max(20.0))
        assert a_lat > 1.0, f"Lateral accel should be > 1 m/s², got {a_lat:.2f}"

    _test("derived_accel_fallback", t_derived_accel_fallback)

    # -- -

    # Test 19  --  exponent is between 1.0 and 3.0

    # -- -

    def t_exponent_range() -> None:
        laps = _make_circular_laps()
        model = build_friction_model(laps, speed_bins=10, percentile=95.0)
        assert 1.0 <= model.exponent <= 3.0, (
            f"Exponent {model.exponent} out of range [1.0, 3.0]"
        )

    _test("exponent_range", t_exponent_range)

    # -- -

    # Test 20  --  max_lateral_accel at full longitudinal = 0

    # -- -

    def t_full_long_zero_lateral() -> None:
        laps = _make_circular_laps()
        model = build_friction_model(laps, speed_bins=10, percentile=95.0)
        a_trac = float(model.traction_max(V_CORNER))
        a_lat = model.max_lateral_accel(V_CORNER, a_trac)
        assert a_lat < 0.1, (
            f"At full traction, lateral should be ~0, got {a_lat:.2f}"
        )

    _test("full_long_zero_lateral", t_full_long_zero_lateral)

    # -- -

    # Summary

    # -- -

    total = len(passed) + len(failed)
    print(f"\nFriction Model Tests: {len(passed)}/{total} passed")
    for name in passed:
        print(f"   --  {name}")
    for name, tb in failed:
        print(f"  x{name}\n{tb}")

    if failed:
        raise AssertionError(f"{len(failed)} test(s) failed.")


# -- -

# Entry point

# -- -


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _run_tests()
