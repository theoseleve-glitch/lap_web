"""
track_surface/solver_bridge.py
------------------------------
Bridge between TrackSurface and the existing CasADi OCP solver.

Converts a TrackSurface into the lap_oracle's TrackModel format so the
existing solver (ocp.py) can optimise lateral offset + speed using real
track data instead of defaults.
"""
from __future__ import annotations

import logging

import numpy as np

from track_surface.model import TrackSurface

logger = logging.getLogger(__name__)

_DEFAULT_WIDTH_M = 5.0


def surface_to_track_model(surface: TrackSurface):
    """Convert a TrackSurface to the OCP solver's TrackModel.

    Maps surface data to TrackModel fields.  Falls back to sensible
    defaults for any fields that are None (< minimum laps).

    Returns
    -------
    TrackModel instance ready for ocp.solve_minimum_time().
    """
    try:
        from lap_oracle.config import TrackModel
    except ImportError:
        raise ImportError(
            "lap_oracle.config.TrackModel not available — "
            "CasADi solver bridge requires the lap_oracle package"
        )

    n = surface.frenet.n_points

    width_left = (
        surface.width_left if surface.width_left is not None
        else np.full(n, _DEFAULT_WIDTH_M)
    )
    width_right = (
        surface.width_right if surface.width_right is not None
        else np.full(n, _DEFAULT_WIDTH_M)
    )
    elevation = (
        surface.elevation_m if surface.elevation_m is not None
        else np.zeros(n)
    )
    banking = (
        surface.camber_rad if surface.camber_rad is not None
        else np.zeros(n)
    )

    # Grip: use centerline slice from 2D grip, or default ones
    if surface.grip_2d is not None:
        grip_map = surface.grip_2d.centerline_slice()
        # Resample to match centerline point count if needed
        if len(grip_map) != n:
            grip_map = np.interp(
                np.linspace(0, 1, n),
                np.linspace(0, 1, len(grip_map)),
                grip_map,
            )
    else:
        grip_map = np.ones(n)

    # Vertical curvature → speed-dependent grip multiplier.
    #
    # At speed v through vertical curvature kappa_v:
    #   g_effective = g + v² * kappa_v
    #   grip_effective = mu * g_effective / g
    #
    # The OCP solver's friction constraint is:
    #   (ax/ax_lim)^2 + (ay/ay_lim)^2 <= 1
    # where ay_lim = mu * g.
    #
    # To inject the compression bonus without modifying the solver itself,
    # we fold an estimated compression multiplier into the grip_map.
    # We use a reference speed of ~60% of the estimated corner speed
    # (conservative: underestimates the bonus at high speed, but prevents
    # overestimation at low speed where it matters less).
    if surface.vert_curvature_1pm is not None:
        kv = surface.vert_curvature_1pm
        if len(kv) != n:
            kv = np.interp(np.linspace(0, 1, n), np.linspace(0, 1, len(kv)), kv)
        # Reference speed: use curvature-based cornering speed estimate
        kappa_abs = np.abs(surface.frenet.curvature_1pm)
        kappa_safe = np.maximum(kappa_abs, 0.002)  # min 500m radius
        v_ref = np.sqrt(1.2 * 9.81 / kappa_safe)   # approx corner speed at 1.2G
        v_ref = np.clip(v_ref, 15.0, 80.0)          # 54-288 kph range
        compression_multiplier = (9.81 + v_ref ** 2 * kv) / 9.81
        compression_multiplier = np.clip(compression_multiplier, 0.3, 3.0)
        grip_map = grip_map * compression_multiplier

    return TrackModel(
        name=surface.track_id,
        sim=surface.sim_sources[0] if surface.sim_sources else "",
        centerline_xy=surface.frenet.centerline_xy.copy(),
        width_left=width_left,
        width_right=width_right,
        curvature=surface.frenet.curvature_1pm.copy(),
        elevation=elevation,
        banking=banking,
        grip_map=grip_map,
        total_length_m=surface.frenet.total_length_m,
    )


def solve_optimal_line(
    surface: TrackSurface,
    vehicle_params=None,
    weather=None,
    n_points: int = 500,
    max_time_s: float = 120.0,
):
    """Compute the optimal racing line through the track surface.

    Bridges TrackSurface to the existing CasADi OCP solver, which
    already optimises N_lat (lateral offset) as a decision variable.

    Parameters
    ----------
    surface : TrackSurface with at least a centerline.
    vehicle_params : VehicleParams (from lap_oracle.config).
    weather : WeatherConditions (from lap_oracle.config), optional.
    n_points : discretisation points for the OCP solver.
    max_time_s : IPOPT time limit.

    Returns
    -------
    OCPSolution with lateral_offset_m, speed_mps, etc.

    Raises
    ------
    ImportError : if casadi or lap_oracle not available.
    """
    try:
        from lap_oracle.solver.ocp import solve_minimum_time
    except ImportError:
        raise ImportError(
            "CasADi OCP solver not available — "
            "install casadi and ensure lap_oracle.solver.ocp is importable"
        )

    track_model = surface_to_track_model(surface)

    return solve_minimum_time(
        track_model,
        vehicle_params,
        weather=weather,
        n_points=n_points,
        max_time_s=max_time_s,
    )
