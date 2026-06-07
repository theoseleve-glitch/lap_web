"""2D grip-aware CasADi minimum-time OCP.

Same spatial (arc-length) formulation as :mod:`ocp`, but the friction
limit is a true 2D field mu(s, n) evaluated AT THE CHOSEN LINE inside
the NLP via a ``casadi.interpolant`` — so the optimizer routes around
lateral low-grip zones (wet rubber line, puddles) instead of only
slowing down for them.

Layering: this module imports nothing from ``track_surface``.  Callers
build a :class:`MuField` (see ``track_surface/mu_field.py``) and pass it
in.  ``ocp.py`` is intentionally untouched.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import numpy as np

from telemetry_tool.lap_oracle.config import (
    OCPSolution,
    TrackModel,
    VehicleParams,
    WeatherConditions,
)
from telemetry_tool.lap_oracle.physics.bicycle_model import corner_speed
from telemetry_tool.lap_oracle.solver.ocp import HAS_CASADI, _build_solution
from telemetry_tool.lap_oracle.track.model import resample_track

logger = logging.getLogger(__name__)

if HAS_CASADI:
    import casadi as ca

G: float = 9.80665
RHO_AIR: float = 1.225
EPS_GRIP: float = 0.05   # NLP conditioning floor — ocp.py clips grip to [0.3, 3.0];
                         # without a floor a zero-grip cell NaN-poisons the Jacobian
                         # and the except-path returns silent garbage as "suboptimal".


@dataclass(frozen=True)
class MuField:
    """Solver-ready 2D friction field on an (s, n) grid.

    Plain numpy value object so lap_oracle stays decoupled from
    track_surface.  ``mu_grid[i_s, i_n]`` with ``s_bins`` (M,) strictly
    increasing arclength centres and ``n_bins`` (K,) strictly increasing
    lateral-offset centres (+ = track-left, matching FrenetFrame).
    """

    s_bins: np.ndarray
    n_bins: np.ndarray
    mu_grid: np.ndarray

    def __post_init__(self) -> None:
        object.__setattr__(self, "s_bins", np.asarray(self.s_bins, dtype=np.float64))
        object.__setattr__(self, "n_bins", np.asarray(self.n_bins, dtype=np.float64))
        object.__setattr__(self, "mu_grid", np.asarray(self.mu_grid, dtype=np.float64))
        if self.mu_grid.shape != (len(self.s_bins), len(self.n_bins)):
            raise ValueError(
                f"mu_grid shape {self.mu_grid.shape} != "
                f"({len(self.s_bins)}, {len(self.n_bins)})"
            )


def _make_mu_interpolant(field: MuField):
    """Build the differentiable 2D lookup mu(s, n) for use inside the NLP.

    CasADi expects ``values`` flattened with the FIRST grid dimension
    varying FASTEST — Fortran order for our (M, K) grid.  Locked by
    ``test_interpolant_matches_gripsurface_bilinear``.
    """
    return ca.interpolant(
        "mu_sn",
        "linear",
        [field.s_bins.tolist(), field.n_bins.tolist()],
        field.mu_grid.flatten(order="F").tolist(),
    )


def solve_minimum_time_2d(
    track: TrackModel,
    vehicle: VehicleParams,
    mu_field: MuField,
    weather: WeatherConditions | None = None,
    n_points: int = 400,
    max_time_s: float = 120.0,
    warm_start: OCPSolution | None = None,
) -> OCPSolution:
    """Minimum-time OCP with a 2D friction field mu(s, n) inside the NLP.

    Identical formulation to ocp._solve_casadi except the friction-ellipse
    limits use mu_field evaluated at (s_i, N_lat[i]) — grip depends on the
    line the optimizer chooses, so it can route around lateral low-grip
    cells instead of only slowing for them.

    The per-point grip multiplier from TrackModel.grip_map is IGNORED here;
    mu_field is the single source of surface grip.  Vehicle tyre D and
    weather.grip_multiplier still scale globally as in ocp.py.

    Domain guards (CasADi linear interpolants EXTRAPOLATE outside the grid;
    see test_interpolant_extrapolates_outside_grid_documented): s coords are
    clamped into [s_bins[0], s_bins[-1]] and the N_lat bounds are
    intersected with [n_bins[0], n_bins[-1]].  Grip is floored at EPS_GRIP
    inside the NLP for conditioning; callers should still pass floored fields
    (build_wet_mu_field clips to [0.2, 1.0]).
    """
    if not HAS_CASADI:
        raise ImportError("solve_minimum_time_2d requires casadi")
    if weather is None:
        weather = WeatherConditions()

    t0 = time.perf_counter()

    ds_target = track.total_length_m / n_points
    tk = resample_track(track, ds_target=ds_target)
    N = tk.n_points
    ds = tk.ds.astype(np.float64)
    kappa = np.abs(tk.curvature).astype(np.float64)
    s_coords = np.concatenate(([0.0], np.cumsum(ds)))          # (N,)
    s_coords = np.clip(s_coords, float(mu_field.s_bins[0]), float(mu_field.s_bins[-1]))

    kv = np.zeros(N, dtype=np.float64)
    if tk.vert_curvature is not None and len(tk.vert_curvature) == N:
        kv = np.asarray(tk.vert_curvature, dtype=np.float64)

    m = vehicle.mass_kg
    cda = vehicle.cda
    cla = vehicle.cla
    p_max = vehicle.max_power_w
    a_brake_max = vehicle.max_brake_decel
    mu_lat_base = vehicle.tyre_lat.D * weather.grip_multiplier
    mu_long_base = vehicle.tyre_long.D * weather.grip_multiplier

    mu_lut = _make_mu_interpolant(mu_field)

    v_guess = corner_speed(kappa, vehicle) * weather.grip_multiplier
    v_guess = np.clip(v_guess, 10.0, 100.0)
    n_guess = np.zeros(N)
    ax_guess = np.zeros(N - 1)
    if warm_start is not None and len(warm_start.speed_mps) > 1:
        ws_d = np.asarray(warm_start.distance_m, dtype=np.float64)
        v_guess = np.interp(s_coords, ws_d, warm_start.speed_mps)
        n_guess = np.interp(s_coords, ws_d, warm_start.lateral_offset_m)
        ax_guess = np.diff(v_guess ** 2) / (2.0 * np.maximum(ds, 1e-6))
        ax_guess = np.clip(ax_guess, -50.0, 50.0)
        v_guess = np.clip(v_guess, 5.0, 120.0)

    opti = ca.Opti()
    V = opti.variable(N)
    N_lat = opti.variable(N)
    Ax = opti.variable(N - 1)
    opti.set_initial(V, v_guess)
    opti.set_initial(N_lat, n_guess)
    opti.set_initial(Ax, ax_guess)

    total_time = 0
    for i in range(N - 1):
        v_avg = (V[i] + V[i + 1]) / 2.0
        total_time = total_time + ds[i] / v_avg
    opti.minimize(total_time)

    for i in range(N - 1):
        opti.subject_to(V[i + 1] ** 2 == V[i] ** 2 + 2 * Ax[i] * ds[i])

        kappa_i = kappa[i]
        denom_i = ca.fmax(1.0 - N_lat[i] * kappa_i, 0.1)
        ay_i = V[i] ** 2 * (kappa_i / denom_i)

        g_eff_i = ca.fmax(G + V[i] ** 2 * kv[i], 1.0)
        fz_total = m * g_eff_i + 0.5 * RHO_AIR * cla * V[i] ** 2

        # ── THE 2D UPGRADE: grip evaluated at the chosen line ──
        grip_i = mu_lut(ca.vertcat(s_coords[i], N_lat[i]))
        grip_i = ca.fmax(grip_i, EPS_GRIP)
        mu_lat_i = mu_lat_base * grip_i
        mu_long_i = mu_long_base * grip_i
        ax_lim = mu_long_i * fz_total / m
        ay_lim = mu_lat_i * fz_total / m
        opti.subject_to((Ax[i] / ax_lim) ** 2 + (ay_i / ay_lim) ** 2 <= 1.0)

        drag = 0.5 * RHO_AIR * cda * V[i] ** 2 / m
        rr = 0.01 * g_eff_i
        v_safe = ca.fmax(V[i], 5.0)
        opti.subject_to(Ax[i] <= p_max / (m * v_safe) - drag - rr)
        opti.subject_to(Ax[i] >= -(a_brake_max * g_eff_i / G + drag + rr))

    opti.subject_to(opti.bounded(5.0, V, 120.0))
    n_lo_field = float(mu_field.n_bins[0])
    n_hi_field = float(mu_field.n_bins[-1])
    for i in range(N):
        lo = max(-float(tk.width_right[i]) * 0.9, n_lo_field)
        hi = min(float(tk.width_left[i]) * 0.9, n_hi_field)
        opti.subject_to(opti.bounded(lo, N_lat[i], hi))
    opti.subject_to(V[0] == V[N - 1])
    opti.subject_to(N_lat[0] == N_lat[N - 1])

    opti.solver("ipopt", {
        "ipopt.max_iter": 3000,
        "ipopt.max_cpu_time": max_time_s,
        "ipopt.print_level": 0,
        "ipopt.sb": "yes",
        "print_time": 0,
    })

    status = "optimal"
    try:
        sol = opti.solve()
        v_sol = np.array(sol.value(V)).flatten()
        n_lat_sol = np.array(sol.value(N_lat)).flatten()
        ax_sol = np.array(sol.value(Ax)).flatten()
    except RuntimeError:
        logger.warning("ocp_2d: IPOPT did not converge — extracting debug values")
        status = "suboptimal"
        v_sol = np.clip(np.array(opti.debug.value(V)).flatten(), 5.0, 120.0)
        n_lat_sol = np.array(opti.debug.value(N_lat)).flatten()
        ax_sol = np.array(opti.debug.value(Ax)).flatten()

    elapsed = time.perf_counter() - t0
    return _build_solution(
        track, vehicle, weather, tk, v_sol, n_lat_sol, ax_sol, ds, status, elapsed,
    )
