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
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

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

# Type-only: keeps the "this module imports nothing from track_surface"
# layering invariant at runtime (TYPE_CHECKING is False when executed) while
# still giving IDEs/mypy a real type for the geom_field: GeomField param.
if TYPE_CHECKING:
    from telemetry_tool.track_surface.geom_field import GeomField

logger = logging.getLogger(__name__)

if HAS_CASADI:
    import casadi as ca

G: float = 9.80665
RHO_AIR: float = 1.225
EPS_GRIP: float = 0.05   # NLP conditioning floor — ocp.py clips grip to [0.3, 3.0];
                         # without a floor a zero-grip cell NaN-poisons the Jacobian
                         # and the except-path returns silent garbage as "suboptimal".
# Camber lateral-grip boost: ay_lim *= (1 + K_CAMBER * |camber_rad|). Tuning knob.
# Conservative linear model; camber_s is treated as banking MAGNITUDE (adverse/
# off-camber is treated as favourable in v1 — a documented simplification).
K_CAMBER: float = 0.6
# Frenet path-length Jacobian floor: ds_path = ds * fmax(1 - n*kappa_ref, _PATH_LEN_FLOOR).
# Deliberately SMALLER than the 0.1 curvature-denominator floor so the inside line's
# arc-length shortening (which is the whole point of the path-length credit) isn't
# understated — at most the path collapses to 1% of the centerline step, not 10%.
_PATH_LEN_FLOOR: float = 1e-2
# Minimal n'' smoothing (Task 4). Pricing n'' into ay (Task 2) already made the
# line ~9x smoother and apexes both lobes; these add the lightest extra coupling
# to (a) kill residual lateral chatter and (b) re-condition the NLP (the n'' ay
# term stiffens IPOPT on step-discontinuous puddle grids).
LAMBDA_SMOOTH: float = 5.0    # soft n'' regularizer weight; "minimal smoothing"; tune by eyegate in Task 6
DKAPPA_MAX: float = 0.5       # 1/m hard cap on |d2n|; safety rail only (must NOT bind the clean line)
# ── Step 2: driver model ─────────────────────────────────────────────────────
# Steering rate limit (driver input). delta_i = atan(L * kappa_line_i) is the
# steering angle implied by the line's true path curvature on segment i; the
# constraint |delta[i+1]-delta[i]| <= DDELTA_MAX * dt_i (dt_i = ds_path_i /
# v_avg_i) forbids wheel flicks faster than human hands. Kart default ≈ 3 rad/s
# (direct steering, fast hands — spec, tune by eyegate).
DDELTA_MAX: float = 3.0       # rad/s
# Longitudinal jerk limit |Ax[i+1]-Ax[i]| <= JERK_MAX * dt_i: a kart pedal can
# go full-throttle to full-brake in roughly half a second (~18+5 m/s² swing),
# not instantaneously. Safety rail against pedal-slam chatter; must not
# meaningfully bind a smooth brake ramp.
JERK_MAX: float = 50.0        # m/s^3
# Lexicographic tiebreak: lap times within this relative band are "equal" and
# the lower-RMS-n'' (smoother) candidate wins. Wet multi-start candidates on
# either side of a puddle often land within IPOPT tolerance of each other;
# without the tiebreak the winner flips run-to-run with meaningless digits.
_LAP_TIE_REL: float = 1e-3


def central_second_diff_periodic(n: np.ndarray, ds: np.ndarray) -> np.ndarray:
    """Central second difference d2n/ds2 with periodic wrap (closed track).

    n: (N,) lateral offsets with n[0]==n[N-1] on a closed loop.
    ds: (N-1,) or (N,) arc-length spacing. The node before index 0 is N-2.
    """
    n = np.asarray(n, dtype=float)
    N = len(n)
    dsq = np.asarray(ds, dtype=float)
    h = np.empty(N)
    h[:len(dsq)] = dsq
    h[len(dsq):] = dsq[-1]
    h = np.maximum(h, 1e-6)
    nm = np.empty(N); npl = np.empty(N)
    nm[1:] = n[:-1]; nm[0] = n[N-2]      # i-1 with wrap across the seam
    npl[:-1] = n[1:]; npl[-1] = n[1]     # i+1 with wrap
    return (npl - 2.0 * n + nm) / (h**2)


def _offset_ds(ds: np.ndarray, n_sol: np.ndarray, kappa: np.ndarray) -> np.ndarray:
    """Offset-path arc length per centerline step: ds*(1 - n_mid*kappa_ref).

    The Frenet path-length Jacobian. ``kappa`` is SIGNED (+=left/CCW). On the
    inside of a corner ``n_mid*kappa > 0`` so the factor < 1 (shorter path);
    on the outside it is > 1 (longer path). Floored at ``_PATH_LEN_FLOOR`` to
    match the in-NLP per-segment scaling, so the numpy ranking and the solver
    objective integrate the SAME quantity.
    """
    n_mid = 0.5 * (np.asarray(n_sol)[:-1] + np.asarray(n_sol)[1:])
    k = np.asarray(kappa, dtype=float)[:len(ds)]
    return np.asarray(ds, dtype=float) * np.maximum(1.0 - n_mid * k, _PATH_LEN_FLOOR)


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
    """Linear 2D lookup mu(s, n) — the layout-locked SAMPLING contract.

    NOT used inside the NLP (the solver reads grip through
    :func:`_make_mu_interpolant_smooth`, a C2 bspline — IPOPT needs smooth
    derivatives).  This linear variant exactly matches GripSurface.mu_at's
    bilinear interpolation and pins the data layout: CasADi expects
    ``values`` flattened with the FIRST grid dimension varying FASTEST —
    Fortran order for our (M, K) grid.  Locked by
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


def _make_geom_interpolants(geom: "GeomField") -> dict:
    """Quasi-3D lookups kv(s,n)/camber(s,n)/grade(s,n) for use INSIDE the NLP.

    Mirrors :func:`_make_mu_interpolant_smooth` exactly: same C2 cubic-bspline
    interpolant family, same Fortran-order flatten (CasADi's FIRST grid
    dimension varies fastest). One interpolant per GeomField grid, returned
    keyed "kv"/"camber"/"grade" for the per-node lookups in :func:`_solve_once`.

    Falls back to "linear" when either axis has < 4 points: CasADi's cubic
    bspline needs >= 4 knots per dimension, and geometry grids (built from
    sparser elevation sampling than the mu grid) may not reach that density.
    mu's interpolant has no such fallback (its grids are always dense enough
    in practice), so this is new logic, not a mirror of mu's behaviour.
    """
    s_bins = geom.s_bins.tolist()
    n_bins = geom.n_bins.tolist()
    grids = [s_bins, n_bins]
    kind = "bspline" if (len(s_bins) >= 4 and len(n_bins) >= 4) else "linear"
    return {
        "kv": ca.interpolant(
            "kv_sn", kind, grids, geom.kv_grid.flatten(order="F").tolist(),
        ),
        "camber": ca.interpolant(
            "camber_sn", kind, grids, geom.camber_grid.flatten(order="F").tolist(),
        ),
        "grade": ca.interpolant(
            "grade_sn", kind, grids, geom.grade_grid.flatten(order="F").tolist(),
        ),
    }


def _candidate_lap_time(
    v_sol: np.ndarray,
    ds: np.ndarray,
    n_sol: np.ndarray | None = None,
    kappa: np.ndarray | None = None,
) -> float:
    """Lap time for a candidate solve.

    Default (``n_sol``/``kappa`` omitted) integrates the raw CENTERLINE
    ``ds`` — byte-for-byte the previous behaviour, kept for any caller that
    only has speed.  When both ``n_sol`` and ``kappa`` (SIGNED) are supplied
    the integral uses the OFFSET path length ``_offset_ds(ds, n_sol, kappa)``,
    so multi-start ranking credits the shorter inside line — consistent with
    the in-NLP objective (which now integrates the same Frenet Jacobian).
    """
    if n_sol is not None and kappa is not None:
        ds = _offset_ds(ds, n_sol, kappa)
    v_avg = np.maximum((v_sol[:-1] + v_sol[1:]) / 2.0, 1.0)
    return float(np.sum(ds / v_avg))


def _rms_d2n(n_sol: np.ndarray, ds: np.ndarray) -> float:
    """RMS of the periodic second difference n'' — the smoothness key of the
    lexicographic tiebreak (lower = smoother line)."""
    d2 = central_second_diff_periodic(np.asarray(n_sol, dtype=float), ds)
    return float(np.sqrt(np.mean(d2 ** 2)))


def _select_winner(
    candidates: Sequence[tuple],
    ds: np.ndarray,
    kappa: np.ndarray,
):
    """Status-tiered, lexicographic multi-start selection (Step 2).

    ``candidates`` are ``(status, v_sol, n_sol, ax_sol)`` in seed order.
    Tiers: "optimal" > "acceptable" > first candidate as-is ("suboptimal"
    exits have untrustworthy lap numbers — ranking them is false precision).
    Within a tier the key is lexicographic: PRIMARY offset-path lap time;
    SECONDARY (laps within ``_LAP_TIE_REL`` of each other) RMS n'' — wet
    multi-start candidates straddling a puddle often land within IPOPT
    tolerance of one another, and without the tiebreak the winner flips
    run-to-run on meaningless digits. Full ties keep the EARLIEST seed.
    Returns the winning candidate tuple itself (identity-preserved).
    """
    if not candidates:
        raise ValueError("candidates must be non-empty")
    for tier in ("optimal", "acceptable"):
        best = None
        best_lap = float("inf")
        best_rms = float("inf")
        for cand in candidates:
            if cand[0] != tier:
                continue
            lap = _candidate_lap_time(cand[1], ds, cand[2], kappa)
            rms = _rms_d2n(cand[2], ds)
            tie_band = _LAP_TIE_REL * min(lap, best_lap)
            if lap < best_lap - tie_band:
                best, best_lap, best_rms = cand, lap, rms
            elif lap <= best_lap + tie_band and rms < best_rms:
                best, best_lap, best_rms = cand, lap, rms
        if best is not None:
            return best
    return candidates[0]


def spread_n_lat_starts(
    width_left: np.ndarray,
    width_right: np.ndarray,
) -> tuple[float, ...]:
    """Default multi-start seeds spread across the track width (Step 2).

    The old wet default ``(0.0, 2.0, -2.0)`` under-reaches on wide tracks: a
    dry lane hugging the outer edge is never seeded, so a step-discontinuous
    puddle field's global (dry-side) line can be missed entirely. Seeds at
    fixed FRACTIONS of the usable half-width (0, ±45%, ±85% of 0.9·min width,
    matching the solver's 0.9 width margin) reach both edges on any track.
    Deterministic, centerline first, duplicates removed preserving order.
    """
    wl = 0.9 * float(np.min(np.asarray(width_left, dtype=float)))
    wr = 0.9 * float(np.min(np.asarray(width_right, dtype=float)))
    raw = [0.0]
    for f in (0.45, 0.85):
        raw.append(round(f * wl, 3))
        raw.append(round(-f * wr, 3))
    out: list[float] = []
    for o in raw:
        if o not in out:
            out.append(o)
    return tuple(out)


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
    ax_drive_interp=None,
    ax_brake_interp=None,
    grade_n=None,
    camber_n=None,
    geom_luts: dict | None = None,
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

    # Objective and the speed ODE both integrate the OFFSET path length, not
    # the raw centerline ds — folded into the single constraint loop below so
    # ds_path_i is computed once and used identically in both places. (Was a
    # separate raw-ds loop; the inside line earned no time credit.)
    total_time = 0
    # Task 4: accumulate the soft n'' regularizer (minimal smoothing). Uses the
    # SAME d2n_i second difference already computed for ay below.
    smooth_pen = 0
    # Step 2 driver model: per-segment steering angle (from the line's true
    # path curvature) and segment time, collected for the rate constraints
    # added after the loop (they couple consecutive segments incl. the seam).
    deltas: list = []
    dts: list = []

    for i in range(N - 1):
        kappa_i = kappa[i]
        # Frenet path-length Jacobian: an offset line covers (1 - n*kappa_ref)
        # of the centerline step — shorter inside a corner, longer outside.
        # kappa_i is SIGNED (Task 1). Floored at _PATH_LEN_FLOOR (< the 0.1
        # curvature denom floor) so inside-line shortening isn't understated.
        n_mid_i = (N_lat[i] + N_lat[i + 1]) / 2.0
        ds_path_i = ds[i] * ca.fmax(1.0 - n_mid_i * kappa_i, _PATH_LEN_FLOOR)

        v_avg = (V[i] + V[i + 1]) / 2.0
        total_time = total_time + ds_path_i / v_avg

        opti.subject_to(V[i + 1] ** 2 == V[i] ** 2 + 2 * Ax[i] * ds_path_i)

        denom_i = ca.fmax(1.0 - N_lat[i] * kappa_i, 0.1)
        im1 = N - 2 if i == 0 else i - 1                 # periodic wrap (node before the seam)
        d2n_i = (N_lat[i + 1] - 2.0 * N_lat[i] + N_lat[im1]) / (ds[i] ** 2)
        kappa_line_i = kappa_i / denom_i + d2n_i         # line's true path curvature (signed)
        ay_i = V[i] ** 2 * kappa_line_i

        # Step 2: steering angle implied by the line (bicycle kinematics,
        # kappa_line = tan(delta)/L) and the segment traversal time.
        deltas.append(ca.atan(vehicle.wheelbase_m * kappa_line_i))
        dts.append(ds_path_i / v_avg)

        # Task 4: minimal n'' smoothing, reusing the SAME d2n_i.
        #  - hard rail: forbid pathological |n''| spikes (generous safety cap,
        #    must NOT bind the clean line where max|d2n| ~ 0.02 << DKAPPA_MAX).
        #  - soft pen: small LAMBDA_SMOOTH*sum(d2n^2) kills residual chatter and
        #    re-conditions the step-discontinuous-puddle NLP.
        opti.subject_to(ca.fabs(d2n_i) <= DKAPPA_MAX)
        smooth_pen = smooth_pen + d2n_i ** 2

        if geom_luts is not None:
            # Quasi-3D: vertical curvature sampled at the LINE's (s, n), not
            # the centerline kv[i] — a banked/cambered line's effective kv
            # differs from the centerline's as the optimizer moves in n.
            kv_i = geom_luts["kv"](ca.vertcat(s_coords[i], N_lat[i]))
            g_eff_i = ca.fmax(G + V[i] ** 2 * kv_i, 1.0)
        else:
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
        if geom_luts is not None:
            # Quasi-3D: banking sampled at the LINE's (s, n) — camber_n
            # (legacy 1D, below) only ever saw the centerline's camber.
            # geom_luts being present governs this branch; the legacy
            # camber_n is not None condition applies only to the else path.
            camber_i = geom_luts["camber"](ca.vertcat(s_coords[i], N_lat[i]))
            ay_lim = ay_lim * (1.0 + K_CAMBER * ca.fabs(camber_i))
        elif camber_n is not None:
            # banking adds effective lateral grip (see K_CAMBER); camber_n is
            # banking magnitude — adverse camber treated as favourable in v1.
            ay_lim = ay_lim * (1.0 + K_CAMBER * abs(float(camber_n[i])))
        opti.subject_to((Ax[i] / ax_lim) ** 2 + (ay_i / ay_lim) ** 2 <= 1.0)

        drag = 0.5 * RHO_AIR * cda * V[i] ** 2 / m
        rr = 0.01 * g_eff_i
        v_safe = ca.fmax(V[i], 5.0)
        if geom_luts is not None:
            # Quasi-3D: grade sampled at the LINE's (s, n) — replaces the
            # frozen centerline g_sin in BOTH bounds below (drive and brake).
            grade_i = geom_luts["grade"](ca.vertcat(s_coords[i], N_lat[i]))
            g_sin = G * ca.sin(grade_i)
        else:
            g_sin = 0.0 if grade_n is None else G * float(np.sin(grade_n[i]))
        opti.subject_to(Ax[i] <= p_max / (m * v_safe) - drag - rr - g_sin)
        opti.subject_to(Ax[i] >= -(a_brake_max * g_eff_i / G + drag + rr) - g_sin)
        if ax_drive_interp is not None:
            opti.subject_to(Ax[i] <= ax_drive_interp(V[i]) - drag - rr)
        if ax_brake_interp is not None:
            opti.subject_to(Ax[i] >= -(ax_brake_interp(V[i]) + drag + rr))

    # Step 2 driver model: rate limits on consecutive segments, periodic at
    # the seam (segment N-2 wraps to segment 0 on a closed lap).
    #  - steering rate: hands can't flick the wheel faster than DDELTA_MAX
    #  - longitudinal jerk: the pedal swing Ax[i] -> Ax[i+1] takes time
    # Two-sided SMOOTH inequalities, NOT ca.fabs(diff) <= bound: fabs is
    # nonsmooth at 0 and every straight segment sits exactly there — the fabs
    # form blew the MKR dry solve past the 60 s gate-5 budget (64 s,
    # Maximum_CpuTime_Exceeded); the split form keeps IPOPT's derivatives
    # exact.
    for i in range(N - 2):
        opti.subject_to(deltas[i + 1] - deltas[i] <= DDELTA_MAX * dts[i])
        opti.subject_to(deltas[i] - deltas[i + 1] <= DDELTA_MAX * dts[i])
        opti.subject_to(Ax[i + 1] - Ax[i] <= JERK_MAX * dts[i])
        opti.subject_to(Ax[i] - Ax[i + 1] <= JERK_MAX * dts[i])
    opti.subject_to(deltas[0] - deltas[N - 2] <= DDELTA_MAX * dts[N - 2])
    opti.subject_to(deltas[N - 2] - deltas[0] <= DDELTA_MAX * dts[N - 2])
    opti.subject_to(Ax[0] - Ax[N - 2] <= JERK_MAX * dts[N - 2])
    opti.subject_to(Ax[N - 2] - Ax[0] <= JERK_MAX * dts[N - 2])

    # Task 4: total_time (~22 s) dominates; LAMBDA_SMOOTH*smooth_pen is the
    # "minimal smoothing" nudge that removes residual scatter without distorting
    # the line. smooth_pen is tiny on a smooth line, so the weight must bite.
    opti.minimize(total_time + LAMBDA_SMOOTH * smooth_pen)

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
    n_windows: Sequence[tuple[float, float, float, float]] = (),
    envelope_caps: dict | None = None,
    grade_s: np.ndarray | None = None,
    camber_s: np.ndarray | None = None,
    geom_field: "GeomField | None" = None,
) -> OCPSolution:
    """Minimum-time OCP with a 2D friction field mu(s, n) inside the NLP.

    Identical formulation to ocp._solve_casadi except the friction-ellipse
    limits use mu_field evaluated at (s_i, N_lat[i]) — grip depends on the
    line the optimizer chooses, so it can route around lateral low-grip
    cells instead of only slowing for them.

    The per-point grip multiplier from TrackModel.grip_map is IGNORED here;
    mu_field is the single source of surface grip.  Vehicle tyre D and
    weather.grip_multiplier still scale globally as in ocp.py.

    Quasi-3D geometry (``geom_field``)
    -----------------------------------
    When ``geom_field`` (a ``track_surface.geom_field.GeomField``) is given,
    kv/camber/grade are looked up at the LINE's chosen (s, N_lat[i]) via
    casadi bspline interpolants built once here (:func:`_make_geom_interpolants`)
    and threaded through every multi-start candidate — the same treatment
    mu_field already gets. This supersedes the legacy centerline-only
    ``grade_s``/``camber_s`` 1D arrays and the resampled ``kv`` array for the
    three terms they feed (g_eff, the camber ay_lim boost, g_sin) wherever
    both are supplied. ``geom_field=None`` (the default) is BYTE-COMPATIBLE
    with the pre-quasi-3D solve: every new code path is guarded behind
    ``if geom_luts is not None`` with the prior lines preserved verbatim in
    the else branch.

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

    Hard corridor exclusions (``n_windows``)
    ----------------------------------------
    Each entry ``(s_start, s_end, n_lo, n_hi)`` further constrains the
    lateral corridor: for every resampled point whose (clamped) arclength
    ``s_coords[i]`` lies in ``[s_start, s_end]``, the per-point N_lat bounds
    are INTERSECTED with ``[n_lo, n_hi]`` (use ``±float('inf')`` to leave one
    side unconstrained).  This is the HARD-exclusion mechanism for KNOWN
    hazards — standing-water puddles whose geometry comes from the drainage
    model — as opposed to the soft mu-penalty cells that free optimization
    routes around.  Free optimization handles PREFERENCE (route toward grip);
    windows handle PROHIBITION (never enter this lateral band here).  The
    bounds are applied BEFORE they are used for both the box constraints and
    the multi-start guess clipping, so seeded guesses are clipped into the
    corridor automatically.  If the intersection leaves ``lo > hi`` at any
    point, a ``ValueError`` is raised with the offending ``s`` — an impossible
    corridor is a caller bug (e.g. overlapping exclusions), not a solve
    failure.  The default ``()`` applies no exclusions.

    Empirical conditioning note: corridor bounds that sit ON a steep grip
    transition ill-condition the friction ellipse (observed:
    Maximum_Iterations_Exceeded even at 8000 iters with the bound at the mu
    step; <2s solve with the bound 1 bin clear).
    ``puddles_to_n_windows`` bounds always sit at radius+margin, clear of the
    flooded cells.
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
    kappa = tk.curvature.astype(np.float64)  # SIGNED (+=left/CCW)
    s_coords = np.concatenate(([0.0], np.cumsum(ds)))          # (N,)
    s_coords = np.clip(s_coords, float(mu_field.s_bins[0]), float(mu_field.s_bins[-1]))

    kv = np.zeros(N, dtype=np.float64)
    if tk.vert_curvature is not None and len(tk.vert_curvature) == N:
        kv = np.asarray(tk.vert_curvature, dtype=np.float64)

    def _to_n(arr):
        if arr is None:
            return None
        a = np.asarray(arr, dtype=np.float64)
        if len(a) == N:
            return a
        return np.interp(np.linspace(0, 1, N), np.linspace(0, 1, len(a)), a)
    grade_n = _to_n(grade_s)        # radians, + = uphill along travel
    camber_n = _to_n(camber_s)      # radians, banking magnitude raises lateral grip

    # The NLP reads grip through the C2 cubic-bspline interpolant: IPOPT
    # assumes twice-differentiable constraints, and the C0 'linear' field's
    # derivative kinks both stall certification (spurious "suboptimal") and
    # let iterates slide back across grip steps into local basins.  The linear
    # interpolant remains the layout-locked data-sampling contract elsewhere.
    # Built ONCE here and reused across every multi-start solve.
    mu_lut = _make_mu_interpolant_smooth(mu_field)
    # Quasi-3D: built ONCE and reused across every multi-start solve, same as
    # mu_lut above. None when no geom_field is supplied — the sole gate that
    # keeps the default solve byte-compatible with the pre-quasi-3D behaviour.
    geom_luts = _make_geom_interpolants(geom_field) if geom_field is not None else None
    ax_drive_interp = None
    ax_brake_interp = None
    if (envelope_caps and "v_grid" in envelope_caps
            and "ax_drive_max" in envelope_caps and "ax_brake_max" in envelope_caps):
        _ev = [float(x) for x in envelope_caps["v_grid"]]
        ax_drive_interp = ca.interpolant(
            "ax_drive_lookup", "linear", [_ev],
            [float(x) for x in envelope_caps["ax_drive_max"]])
        ax_brake_interp = ca.interpolant(
            "ax_brake_lookup", "linear", [_ev],
            [float(x) for x in envelope_caps["ax_brake_max"]])
    # Floor mu_ceiling at EPS_GRIP so a degenerate all-zero field doesn't let
    # the cap override the EPS_GRIP floor (fmin(EPS_GRIP, 0) = 0 → NaN Jacobian)
    mu_ceiling = max(float(mu_field.mu_grid.max()), EPS_GRIP)

    v_guess = corner_speed(np.abs(kappa), vehicle) * weather.grip_multiplier
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

    # Per-point N_lat bounds: track width ∩ field n-domain (same as
    # constraints).  Then HARD corridor exclusions (n_windows) are intersected
    # in BEFORE the bounds feed both the box constraints and the guess clip, so
    # known-hazard prohibition and guess seeding stay consistent.
    n_lo_field = float(mu_field.n_bins[0])
    n_hi_field = float(mu_field.n_bins[-1])
    # Geometry lookups must never extrapolate: cubic bspline is unbounded
    # outside knots, so additionally intersect with geom_field's n-domain when
    # geom_field is provided (same pattern as mu_field intersection).
    if geom_field is not None:
        n_lo_field = max(n_lo_field, float(geom_field.n_bins[0]))
        n_hi_field = min(n_hi_field, float(geom_field.n_bins[-1]))
    n_bounds: list[tuple[float, float]] = []
    lo_arr = np.empty(N)
    hi_arr = np.empty(N)
    for i in range(N):
        lo = max(-float(tk.width_right[i]) * 0.9, n_lo_field)
        hi = min(float(tk.width_left[i]) * 0.9, n_hi_field)
        for (s_start, s_end, w_lo, w_hi) in n_windows:
            if s_start <= s_coords[i] <= s_end:
                lo = max(lo, w_lo)
                hi = min(hi, w_hi)
        if lo > hi:
            raise ValueError(
                f"n_windows produced an empty lateral corridor at s={s_coords[i]:.2f} "
                f"(lo={lo:.3f} > hi={hi:.3f}) — an impossible corridor is a caller bug, "
                "not a solve failure"
            )
        n_bounds.append((lo, hi))
        lo_arr[i] = lo
        hi_arr[i] = hi

    # Deterministic multi-start: one independent solve per offset, in order.
    # Selection is delegated to _select_winner: status-tiered ("optimal" >
    # "acceptable" > first as-is), lexicographic within a tier (offset-path
    # lap time, then RMS n'' when laps tie within _LAP_TIE_REL).
    candidates: list[tuple[str, np.ndarray, np.ndarray, np.ndarray]] = []
    for o in n_lat_starts:
        n_guess = np.clip(base_n_guess + o, lo_arr, hi_arr)
        candidates.append(_solve_once(
            N=N, ds=ds, kappa=kappa, kv=kv, s_coords=s_coords, mu_lut=mu_lut,
            n_bounds=n_bounds, v_guess=v_guess, n_guess=n_guess, ax_guess=ax_guess,
            vehicle=vehicle, weather=weather, max_time_s=max_time_s,
            mu_ceiling=mu_ceiling,
            ax_drive_interp=ax_drive_interp, ax_brake_interp=ax_brake_interp,
            grade_n=grade_n, camber_n=camber_n, geom_luts=geom_luts,
        ))

    status, v_sol, n_lat_sol, ax_sol = _select_winner(candidates, ds, kappa)

    elapsed = time.perf_counter() - t0
    solution = _build_solution(
        track, vehicle, weather, tk, v_sol, n_lat_sol, ax_sol, ds, status, elapsed,
    )
    # _build_solution integrates the raw centerline ds (it is SHARED with the 1D
    # solver and must keep that behaviour for the 1D caller). For the 2D solver
    # the inside line is genuinely shorter, so overwrite the REPORTED lap time
    # with the offset-path integral — same Frenet Jacobian the NLP minimised.
    # distance_m stays centerline-based (unchanged), so only the scalar shifts.
    solution.optimal_lap_time_s = _candidate_lap_time(v_sol, ds, n_lat_sol, kappa)
    return solution
