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


def _make_mu_interpolant_smooth(field: MuField):
    """C2-smooth cubic-bspline lookup mu(s, n) for use INSIDE the NLP.

    IPOPT assumes twice-differentiable constraints; the 'linear' interpolant
    is C0 (derivative kinks at every knot), which stalls the line search on
    step-like fields (spurious "suboptimal") and lets iterates slide through
    gradient gaps into local basins.  The bspline passes through the same
    grid values at the knots but is smooth between them.  Small undershoot
    ringing near steps is floored by EPS_GRIP in the solver; overshoot is
    capped at the field's true maximum inside the NLP.
    Same Fortran-order data layout as _make_mu_interpolant.
    """
    return ca.interpolant(
        "mu_sn_smooth",
        "bspline",
        [field.s_bins.tolist(), field.n_bins.tolist()],
        field.mu_grid.flatten(order="F").tolist(),
    )


def _candidate_lap_time(v_sol: np.ndarray, ds: np.ndarray) -> float:
    """Lap time for a candidate solve — IDENTICAL formula to _build_solution.

    Used to rank multi-start candidates without paying for the full
    _build_solution package on every start.
    """
    v_avg = np.maximum((v_sol[:-1] + v_sol[1:]) / 2.0, 1.0)
    return float(np.sum(ds / v_avg))


def _solve_once(
    *,
    N: int,
    ds: np.ndarray,
    kappa: np.ndarray,
    kv: np.ndarray,
    s_coords: np.ndarray,
    mu_lut,
    n_bounds: list[tuple[float, float]],
    v_guess: np.ndarray,
    n_guess: np.ndarray,
    ax_guess: np.ndarray,
    vehicle: VehicleParams,
    weather: WeatherConditions,
    max_time_s: float,
    mu_ceiling: float,
) -> tuple[str, np.ndarray, np.ndarray, np.ndarray]:
    """Build a FRESH ca.Opti() and run one IPOPT solve from the given guess.

    Returns ``(status, v_sol, n_lat_sol, ax_sol)``.  No CasADi state is
    reused between calls — each start is fully independent so the multi-start
    loop cannot leak warm-state across seeds.
    """
    m = vehicle.mass_kg
    cda = vehicle.cda
    cla = vehicle.cla
    p_max = vehicle.max_power_w
    a_brake_max = vehicle.max_brake_decel
    mu_lat_base = vehicle.tyre_lat.D * weather.grip_multiplier
    mu_long_base = vehicle.tyre_long.D * weather.grip_multiplier

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
        grip_i = ca.fmin(grip_i, mu_ceiling)  # cap bspline overshoot: never
        # hand the NLP more grip than the field's true maximum
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
    for i in range(N):
        lo, hi = n_bounds[i]
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
        # IPOPT raised — but read its return_status: "Solved_To_Acceptable_Level"
        # is a real (looser-tolerance) convergence tier, not divergence garbage.
        # Map that to "acceptable"; everything else stays "suboptimal".
        ret = opti.return_status()
        if ret == "Solved_To_Acceptable_Level":
            status = "acceptable"
        else:
            status = "suboptimal"
        logger.warning(
            "ocp_2d: IPOPT did not reach optimal (return_status=%s, mapped=%s)"
            " — extracting debug values", ret, status,
        )
        v_sol = np.clip(np.array(opti.debug.value(V)).flatten(), 5.0, 120.0)
        n_lat_sol = np.array(opti.debug.value(N_lat)).flatten()
        ax_sol = np.array(opti.debug.value(Ax)).flatten()

    return status, v_sol, n_lat_sol, ax_sol


def solve_minimum_time_2d(
    track: TrackModel,
    vehicle: VehicleParams,
    mu_field: MuField,
    weather: WeatherConditions | None = None,
    n_points: int = 400,
    max_time_s: float = 120.0,
    warm_start: OCPSolution | None = None,
    n_lat_starts: tuple[float, ...] = (0.0,),
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

    Deterministic multi-start (``n_lat_starts``)
    --------------------------------------------
    WHY: real wet fields contain step-clamped puddle blocks (mu drops
    discontinuously across a lateral edge).  IPOPT is a local solver — its
    "optimal" status certifies only LOCAL optimality.  Cold-started at
    N_lat=0, the solve descends into whichever grip basin contains the
    origin; if that is the puddle side it converges there and reports
    "optimal" even though a dry line off to one side is globally faster, and
    it cannot cross the grip step to find it.

    ``n_lat_starts`` is the deterministic escape: for each offset ``o`` (in
    FIXED tuple order, so the result is reproducible) we run one fully
    independent solve whose N_lat initial guess is the base guess (zeros, or
    the warm-start interp) shifted by ``o`` and clipped to the per-point
    bounds.  This seeds solves on either side of a step so at least one lands
    in the dry basin.

    SELECTION (status-tiered): among candidates with status == "optimal" we
    keep the one with the lowest lap time (formula matches _build_solution);
    ties break to the EARLIEST offset in the tuple.  If NO candidate is
    optimal, we fall back to the lowest-lap candidate among the "acceptable"
    tier (IPOPT's "Solved_To_Acceptable_Level" — a real looser-tolerance
    convergence, not divergence garbage).  If neither tier has a candidate we
    return the FIRST candidate, preserving its "suboptimal" status.
    _build_solution is built ONLY for the winner.

    The default ``(0.0,)`` runs exactly one cold start — byte-for-byte the
    previous single-solve behavior and timing.
    """
    if not HAS_CASADI:
        raise ImportError("solve_minimum_time_2d requires casadi")
    if not n_lat_starts:
        raise ValueError("n_lat_starts must be non-empty")
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

    # The NLP reads grip through the C2 cubic-bspline interpolant: IPOPT
    # assumes twice-differentiable constraints, and the C0 'linear' field's
    # derivative kinks both stall certification (spurious "suboptimal") and
    # let iterates slide back across grip steps into local basins.  The linear
    # interpolant remains the layout-locked data-sampling contract elsewhere.
    # Built ONCE here and reused across every multi-start solve.
    mu_lut = _make_mu_interpolant_smooth(mu_field)
    # Floor mu_ceiling at EPS_GRIP so a degenerate all-zero field doesn't let
    # the cap override the EPS_GRIP floor (fmin(EPS_GRIP, 0) = 0 → NaN Jacobian)
    mu_ceiling = max(float(mu_field.mu_grid.max()), EPS_GRIP)

    v_guess = corner_speed(kappa, vehicle) * weather.grip_multiplier
    v_guess = np.clip(v_guess, 10.0, 100.0)
    base_n_guess = np.zeros(N)
    ax_guess = np.zeros(N - 1)
    if warm_start is not None and len(warm_start.speed_mps) > 1:
        ws_d = np.asarray(warm_start.distance_m, dtype=np.float64)
        v_guess = np.interp(s_coords, ws_d, warm_start.speed_mps)
        base_n_guess = np.interp(s_coords, ws_d, warm_start.lateral_offset_m)
        ax_guess = np.diff(v_guess ** 2) / (2.0 * np.maximum(ds, 1e-6))
        ax_guess = np.clip(ax_guess, -50.0, 50.0)
        v_guess = np.clip(v_guess, 5.0, 120.0)

    # Per-point N_lat bounds: track width ∩ field n-domain (same as constraints).
    n_lo_field = float(mu_field.n_bins[0])
    n_hi_field = float(mu_field.n_bins[-1])
    n_bounds: list[tuple[float, float]] = []
    lo_arr = np.empty(N)
    hi_arr = np.empty(N)
    for i in range(N):
        lo = max(-float(tk.width_right[i]) * 0.9, n_lo_field)
        hi = min(float(tk.width_left[i]) * 0.9, n_hi_field)
        n_bounds.append((lo, hi))
        lo_arr[i] = lo
        hi_arr[i] = hi

    # Deterministic multi-start: one independent solve per offset, in order.
    # Tiered selection: best "optimal" lap, else best "acceptable" lap, else
    # the FIRST candidate (preserving its "suboptimal" status).
    best_opt: tuple[str, np.ndarray, np.ndarray, np.ndarray] | None = None
    best_opt_lap = float("inf")
    best_acc: tuple[str, np.ndarray, np.ndarray, np.ndarray] | None = None
    best_acc_lap = float("inf")
    first: tuple[str, np.ndarray, np.ndarray, np.ndarray] | None = None
    for o in n_lat_starts:
        n_guess = np.clip(base_n_guess + o, lo_arr, hi_arr)
        cand = _solve_once(
            N=N, ds=ds, kappa=kappa, kv=kv, s_coords=s_coords, mu_lut=mu_lut,
            n_bounds=n_bounds, v_guess=v_guess, n_guess=n_guess, ax_guess=ax_guess,
            vehicle=vehicle, weather=weather, max_time_s=max_time_s,
            mu_ceiling=mu_ceiling,
        )
        if first is None:
            first = cand
        if cand[0] == "optimal":
            lap = _candidate_lap_time(cand[1], ds)
            if lap < best_opt_lap:   # strict < ⇒ ties keep the earlier start
                best_opt_lap = lap
                best_opt = cand
        elif cand[0] == "acceptable":
            lap = _candidate_lap_time(cand[1], ds)
            if lap < best_acc_lap:   # strict < ⇒ ties keep the earlier start
                best_acc_lap = lap
                best_acc = cand

    winner = best_opt if best_opt is not None else (
        best_acc if best_acc is not None else first  # suboptimal exits have untrustworthy lap numbers — ranking them is false precision; first = deterministic
    )
    # winner is not None — the loop ran at least once given the non-empty guard above
    status, v_sol, n_lat_sol, ax_sol = winner  # type: ignore[misc]

    elapsed = time.perf_counter() - t0
    return _build_solution(
        track, vehicle, weather, tk, v_sol, n_lat_sol, ax_sol, ds, status, elapsed,
    )
