"""Single-track (bicycle) vehicle dynamics for the OCP solver.

All functions are vectorized numpy and operate on VehicleParams from
``telemetry_tool.lap_oracle.config``.  The OCP solver calls these
directly to evaluate acceleration limits and corner speeds.
"""
from __future__ import annotations

import numpy as np

from telemetry_tool.lap_oracle.config import VehicleParams

# -- Physical constants ----------------------------------------------------
G: float = 9.80665
RHO_AIR: float = 1.225


# -- Lateral dynamics ------------------------------------------------------

def max_lateral_accel(v: np.ndarray | float, vp: VehicleParams) -> np.ndarray | float:
    """Maximum lateral acceleration (m/s^2) at speed *v*.

    Includes aerodynamic downforce contribution:

        ay_max = mu * (m*g + 0.5*rho*Cla*v^2) / m

    where mu = tyre_lat.D (peak friction coefficient).
    """
    v = np.asarray(v, dtype=np.float64)
    mu = vp.tyre_lat.D
    m = vp.mass_kg
    downforce = 0.5 * RHO_AIR * vp.cla * v ** 2
    return mu * (m * G + downforce) / m


# -- Longitudinal dynamics -------------------------------------------------

def max_longitudinal_accel(
    v: np.ndarray | float,
    vp: VehicleParams,
    braking: bool = False,
) -> np.ndarray | float:
    """Maximum longitudinal acceleration (m/s^2) at speed *v*.

    Parameters
    ----------
    v : float or array
        Vehicle speed (m/s).
    vp : VehicleParams
        Vehicle specification.
    braking : bool
        If True computes braking (negative direction, returned as positive
        magnitude).  If False computes traction-limited acceleration.

    Returns
    -------
    float or array
        Acceleration magnitude (always >= 0).

    Notes
    -----
    Braking:
        min(tyre_limit, max_brake_decel) + drag + rr
        (drag and rolling resistance *assist* braking)

    Accelerating:
        min(tyre_traction_limit, power_limit) - drag - rr
        Tyre traction uses rear-axle load only (RWD assumption).
        power_limit = P_max / (m * v)
    """
    v = np.asarray(v, dtype=np.float64)
    m = vp.mass_kg
    mu_long = vp.tyre_long.D

    # Aerodynamic drag deceleration: 0.5 * rho * CdA * v^2 / m
    drag = 0.5 * RHO_AIR * vp.cda * v ** 2 / m

    # Rolling resistance: ~0.01 * g
    rr = 0.01 * G

    if braking:
        # Total downforce on all tyres
        downforce = 0.5 * RHO_AIR * vp.cla * v ** 2
        tyre_limit = mu_long * (m * G + downforce) / m
        brake_limit = vp.max_brake_decel
        return np.maximum(np.minimum(tyre_limit, brake_limit) + drag + rr, 0.0)
    else:
        # RWD: rear axle normal load = (1 - weight_dist_front) * total weight
        rear_weight_frac = 1.0 - vp.weight_dist_front
        rear_downforce = rear_weight_frac * 0.5 * RHO_AIR * vp.cla * v ** 2
        rear_normal = rear_weight_frac * m * G + rear_downforce
        tyre_traction = mu_long * rear_normal / m

        # Power limit: P_max / (m * v).  Guard against v ~ 0.
        v_safe = np.maximum(v, 1.0)
        power_limit = vp.max_power_w / (m * v_safe)

        return np.maximum(
            np.minimum(tyre_traction, power_limit) - drag - rr,
            0.0,
        )


# -- Corner speed ----------------------------------------------------------

def corner_speed(curvature: np.ndarray, vp: VehicleParams) -> np.ndarray:
    """Maximum cornering speed for each curvature value.

    Solves  v^2 * kappa = ay_max(v)  analytically including aero downforce:

        v^2 * kappa = mu * (m*g + 0.5*rho*Cla*v^2) / m

    Rearranging:
        v^2 * (kappa - mu * 0.5*rho*Cla / m) = mu * g
        v^2 = mu * g / (kappa - mu * 0.5*rho*Cla / m)

    If the denominator <= 0, downforce dominates and speed is effectively
    unlimited (capped at 150 m/s for safety).

    Parameters
    ----------
    curvature : array
        Path curvature (1/m).  Values <= 0 are treated as straights.
    vp : VehicleParams
        Vehicle specification.

    Returns
    -------
    array
        Maximum speed (m/s) at each point.
    """
    curvature = np.asarray(curvature, dtype=np.float64)
    mu = vp.tyre_lat.D
    m = vp.mass_kg

    aero_term = mu * 0.5 * RHO_AIR * vp.cla / m
    denom = curvature - aero_term

    v_max = np.full_like(curvature, 150.0)
    valid = denom > 1e-9
    v_max[valid] = np.sqrt(mu * G / denom[valid])
    # Cap to reasonable maximum
    v_max = np.clip(v_max, 0.0, 150.0)
    return v_max


# -- Combined acceleration envelope ---------------------------------------

def combined_accel_limit(
    ax: float | np.ndarray,
    ay: float | np.ndarray,
    v: float | np.ndarray,
    vp: VehicleParams,
) -> float | np.ndarray:
    """Friction-ellipse utilisation: (ax/ax_max)^2 + (ay/ay_max)^2.

    Returns a value <= 1.0 if the (ax, ay) demand is feasible at speed *v*.

    Parameters
    ----------
    ax : float or array
        Longitudinal acceleration demand (m/s^2, positive = traction).
    ay : float or array
        Lateral acceleration demand (m/s^2, positive = either direction).
    v : float or array
        Vehicle speed (m/s).
    vp : VehicleParams
        Vehicle specification.

    Returns
    -------
    float or array
        Utilisation factor.  <= 1.0 means feasible.
    """
    ax = np.asarray(ax, dtype=np.float64)
    ay = np.asarray(ay, dtype=np.float64)
    v = np.asarray(v, dtype=np.float64)

    ay_max = max_lateral_accel(v, vp)
    # Choose ax_max based on sign of ax
    ax_pos = max_longitudinal_accel(v, vp, braking=False)
    ax_neg = max_longitudinal_accel(v, vp, braking=True)
    ax_max = np.where(ax >= 0, ax_pos, ax_neg)

    # Guard against zero limits
    ax_max_safe = np.maximum(ax_max, 1e-6)
    ay_max_safe = np.maximum(ay_max, 1e-6)

    return (ax / ax_max_safe) ** 2 + (ay / ay_max_safe) ** 2
