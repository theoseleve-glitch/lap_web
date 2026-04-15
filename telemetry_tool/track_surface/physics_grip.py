"""
Physics-robust grip coefficient map from per-wheel load reconstruction.

Unlike grip_2d.py which computes body-frame mu_sample = |a_body| / g_eff,
this module reconstructs individual wheel normal loads and tangential
forces using a full rigid-body model, then computes per-wheel
mu = |F_tangential| / |F_normal|.

The per-cell ceiling is the MAX across all four wheels at high-utilisation
moments, because any single saturated wheel caps the combined body G.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Final

import numpy as np

logger = logging.getLogger(__name__)

_G: Final[float] = 9.80665
_RHO_AIR_DEFAULT: Final[float] = 1.225  # kg/m³ at sea level
_MIN_SPEED_MPS: Final[float] = 5.0
_DEFAULT_UTIL_THRESHOLD: Final[float] = 0.55


# -- Vehicle geometry -------------------------------------------------------


@dataclass
class VehicleGeometry:
    """Geometric constants for a rigid-body vehicle.

    All distances in metres. brake_bias_front is a dimensionless fraction.
    """
    wheelbase_m: float
    track_front_m: float
    track_rear_m: float
    cg_height_m: float
    cg_to_front_m: float   # distance CG -> front axle
    cg_to_rear_m: float    # = wheelbase - cg_to_front
    brake_bias_front: float

    @property
    def weight_dist_front(self) -> float:
        """Static front weight fraction from geometry: b/L."""
        return self.cg_to_rear_m / self.wheelbase_m

    @property
    def weight_dist_rear(self) -> float:
        return self.cg_to_front_m / self.wheelbase_m


def build_vehicle_geometry(
    vehicle,  # VehicleModel — type hint avoided to prevent circular import
    *,
    wheelbase_default: float = 2.67,
    track_front_default: float = 1.666,
    track_rear_default: float = 1.627,
    cg_height_default: float = 0.35,
    weight_dist_front_default: float = 0.46,
    shock_defl_mean: tuple[float, float, float, float] | None = None,
) -> VehicleGeometry:
    """Build VehicleGeometry from a VehicleModel + optional telemetry hints.

    Parameters
    ----------
    vehicle
        Fitted VehicleModel. Only its brake.brake_bias_front is read here;
        wheelbase/track/CG are taken from defaults (iRacing does not expose
        them in the .ibt channels).
    shock_defl_mean
        Optional tuple (LF, RF, LR, RR) of mean steady-state shock
        deflections. When provided, weight_dist_front is inferred from
        the front/total ratio instead of using the default.
    """
    brake_bias_front = weight_dist_front_default
    try:
        if vehicle is not None and hasattr(vehicle, "brake") and vehicle.brake is not None:
            bbf = getattr(vehicle.brake, "brake_bias_front", None)
            if bbf is not None and 0.3 <= bbf <= 0.8:
                brake_bias_front = float(bbf)
    except Exception:
        pass

    weight_dist_front = weight_dist_front_default
    if shock_defl_mean is not None:
        lf, rf, lr, rr = shock_defl_mean
        total = lf + rf + lr + rr
        if total > 1e-6:
            inferred = (lf + rf) / total
            if 0.30 <= inferred <= 0.65:
                weight_dist_front = float(inferred)
                logger.info(
                    "Weight distribution from shock deflection: %.3f front",
                    weight_dist_front,
                )

    cg_to_front = wheelbase_default * (1.0 - weight_dist_front)
    cg_to_rear = wheelbase_default * weight_dist_front

    return VehicleGeometry(
        wheelbase_m=wheelbase_default,
        track_front_m=track_front_default,
        track_rear_m=track_rear_default,
        cg_height_m=cg_height_default,
        cg_to_front_m=cg_to_front,
        cg_to_rear_m=cg_to_rear,
        brake_bias_front=brake_bias_front,
    )


# -- Per-wheel normal load --------------------------------------------------


@dataclass
class PerWheelLoads:
    """Per-wheel normal forces (N) over a sample sequence.

    Column order: [LF, RF, LR, RR].
    """
    fz: np.ndarray          # shape (N, 4)
    fz_total: np.ndarray    # shape (N,) — includes aero
    aero_factor: np.ndarray # shape (N,) — downforce multiplier


def compute_per_wheel_normal_loads(
    *,
    mass_kg: float,
    speed_mps: np.ndarray,
    a_long_body: np.ndarray,   # +forward, -braking (m/s²)
    a_lat_body: np.ndarray,    # sign meaningful: +right-turn push (iRacing)
    roll_rad: np.ndarray,
    pitch_rad: np.ndarray,
    aero_cla: float,
    air_density: np.ndarray | float = _RHO_AIR_DEFAULT,
    geom: VehicleGeometry,
    lateral_frac_f: float | None = None,
) -> PerWheelLoads:
    """Rigid-body per-wheel vertical load reconstruction.

    Physics:
        Fz_total   = m·g·cos(θ)·cos(φ) + F_down
        F_down     = 0.5·ρ·ClA·v²
        Fz_f_stat  = Fz_total · (b/L)  [b = cg_to_rear → more rear weight → smaller front]
        Fz_r_stat  = Fz_total · (a/L)

    Wait — correction: b/L gives REAR fraction, so:
        Fz_f_stat  = Fz_total · r_f  where r_f = cg_to_rear / L (front weight on a CG closer to front)

    Actually the standard convention: if CG is at distance a from front
    and b from rear, then the static weight on the FRONT axle is
    (b / L) × Fz_total (because the rear axle supports more of the weight
    if the CG is closer to the front — wait, that's backward too).

    Correct: for a CG at distance a from front, b from rear:
        Fz_front_static = (b / L) × Fz_total   [more weight on front if CG is closer to front]
                          ^ moment arm from rear axle

    In our VehicleGeometry:
        cg_to_front_m = a (CG → front axle distance)
        cg_to_rear_m  = b (CG → rear axle distance)
        weight_dist_front = b / L  (static front fraction)

    Load transfer:
        ΔFz_long = m · a_long · h / L        [+ means shift to REAR]
        ΔFz_lat_axle = |m · a_lat| · h · frac_axle / track_axle

    Per-wheel (s = sign of a_lat, +1 for right turn):
        Fz_LF = 0.5 · (Fz_f_static − ΔFz_long) − s · ΔFz_lat_f
        Fz_RF = 0.5 · (Fz_f_static − ΔFz_long) + s · ΔFz_lat_f
        Fz_LR = 0.5 · (Fz_r_static + ΔFz_long) − s · ΔFz_lat_r
        Fz_RR = 0.5 · (Fz_r_static + ΔFz_long) + s · ΔFz_lat_r

    All per-wheel Fz clipped to zero (wheel lift → no downforce, no traction).
    """
    n = len(speed_mps)
    if isinstance(air_density, (int, float)):
        rho = np.full(n, float(air_density))
    else:
        rho = np.asarray(air_density, dtype=np.float64)

    # Aero downforce
    f_down = 0.5 * rho * max(aero_cla, 0.0) * speed_mps ** 2
    # Gravity projected onto body-z (correct for banking/pitch)
    fz_gravity = mass_kg * _G * np.cos(pitch_rad) * np.cos(roll_rad)
    fz_total = fz_gravity + f_down
    aero_factor = fz_total / np.maximum(mass_kg * _G, 1.0)

    # Static per-axle shares
    r_f = geom.weight_dist_front
    r_r = 1.0 - r_f
    fz_f_static = fz_total * r_f
    fz_r_static = fz_total * r_r

    # Longitudinal load transfer (+ shifts rearward when accelerating)
    d_fz_long = mass_kg * a_long_body * geom.cg_height_m / geom.wheelbase_m

    # Lateral transfer fractions by axle
    if lateral_frac_f is None:
        lateral_frac_f = r_f
    lateral_frac_r = 1.0 - lateral_frac_f

    # Lateral load transfer magnitudes per axle
    abs_a_lat = np.abs(a_lat_body)
    d_fz_lat_f = mass_kg * abs_a_lat * geom.cg_height_m * lateral_frac_f / geom.track_front_m
    d_fz_lat_r = mass_kg * abs_a_lat * geom.cg_height_m * lateral_frac_r / geom.track_rear_m

    # Sign of lateral transfer: +1 for right turn (load shifts to right side)
    s_lat = np.sign(a_lat_body)
    # Treat exactly-zero as no lateral load transfer
    s_lat[s_lat == 0] = 0.0

    # Per-wheel normal loads (before clipping)
    fz_lf = 0.5 * (fz_f_static - d_fz_long) - s_lat * d_fz_lat_f
    fz_rf = 0.5 * (fz_f_static - d_fz_long) + s_lat * d_fz_lat_f
    fz_lr = 0.5 * (fz_r_static + d_fz_long) - s_lat * d_fz_lat_r
    fz_rr = 0.5 * (fz_r_static + d_fz_long) + s_lat * d_fz_lat_r

    # Clip wheel lift to zero
    fz_per_wheel = np.maximum(
        np.column_stack([fz_lf, fz_rf, fz_lr, fz_rr]),
        0.0,
    )

    return PerWheelLoads(
        fz=fz_per_wheel,
        fz_total=fz_total,
        aero_factor=aero_factor,
    )


# -- Per-wheel tangential forces --------------------------------------------


def compute_per_wheel_tangential_forces(
    *,
    mass_kg: float,
    fz_per_wheel: np.ndarray,        # (N, 4)
    a_long_body: np.ndarray,
    a_lat_body: np.ndarray,
    brake_line_press: np.ndarray | None = None,  # (N, 4) kPa, optional
    brake_bias_front: float = 0.50,
    drive_rear_only: bool = True,
) -> np.ndarray:
    """Decompose body-frame longitudinal+lateral forces to 4 wheels.

    Returns shape (N, 4) — the magnitude of the tangential
    (friction-consuming) force at each wheel.

    Decomposition rules:

    Lateral: split across all 4 wheels in proportion to Fz (tire lat
    capacity ≈ linear in Fz at peak):
        F_lat_i = F_lat_total × Fz_i / ΣFz

    Longitudinal — braking (a_long < 0):
        If per-wheel brake_line_press available:
            F_long_i = F_long_total × p_i / Σp
        Else:
            Apportion F_long_total by brake bias front/rear,
            then split within each axle by Fz ratio.

    Longitudinal — traction (a_long > 0):
        drive_rear_only: split between LR, RR by Fz ratio, zero to front.
        Else split all 4 by Fz ratio.

    Per wheel tangential magnitude:
        F_t_i = sqrt(F_lat_i² + F_long_i²)
    """
    n = fz_per_wheel.shape[0]

    f_long_total = mass_kg * a_long_body  # (N,)
    f_lat_total = mass_kg * a_lat_body    # (N,)

    fz_sum = np.maximum(fz_per_wheel.sum(axis=1), 1.0)  # (N,)
    fz_front_sum = np.maximum(fz_per_wheel[:, 0] + fz_per_wheel[:, 1], 1.0)
    fz_rear_sum = np.maximum(fz_per_wheel[:, 2] + fz_per_wheel[:, 3], 1.0)

    # Lateral split: proportional to Fz
    f_lat_per_wheel = f_lat_total[:, None] * fz_per_wheel / fz_sum[:, None]

    # Longitudinal split
    f_long_per_wheel = np.zeros((n, 4), dtype=np.float64)
    braking_mask = a_long_body < 0
    traction_mask = a_long_body > 0

    # Braking
    if brake_line_press is not None and brake_line_press.shape == (n, 4):
        p = brake_line_press.astype(np.float64)
        p_sum = np.maximum(p.sum(axis=1), 1e-3)
        # Use pressure ratio when any brake is applied, else fall back to bias
        any_brake = p_sum > 0.01 * np.max(p_sum)
        for w in range(4):
            ratio = p[:, w] / p_sum
            f_long_per_wheel[any_brake & braking_mask, w] = (
                f_long_total[any_brake & braking_mask] * ratio[any_brake & braking_mask]
            )
        # Samples with no brake pressure but negative a_long (engine braking):
        # fall back to bias.
        fallback = braking_mask & ~any_brake
        if fallback.any():
            f_long_per_wheel[fallback, 0] = (
                f_long_total[fallback] * brake_bias_front
                * fz_per_wheel[fallback, 0] / fz_front_sum[fallback]
            )
            f_long_per_wheel[fallback, 1] = (
                f_long_total[fallback] * brake_bias_front
                * fz_per_wheel[fallback, 1] / fz_front_sum[fallback]
            )
            f_long_per_wheel[fallback, 2] = (
                f_long_total[fallback] * (1 - brake_bias_front)
                * fz_per_wheel[fallback, 2] / fz_rear_sum[fallback]
            )
            f_long_per_wheel[fallback, 3] = (
                f_long_total[fallback] * (1 - brake_bias_front)
                * fz_per_wheel[fallback, 3] / fz_rear_sum[fallback]
            )
    else:
        # No per-wheel brake pressure: use bias front/rear, Fz split within axle
        for b_mask, sign in [(braking_mask, -1)]:
            f_long_per_wheel[b_mask, 0] = (
                f_long_total[b_mask] * brake_bias_front
                * fz_per_wheel[b_mask, 0] / fz_front_sum[b_mask]
            )
            f_long_per_wheel[b_mask, 1] = (
                f_long_total[b_mask] * brake_bias_front
                * fz_per_wheel[b_mask, 1] / fz_front_sum[b_mask]
            )
            f_long_per_wheel[b_mask, 2] = (
                f_long_total[b_mask] * (1 - brake_bias_front)
                * fz_per_wheel[b_mask, 2] / fz_rear_sum[b_mask]
            )
            f_long_per_wheel[b_mask, 3] = (
                f_long_total[b_mask] * (1 - brake_bias_front)
                * fz_per_wheel[b_mask, 3] / fz_rear_sum[b_mask]
            )

    # Traction
    if drive_rear_only:
        f_long_per_wheel[traction_mask, 0] = 0.0
        f_long_per_wheel[traction_mask, 1] = 0.0
        f_long_per_wheel[traction_mask, 2] = (
            f_long_total[traction_mask] * fz_per_wheel[traction_mask, 2] / fz_rear_sum[traction_mask]
        )
        f_long_per_wheel[traction_mask, 3] = (
            f_long_total[traction_mask] * fz_per_wheel[traction_mask, 3] / fz_rear_sum[traction_mask]
        )
    else:
        for w in range(4):
            f_long_per_wheel[traction_mask, w] = (
                f_long_total[traction_mask] * fz_per_wheel[traction_mask, w]
                / fz_sum[traction_mask]
            )

    # Tangential magnitude per wheel
    f_tang = np.sqrt(f_lat_per_wheel ** 2 + f_long_per_wheel ** 2)
    return f_tang


# -- Per-wheel mu -----------------------------------------------------------


def compute_mu_per_wheel(
    fz_per_wheel: np.ndarray,        # (N, 4)
    f_tang_per_wheel: np.ndarray,    # (N, 4)
    fz_min_n: float = 800.0,
    mu_absolute_cap: float = 2.5,
) -> np.ndarray:
    """Per-wheel friction utilisation μ = |F_t| / Fz.

    Returns (N, 4) with NaN where:
    - Fz < fz_min_n (wheel too close to lift — μ undefined)
    - μ > mu_absolute_cap (physically impossible for road rubber, indicates
      decomposition artefact from load-transfer mismatch)

    The fz_min_n floor of 800 N excludes borderline cases where a wheel
    is between "lifted" and "loaded" and the decomposition assumptions
    (pressure-ratio brake split, Fz-proportional lateral split) break down.
    """
    mu = np.full_like(fz_per_wheel, np.nan)
    valid = fz_per_wheel >= fz_min_n
    mu[valid] = f_tang_per_wheel[valid] / fz_per_wheel[valid]
    # Clamp physically impossible values (decomposition artefacts)
    mu[mu > mu_absolute_cap] = np.nan
    return mu


# -- Per-cell grip ceiling --------------------------------------------------


def build_physics_grip_grid(
    *,
    s_proj: np.ndarray,              # (N,)
    n_proj: np.ndarray,              # (N,)
    mu_per_wheel: np.ndarray,        # (N, 4)
    a_body_mag: np.ndarray,          # (N,) |a_body| = sqrt(a_lat²+a_long²)
    g_eff: np.ndarray,               # (N,) terrain-corrected gravity
    s_bins: np.ndarray,              # (M+1,) bin edges
    n_bins: np.ndarray,              # (K+1,) bin edges
    util_threshold: float = _DEFAULT_UTIL_THRESHOLD,
    percentile: float = 95.0,
) -> np.ndarray:
    """Per-cell grip ceiling from max-across-wheels μ.

    Per sample, the limiting wheel drives the ceiling:
        mu_sample = max(μ_LF, μ_RF, μ_LR, μ_RR)

    Samples are gated by util = |a_body| / g_eff > util_threshold so
    only near-limit moments define the ceiling.

    Per cell, take the `percentile` across the kept samples.
    """
    M = len(s_bins) - 1
    K = len(n_bins) - 1

    # Per-sample max-wheel mu
    mu_max = np.nanmax(mu_per_wheel, axis=1)  # (N,)

    # Utilisation gate
    util = a_body_mag / np.maximum(g_eff, 1.0)
    keep = (util > util_threshold) & np.isfinite(mu_max)

    if not keep.any():
        return np.full((M, K), np.nan)

    s_kept = s_proj[keep]
    n_kept = n_proj[keep]
    mu_kept = mu_max[keep]

    s_idx = np.clip(np.searchsorted(s_bins, s_kept) - 1, 0, M - 1).astype(np.int32)
    n_idx = np.clip(np.searchsorted(n_bins, n_kept) - 1, 0, K - 1).astype(np.int32)
    flat_idx = s_idx * K + n_idx

    # Group by cell via argsort + run-length encoding
    order = np.argsort(flat_idx)
    sorted_flat = flat_idx[order]
    sorted_mu = mu_kept[order]

    mu_grid = np.full((M, K), np.nan, dtype=np.float64)

    if len(sorted_flat) == 0:
        return mu_grid

    # Find run starts
    diff = np.diff(sorted_flat)
    starts = np.concatenate([[0], np.where(diff > 0)[0] + 1])
    ends = np.concatenate([starts[1:], [len(sorted_flat)]])

    for start, end in zip(starts, ends):
        if end - start < 2:
            continue
        cell = int(sorted_flat[start])
        si, ni = divmod(cell, K)
        cell_mu = sorted_mu[start:end]
        mu_grid[si, ni] = float(np.percentile(cell_mu, percentile))

    return mu_grid


def propagate_physics_grip(mu_grid: np.ndarray, iterations: int = 3) -> np.ndarray:
    """Fill empty cells via local maximum filter (matches process_ibt_extreme).

    If a cell has no direct near-limit evidence, take the max from a
    local 5×5 neighborhood. Repeated iterations expand the reach.
    """
    from scipy.ndimage import gaussian_filter, maximum_filter

    filled = np.where(np.isnan(mu_grid), 0.0, mu_grid)
    mask = np.isnan(mu_grid)

    for _ in range(iterations):
        expanded = maximum_filter(filled, size=5, mode="nearest")
        filled = np.where(mask, expanded, filled)

    filled = gaussian_filter(filled, sigma=1.0)
    return filled
