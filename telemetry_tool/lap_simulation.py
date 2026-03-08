"""
lap_simulation.py
-----------------
Advanced hybrid lap time simulation using physics + telemetry-fitted models.

Combines a **point-mass forward-backward solver** (the industry-standard
quasi-steady-state method used in OptimumLap, ChassisSim, and F1 teams)
with **telemetry-derived vehicle models** to produce the most accurate
theoretical lap possible.

Key innovations over a basic forward-backward sim
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
1. **Power-limited acceleration** — real engines cannot maintain constant
   force at high speed.  We fit a power envelope P(v) from telemetry so
   a_power(v) = P(v) / (m·v), correctly capturing the drop-off.

2. **Telemetry-fitted traction force curve** — instead of using a single
   friction coefficient, we build a speed-dependent traction force envelope
   F_trac(v) from observed (v, a_long) pairs.  This captures gearing effects,
   turbo lag, traction control, and every other real-world limitation.

3. **Braking performance envelope** — similarly fitted from telemetry,
   capturing ABS behaviour, brake fade, and aero-assisted braking.

4. **Aerodynamic model** — downforce increases available grip
   (F_grip = μ·(mg + 0.5·CL·A·ρ·v²)), while drag reduces net traction
   (F_drag = 0.5·CD·A·ρ·v²).  Both are speed-dependent.

5. **Tire load sensitivity** — as vertical load increases (from downforce
   or load transfer), the effective friction coefficient decreases.
   We model this with a linear sensitivity factor:
   μ_eff = μ_base · (1 - k_load · ΔFz / Fz_ref).

6. **Apex-seeded solver** — detect local speed minima (apices) in the
   cornering profile, then run forward from each apex and backward into
   each apex.  This eliminates convergence issues and gives physically
   correct brake-then-turn-then-accelerate sequencing.

7. **Closed-loop wrap-around convergence** with improved damping.

8. **Combined grip via friction ellipse** with proper speed-dependent
   asymmetric limits (traction ≠ braking).

Algorithm
~~~~~~~~~
Phase A — Build vehicle model from telemetry:
  1. Extract (speed, acceleration) pairs from all resampled laps.
  2. Fit power envelope: P(v) = envelope of v · F_trac observations.
  3. Fit braking envelope: F_brake(v) from observed decelerations.
  4. Estimate aero parameters (drag, downforce) from high-speed behaviour.

Phase B — Forward-backward simulation:
  1. Cornering limit: v_corner(s) from curvature + friction circle.
  2. Find apex points (local minima of v_corner).
  3. Forward pass from each apex: a = min(a_grip, a_power) - a_drag - a_rr.
  4. Backward pass into each apex: a = a_brake + a_drag + a_rr.
  5. Combine: v_final = min(v_forward, v_backward, v_corner).
  6. Integrate time: Σ ds / v.

Phase C — Blending:
  If telemetry-fitted model produces unrealistic results, blend with
  the friction-circle-only model using confidence weighting.

Public API
~~~~~~~~~~
``simulate_theoretical_lap(curvature_profile, friction, ...)``
    Core physics simulation → TheoreticalLapResult.

``simulate_with_fallback(resampled_laps, curvature_profile, friction, ...)``
    Try physics sim, fall back to percentile envelope.

``result_to_theoretical_df(result)``
    Convert result to the DataFrame format expected by the pipeline.

``fit_vehicle_model(resampled_laps, friction)``
    Fit a telemetry-derived vehicle performance model.

Design principles
~~~~~~~~~~~~~~~~~
- Pure functions; no side effects, no global mutable state.
- NaN-robust; graceful degradation on bad input.
- Structured logging; zero print statements.
- Deterministic: identical inputs → identical outputs.
- Numpy / pandas only (no scipy dependency).
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final, Optional, Protocol

if TYPE_CHECKING:
    from grip_map import GripMap
    from friction_envelope import FrictionEnvelope

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Physical constants
# ---------------------------------------------------------------------------

_G: Final[float] = 9.80665
_MIN_SPEED_MPS: Final[float] = 1.0       # never let speed drop below 1 m/s
_MAX_SPEED_MPS: Final[float] = 120.0     # kart / club car sanity cap
_DEFAULT_N_PTS: Final[int]   = 1000
_WRAP_ITERATIONS: Final[int] = 8         # convergence passes for closed-loop
_WRAP_TOL_MPS: Final[float]  = 0.02      # convergence tolerance [m/s]
_AIR_DENSITY: Final[float]   = 1.225     # kg/m³ at sea level, 15°C

# Output column names (compatible with theoretical_engine.py and pipeline.py)
_OUT_DIST:  Final[str] = "distance_m"
_OUT_SPEED: Final[str] = "v_env_mps"
_OUT_ACCEL: Final[str] = "accel_max_mps2"
_OUT_BRAKE: Final[str] = "brake_max_mps2"


# ---------------------------------------------------------------------------
# Friction interface protocol
# ---------------------------------------------------------------------------

class FrictionLike(Protocol):
    """
    Structural interface for a friction model.

    Any object providing these methods works — typically
    ``friction_model.FrictionCircle``.
    """

    def max_cornering_speed(
        self, curvature: float, longitudinal_accel: float = 0.0,
    ) -> float: ...

    def max_longitudinal_accel(
        self, speed: float, lateral_accel: float = 0.0, *, braking: bool = False,
    ) -> float: ...

    def lateral_max(self, speed: float | np.ndarray) -> np.ndarray: ...

    def traction_max(self, speed: float | np.ndarray) -> np.ndarray: ...

    def braking_max(self, speed: float | np.ndarray) -> np.ndarray: ...


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class VehicleModel:
    """
    Telemetry-derived vehicle performance model.

    Captures the *actual achievable* acceleration and braking performance
    as a function of speed, including engine power limits, gearing, aero,
    and tire grip — all fitted from observed data.

    Attributes
    ----------
    v_knots : np.ndarray
        Speed knots [m/s] for interpolation.
    traction_force_per_kg : np.ndarray
        Max traction acceleration [m/s²] at each speed knot.
        This is F_trac / m, already incorporating engine power limits.
    braking_force_per_kg : np.ndarray
        Max braking deceleration [m/s²] at each speed knot (positive).
    power_envelope_w_per_kg : np.ndarray
        Power envelope P/m [W/kg] at each speed knot.
    estimated_peak_power_w_per_kg : float
        Estimated peak power-to-mass ratio [W/kg].
    aero_drag_coeff : float
        Estimated 0.5·Cd·A·ρ/m [1/m].
    aero_downforce_coeff : float
        Estimated 0.5·CL·A·ρ/m [1/m]. Downforce → extra grip.
    rolling_resistance : float
        Rolling resistance coefficient Crr.
    tire_load_sensitivity : float
        Grip coefficient reduction per unit of additional load fraction.
        μ_eff = μ_base · (1 - k · ΔFz/Fz_ref). Typical: 0.05–0.15.
    confidence : float
        Quality metric 0–1 indicating how well the model fits the data.
    n_samples : int
        Number of (speed, accel) data points used for fitting.
    """
    v_knots:                     np.ndarray
    traction_force_per_kg:       np.ndarray
    braking_force_per_kg:        np.ndarray
    power_envelope_w_per_kg:     np.ndarray
    estimated_peak_power_w_per_kg: float = 0.0
    aero_drag_coeff:             float = 0.0
    aero_downforce_coeff:        float = 0.0
    rolling_resistance:          float = 0.015
    tire_load_sensitivity:       float = 0.08
    confidence:                  float = 0.5
    n_samples:                   int = 0

    def traction_accel(self, speed: float) -> float:
        """Max traction acceleration [m/s²] at *speed*, power-limited."""
        v = max(speed, _MIN_SPEED_MPS)
        # Interpolate from the fitted envelope
        a_envelope = float(np.interp(v, self.v_knots, self.traction_force_per_kg))
        # Also apply power limit: a = P / (m·v)
        if self.estimated_peak_power_w_per_kg > 0 and v > _MIN_SPEED_MPS:
            p_at_v = float(np.interp(v, self.v_knots, self.power_envelope_w_per_kg))
            a_power = p_at_v / v
            a_envelope = min(a_envelope, a_power)
        return max(a_envelope, 0.0)

    def braking_decel(self, speed: float) -> float:
        """Max braking deceleration [m/s²] (positive) at *speed*."""
        v = max(speed, _MIN_SPEED_MPS)
        return max(float(np.interp(v, self.v_knots, self.braking_force_per_kg)), 0.1)

    def drag_accel(self, speed: float) -> float:
        """Aerodynamic drag deceleration [m/s²] at *speed*."""
        return self.aero_drag_coeff * speed * speed

    def downforce_grip_boost(self, speed: float) -> float:
        """Additional grip [m/s²] from aerodynamic downforce at *speed*."""
        # Extra normal force from downforce → extra friction
        # ΔF_grip = μ · (0.5 · CL · A · ρ · v²) → Δa = aero_df_coeff · v²
        # But with load sensitivity, the marginal μ is lower
        raw = self.aero_downforce_coeff * speed * speed
        # Apply load sensitivity: diminishing returns
        sensitivity_factor = max(1.0 - self.tire_load_sensitivity * raw / _G, 0.5)
        return raw * sensitivity_factor

    def resistance_accel(self, speed: float, grade: float = 0.0) -> float:
        """Total resistance deceleration [m/s²] (drag + rolling + grade)."""
        a_rr = self.rolling_resistance * _G
        a_drag = self.drag_accel(speed)
        a_grade = _G * math.sin(math.atan(grade)) if grade != 0.0 else 0.0
        return a_rr + a_drag + a_grade


@dataclass
class TheoreticalLapResult:
    """
    Output of the point-mass lap simulation.

    Attributes
    ----------
    speed_profile : np.ndarray
        Max achievable speed at each distance point [m/s].
    accel_profile : np.ndarray
        Longitudinal acceleration at each point [m/s²].
    lap_time_s : float
        Integrated lap time [s].
    distance_m : np.ndarray
        Distance grid [m].
    cornering_limited : np.ndarray
        Bool mask: True where speed is set by cornering grip.
    accel_limited : np.ndarray
        Bool mask: True where speed is set by traction.
    braking_limited : np.ndarray
        Bool mask: True where speed is set by braking.
    power_limited : np.ndarray
        Bool mask: True where speed is set by engine power (subset of accel).
    method : str
        ``"physics"``, ``"hybrid"``, or ``"percentile_fallback"``.
    n_wrap_iterations : int
        Number of closed-loop convergence passes used.
    vehicle_model : VehicleModel or None
        The telemetry-fitted model used (if any).
    simulation_method_detail : str
        More detailed description of the method used.
    """
    speed_profile:     np.ndarray
    accel_profile:     np.ndarray
    lap_time_s:        float
    distance_m:        np.ndarray
    cornering_limited: np.ndarray
    accel_limited:     np.ndarray
    braking_limited:   np.ndarray
    power_limited:     np.ndarray = field(default_factory=lambda: np.array([], dtype=bool))
    method:            str = "physics"
    n_wrap_iterations: int = 0
    vehicle_model:     Any = None
    simulation_method_detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = {
            "lap_time_s":    round(self.lap_time_s, 4),
            "method":        self.method,
            "n_points":      len(self.distance_m),
            "track_length_m": round(float(self.distance_m[-1] - self.distance_m[0]), 2),
            "speed_mean_mps": round(float(np.mean(self.speed_profile)), 2),
            "speed_max_mps":  round(float(np.max(self.speed_profile)), 2),
            "speed_min_mps":  round(float(np.min(self.speed_profile)), 2),
            "pct_cornering":  round(float(self.cornering_limited.mean()) * 100, 1),
            "pct_accel":      round(float(self.accel_limited.mean()) * 100, 1),
            "pct_braking":    round(float(self.braking_limited.mean()) * 100, 1),
            "n_wrap_iterations": self.n_wrap_iterations,
            "simulation_method_detail": self.simulation_method_detail,
        }
        if len(self.power_limited) > 0:
            d["pct_power_limited"] = round(float(self.power_limited.mean()) * 100, 1)
        return d


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class LapSimulationError(ValueError):
    """Raised when the simulation encounters irrecoverable issues."""


# ---------------------------------------------------------------------------
# Internal helpers — time integration, acceleration computation
# ---------------------------------------------------------------------------

def _integrate_time(distance: np.ndarray, speed: np.ndarray) -> float:
    """Trapezoidal integration of ds / v."""
    ds = np.diff(distance)
    v_avg = 0.5 * (speed[:-1] + speed[1:])
    v_avg = np.maximum(v_avg, _MIN_SPEED_MPS)
    dt = ds / v_avg
    return float(np.sum(dt[np.isfinite(dt)]))


def _compute_accel_profile(
    distance: np.ndarray,
    speed: np.ndarray,
) -> np.ndarray:
    """Compute longitudinal acceleration from speed profile: a = v·dv/ds."""
    ds = np.diff(distance)
    dv = np.diff(speed)
    with np.errstate(divide="ignore", invalid="ignore"):
        a = np.where(ds > 0, speed[:-1] * dv / ds, 0.0)
    return np.concatenate([a, [a[-1] if len(a) > 0 else 0.0]])


def _gaussian_smooth(arr: np.ndarray, half_window: int = 3) -> np.ndarray:
    """Simple 1-D Gaussian kernel smoothing (no scipy dependency)."""
    if half_window < 1 or len(arr) < 2 * half_window + 1:
        return arr.copy()
    kernel_x = np.arange(-half_window, half_window + 1, dtype=float)
    kernel = np.exp(-0.5 * (kernel_x / max(half_window / 2, 1)) ** 2)
    kernel /= kernel.sum()
    padded = np.pad(arr, half_window, mode="edge")
    return np.convolve(padded, kernel, mode="valid")[: len(arr)]


# ---------------------------------------------------------------------------
# Phase A: Telemetry-fitted vehicle model
# ---------------------------------------------------------------------------

def fit_vehicle_model(
    resampled_laps: dict[int, pd.DataFrame],
    friction: FrictionLike | None = None,
    *,
    n_speed_bins: int = 25,
    traction_percentile: float = 95.0,
    braking_percentile: float = 97.0,
    smooth_window: int = 3,
) -> VehicleModel:
    """
    Fit a vehicle performance model from telemetry data.

    Extracts the maximum observed traction and braking performance
    as a function of speed, plus a power envelope.  This captures
    *all* real-world limitations: engine power curve, gearing,
    traction control, brake fade, aero effects.

    Parameters
    ----------
    resampled_laps : dict[int, pd.DataFrame]
        Resampled lap data with speed and acceleration columns.
    friction : FrictionLike or None
        If provided, used to set physical upper bounds on fitted values.
    n_speed_bins : int
        Number of speed bins for the envelope.
    traction_percentile : float
        Percentile for traction envelope extraction.
    braking_percentile : float
        Percentile for braking envelope extraction.

    Returns
    -------
    VehicleModel
    """
    # Collect (speed, accel) pairs from all laps
    speeds_all: list[float] = []
    accels_all: list[float] = []

    speed_col = None
    accel_col = None

    for lap_df in resampled_laps.values():
        # Detect column names
        if speed_col is None:
            for c in ("speed_mps", "Speed (m/s)"):
                if c in lap_df.columns:
                    speed_col = c
                    break
            for c in ("accel_long_mps2", "accel_long"):
                if c in lap_df.columns:
                    accel_col = c
                    break

        if speed_col is None or accel_col is None:
            continue
        if speed_col not in lap_df.columns or accel_col not in lap_df.columns:
            continue

        v = pd.to_numeric(lap_df[speed_col], errors="coerce").values
        a = pd.to_numeric(lap_df[accel_col], errors="coerce").values
        mask = np.isfinite(v) & np.isfinite(a) & (v > _MIN_SPEED_MPS)
        speeds_all.extend(v[mask].tolist())
        accels_all.extend(a[mask].tolist())

    speeds = np.array(speeds_all, dtype=float)
    accels = np.array(accels_all, dtype=float)

    if len(speeds) < 50:
        logger.warning(
            "Only %d (speed, accel) samples — insufficient for vehicle model.",
            len(speeds),
        )
        return _default_vehicle_model(friction)

    # Build velocity grid
    v_min = max(float(np.percentile(speeds, 2)), _MIN_SPEED_MPS)
    v_max = float(np.percentile(speeds, 99))
    if v_max <= v_min:
        v_max = v_min + 10.0
    v_knots = np.linspace(v_min, v_max, n_speed_bins)

    # Bin observations by speed
    bin_indices = np.searchsorted(v_knots, speeds) - 1
    bin_indices = np.clip(bin_indices, 0, n_speed_bins - 1)

    traction_env = np.full(n_speed_bins, np.nan)
    braking_env = np.full(n_speed_bins, np.nan)
    power_env = np.full(n_speed_bins, np.nan)

    for b in range(n_speed_bins):
        mask_b = bin_indices == b
        if mask_b.sum() < 5:
            continue

        a_bin = accels[mask_b]
        v_bin = speeds[mask_b]

        # Traction: positive accelerations
        a_pos = a_bin[a_bin > 0.1]
        if len(a_pos) >= 3:
            traction_env[b] = float(np.percentile(a_pos, traction_percentile))

        # Braking: negative accelerations (store as positive)
        a_neg = a_bin[a_bin < -0.1]
        if len(a_neg) >= 3:
            braking_env[b] = float(np.percentile(np.abs(a_neg), braking_percentile))

        # Power envelope: P/m = (a + Crr·g + Cd_factor·v²) · v
        # Use force-balance rather than simple a·v to capture true engine power.
        # This accounts for rolling resistance and aero drag that the engine
        # must overcome, yielding a more accurate peak power estimate.
        if len(a_pos) >= 3:
            v_pos = v_bin[a_bin > 0.1]
            _Crr_g = 0.015 * _G  # rolling resistance (~0.15 m/s²)
            _Cd_fac = 0.002      # ≈ 0.5·CdA·ρ/m for karts
            f_per_m = a_pos + _Crr_g + _Cd_fac * v_pos ** 2
            p_samples = f_per_m * v_pos
            power_env[b] = float(np.percentile(p_samples, traction_percentile))

    # Interpolate NaN gaps
    for arr in (traction_env, braking_env, power_env):
        valid = np.isfinite(arr)
        if valid.sum() >= 2:
            arr[~valid] = np.interp(
                v_knots[~valid], v_knots[valid], arr[valid]
            )
        elif valid.sum() == 1:
            arr[:] = arr[valid][0]

    # Apply physical upper bounds from friction model
    if friction is not None:
        trac_max = np.asarray(friction.traction_max(v_knots), dtype=float).ravel()
        brake_max = np.asarray(friction.braking_max(v_knots), dtype=float).ravel()
        # The telemetry envelope can't exceed the friction circle limit
        valid_t = np.isfinite(traction_env)
        valid_b = np.isfinite(braking_env)
        traction_env[valid_t] = np.minimum(traction_env[valid_t],
                                           trac_max[valid_t] * 1.05)
        braking_env[valid_b] = np.minimum(braking_env[valid_b],
                                          brake_max[valid_b] * 1.05)

    # Handle any remaining NaN
    traction_env = np.where(np.isfinite(traction_env), traction_env, 3.0)
    braking_env = np.where(np.isfinite(braking_env), braking_env, 8.0)
    power_env = np.where(np.isfinite(power_env), power_env, 0.0)

    # Clip to physical limits
    traction_env = np.clip(traction_env, 0.5, 50.0)
    braking_env = np.clip(braking_env, 1.0, 50.0)
    power_env = np.clip(power_env, 0.0, 5000.0)

    # Smooth
    traction_env = _gaussian_smooth(traction_env, smooth_window)
    braking_env = _gaussian_smooth(braking_env, smooth_window)
    power_env = _gaussian_smooth(power_env, smooth_window)

    # Estimate peak power/mass
    peak_power = float(np.max(power_env)) if np.any(power_env > 0) else 0.0

    # Estimate aero drag coefficient from high-speed deceleration
    # At high speed on straights, coasting decel ≈ Cd·A·ρ/(2m) · v²
    aero_drag = _estimate_aero_drag(speeds, accels, v_max)

    # Estimate downforce from cornering at different speeds
    aero_downforce = _estimate_aero_downforce(speeds, accels, v_knots, friction)

    # Estimate tire load sensitivity
    load_sens = _estimate_load_sensitivity(speeds, accels, v_knots, friction)

    # Confidence metric: how many bins are well-populated?
    well_populated = sum(
        1 for b in range(n_speed_bins)
        if (bin_indices == b).sum() >= 10
    )
    confidence = min(well_populated / n_speed_bins, 1.0)

    logger.info(
        "Vehicle model fitted: %d samples, %d/%d bins populated, "
        "peak_power=%.0f W/kg, Cd_factor=%.4f, CL_factor=%.4f, "
        "load_sens=%.3f, confidence=%.2f",
        len(speeds), well_populated, n_speed_bins,
        peak_power, aero_drag, aero_downforce, load_sens, confidence,
    )

    return VehicleModel(
        v_knots=v_knots,
        traction_force_per_kg=traction_env,
        braking_force_per_kg=braking_env,
        power_envelope_w_per_kg=power_env,
        estimated_peak_power_w_per_kg=peak_power,
        aero_drag_coeff=aero_drag,
        aero_downforce_coeff=aero_downforce,
        rolling_resistance=0.015,
        tire_load_sensitivity=load_sens,
        confidence=confidence,
        n_samples=len(speeds),
    )


def _default_vehicle_model(friction: FrictionLike | None) -> VehicleModel:
    """Return a conservative default model when telemetry is insufficient."""
    v_knots = np.linspace(2.0, 50.0, 15)

    if friction is not None:
        trac = np.asarray(friction.traction_max(v_knots), dtype=float).ravel()
        brake = np.asarray(friction.braking_max(v_knots), dtype=float).ravel()
    else:
        trac = np.full(15, 5.0)
        brake = np.full(15, 10.0)

    power = trac * v_knots  # P = F·v / m

    return VehicleModel(
        v_knots=v_knots,
        traction_force_per_kg=trac,
        braking_force_per_kg=brake,
        power_envelope_w_per_kg=power,
        estimated_peak_power_w_per_kg=float(np.max(power)),
        confidence=0.2,
    )


def _estimate_aero_drag(
    speeds: np.ndarray,
    accels: np.ndarray,
    v_max: float,
) -> float:
    """Estimate aero drag coefficient 0.5·Cd·A·ρ/m from high-speed data."""
    # At high speed, look at mild deceleration events (coasting / partial throttle)
    # These should correlate with v² (drag-dominated)
    high_speed_mask = speeds > v_max * 0.7
    mild_decel_mask = (accels < -0.5) & (accels > -5.0)
    mask = high_speed_mask & mild_decel_mask

    if mask.sum() < 10:
        return 0.0  # Not enough data to estimate

    v_sq = speeds[mask] ** 2
    a_decel = np.abs(accels[mask])

    # Simple regression: a_decel ≈ Crr·g + Cd_factor · v²
    # Least squares for Cd_factor
    if v_sq.std() < 1.0:
        return 0.0

    # Remove rolling resistance baseline
    a_baseline = float(np.percentile(a_decel, 10))  # ≈ Crr·g
    a_aero = np.maximum(a_decel - a_baseline, 0.0)

    with np.errstate(divide="ignore", invalid="ignore"):
        cd_estimates = a_aero / np.maximum(v_sq, 1.0)

    cd_factor = float(np.median(cd_estimates[cd_estimates > 0]))
    if not math.isfinite(cd_factor):
        return 0.0

    return max(min(cd_factor, 0.05), 0.0)  # Reasonable range


def _estimate_aero_downforce(
    speeds: np.ndarray,
    accels: np.ndarray,
    v_knots: np.ndarray,
    friction: FrictionLike | None,
) -> float:
    """Estimate downforce coefficient from speed-dependent lateral grip increase."""
    if friction is None:
        return 0.0

    # Compare lateral grip at low speed vs high speed
    # If grip increases with v², there's downforce
    lat_low = float(np.mean(np.asarray(friction.lateral_max(v_knots[:3]))))
    lat_high = float(np.mean(np.asarray(friction.lateral_max(v_knots[-3:]))))
    v_low = float(np.mean(v_knots[:3]))
    v_high = float(np.mean(v_knots[-3:]))

    if lat_high > lat_low and v_high > v_low:
        # Δa_lat ≈ CL_factor · (v_high² - v_low²)
        delta_a = lat_high - lat_low
        delta_v_sq = v_high ** 2 - v_low ** 2
        if delta_v_sq > 10:
            cl_factor = delta_a / delta_v_sq
            return max(min(cl_factor, 0.05), 0.0)

    return 0.0


def _estimate_load_sensitivity(
    speeds: np.ndarray,
    accels: np.ndarray,
    v_knots: np.ndarray,
    friction: FrictionLike | None,
) -> float:
    """Estimate tire load sensitivity from grip vs speed variation."""
    # Higher speed → more aero load → if grip/weight ratio decreases, there's
    # load sensitivity.  For karts/low-aero cars, this is small.
    if friction is None:
        return 0.08  # Default

    lat_vals = np.asarray(friction.lateral_max(v_knots), dtype=float).ravel()
    if len(lat_vals) < 5:
        return 0.08

    # If lateral grip is roughly constant, load sensitivity is low
    # If it varies significantly, estimate from the variation
    cv = float(np.std(lat_vals) / max(np.mean(lat_vals), 1.0))
    # Map coefficient of variation to load sensitivity
    return max(min(cv * 0.5, 0.20), 0.03)


# ---------------------------------------------------------------------------
# Phase B: Forward-backward simulation
# ---------------------------------------------------------------------------

def _cornering_speed_profile(
    distance: np.ndarray,
    curvature: np.ndarray,
    friction: FrictionLike,
    *,
    vehicle_model: VehicleModel | None = None,
    max_speed: float = _MAX_SPEED_MPS,
) -> np.ndarray:
    """
    STEP 1: Compute maximum speed at each point from cornering grip.

    With downforce: effective lateral grip increases with v², but the speed
    limit still comes from the friction ellipse / curvature relationship.
    """
    n = len(distance)
    v_corner = np.full(n, max_speed, dtype=float)

    for i in range(n):
        k = float(curvature[i])
        if k > 1e-6:
            # Base cornering speed from friction model
            v = friction.max_cornering_speed(k)
            v = min(max(v, _MIN_SPEED_MPS), max_speed)

            # If we have a vehicle model with downforce, iterate to find
            # the speed where a_lat_avail(v) = v²·κ
            if vehicle_model is not None and vehicle_model.aero_downforce_coeff > 0:
                for _ in range(4):
                    # Extra grip from downforce
                    df_boost = vehicle_model.downforce_grip_boost(v)
                    a_lat_total = float(np.asarray(friction.lateral_max(v)).ravel()[0]) + df_boost
                    if a_lat_total <= 0:
                        break
                    v_new = math.sqrt(a_lat_total / k)
                    v_new = min(max(v_new, _MIN_SPEED_MPS), max_speed)
                    if abs(v_new - v) < 0.01:
                        break
                    v = v_new

            v_corner[i] = v

    return v_corner


def _find_apex_points(v_corner: np.ndarray, curvature: np.ndarray) -> np.ndarray:
    """
    Find apex points — local minima of the cornering speed profile.

    These are the critical points from which we seed the forward and
    backward passes, ensuring physically correct brake-turn-accelerate
    sequencing.

    Returns
    -------
    np.ndarray of int
        Indices of apex points, sorted by distance.
    """
    n = len(v_corner)
    if n < 3:
        return np.array([0])

    apices: list[int] = []

    # A point is an apex if it's a local minimum and curvature is non-trivial
    for i in range(1, n - 1):
        if curvature[i] > 1e-6:  # In a corner
            if v_corner[i] <= v_corner[i - 1] and v_corner[i] <= v_corner[i + 1]:
                apices.append(i)

    # Also add the global minimum as an apex
    min_idx = int(np.argmin(v_corner))
    if min_idx not in apices:
        apices.append(min_idx)

    # Add points where curvature transitions from 0 to high
    # (corner entries — important for closed tracks)
    for i in range(1, n):
        if curvature[i] > 0.005 and curvature[i - 1] < 0.001:
            # Find the peak curvature in this corner segment
            j = i
            while j < n - 1 and curvature[j + 1] >= curvature[j] * 0.5:
                j += 1
            mid = (i + j) // 2
            if mid not in apices:
                apices.append(mid)

    if not apices:
        apices = [0]

    return np.array(sorted(set(apices)))


def _forward_pass(
    distance: np.ndarray,
    curvature: np.ndarray,
    v_corner: np.ndarray,
    friction: FrictionLike,
    v_start: float,
    *,
    vehicle_model: VehicleModel | None = None,
    grade: np.ndarray | None = None,
    rolling_resistance: float = 0.015,
    aero_drag_factor: float = 0.0,
    mass_kg: float = 1.0,
) -> np.ndarray:
    """
    STEP 2: Forward pass — acceleration-limited speed profile.

    Starting from v_start, integrate forward. At each step:
      v²_next = v²_curr + 2·a_net·ds

    where a_net is the *minimum* of:
      - Friction-circle-limited traction (grip limit)
      - Power-limited acceleration: a = P(v) / (m·v)
      - Telemetry-fitted traction envelope

    minus resistances (drag, rolling resistance, grade).
    """
    n = len(distance)
    v_fwd = np.full(n, v_start, dtype=float)
    v_fwd[0] = min(v_start, v_corner[0])

    for i in range(n - 1):
        ds = distance[i + 1] - distance[i]
        if ds <= 0:
            v_fwd[i + 1] = v_fwd[i]
            continue

        v_cur = v_fwd[i]

        # --- Lateral grip consumed by cornering ---
        k_cur = float(curvature[i])
        a_lat_used = v_cur * v_cur * k_cur if k_cur > 0 else 0.0

        # --- Available traction from friction ellipse ---
        a_grip = friction.max_longitudinal_accel(
            v_cur, a_lat_used, braking=False,
        )

        # --- Power-limited acceleration ---
        a_power = float("inf")
        if vehicle_model is not None:
            # Telemetry-fitted traction (includes power limits)
            a_fitted = vehicle_model.traction_accel(v_cur)
            # Add downforce-enhanced grip
            df_boost = vehicle_model.downforce_grip_boost(v_cur)
            a_grip_boosted = a_grip + df_boost * 0.3  # Fraction goes to traction
            # Use the minimum of fitted and grip-limited
            a_power = a_fitted

        # The actual available acceleration is the min of grip and power
        a_traction = min(a_grip, a_power)

        # --- Subtract resistances ---
        g_val = 0.0
        if grade is not None and i < len(grade):
            g_val = float(grade[i])
            if not math.isfinite(g_val):
                g_val = 0.0

        if vehicle_model is not None:
            a_resist = vehicle_model.resistance_accel(v_cur, g_val)
        else:
            a_resist = rolling_resistance * _G
            if g_val != 0.0:
                a_resist += _G * math.sin(math.atan(g_val))
            if aero_drag_factor > 0:
                a_resist += aero_drag_factor * v_cur * v_cur

        a_net = max(a_traction - a_resist, 0.0)

        # --- Integrate: v²_next = v²_curr + 2·a·ds ---
        v_sq_next = v_cur * v_cur + 2.0 * a_net * ds
        v_next = math.sqrt(max(v_sq_next, _MIN_SPEED_MPS ** 2))

        # Cap at cornering limit
        v_fwd[i + 1] = min(v_next, v_corner[i + 1])

    return v_fwd


def _backward_pass(
    distance: np.ndarray,
    curvature: np.ndarray,
    v_corner: np.ndarray,
    friction: FrictionLike,
    v_end: float,
    *,
    vehicle_model: VehicleModel | None = None,
    grade: np.ndarray | None = None,
    rolling_resistance: float = 0.015,
    aero_drag_factor: float = 0.0,
    mass_kg: float = 1.0,
) -> np.ndarray:
    """
    STEP 3: Backward pass — braking-limited speed profile.

    Starting from v_end, integrate backward. At each step:
      v²_prev = v²_next + 2·a_brake_total·ds

    Braking includes:
      - Friction-circle-limited braking
      - Telemetry-fitted braking envelope
      - Aero drag (assists braking)
      - Rolling resistance (assists braking)
      - Grade effects
    """
    n = len(distance)
    v_bwd = np.full(n, v_end, dtype=float)
    v_bwd[-1] = min(v_end, v_corner[-1])

    for i in range(n - 2, -1, -1):
        ds = distance[i + 1] - distance[i]
        if ds <= 0:
            v_bwd[i] = v_bwd[i + 1]
            continue

        v_next = v_bwd[i + 1]

        # --- Lateral grip consumed by cornering ---
        k_next = float(curvature[i + 1])
        a_lat_used = v_next * v_next * k_next if k_next > 0 else 0.0

        # --- Available braking from friction ellipse ---
        a_brake = friction.max_longitudinal_accel(
            v_next, a_lat_used, braking=True,
        )

        # --- Telemetry-fitted braking ---
        if vehicle_model is not None:
            a_fitted_brake = vehicle_model.braking_decel(v_next)
            # Use the minimum of fitted and grip-limited
            a_brake = min(a_brake, a_fitted_brake)

        # --- Resistances HELP braking (they decelerate the car) ---
        g_val = 0.0
        if grade is not None and i + 1 < len(grade):
            g_val = float(grade[i + 1])
            if not math.isfinite(g_val):
                g_val = 0.0

        if vehicle_model is not None:
            # For braking, resistance assists: grade component is inverted
            a_assist = vehicle_model.resistance_accel(v_next, g_val)
        else:
            a_assist = rolling_resistance * _G
            if g_val != 0.0:
                a_assist += _G * math.sin(math.atan(g_val))
            if aero_drag_factor > 0:
                a_assist += aero_drag_factor * v_next * v_next

        a_total_brake = a_brake + a_assist

        # --- Integrate backward: v²_prev = v²_next + 2·a_brake·ds ---
        v_sq_prev = v_next * v_next + 2.0 * a_total_brake * ds
        v_prev = math.sqrt(max(v_sq_prev, _MIN_SPEED_MPS ** 2))

        # Cap at cornering limit
        v_bwd[i] = min(v_prev, v_corner[i])

    return v_bwd


def _apex_seeded_forward_backward(
    distance: np.ndarray,
    curvature: np.ndarray,
    v_corner: np.ndarray,
    friction: FrictionLike,
    apices: np.ndarray,
    **pass_kwargs: Any,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Run forward pass from each apex and backward pass into each apex,
    then combine into acceleration-limited and braking-limited profiles.

    This is more robust than a single global forward-backward because
    it handles multi-apex tracks correctly from the start.
    """
    n = len(distance)
    v_fwd_global = np.full(n, _MAX_SPEED_MPS, dtype=float)
    v_bwd_global = np.full(n, _MAX_SPEED_MPS, dtype=float)

    # Forward from each apex (acceleration out of corners)
    for apex_idx in apices:
        v_start = float(v_corner[apex_idx])
        v_fwd = _forward_pass(
            distance, curvature, v_corner, friction, v_start,
            **pass_kwargs,
        )
        # Only use the forward pass from this apex onward
        v_fwd_global = np.minimum(v_fwd_global, v_fwd)

    # Backward into each apex (braking into corners)
    for apex_idx in apices:
        v_end = float(v_corner[apex_idx])
        v_bwd = _backward_pass(
            distance, curvature, v_corner, friction, v_end,
            **pass_kwargs,
        )
        v_bwd_global = np.minimum(v_bwd_global, v_bwd)

    return v_fwd_global, v_bwd_global


# ---------------------------------------------------------------------------
# Public API — simulate_theoretical_lap
# ---------------------------------------------------------------------------

def simulate_theoretical_lap(
    curvature_profile: pd.DataFrame,
    friction: FrictionLike,
    *,
    vehicle_model: VehicleModel | None = None,
    grade_profile: np.ndarray | None = None,
    rolling_resistance: float = 0.015,
    aero_drag_factor: float = 0.0,
    mass_kg: float = 1.0,
    max_speed_mps: float = _MAX_SPEED_MPS,
    closed_loop: bool = True,
    grip_map: GripMap | None = None,
    friction_envelope: FrictionEnvelope | None = None,
) -> TheoreticalLapResult:
    """
    Simulate the fastest physically possible lap time.

    Uses a multi-constraint forward-backward solver with:
    - Cornering grip limits (friction circle + curvature)
    - Power-limited acceleration (from vehicle model or friction circle)
    - Braking limits (from vehicle model or friction circle)
    - Aerodynamic effects (drag, downforce)
    - Rolling resistance and grade
    - Apex-seeded multi-pass integration

    Parameters
    ----------
    curvature_profile : pd.DataFrame
        Must contain ``"distance_m"`` and ``"curvature_1pm"`` columns.
    friction : FrictionLike
        Friction circle model.
    vehicle_model : VehicleModel or None
        Telemetry-fitted vehicle model. If None, uses friction-only.
    grade_profile : np.ndarray or None
        Grade at each distance point [fraction]. Positive = uphill.
    rolling_resistance : float
        Rolling resistance coefficient. Default 0.015.
    aero_drag_factor : float
        Combined aero drag: 0.5·Cd·A·ρ/m. Default 0.
    mass_kg : float
        Vehicle mass [kg].
    max_speed_mps : float
        Absolute speed cap [m/s].
    closed_loop : bool
        If True, iterate to converge wrap-around speed.

    Returns
    -------
    TheoreticalLapResult
    """
    # --- Validate inputs ---
    if curvature_profile is None or len(curvature_profile) < 3:
        raise LapSimulationError(
            "Curvature profile must have at least 3 points."
        )

    dist_col = "distance_m"
    curv_col = "curvature_1pm"

    if dist_col not in curvature_profile.columns:
        raise LapSimulationError(f"Missing column '{dist_col}'.")
    if curv_col not in curvature_profile.columns:
        raise LapSimulationError(f"Missing column '{curv_col}'.")

    distance = pd.to_numeric(
        curvature_profile[dist_col], errors="coerce"
    ).values.astype(float)
    curvature = pd.to_numeric(
        curvature_profile[curv_col], errors="coerce"
    ).values.astype(float)

    # Replace NaN curvature with 0 (straight)
    curvature = np.where(np.isfinite(curvature), curvature, 0.0)
    curvature = np.abs(curvature)

    n = len(distance)

    # Use vehicle model's aero/rr if available
    if vehicle_model is not None:
        if vehicle_model.aero_drag_coeff > 0:
            aero_drag_factor = max(aero_drag_factor, vehicle_model.aero_drag_coeff)
        rolling_resistance = vehicle_model.rolling_resistance

    # --- STEP 1: Cornering speed limit ---
    v_corner = _cornering_speed_profile(
        distance, curvature, friction,
        vehicle_model=vehicle_model,
        max_speed=max_speed_mps,
    )

    # --- STEP 1b: Grip-map override (per-distance mu) ---
    if grip_map is not None and not grip_map.is_global_fallback:
        for i in range(n):
            k = float(curvature[i])
            if k > 1e-6:
                mu_at_dist = grip_map.mu_at(float(distance[i]), "p95")
                v_grip = math.sqrt(mu_at_dist * _G / k)
                v_grip = min(max(v_grip, _MIN_SPEED_MPS), max_speed_mps)
                v_corner[i] = min(v_corner[i], v_grip)

    # --- Find apex points ---
    apices = _find_apex_points(v_corner, curvature)

    # --- Shared kwargs for forward/backward passes ---
    pass_kwargs = dict(
        vehicle_model=vehicle_model,
        grade=grade_profile,
        rolling_resistance=rolling_resistance,
        aero_drag_factor=aero_drag_factor,
        mass_kg=mass_kg,
    )

    # --- STEPS 2-4: Apex-seeded forward-backward ---
    # First do apex-seeded passes
    v_fwd_apex, v_bwd_apex = _apex_seeded_forward_backward(
        distance, curvature, v_corner, friction, apices,
        **pass_kwargs,
    )

    # Initial combined profile
    v_start = min(float(v_corner[0]), float(v_fwd_apex[0]), float(v_bwd_apex[0]))
    n_iter = 0

    for iteration in range(_WRAP_ITERATIONS if closed_loop else 1):
        n_iter = iteration + 1

        # STEP 2: Global forward pass
        v_fwd = _forward_pass(
            distance, curvature, v_corner, friction, v_start,
            **pass_kwargs,
        )

        # STEP 3: Global backward pass (start from forward-pass end speed)
        v_end = float(v_fwd[-1])
        v_bwd = _backward_pass(
            distance, curvature, v_corner, friction, v_end,
            **pass_kwargs,
        )

        # STEP 4: Combine all constraints — minimum of everything
        v_final = np.minimum(
            np.minimum(np.minimum(v_fwd, v_bwd), v_corner),
            np.minimum(v_fwd_apex, v_bwd_apex),
        )

        # Enforce bounds
        v_final = np.clip(v_final, _MIN_SPEED_MPS, max_speed_mps)

        if not closed_loop:
            break

        # Closed-loop convergence: wrap-around speed consistency
        v_start_new = float(v_final[-1])
        delta = abs(v_start_new - v_start)
        if delta < _WRAP_TOL_MPS:
            logger.debug(
                "Closed-loop converged in %d iteration(s) (Δv=%.3f m/s).",
                n_iter, delta,
            )
            break

        # Damped update for stability
        v_start = 0.6 * v_start_new + 0.4 * v_start

    # --- STEP 4b: Friction envelope clamp ---
    if friction_envelope is not None and friction_envelope.is_reliable:
        accel_pre = _compute_accel_profile(distance, v_final)
        for i in range(n):
            k = float(curvature[i])
            if k < 1e-6:
                continue
            a_lat_g = float(v_final[i]) ** 2 * k / _G
            a_long_g = float(accel_pre[i]) / _G
            if not friction_envelope.is_feasible(
                float(v_final[i]), a_lat_g, a_long_g,
            ):
                max_lat_g = friction_envelope.max_lat_at_long(
                    float(v_final[i]), a_long_g,
                )
                max_v = math.sqrt(max_lat_g * _G / k)
                max_v = min(max(max_v, _MIN_SPEED_MPS), max_speed_mps)
                v_final[i] = min(float(v_final[i]), max_v)

    # --- STEP 5: Classify limiting factor at each point ---
    tol = 0.05  # m/s tolerance for classification
    cornering_limited = (v_final >= v_corner - tol) & (curvature > 1e-6)

    # Power-limited: where the vehicle model's power limit is binding
    power_limited = np.zeros(n, dtype=bool)
    if vehicle_model is not None:
        for i in range(n):
            if not cornering_limited[i]:
                v = v_final[i]
                a_grip = friction.max_longitudinal_accel(v, 0.0, braking=False)
                a_power = vehicle_model.traction_accel(v)
                if a_power < a_grip * 0.95:
                    power_limited[i] = True

    accel_limited_raw = (v_final >= v_fwd - tol) & ~cornering_limited
    accel_limited = accel_limited_raw & ~power_limited
    braking_limited = ~cornering_limited & ~accel_limited & ~power_limited

    # --- STEP 6: Compute acceleration profile and lap time ---
    accel_profile = _compute_accel_profile(distance, v_final)
    lap_time = _integrate_time(distance, v_final)

    method = "hybrid" if vehicle_model is not None else "physics"
    detail_parts = ["friction_ellipse"]
    if vehicle_model is not None:
        detail_parts.append("telemetry_fitted_power")
        if vehicle_model.aero_drag_coeff > 0:
            detail_parts.append("aero_drag")
        if vehicle_model.aero_downforce_coeff > 0:
            detail_parts.append("aero_downforce")
        if vehicle_model.tire_load_sensitivity > 0.05:
            detail_parts.append("tire_load_sensitivity")
    if grade_profile is not None:
        detail_parts.append("grade_profile")
    detail = "+".join(detail_parts)

    track_length = float(distance[-1] - distance[0])
    logger.info(
        "Lap simulation [%s]: %.2f s (%.1f m track, mean %.1f m/s, "
        "%.0f%% corner / %.0f%% accel / %.0f%% brake / %.0f%% power, "
        "%d iterations).",
        method, lap_time, track_length, float(np.mean(v_final)),
        cornering_limited.mean() * 100,
        accel_limited.mean() * 100,
        braking_limited.mean() * 100,
        power_limited.mean() * 100,
        n_iter,
    )

    return TheoreticalLapResult(
        speed_profile=v_final,
        accel_profile=accel_profile,
        lap_time_s=lap_time,
        distance_m=distance,
        cornering_limited=cornering_limited,
        accel_limited=accel_limited,
        braking_limited=braking_limited,
        power_limited=power_limited,
        method=method,
        n_wrap_iterations=n_iter,
        vehicle_model=vehicle_model,
        simulation_method_detail=detail,
    )


# ---------------------------------------------------------------------------
# Public API — result_to_theoretical_df
# ---------------------------------------------------------------------------

def result_to_theoretical_df(result: TheoreticalLapResult) -> pd.DataFrame:
    """
    Convert a TheoreticalLapResult to the DataFrame format expected by
    ``pipeline._theoretical_metrics_from_lap``.

    Columns: ``distance_m``, ``v_env_mps``, ``accel_max_mps2``,
    ``brake_max_mps2``.
    """
    accel = result.accel_profile.copy()
    accel_pos = np.where(accel > 0, accel, 0.0)
    brake_pos = np.where(accel < 0, np.abs(accel), 0.0)

    return pd.DataFrame({
        _OUT_DIST:  result.distance_m,
        _OUT_SPEED: result.speed_profile,
        _OUT_ACCEL: accel_pos,
        _OUT_BRAKE: brake_pos,
    })


# ---------------------------------------------------------------------------
# Auto-calibration helpers
# ---------------------------------------------------------------------------

class _ScaledFriction:
    """Wrapper that scales all grip values from a FrictionLike by a factor.

    Delegates all attribute and method access to the base friction,
    scaling grip-related outputs by the scale factor.
    """

    def __init__(self, base_friction: "FrictionLike", scale: float):
        self._base = base_friction
        self._scale = scale

    def __getattr__(self, name):
        """Forward any attribute not explicitly defined to the base friction."""
        if name.startswith('_'):
            raise AttributeError(name)
        return getattr(self._base, name)

    def lateral_max(self, speed: float = 0.0) -> float:
        return self._base.lateral_max(speed) * self._scale

    def traction_max(self, speed: float = 0.0) -> float:
        return self._base.traction_max(speed) * self._scale

    def braking_max(self, speed: float = 0.0) -> float:
        return self._base.braking_max(speed) * self._scale

    def max_lateral_accel(self, speed: float = 0.0,
                          longitudinal_accel: float = 0.0) -> float:
        if hasattr(self._base, "max_lateral_accel"):
            return self._base.max_lateral_accel(speed, longitudinal_accel) * self._scale
        return self.lateral_max(speed)

    def max_cornering_speed(self, curvature: float,
                             longitudinal_accel: float = 0.0) -> float:
        """Compute max speed through a corner with scaled grip."""
        if curvature <= 0.0:
            return float("inf")
        # Iterative solve: v² = a_lat / κ with speed-dependent grip
        a_lat = self.max_lateral_accel(5.0, longitudinal_accel)
        if a_lat <= 0:
            return 0.0
        v = math.sqrt(a_lat / curvature)
        for _ in range(5):
            a_lat = self.max_lateral_accel(v, longitudinal_accel)
            if a_lat <= 0:
                return 0.0
            v_new = math.sqrt(a_lat / curvature)
            if abs(v_new - v) < 0.01:
                break
            v = v_new
        return v

    def combined_available(self, speed: float, lat_used: float) -> float:
        if hasattr(self._base, "combined_available"):
            return self._base.combined_available(speed, lat_used) * self._scale
        lat_max = self.lateral_max(speed)
        if lat_max <= 0:
            return 0.0
        frac = min(abs(lat_used) / lat_max, 1.0)
        return self.traction_max(speed) * math.sqrt(max(0, 1 - frac ** 2))


def _auto_calibrate_friction(
    curvature_profile,
    friction,
    *,
    vehicle_model=None,
    grade_profile=None,
    rolling_resistance=0.015,
    aero_drag_factor=0.0,
    mass_kg=1.0,
    max_speed_mps=_MAX_SPEED_MPS,
    target_time_s: float = 40.0,
    initial_sim_time: float = 50.0,
    max_iterations: int = 8,
) -> "TheoreticalLapResult | None":
    """
    Iteratively scale friction until simulated time matches target.

    Uses bisection on the grip scale factor.  Returns the best result
    or None if calibration fails.
    """
    # Estimate initial scale: v ~ sqrt(grip), t ~ dist/v ~ 1/sqrt(grip)
    # So grip_scale ≈ (initial_time / target_time)²
    scale_est = (initial_sim_time / target_time_s) ** 2
    lo_scale = 1.0           # current grip (too slow)
    hi_scale = scale_est * 1.5  # overshoot then bisect

    best_result = None
    best_error = float("inf")

    for iteration in range(max_iterations):
        mid_scale = (lo_scale + hi_scale) / 2.0
        scaled_friction = _ScaledFriction(friction, mid_scale)

        try:
            result = simulate_theoretical_lap(
                curvature_profile, scaled_friction,
                vehicle_model=vehicle_model,
                grade_profile=grade_profile,
                rolling_resistance=rolling_resistance,
                aero_drag_factor=aero_drag_factor,
                mass_kg=mass_kg,
                max_speed_mps=max_speed_mps,
            )
            error = abs(result.lap_time_s - target_time_s)

            logger.debug(
                "Calibration iter %d: scale=%.3f → %.2fs "
                "(target=%.2fs, error=%.2fs)",
                iteration, mid_scale, result.lap_time_s, target_time_s,
                error,
            )

            if error < best_error:
                best_error = error
                best_result = result
                best_result._grip_scale = mid_scale

            if result.lap_time_s > target_time_s:
                lo_scale = mid_scale  # need more grip
            else:
                hi_scale = mid_scale  # too much grip

            # Close enough (within 0.5s)
            if error < 0.5:
                break

        except Exception as exc:
            logger.debug("Calibration iter %d failed: %s", iteration, exc)
            hi_scale = mid_scale  # reduce scale

    if best_result is not None:
        logger.info(
            "Friction calibration converged: scale=%.3f, time=%.2fs "
            "(target=%.2fs, error=%.2fs).",
            getattr(best_result, '_grip_scale', 0),
            best_result.lap_time_s, target_time_s, best_error,
        )

    return best_result


# ---------------------------------------------------------------------------
# Public API — simulate_with_fallback
# ---------------------------------------------------------------------------

def simulate_with_fallback(
    resampled_laps: dict[int, pd.DataFrame],
    curvature_profile: pd.DataFrame | None,
    friction: FrictionLike | None,
    *,
    driver_best_time_s: float | None = None,
    grade_profile: np.ndarray | None = None,
    rolling_resistance: float = 0.015,
    aero_drag_factor: float = 0.0,
    mass_kg: float = 1.0,
    speed_percentile: float = 98.0,
    max_speed_mps: float = _MAX_SPEED_MPS,
    grip_map: GripMap | None = None,
    friction_envelope: FrictionEnvelope | None = None,
) -> TheoreticalLapResult:
    """
    Try physics simulation; fall back to percentile envelope if it fails.

    First attempts a hybrid simulation using a telemetry-fitted vehicle
    model.  If that fails, tries friction-only physics.  If that also
    fails, falls back to the statistical percentile envelope.

    Parameters
    ----------
    resampled_laps : dict[int, pd.DataFrame]
        Resampled lap DataFrames.
    curvature_profile : pd.DataFrame or None
        Curvature profile; None triggers fallback.
    friction : FrictionLike or None
        Friction model; None triggers fallback.
    driver_best_time_s : float or None
        Driver's actual best lap time for sanity checking.
    speed_percentile : float
        Percentile for the fallback envelope method.

    Returns
    -------
    TheoreticalLapResult
    """
    # --- Attempt 1: Hybrid simulation (telemetry-fitted + physics) ---
    if curvature_profile is not None and friction is not None:
        try:
            # Fit vehicle model from telemetry
            vehicle_model: VehicleModel | None = None
            if resampled_laps:
                try:
                    vehicle_model = fit_vehicle_model(resampled_laps, friction)
                    if vehicle_model.confidence < 0.3:
                        logger.info(
                            "Vehicle model confidence too low (%.2f), "
                            "using friction-only.",
                            vehicle_model.confidence,
                        )
                        vehicle_model = None
                except Exception as vm_exc:
                    logger.debug("Vehicle model fitting failed: %s", vm_exc)
                    vehicle_model = None

            result = simulate_theoretical_lap(
                curvature_profile, friction,
                vehicle_model=vehicle_model,
                grade_profile=grade_profile,
                rolling_resistance=rolling_resistance,
                aero_drag_factor=aero_drag_factor,
                mass_kg=mass_kg,
                max_speed_mps=max_speed_mps,
                grip_map=grip_map,
                friction_envelope=friction_envelope,
            )

            # Sanity check against driver's best
            if driver_best_time_s is not None and math.isfinite(driver_best_time_s):
                ratio = result.lap_time_s / driver_best_time_s

                if ratio < 0.60:
                    logger.warning(
                        "Simulated time (%.2fs) < 60%% of driver best "
                        "(%.2fs): model unrealistic, falling back to "
                        "percentile envelope.",
                        result.lap_time_s, driver_best_time_s,
                    )
                    return _percentile_fallback(
                        resampled_laps, speed_percentile,
                    )

                if result.lap_time_s > driver_best_time_s * 1.05:
                    # Auto-calibrate: scale friction up so theoretical ≈ 97%
                    # of driver's best (theoretical should be slightly faster).
                    target_time = driver_best_time_s * 0.97
                    logger.info(
                        "Auto-calibrating friction: sim=%.2fs > 105%% of "
                        "best=%.2fs (ratio=%.3f). Target=%.2fs.",
                        result.lap_time_s, driver_best_time_s, ratio,
                        target_time,
                    )
                    calibrated = _auto_calibrate_friction(
                        curvature_profile, friction,
                        vehicle_model=vehicle_model,
                        grade_profile=grade_profile,
                        rolling_resistance=rolling_resistance,
                        aero_drag_factor=aero_drag_factor,
                        mass_kg=mass_kg,
                        max_speed_mps=max_speed_mps,
                        target_time_s=target_time,
                        initial_sim_time=result.lap_time_s,
                    )
                    if calibrated is not None:
                        calibrated_method = "hybrid_calibrated"
                        result = TheoreticalLapResult(
                            speed_profile=calibrated.speed_profile,
                            accel_profile=calibrated.accel_profile,
                            lap_time_s=calibrated.lap_time_s,
                            distance_m=calibrated.distance_m,
                            cornering_limited=calibrated.cornering_limited,
                            accel_limited=calibrated.accel_limited,
                            braking_limited=calibrated.braking_limited,
                            power_limited=calibrated.power_limited,
                            method=calibrated_method,
                            n_wrap_iterations=calibrated.n_wrap_iterations,
                            simulation_method_detail=(
                                f"physics_calibrated_"
                                f"grip_scale={calibrated._grip_scale:.3f}"
                                if hasattr(calibrated, '_grip_scale')
                                else "physics_calibrated"
                            ),
                        )
                        logger.info(
                            "Calibrated simulation: %.2fs (target %.2fs).",
                            result.lap_time_s, target_time,
                        )

            logger.info(
                "Using %s simulation: %.2f s.",
                result.method, result.lap_time_s,
            )
            return result

        except (LapSimulationError, Exception) as exc:
            logger.warning(
                "Physics simulation failed (%s); falling back to "
                "percentile envelope.",
                exc,
            )

    # --- Fallback: percentile envelope ---
    return _percentile_fallback(resampled_laps, speed_percentile)


def _percentile_fallback(
    resampled_laps: dict[int, pd.DataFrame],
    percentile: float,
) -> TheoreticalLapResult:
    """Statistical fallback: p-th percentile speed at each distance bin."""
    if not resampled_laps:
        raise LapSimulationError("No laps available for fallback.")

    first_df = next(iter(resampled_laps.values()))
    dist_col = "Distance (m)" if "Distance (m)" in first_df.columns else "distance_m"
    speed_col = "Speed (m/s)" if "Speed (m/s)" in first_df.columns else "speed_mps"

    speed_arrays: list[np.ndarray] = []
    dist_arr: np.ndarray | None = None

    for df in resampled_laps.values():
        if dist_col in df.columns and speed_col in df.columns:
            s = pd.to_numeric(df[speed_col], errors="coerce").values
            speed_arrays.append(s)
            if dist_arr is None:
                dist_arr = pd.to_numeric(df[dist_col], errors="coerce").values

    if not speed_arrays or dist_arr is None:
        raise LapSimulationError("No valid speed/distance data for fallback.")

    n_pts = len(dist_arr)
    min_len = min(len(a) for a in speed_arrays)
    min_len = min(min_len, n_pts)
    speed_matrix = np.array([a[:min_len] for a in speed_arrays])
    dist_arr = dist_arr[:min_len]

    v_envelope = np.nanpercentile(speed_matrix, percentile, axis=0)
    v_envelope = np.maximum(v_envelope, _MIN_SPEED_MPS)

    accel_profile = _compute_accel_profile(dist_arr, v_envelope)
    lap_time = _integrate_time(dist_arr, v_envelope)

    logger.info(
        "Fallback percentile envelope (p%.0f): %.2f s.",
        percentile, lap_time,
    )

    n = len(dist_arr)
    return TheoreticalLapResult(
        speed_profile=v_envelope,
        accel_profile=accel_profile,
        lap_time_s=lap_time,
        distance_m=dist_arr,
        cornering_limited=np.zeros(n, dtype=bool),
        accel_limited=np.zeros(n, dtype=bool),
        braking_limited=np.zeros(n, dtype=bool),
        power_limited=np.zeros(n, dtype=bool),
        method="percentile_fallback",
        n_wrap_iterations=0,
        simulation_method_detail="statistical_percentile",
    )


# ============================================================================
# Inline tests
# ============================================================================

def _run_tests() -> None:
    """
    Inline unit tests using synthetic data.
    Raises AssertionError on failure; prints a pass/fail summary.
    """
    import traceback
    from dataclasses import dataclass as _dc

    passed: list[str] = []
    failed: list[tuple[str, str]] = []

    def _test(name: str, fn) -> None:
        try:
            fn()
            passed.append(name)
        except Exception:
            failed.append((name, traceback.format_exc()))

    # -------------------------------------------------------------------
    # Lightweight friction model for testing
    # -------------------------------------------------------------------

    @_dc
    class SimpleFriction:
        """Constant-grip friction circle for testing."""
        lateral_g: float = 1.2
        traction_g: float = 0.8
        braking_g: float = 1.5
        exponent: float = 2.0

        def lateral_max(self, speed):
            return np.full_like(np.asarray(speed, dtype=float),
                                self.lateral_g * _G)

        def traction_max(self, speed):
            return np.full_like(np.asarray(speed, dtype=float),
                                self.traction_g * _G)

        def braking_max(self, speed):
            return np.full_like(np.asarray(speed, dtype=float),
                                self.braking_g * _G)

        def max_cornering_speed(self, curvature, longitudinal_accel=0.0):
            if curvature <= 0:
                return float("inf")
            a_lat = self.lateral_g * _G
            if longitudinal_accel != 0.0:
                a_x_max = (self.traction_g if longitudinal_accel > 0
                           else self.braking_g) * _G
                p = self.exponent
                ratio = min(abs(longitudinal_accel) / a_x_max, 1.0)
                a_lat = a_lat * max(0.0, (1.0 - ratio ** p)) ** (1.0 / p)
            if a_lat <= 0:
                return 0.0
            return math.sqrt(a_lat / curvature)

        def max_longitudinal_accel(self, speed, lateral_accel=0.0,
                                   *, braking=False):
            a_x_max = (self.braking_g if braking else self.traction_g) * _G
            a_y_max = self.lateral_g * _G
            if lateral_accel == 0.0 or a_y_max <= 0:
                return a_x_max
            p = self.exponent
            ratio = min(abs(lateral_accel) / a_y_max, 1.0)
            return a_x_max * max(0.0, (1.0 - ratio ** p)) ** (1.0 / p)

    # -------------------------------------------------------------------
    # Test fixtures
    # -------------------------------------------------------------------

    RADIUS = 50.0
    CURVATURE = 1.0 / RADIUS
    TRACK_LENGTH = 2.0 * math.pi * RADIUS
    FRICTION = SimpleFriction(lateral_g=1.2)

    V_MAX_ANALYTICAL = math.sqrt(1.2 * _G * RADIUS)
    LAP_TIME_ANALYTICAL = TRACK_LENGTH / V_MAX_ANALYTICAL

    def _make_circular_track(n_pts: int = 500) -> pd.DataFrame:
        dist = np.linspace(0, TRACK_LENGTH, n_pts)
        curv = np.full(n_pts, CURVATURE)
        return pd.DataFrame({
            "distance_m": dist,
            "curvature_1pm": curv,
        })

    def _make_oval_track(
        n_pts: int = 1000,
        straight_len: float = 200.0,
        corner_radius: float = 50.0,
    ) -> pd.DataFrame:
        corner_len = math.pi * corner_radius
        total = 2 * straight_len + 2 * corner_len
        dist = np.linspace(0, total, n_pts)
        curv = np.zeros(n_pts)
        for i, d in enumerate(dist):
            frac = d % total
            if frac < straight_len:
                curv[i] = 0.0
            elif frac < straight_len + corner_len:
                curv[i] = 1.0 / corner_radius
            elif frac < 2 * straight_len + corner_len:
                curv[i] = 0.0
            else:
                curv[i] = 1.0 / corner_radius
        return pd.DataFrame({
            "distance_m": dist,
            "curvature_1pm": curv,
        })

    # -------------------------------------------------------------------
    # Test 1 — circular track: known analytical solution
    # -------------------------------------------------------------------

    def t_circular_analytical() -> None:
        track = _make_circular_track(500)
        result = simulate_theoretical_lap(
            track, FRICTION, rolling_resistance=0.0, closed_loop=True,
        )
        speed_mean = float(np.mean(result.speed_profile))
        assert abs(speed_mean - V_MAX_ANALYTICAL) < 0.5, (
            f"Circular track: mean speed {speed_mean:.2f} vs analytical "
            f"{V_MAX_ANALYTICAL:.2f} m/s"
        )
        assert abs(result.lap_time_s - LAP_TIME_ANALYTICAL) < 0.5, (
            f"Circular track: lap time {result.lap_time_s:.2f} vs analytical "
            f"{LAP_TIME_ANALYTICAL:.2f} s"
        )

    _test("circular_track_analytical", t_circular_analytical)

    # Test 2 — mostly cornering-limited on circular track
    def t_circular_cornering_limited() -> None:
        track = _make_circular_track(500)
        result = simulate_theoretical_lap(
            track, FRICTION, rolling_resistance=0.0,
        )
        pct_corner = float(result.cornering_limited.mean())
        assert pct_corner > 0.80, (
            f"Circular track should be >80% corner-limited, got {pct_corner*100:.1f}%"
        )

    _test("circular_cornering_limited", t_circular_cornering_limited)

    # Test 3 — oval track: straights are faster than corners
    def t_oval_speed_variation() -> None:
        track = _make_oval_track(1000)
        result = simulate_theoretical_lap(
            track, FRICTION, rolling_resistance=0.0,
        )
        curv = track["curvature_1pm"].values
        straight_mask = curv < 0.001
        corner_mask = curv > 0.01
        if straight_mask.sum() > 10 and corner_mask.sum() > 10:
            v_straight = float(np.mean(result.speed_profile[straight_mask]))
            v_corner_mean = float(np.mean(result.speed_profile[corner_mask]))
            assert v_straight > v_corner_mean

    _test("oval_straights_faster", t_oval_speed_variation)

    # Test 4 — positive lap time
    def t_positive_lap_time() -> None:
        track = _make_circular_track(200)
        result = simulate_theoretical_lap(track, FRICTION)
        assert result.lap_time_s > 0

    _test("positive_lap_time", t_positive_lap_time)

    # Test 5 — speed always >= _MIN_SPEED_MPS
    def t_speed_floor() -> None:
        track = _make_circular_track(200)
        result = simulate_theoretical_lap(track, FRICTION)
        assert (result.speed_profile >= _MIN_SPEED_MPS - 1e-6).all()

    _test("speed_floor", t_speed_floor)

    # Test 6 — method label is correct
    def t_method_label() -> None:
        track = _make_circular_track(100)
        result = simulate_theoretical_lap(track, FRICTION)
        assert result.method == "physics"

    _test("method_label_physics", t_method_label)

    # Test 7 — result_to_theoretical_df: correct columns
    def t_result_to_df_columns() -> None:
        track = _make_circular_track(100)
        result = simulate_theoretical_lap(track, FRICTION)
        df = result_to_theoretical_df(result)
        for col in (_OUT_DIST, _OUT_SPEED, _OUT_ACCEL, _OUT_BRAKE):
            assert col in df.columns, f"Missing column {col}"
        assert len(df) == 100

    _test("result_to_df_columns", t_result_to_df_columns)

    # Test 8 — pipeline compatibility
    def t_pipeline_compatibility() -> None:
        track = _make_oval_track(500)
        result = simulate_theoretical_lap(track, FRICTION)
        df = result_to_theoretical_df(result)
        dist = df["distance_m"].values
        speed = df["v_env_mps"].values
        mask = (speed > 0) & np.isfinite(speed) & np.isfinite(dist)
        ds = np.diff(dist[mask])
        invv = 1.0 / speed[mask]
        dt = 0.5 * (invv[:-1] + invv[1:]) * np.abs(ds)
        best_s = float(np.sum(dt))
        assert math.isfinite(best_s) and best_s > 0
        assert df["accel_max_mps2"].max() > 0

    _test("pipeline_compatibility", t_pipeline_compatibility)

    # Test 9 — more grip → faster lap
    def t_more_grip_faster() -> None:
        track = _make_circular_track(300)
        low = SimpleFriction(lateral_g=0.8, traction_g=0.5, braking_g=1.0)
        high = SimpleFriction(lateral_g=1.5, traction_g=1.2, braking_g=2.0)
        r_low = simulate_theoretical_lap(track, low, rolling_resistance=0.0)
        r_high = simulate_theoretical_lap(track, high, rolling_resistance=0.0)
        assert r_high.lap_time_s < r_low.lap_time_s

    _test("more_grip_faster", t_more_grip_faster)

    # Test 10 — rolling resistance slows the lap
    def t_rolling_resistance_slows() -> None:
        track = _make_oval_track(500)
        r_clean = simulate_theoretical_lap(track, FRICTION, rolling_resistance=0.0)
        r_drag = simulate_theoretical_lap(track, FRICTION, rolling_resistance=0.03)
        assert r_drag.lap_time_s > r_clean.lap_time_s

    _test("rolling_resistance_slows", t_rolling_resistance_slows)

    # Test 11 — to_dict serialisation
    def t_to_dict() -> None:
        track = _make_circular_track(100)
        result = simulate_theoretical_lap(track, FRICTION)
        d = result.to_dict()
        assert "lap_time_s" in d
        assert "method" in d
        assert d["method"] == "physics"
        assert d["pct_cornering"] + d["pct_accel"] + d["pct_braking"] > 0

    _test("to_dict_serialisation", t_to_dict)

    # Test 12 — closed_loop=False produces a result
    def t_open_loop() -> None:
        track = _make_oval_track(300)
        result = simulate_theoretical_lap(track, FRICTION, closed_loop=False)
        assert result.n_wrap_iterations == 1
        assert result.lap_time_s > 0

    _test("open_loop_produces_result", t_open_loop)

    # Test 13 — closed-loop converges
    def t_closed_loop_converges() -> None:
        track = _make_oval_track(500)
        result = simulate_theoretical_lap(track, FRICTION)
        assert result.n_wrap_iterations <= _WRAP_ITERATIONS

    _test("closed_loop_converges", t_closed_loop_converges)

    # Test 14 — pure straight: speed should increase
    def t_pure_straight() -> None:
        n = 400
        dist = np.linspace(0, 600, n)
        curv = np.zeros(n)
        corner_end = int(n * 50 / 600)
        curv[:corner_end] = 0.05
        track = pd.DataFrame({"distance_m": dist, "curvature_1pm": curv})
        result = simulate_theoretical_lap(
            track, FRICTION, rolling_resistance=0.0, closed_loop=False,
        )
        straight_start = corner_end + 5
        straight_end = int(n * 0.6)
        assert result.speed_profile[straight_end] > result.speed_profile[straight_start] + 1.0

    _test("pure_straight_acceleration", t_pure_straight)

    # Test 15 — fallback: no friction → percentile fallback
    def t_fallback_no_friction() -> None:
        dist = np.linspace(0, 300, 200)
        laps = {
            i: pd.DataFrame({
                "Distance (m)": dist,
                "Speed (m/s)": 20 + np.random.default_rng(i).normal(0, 1, 200),
            })
            for i in range(1, 6)
        }
        result = simulate_with_fallback(laps, None, None)
        assert result.method == "percentile_fallback"
        assert result.lap_time_s > 0

    _test("fallback_no_friction", t_fallback_no_friction)

    # Test 16 — fallback: unrealistic sim → percentile fallback
    def t_fallback_unrealistic() -> None:
        track = _make_circular_track(200)
        super_grip = SimpleFriction(lateral_g=5.0, traction_g=5.0, braking_g=5.0)
        dist = np.linspace(0, TRACK_LENGTH, 200)
        laps = {
            i: pd.DataFrame({
                "Distance (m)": dist,
                "Speed (m/s)": np.full(200, 15.0),
            })
            for i in range(1, 6)
        }
        result = simulate_with_fallback(
            laps, track, super_grip,
            driver_best_time_s=60.0,
        )
        assert result.method == "percentile_fallback"

    _test("fallback_unrealistic_sim", t_fallback_unrealistic)

    # Test 17 — grade profile: uphill is slower
    def t_uphill_slower() -> None:
        track = _make_oval_track(500)
        n = len(track)
        flat = np.zeros(n)
        uphill = np.full(n, 0.05)
        r_flat = simulate_theoretical_lap(track, FRICTION, grade_profile=flat)
        r_hill = simulate_theoretical_lap(track, FRICTION, grade_profile=uphill)
        assert r_hill.lap_time_s > r_flat.lap_time_s

    _test("uphill_slower", t_uphill_slower)

    # Test 18 — invalid input raises
    def t_invalid_input_raises() -> None:
        too_short = pd.DataFrame({"distance_m": [0, 1], "curvature_1pm": [0, 0]})
        try:
            simulate_theoretical_lap(too_short, FRICTION)
            raise AssertionError("Should have raised LapSimulationError")
        except LapSimulationError:
            pass

    _test("invalid_input_raises", t_invalid_input_raises)

    # Test 19 — arrays same length
    def t_arrays_same_length() -> None:
        track = _make_oval_track(800)
        result = simulate_theoretical_lap(track, FRICTION)
        n = len(result.distance_m)
        assert len(result.speed_profile) == n
        assert len(result.accel_profile) == n
        assert len(result.cornering_limited) == n
        assert len(result.accel_limited) == n
        assert len(result.braking_limited) == n

    _test("arrays_same_length", t_arrays_same_length)

    # Test 20 — deterministic: same inputs → same output
    def t_deterministic() -> None:
        track = _make_oval_track(400)
        r1 = simulate_theoretical_lap(track, FRICTION)
        r2 = simulate_theoretical_lap(track, FRICTION)
        np.testing.assert_array_equal(r1.speed_profile, r2.speed_profile)
        assert r1.lap_time_s == r2.lap_time_s

    _test("deterministic", t_deterministic)

    # Test 21 — circular track: lap time within 5% of analytical
    def t_circular_precision() -> None:
        track = _make_circular_track(1000)
        result = simulate_theoretical_lap(
            track, FRICTION, rolling_resistance=0.0,
        )
        error_pct = abs(result.lap_time_s - LAP_TIME_ANALYTICAL) / LAP_TIME_ANALYTICAL * 100
        assert error_pct < 5.0, (
            f"Lap time error {error_pct:.1f}% exceeds 5% tolerance"
        )

    _test("circular_precision_5pct", t_circular_precision)

    # Test 22 — oval: accel and braking zones exist
    def t_oval_accel_brake_zones() -> None:
        track = _make_oval_track(1000)
        result = simulate_theoretical_lap(track, FRICTION, rolling_resistance=0.0)
        assert result.accel_limited.any(), "Oval should have accel zones"
        assert result.braking_limited.any(), "Oval should have braking zones"
        assert result.cornering_limited.any(), "Oval should have cornering zones"

    _test("oval_accel_brake_zones", t_oval_accel_brake_zones)

    # Test 23 — oval: braking happens before corners
    def t_oval_brake_before_corner() -> None:
        track = _make_oval_track(1000)
        result = simulate_theoretical_lap(track, FRICTION, rolling_resistance=0.0)
        curv = track["curvature_1pm"].values
        accel = result.accel_profile
        for i in range(1, len(curv)):
            if curv[i] > 0.01 and curv[i - 1] < 0.001:
                zone = accel[max(0, i - 30):i]
                has_braking = (zone < -0.5).any()
                assert has_braking, f"Expected braking before corner entry at idx {i}"
                break

    _test("oval_brake_before_corner", t_oval_brake_before_corner)

    # Test 24 — simulate_with_fallback: physics succeeds when valid
    def t_fallback_physics_succeeds() -> None:
        track = _make_circular_track(200)
        laps = {}
        result = simulate_with_fallback(
            laps, track, FRICTION,
            driver_best_time_s=LAP_TIME_ANALYTICAL * 1.1,
        )
        assert result.method == "physics"

    _test("fallback_physics_succeeds", t_fallback_physics_succeeds)

    # Test 25 — aero drag slows the lap
    def t_aero_drag_slows() -> None:
        track = _make_oval_track(500)
        r_no_drag = simulate_theoretical_lap(track, FRICTION, aero_drag_factor=0.0)
        r_drag = simulate_theoretical_lap(track, FRICTION, aero_drag_factor=0.005)
        assert r_drag.lap_time_s > r_no_drag.lap_time_s

    _test("aero_drag_slows", t_aero_drag_slows)

    # -------------------------------------------------------------------
    # NEW TESTS for the advanced model
    # -------------------------------------------------------------------

    # Test 26 — vehicle model: power-limited acceleration is slower
    def t_power_limited_slower() -> None:
        """A power-limited vehicle should be slower than unlimited grip."""
        track = _make_oval_track(800)
        # Unlimited (grip only)
        r_grip = simulate_theoretical_lap(track, FRICTION, rolling_resistance=0.0)
        # With power limit: cap traction at low value for high speeds
        v_knots = np.linspace(2, 50, 15)
        # Power limited: constant power → a = P/(m·v) decreasing
        peak_power = 100.0  # W/kg (low)
        a_trac = np.minimum(
            np.full(15, FRICTION.traction_g * _G),
            peak_power / np.maximum(v_knots, 1.0),
        )
        vm = VehicleModel(
            v_knots=v_knots,
            traction_force_per_kg=a_trac,
            braking_force_per_kg=np.full(15, FRICTION.braking_g * _G),
            power_envelope_w_per_kg=peak_power * np.ones(15),
            estimated_peak_power_w_per_kg=peak_power,
        )
        r_power = simulate_theoretical_lap(
            track, FRICTION, vehicle_model=vm, rolling_resistance=0.0,
        )
        assert r_power.lap_time_s > r_grip.lap_time_s, (
            f"Power-limited ({r_power.lap_time_s:.2f}s) should be slower "
            f"than grip-only ({r_grip.lap_time_s:.2f}s)"
        )

    _test("power_limited_slower", t_power_limited_slower)

    # Test 27 — hybrid method label
    def t_hybrid_method_label() -> None:
        track = _make_circular_track(100)
        vm = _default_vehicle_model(FRICTION)
        result = simulate_theoretical_lap(track, FRICTION, vehicle_model=vm)
        assert result.method == "hybrid"

    _test("hybrid_method_label", t_hybrid_method_label)

    # Test 28 — fit_vehicle_model produces a valid model
    def t_fit_vehicle_model() -> None:
        rng = np.random.default_rng(42)
        dist = np.linspace(0, 300, 200)
        laps = {}
        for i in range(1, 11):
            speed = 15 + rng.normal(0, 3, 200).cumsum() * 0.05
            speed = np.clip(speed, 3, 40)
            accel = rng.normal(0, 3, 200)
            laps[i] = pd.DataFrame({
                "speed_mps": speed,
                "accel_long_mps2": accel,
                "Distance (m)": dist,
            })
        vm = fit_vehicle_model(laps, FRICTION)
        assert vm.n_samples > 0
        assert vm.confidence > 0
        assert len(vm.v_knots) > 5
        assert vm.traction_accel(10.0) > 0
        assert vm.braking_decel(10.0) > 0

    _test("fit_vehicle_model", t_fit_vehicle_model)

    # Test 29 — power_limited array in result
    def t_power_limited_array() -> None:
        track = _make_oval_track(500)
        result = simulate_theoretical_lap(track, FRICTION)
        assert len(result.power_limited) == len(result.distance_m)

    _test("power_limited_array", t_power_limited_array)

    # Test 30 — apex detection finds apices on oval
    def t_apex_detection() -> None:
        track = _make_oval_track(1000)
        curv = track["curvature_1pm"].values
        v_corner = _cornering_speed_profile(
            track["distance_m"].values, curv, FRICTION,
        )
        apices = _find_apex_points(v_corner, curv)
        assert len(apices) >= 2, (
            f"Oval should have at least 2 apices, got {len(apices)}"
        )

    _test("apex_detection_oval", t_apex_detection)

    # -------------------------------------------------------------------
    # Summary
    # -------------------------------------------------------------------

    total = len(passed) + len(failed)
    print(f"\nLap Simulation Tests: {len(passed)}/{total} passed")
    for name in passed:
        print(f"  OK {name}")
    for name, tb in failed:
        print(f"  FAIL {name}\n{tb}")

    if failed:
        raise AssertionError(f"{len(failed)} test(s) failed.")


def caps_from_vehicle_model(
    *,
    distance_m: "np.ndarray",
    curvature: "np.ndarray",
    traction_mps2: float,
    braking_mps2: float,
    mu: float,
    v_max_mps: float = 80.0,
    grip_map: Any = None,
) -> "OptimalCaps":
    """Build OptimalCaps from physics vehicle model parameters.

    Parameters
    ----------
    distance_m : distance grid [m]
    curvature : curvature [1/m] at each point
    traction_mps2 : max traction accel [m/s^2]
    braking_mps2 : max braking decel [m/s^2]
    mu : global friction coefficient
    v_max_mps : max vehicle speed [m/s]
    grip_map : optional per-distance grip map (overrides mu)

    Returns
    -------
    OptimalCaps ready for solve_optimal_speed().
    """
    from optimal_solver import OptimalCaps

    n = len(distance_m)

    # Per-point mu
    mu_arr = np.full(n, mu)
    if grip_map is not None and hasattr(grip_map, 'is_global_fallback') and not grip_map.is_global_fallback:
        for i in range(n):
            mu_arr[i] = grip_map.mu_at(float(distance_m[i]), "p95")

    # Cornering speed cap: v = sqrt(mu * g / |curvature|)
    v_cap = np.full(n, v_max_mps)
    for i in range(n):
        kappa = abs(curvature[i])
        if kappa > 1e-6:
            v_corner = math.sqrt(mu_arr[i] * _G / kappa)
            v_cap[i] = min(v_cap[i], v_corner)

    return OptimalCaps(
        distance_m=distance_m,
        v_cap=np.clip(v_cap, 1.0, v_max_mps),
        ax_accel=np.full(n, traction_mps2),
        ax_brake=np.full(n, braking_mps2),
        curvature=np.abs(curvature),
        mu=mu_arr,
        cap_source=["physics_model"] * n,
        solver_version="optimal_v2_1.0",
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _run_tests()
