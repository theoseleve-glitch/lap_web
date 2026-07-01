"""Stitched minimum-time 2D OCP: solve the lap as ≤50 m sub-sectors.

Scheme (design spec 2026-06-10, Telemetry root docs/superpowers/specs/):
coarse-anchored overlap windows + Jacobi consensus sweeps. Each sub-sector
is the SAME friction-ellipse physics as :mod:`ocp_2d` but solved as an open
boundary-value problem whose ends are pinned (V and two N_lat nodes — fixing
n and dn/ds) to a shared consensus trajectory; after each parallel-safe sweep
the consensus is rebuilt from the sector solutions. Enables per-sector
re-solves and parallel solving.
"""
from __future__ import annotations

import logging

import numpy as np

from telemetry_tool.lap_oracle.config import VehicleParams, WeatherConditions
from telemetry_tool.lap_oracle.solver.ocp import HAS_CASADI
from telemetry_tool.lap_oracle.solver.ocp_2d import (
    DDELTA_MAX,
    DKAPPA_MAX,
    EPS_GRIP,
    G,
    JERK_MAX,
    K_CAMBER,
    LAMBDA_SMOOTH,
    RHO_AIR,
    _PATH_LEN_FLOOR,
)

if HAS_CASADI:
    import casadi as ca

logger = logging.getLogger(__name__)

_N_PIN = 2  # nodes pinned at each window end: fixes V, n AND dn/ds at the seam
# Soft V pins: hard equalities made a sector infeasible whenever the consensus
# was even slightly hotter than the window physics allows (with the Step-2
# jerk limits the end Ax is nearly fixed by hard pins too). The line pins (n)
# stay HARD — they carry the seam-continuity acceptance; V pins only need to
# keep the line solved at realistic speeds, the OUTPUT speed comes from the
# global speed-on-line pass. The band bounds the worst case; the quadratic
# penalty keeps V at the pin whenever the pin is feasible.
V_PIN_BAND = 3.0    # m/s hard band around the consensus pin
W_VPIN = 10.0       # s/(m/s)^2 quadratic pin penalty (lap time is ~10-60 s)
# Partition-of-unity blend + damping. Hard ownership splicing discarded the
# transition tails each sector's local optimum relied on, leaving kinks at
# every cut that the next (Jacobi, simultaneous) sweep amplified — observed
# monotone divergence 22.7 -> 28.5 s with every sector individually
# 'optimal' and claiming a local improvement. Triangular weights fade each
# window's influence to zero at its free-zone edges (smooth handoff into the
# neighbour, no kink injection); the damped update keeps simultaneous moves
# from overshooting.
_BLEND_DAMP = 0.7   # fraction of the blended proposal applied per sweep
_V_CRAWL = 1.0      # m/s speed-pass V floor (see _solve_speed_on_line note)

_MIN_SECTOR_NODES = 4
_SNAP_RADIUS = 2  # nodes a cut may move to land on a straighter node


def partition_sectors(
    ds: np.ndarray,
    kappa: np.ndarray,
    sector_length_m: float = 50.0,
) -> list[tuple[int, int]]:
    """Partition node indices 0..N-1 into contiguous sectors ≤ sector_length_m.

    Returns ``[(start, end), ...]`` where each sector owns nodes
    ``start..end`` and consecutive sectors share their cut node
    (``end`` of one == ``start`` of the next), tiling the closed lap.
    Each interior cut is snapped (within ±_SNAP_RADIUS nodes) to the node of
    minimum ``|kappa|`` — boundary states are least sensitive on the
    straightest available node — but only if the snap keeps both adjacent
    sectors ≤ sector_length_m and ≥ _MIN_SECTOR_NODES nodes. Deterministic:
    greedy walk, ties snap to the lowest index.
    """
    ds = np.asarray(ds, dtype=float)
    kappa = np.asarray(kappa, dtype=float)
    n_nodes = len(ds) + 1
    s = np.concatenate(([0.0], np.cumsum(ds)))  # (N,)

    # Greedy walk with in-walk snapping: extend the sector as far as the
    # length cap allows, then snap the cut BACKWARD (≤ _SNAP_RADIUS nodes) to
    # the straightest candidate. Snapping forward would exceed the cap;
    # snapping during the walk (not after) lets the next sector start from
    # the snapped node, so every sector still honours the cap.
    cuts = [0]
    i = 0
    while i < n_nodes - 1:
        j = i
        while j < n_nodes - 1 and s[j + 1] - s[i] <= sector_length_m + 1e-9:
            j += 1
        if j == i:  # single step longer than the cap — still advance
            j = i + 1
        if j < n_nodes - 1:  # interior cut: snap to min |kappa| (ties → lowest)
            lo = max(i + _MIN_SECTOR_NODES - 1, j - _SNAP_RADIUS)
            best = j
            for cand in range(lo, j + 1):
                if abs(kappa[cand]) < abs(kappa[best]) - 1e-15 or (
                    abs(kappa[cand]) <= abs(kappa[best]) + 1e-15 and cand < best
                ):
                    best = cand
            j = best
        cuts.append(j)
        i = j
    # Merge a runt tail (< _MIN_SECTOR_NODES) into the previous sector when
    # the combined length still fits; otherwise keep it (length cap wins).
    if (len(cuts) >= 3 and cuts[-1] - cuts[-2] + 1 < _MIN_SECTOR_NODES
            and s[cuts[-1]] - s[cuts[-3]] <= sector_length_m + 1e-9):
        cuts.pop(-2)

    return [(cuts[k], cuts[k + 1]) for k in range(len(cuts) - 1)]


def _solve_sector(
    *,
    ds: np.ndarray,
    kappa: np.ndarray,
    kv: np.ndarray,
    s_coords: np.ndarray,
    mu_lut,
    n_bounds: list[tuple[float, float]],
    cons_v: np.ndarray,
    cons_n: np.ndarray,
    ax_guess: np.ndarray,
    vehicle: VehicleParams,
    weather: WeatherConditions,
    max_time_s: float,
    mu_ceiling: float,
    n_ghost_prev: float,
    ax_drive_interp=None,
    ax_brake_interp=None,
    grade_n=None,
    camber_n=None,
) -> tuple[str, np.ndarray, np.ndarray, np.ndarray]:
    """One open-window sector solve, boundary-pinned to the consensus.

    Identical per-segment physics to ocp_2d._solve_once (offset path length
    in objective and speed ODE, n''-priced friction ellipse, DKAPPA_MAX rail,
    LAMBDA_SMOOTH regularizer, grip LUT at the line) but the window is OPEN:
    instead of periodic closure, the outermost _N_PIN nodes at each end have
    V and N_lat fixed to the consensus trajectory. Two pinned N_lat nodes fix
    both n and dn/ds at the seam, so neighbouring sectors pinned to the same
    consensus are V/n/n'-continuous by construction. d2n at the first segment
    uses ``n_ghost_prev`` (the consensus n just before the window) so seam
    curvature is priced exactly as the monolithic NLP would.

    Returns ``(status, v_sol, n_sol, ax_sol)`` over the window nodes.
    """
    n_w = len(cons_v)
    m = vehicle.mass_kg
    cda = vehicle.cda
    cla = vehicle.cla
    p_max = vehicle.max_power_w
    a_brake_max = vehicle.max_brake_decel
    mu_lat_base = vehicle.tyre_lat.D * weather.grip_multiplier
    mu_long_base = vehicle.tyre_long.D * weather.grip_multiplier

    opti = ca.Opti()
    V = opti.variable(n_w)
    N_lat = opti.variable(n_w)
    Ax = opti.variable(n_w - 1)
    opti.set_initial(V, cons_v)
    opti.set_initial(N_lat, cons_n)
    opti.set_initial(Ax, ax_guess)

    total_time = 0
    smooth_pen = 0
    # Step 2 driver model (same as the monolithic NLP): per-segment steering
    # angle and traversal time, for the rate limits added after the loop.
    deltas = []
    dts = []
    for i in range(n_w - 1):
        kappa_i = kappa[i]
        n_mid_i = (N_lat[i] + N_lat[i + 1]) / 2.0
        ds_path_i = ds[i] * ca.fmax(1.0 - n_mid_i * kappa_i, _PATH_LEN_FLOOR)

        v_avg = (V[i] + V[i + 1]) / 2.0
        total_time = total_time + ds_path_i / v_avg

        opti.subject_to(V[i + 1] ** 2 == V[i] ** 2 + 2 * Ax[i] * ds_path_i)

        denom_i = ca.fmax(1.0 - N_lat[i] * kappa_i, 0.1)
        # open window: the node before i=0 is the consensus ghost, NOT a wrap
        nm1 = n_ghost_prev if i == 0 else N_lat[i - 1]
        d2n_i = (N_lat[i + 1] - 2.0 * N_lat[i] + nm1) / (ds[i] ** 2)
        kappa_line_i = kappa_i / denom_i + d2n_i
        ay_i = V[i] ** 2 * kappa_line_i

        deltas.append(ca.atan(vehicle.wheelbase_m * kappa_line_i))
        dts.append(ds_path_i / v_avg)

        opti.subject_to(ca.fabs(d2n_i) <= DKAPPA_MAX)
        smooth_pen = smooth_pen + d2n_i ** 2

        g_eff_i = ca.fmax(G + V[i] ** 2 * kv[i], 1.0)
        fz_total = m * g_eff_i + 0.5 * RHO_AIR * cla * V[i] ** 2

        grip_i = mu_lut(ca.vertcat(s_coords[i], N_lat[i]))
        grip_i = ca.fmax(grip_i, EPS_GRIP)
        grip_i = ca.fmin(grip_i, mu_ceiling)
        mu_lat_i = mu_lat_base * grip_i
        mu_long_i = mu_long_base * grip_i
        ax_lim = mu_long_i * fz_total / m
        ay_lim = mu_lat_i * fz_total / m
        if camber_n is not None:
            ay_lim = ay_lim * (1.0 + K_CAMBER * abs(float(camber_n[i])))
        opti.subject_to((Ax[i] / ax_lim) ** 2 + (ay_i / ay_lim) ** 2 <= 1.0)

        drag = 0.5 * RHO_AIR * cda * V[i] ** 2 / m
        rr = 0.01 * g_eff_i
        v_safe = ca.fmax(V[i], 5.0)
        g_sin = 0.0 if grade_n is None else G * float(np.sin(grade_n[i]))
        opti.subject_to(Ax[i] <= p_max / (m * v_safe) - drag - rr - g_sin)
        opti.subject_to(Ax[i] >= -(a_brake_max * g_eff_i / G + drag + rr) - g_sin)
        if ax_drive_interp is not None:
            opti.subject_to(Ax[i] <= ax_drive_interp(V[i]) - drag - rr)
        if ax_brake_interp is not None:
            opti.subject_to(Ax[i] >= -(ax_brake_interp(V[i]) + drag + rr))

    # Step 2 driver model: steering-rate + longitudinal-jerk limits between
    # consecutive segments. Open window — no wrap; cross-seam continuity is
    # the consensus pins' job (the consensus comes from rate-limited solves).
    # Two-sided smooth form (no fabs) — same rationale as the monolithic NLP.
    for i in range(n_w - 2):
        opti.subject_to(deltas[i + 1] - deltas[i] <= DDELTA_MAX * dts[i])
        opti.subject_to(deltas[i] - deltas[i + 1] <= DDELTA_MAX * dts[i])
        opti.subject_to(Ax[i + 1] - Ax[i] <= JERK_MAX * dts[i])
        opti.subject_to(Ax[i] - Ax[i + 1] <= JERK_MAX * dts[i])

    # _V_CRAWL floor (not the monolithic 5.0): the consensus pins come from
    # the speed pass, which crawls below 5 m/s through hairpins the anchor
    # line takes badly — a 5.0 floor makes the pin band [max(pv-B, 5), pv+B]
    # EMPTY exactly in the sectors that must fix that line (observed on MKR:
    # the hairpin sectors went infeasible, fell back, and the line never
    # recovered from the anchor).
    opti.subject_to(opti.bounded(_V_CRAWL, V, 120.0))
    for i in range(n_w):
        lo, hi = n_bounds[i]
        opti.subject_to(opti.bounded(lo, N_lat[i], hi))

    # Boundary pins — the continuity mechanism (replaces periodic closure).
    # n pins HARD (they carry seam continuity of the line and its slope);
    # V pins SOFT (quadratic penalty + V_PIN_BAND hard band) so a consensus
    # speed slightly hotter than the window physics bends the solve instead
    # of making it infeasible (see V_PIN_BAND note at module top).
    vpin_pen = 0
    for i in list(range(_N_PIN)) + list(range(n_w - _N_PIN, n_w)):
        pv = float(cons_v[i])
        opti.subject_to(opti.bounded(
            max(pv - V_PIN_BAND, _V_CRAWL), V[i],
            min(pv + V_PIN_BAND, 120.0)))
        vpin_pen = vpin_pen + (V[i] - pv) ** 2
        opti.subject_to(N_lat[i] == float(cons_n[i]))

    opti.minimize(total_time + LAMBDA_SMOOTH * smooth_pen + W_VPIN * vpin_pen)

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
        n_sol = np.array(sol.value(N_lat)).flatten()
        ax_sol = np.array(sol.value(Ax)).flatten()
    except RuntimeError:
        ret = opti.return_status()
        status = "acceptable" if ret == "Solved_To_Acceptable_Level" else "suboptimal"
        logger.warning(
            "ocp_2d_stitched: sector IPOPT non-optimal (return_status=%s)", ret,
        )
        v_sol = np.clip(np.array(opti.debug.value(V)).flatten(), 5.0, 120.0)
        n_sol = np.array(opti.debug.value(N_lat)).flatten()
        ax_sol = np.array(opti.debug.value(Ax)).flatten()
    return status, v_sol, n_sol, ax_sol


def _lateral_speed_cap(
    v: np.ndarray,
    cons_n: np.ndarray,
    kappa: np.ndarray,
    ds: np.ndarray,
    mu_line: np.ndarray,
    vehicle: VehicleParams,
    weather: WeatherConditions | None = None,
    margin: float = 0.99,
) -> np.ndarray:
    """Cap consensus V under the lateral grip limit at the consensus line.

    The coarse anchor under-samples curvature peaks; interpolated onto the
    fine grid its V can violate ``V²·κ_line ≤ ay_lim`` at a pinned node — a
    hard friction-ellipse infeasibility no accel clamp can fix. Solves the
    point-mass corner-speed balance per node, downforce included:
    ``v²·κ = margin·mu_lat·(g + 0.5·rho·cla·v²/m)`` →
    ``v² = margin·mu_lat·g / (κ − margin·mu_lat·0.5·rho·cla/m)`` (cap only
    when the denominator is positive — otherwise downforce wins and grip
    never binds). κ_line is the SIGNED sum κ_ref/denom + n'' the NLP prices —
    a racing line typically REDUCES curvature, so summing magnitudes instead
    would grossly over-cap corner speed (observed +11% lap on the oval).
    Only ever LOWERS speeds. ``mu_line`` is mu sampled at (s_i, cons_n_i).
    ``margin`` is deliberately mild (0.99): the cap exists to keep pinned
    nodes out of hard ellipse infeasibility, not to act as a speed solver.
    """
    from telemetry_tool.lap_oracle.solver.ocp_2d import (
        central_second_diff_periodic,
    )
    if weather is None:
        weather = WeatherConditions()
    v = np.asarray(v, dtype=float).copy()
    m = vehicle.mass_kg
    cla = vehicle.cla
    mu_lat = vehicle.tyre_lat.D * weather.grip_multiplier * np.asarray(mu_line)
    denom_ref = np.maximum(1.0 - np.asarray(cons_n) * np.asarray(kappa), 0.1)
    d2n = central_second_diff_periodic(np.asarray(cons_n), ds)
    kappa_line = np.abs(np.asarray(kappa) / denom_ref + d2n)
    eff = kappa_line - margin * mu_lat * 0.5 * RHO_AIR * cla / m
    cap_mask = eff > 1e-9
    v_cap = np.sqrt(margin * mu_lat[cap_mask] * G / eff[cap_mask])
    v[cap_mask] = np.minimum(v[cap_mask], v_cap)
    return v


def _clamp_consensus_speed(
    v: np.ndarray,
    ds: np.ndarray,
    vehicle: VehicleParams,
    margin: float = 0.95,
    envelope_caps: dict | None = None,
    long_scale: np.ndarray | None = None,
    ax_grip_lim: np.ndarray | None = None,
) -> np.ndarray:
    """Forward-backward feasibility clamp on the consensus speed profile.

    Boundary pins are EQUALITY constraints on V; if the consensus asks for a
    speed change a sector's accel/brake limits cannot deliver, the sector NLP
    is infeasible by construction (observed on MKR: Infeasible_Problem_
    Detected). This pure-numpy pass pulls the profile under conservative
    point-mass limits — power-limited drive ``margin*p/(m*v)`` and brake
    ``margin*max_brake_decel`` — iterated forward and backward around the
    closed lap until stable, so every pinned pair is mutually reachable.
    Only ever LOWERS speeds. ``margin`` (< 1) leaves the in-NLP physics
    (drag, rr, grade, grip ellipse) slack to bind first.

    ``long_scale`` (per-node, in [0, 1]) is the friction-ellipse longitudinal
    headroom ``sqrt(1 - (ay/ay_lim)²)`` at the consensus line: braking while
    cornering leaves less longitudinal grip, so a corner-entry pin reachable
    under full straight-line braking can still be infeasible. None → 1.

    ``ax_grip_lim`` (per-node, m/s²) is the grip-limited longitudinal cap
    ``mu_long·fz/m`` at the consensus line — on low grip it sits far below
    the power/brake limits and is the binding constraint at a pinned node
    (where the pins fix BOTH ay and Ax). None → power/brake/envelope only.
    """
    v = np.asarray(v, dtype=float).copy()
    ds = np.asarray(ds, dtype=float)
    m = vehicle.mass_kg
    n = len(v)
    env_v = env_drive = env_brake = None
    if (envelope_caps and "v_grid" in envelope_caps
            and "ax_drive_max" in envelope_caps
            and "ax_brake_max" in envelope_caps):
        env_v = np.asarray(envelope_caps["v_grid"], dtype=float)
        env_drive = np.asarray(envelope_caps["ax_drive_max"], dtype=float)
        env_brake = np.asarray(envelope_caps["ax_brake_max"], dtype=float)
    scale = np.ones(n) if long_scale is None else np.clip(
        np.asarray(long_scale, dtype=float), 0.05, 1.0)
    for _ in range(3):  # wrap coupling settles in <= 3 ring passes
        changed = False
        for i in range(n - 1):  # forward: accel limit
            a_max = vehicle.max_power_w / (m * max(v[i], 5.0))
            if env_v is not None:
                a_max = min(a_max, float(np.interp(v[i], env_v, env_drive)))
            if ax_grip_lim is not None:
                a_max = min(a_max, float(ax_grip_lim[i]))
            a_max = max(a_max, 0.1) * scale[i]
            cap = np.sqrt(v[i] ** 2 + 2.0 * margin * a_max * ds[i])
            if v[i + 1] > cap:
                v[i + 1] = cap
                changed = True
        if v[0] > v[n - 1]:
            v[0] = v[n - 1]
            changed = True
        for i in range(n - 2, -1, -1):  # backward: brake limit
            b_max = vehicle.max_brake_decel
            if env_v is not None:
                b_max = min(b_max, float(np.interp(v[i + 1], env_v, env_brake)))
            if ax_grip_lim is not None:
                b_max = min(b_max, float(ax_grip_lim[i]))
            b_max = max(b_max, 0.1) * scale[i]
            cap = np.sqrt(v[i + 1] ** 2 + 2.0 * margin * b_max * ds[i])
            if v[i] > cap:
                v[i] = cap
                changed = True
        if v[n - 1] > v[0]:
            v[n - 1] = v[0]
            changed = True
        if not changed:
            break
    return v


def _solve_speed_on_line(
    *,
    ds: np.ndarray,
    kappa: np.ndarray,
    kv: np.ndarray,
    s_coords: np.ndarray,
    mu_lut,
    n_line: np.ndarray,
    v_guess: np.ndarray,
    vehicle: VehicleParams,
    weather: WeatherConditions,
    max_time_s: float,
    mu_ceiling: float,
    ax_drive_interp=None,
    ax_brake_interp=None,
    grade_n=None,
    camber_n=None,
) -> tuple[str, np.ndarray, np.ndarray]:
    """Global speed-only solve on a FIXED line (the stitch coordination pass).

    Same physics as the monolithic NLP but with N_lat a numpy constant
    (the stitched line), so the only variables are V and Ax over the full
    closed lap with periodic closure. This is what makes the stitched result
    globally consistent: the line comes from the sub-sector solves, the speed
    from one cheap whole-lap pass — V is continuous everywhere by
    construction and there are no boundary speed pins left to go infeasible.
    """
    from telemetry_tool.lap_oracle.solver.ocp_2d import (
        central_second_diff_periodic,
    )
    N = len(n_line)
    m = vehicle.mass_kg
    cda = vehicle.cda
    cla = vehicle.cla
    p_max = vehicle.max_power_w
    a_brake_max = vehicle.max_brake_decel
    mu_lat_base = vehicle.tyre_lat.D * weather.grip_multiplier
    mu_long_base = vehicle.tyre_long.D * weather.grip_multiplier

    n = np.asarray(n_line, dtype=float)
    d2n = central_second_diff_periodic(n, ds)
    mu_line = np.array([
        float(mu_lut(ca.DM([s_coords[i], n[i]]))) for i in range(N)
    ])
    mu_line = np.clip(mu_line, EPS_GRIP, mu_ceiling)

    # Shape the initial guess to near-feasibility (lateral grip, steering
    # rate, reachability). With hairpin-grade flicks the crawl profile is
    # far from a flat guess and IPOPT's restoration phase can stall at a
    # local infeasibility instead of finding it.
    v0 = _lateral_speed_cap(
        np.asarray(v_guess, dtype=float).copy(), n, kappa, ds, mu_line,
        vehicle, weather=weather)
    delta_arr = np.arctan(
        vehicle.wheelbase_m
        * (kappa[:-1] / np.maximum(1.0 - n[:-1] * kappa[:-1], 0.1)
           + d2n[:-1]))
    dd_arr = np.abs(np.diff(delta_arr))
    for i in range(len(dd_arr)):
        if dd_arr[i] > 1e-12:
            cap = max(float(DDELTA_MAX * ds[i] / dd_arr[i]), 5.1)
            v0[i] = min(v0[i], cap + 0.5)
            v0[i + 1] = min(v0[i + 1], cap + 0.5)
    v0 = _clamp_consensus_speed(v0, ds, vehicle)
    v0 = np.clip(v0, 5.0, 120.0)

    opti = ca.Opti()
    V = opti.variable(N)
    Ax = opti.variable(N - 1)
    opti.set_initial(V, v0)
    opti.set_initial(Ax, np.diff(v0 ** 2) / (2.0 * np.maximum(ds, 1e-6)))

    total_time = 0
    # Step-2 driver model on a FIXED line: delta_i is a CONSTANT per segment,
    # so the steering-rate limit |Δdelta| <= DDELTA_MAX·dt becomes a pure
    # speed cap (dt_i >= |Δdelta|/DDELTA_MAX). Without it the speed pass
    # reports laps the driver model forbids — and can illegitimately beat
    # the monolithic solve through flicks. Jerk stays a constraint on Ax.
    deltas = []
    dts = []
    ds_paths = []
    for i in range(N - 1):
        kappa_i = kappa[i]
        n_mid_i = (n[i] + n[i + 1]) / 2.0
        ds_path_i = ds[i] * max(1.0 - n_mid_i * kappa_i, _PATH_LEN_FLOOR)
        v_avg = (V[i] + V[i + 1]) / 2.0
        total_time = total_time + ds_path_i / v_avg
        opti.subject_to(V[i + 1] ** 2 == V[i] ** 2 + 2 * Ax[i] * ds_path_i)

        denom_i = max(1.0 - n[i] * kappa_i, 0.1)
        kappa_line_i = kappa_i / denom_i + d2n[i]
        ay_i = V[i] ** 2 * kappa_line_i
        deltas.append(float(np.arctan(vehicle.wheelbase_m * kappa_line_i)))
        dts.append(ds_path_i / v_avg)
        ds_paths.append(ds_path_i)

        g_eff_i = ca.fmax(G + V[i] ** 2 * kv[i], 1.0)
        fz_total = m * g_eff_i + 0.5 * RHO_AIR * cla * V[i] ** 2
        mu_lat_i = mu_lat_base * mu_line[i]
        mu_long_i = mu_long_base * mu_line[i]
        ax_lim = mu_long_i * fz_total / m
        ay_lim = mu_lat_i * fz_total / m
        if camber_n is not None:
            ay_lim = ay_lim * (1.0 + K_CAMBER * abs(float(camber_n[i])))
        opti.subject_to((Ax[i] / ax_lim) ** 2 + (ay_i / ay_lim) ** 2 <= 1.0)

        drag = 0.5 * RHO_AIR * cda * V[i] ** 2 / m
        rr = 0.01 * g_eff_i
        v_safe = ca.fmax(V[i], 5.0)
        g_sin = 0.0 if grade_n is None else G * float(np.sin(grade_n[i]))
        opti.subject_to(Ax[i] <= p_max / (m * v_safe) - drag - rr - g_sin)
        opti.subject_to(
            Ax[i] >= -(a_brake_max * g_eff_i / G + drag + rr) - g_sin)
        if ax_drive_interp is not None:
            opti.subject_to(Ax[i] <= ax_drive_interp(V[i]) - drag - rr)
        if ax_brake_interp is not None:
            opti.subject_to(Ax[i] >= -(ax_brake_interp(V[i]) + drag + rr))

    # Rate limits, periodic at the seam — mirrors the monolithic NLP. With
    # deltas constant the steering-rate constraint is linear in v_avg:
    # |Δdelta|·v_avg <= DDELTA_MAX·ds_path.
    def _rate_pair(i, j):
        dd = abs(deltas[j] - deltas[i])
        if dd > 1e-12:
            # Floor the cap above the crawl floor so the constraint can
            # never contradict the variable bound.
            cap = max(DDELTA_MAX * ds_paths[i] / dd, _V_CRAWL + 0.1)
            v_avg_i = (V[i] + V[i + 1]) / 2.0
            opti.subject_to(v_avg_i <= cap)
        opti.subject_to(Ax[j] - Ax[i] <= JERK_MAX * dts[i])
        opti.subject_to(Ax[i] - Ax[j] <= JERK_MAX * dts[i])

    for i in range(N - 2):
        _rate_pair(i, i + 1)
    _rate_pair(N - 2, 0)

    opti.minimize(total_time)
    # _V_CRAWL, not the monolithic 5.0: on a FROZEN tight line the grip-
    # limited corner speed can drop below 5 m/s (kart hairpin + anchor
    # ringing: 4.86 m/s at kappa=0.5, mu=1.2) and a 5.0 floor makes the
    # ellipse structurally infeasible — the monolithic NLP escapes by
    # bending the line, the speed pass cannot. It crawls instead; the
    # sector solves then fix the LINE and the speed comes back up.
    opti.subject_to(opti.bounded(_V_CRAWL, V, 120.0))
    opti.subject_to(V[0] == V[N - 1])

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
        ax_sol = np.array(sol.value(Ax)).flatten()
    except RuntimeError:
        ret = opti.return_status()
        status = ("acceptable" if ret == "Solved_To_Acceptable_Level"
                  else "suboptimal")
        logger.warning(
            "ocp_2d_stitched: speed pass non-optimal (return_status=%s)", ret)
        v_sol = np.clip(np.array(opti.debug.value(V)).flatten(), 5.0, 120.0)
        ax_sol = np.array(opti.debug.value(Ax)).flatten()
    return status, v_sol, ax_sol


def _ring_window(a: int, b: int, overlap: int, ring: int) -> list[int]:
    """Node indices of the extended window for sector (a, b) on the node ring.

    The closed lap has ``ring`` unique nodes (node ring == node 0); windows
    extend ``overlap`` nodes into each neighbour with modular wrap, so the
    sector spanning the periodic seam needs no special casing.
    """
    return [(a - overlap + t) % ring for t in range(b - a + 2 * overlap + 1)]


def solve_minimum_time_2d_stitched(
    track,
    vehicle: VehicleParams,
    mu_field,
    weather: WeatherConditions | None = None,
    n_points: int = 400,
    max_time_s: float = 120.0,
    sector_length_m: float = 50.0,
    overlap_nodes: int = 3,
    n_sweeps: int = 6,
    seam_d2n_tol: float = 0.05,
    coarse_n_points: int | None = None,
    envelope_caps: dict | None = None,
    grade_s: np.ndarray | None = None,
    camber_s: np.ndarray | None = None,
    warm_start=None,
    return_info: bool = False,
):
    """Stitched minimum-time 2D solve from ≤``sector_length_m`` sub-sectors.

    Scheme: coarse-anchored overlap windows + Jacobi consensus sweeps (design
    spec 2026-06-10). A cheap monolithic solve at ``coarse_n_points`` seeds a
    consensus trajectory on the fine grid; each sweep solves every sub-sector
    independently (parallel-safe — all read the PREVIOUS consensus) with its
    window ends pinned to the consensus, then rebuilds the consensus as the
    per-node mean of the free (un-pinned) window values. Deterministic: fixed
    sector order, fixed blend rule, fixed sweep count with a tolerance-based
    early exit on unchanging metrics.
    """
    import time as _time

    from telemetry_tool.lap_oracle.solver.ocp import _build_solution
    from telemetry_tool.lap_oracle.solver.ocp_2d import (
        _candidate_lap_time,
        _make_mu_interpolant_smooth,
        central_second_diff_periodic,
    )
    from telemetry_tool.lap_oracle.solver.ocp_2d import (
        solve_minimum_time_2d as _solve_mono,
    )
    from telemetry_tool.lap_oracle.track.model import resample_track

    if not HAS_CASADI:
        raise ImportError("solve_minimum_time_2d_stitched requires casadi")
    if weather is None:
        weather = WeatherConditions()
    t0 = _time.perf_counter()

    # ── shared discretization: byte-identical to solve_minimum_time_2d ──
    ds_target = track.total_length_m / n_points
    tk = resample_track(track, ds_target=ds_target)
    N = tk.n_points
    ring = N - 1                                   # unique nodes (closed lap)
    ds = tk.ds.astype(np.float64)
    kappa = tk.curvature.astype(np.float64)        # SIGNED
    s_coords = np.concatenate(([0.0], np.cumsum(ds)))
    s_coords = np.clip(
        s_coords, float(mu_field.s_bins[0]), float(mu_field.s_bins[-1]))
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
    grade_n = _to_n(grade_s)
    camber_n = _to_n(camber_s)

    mu_lut = _make_mu_interpolant_smooth(mu_field)
    ax_drive_interp = None
    ax_brake_interp = None
    if (envelope_caps and "v_grid" in envelope_caps
            and "ax_drive_max" in envelope_caps
            and "ax_brake_max" in envelope_caps):
        _ev = [float(x) for x in envelope_caps["v_grid"]]
        ax_drive_interp = ca.interpolant(
            "ax_drive_lookup", "linear", [_ev],
            [float(x) for x in envelope_caps["ax_drive_max"]])
        ax_brake_interp = ca.interpolant(
            "ax_brake_lookup", "linear", [_ev],
            [float(x) for x in envelope_caps["ax_brake_max"]])
    mu_ceiling = max(float(mu_field.mu_grid.max()), EPS_GRIP)

    n_lo_field = float(mu_field.n_bins[0])
    n_hi_field = float(mu_field.n_bins[-1])
    n_bounds: list[tuple[float, float]] = []
    for i in range(N):
        lo = max(-float(tk.width_right[i]) * 0.9, n_lo_field)
        hi = min(float(tk.width_left[i]) * 0.9, n_hi_field)
        n_bounds.append((lo, hi))

    # ── anchor: one monolithic solve seeds the consensus ──
    # Default = SOLVE resolution. On real grip fields (lateral mu structure)
    # the minimum-time landscape is multi-modal ACROSS resolutions: on MKR
    # the 200-pt and 400-pt monolithic solves sit 1.48 m rms apart, and the
    # coarse line — though smooth — prices 19 s slower on the fine grid; no
    # amount of ±V_PIN_BAND pinned sweeping recovers that. The stitched
    # solver's value is per-sector re-solves and parallel solving around a
    # known lap, not a cheaper cold solve. Callers may still pass a lower
    # coarse_n_points (uniform fields tolerate it — the oval holds 0.57%
    # from a 120-pt anchor) or a warm_start to skip the anchor cost.
    if coarse_n_points is None:
        coarse_n_points = n_points
    coarse = _solve_mono(
        track, vehicle, mu_field, weather=weather,
        n_points=coarse_n_points, max_time_s=max_time_s,
        warm_start=warm_start,
        envelope_caps=envelope_caps, grade_s=grade_s, camber_s=camber_s,
    )
    cd = np.asarray(coarse.distance_m, dtype=np.float64)
    cons_v = np.interp(s_coords, cd, np.asarray(coarse.speed_mps))
    # Smooth-monotone (PCHIP) interpolation for the LINE: linear interp makes
    # the anchor a polyline whose d2n spikes at every knot (the steering-rate
    # and ellipse terms then price phantom flicks, ~0.6 s on the oval before
    # any sweep runs). A C2 cubic spline fixes that but OVERSHOOTS at kart
    # hairpins; the overshoot leaves the track bounds and the subsequent clip
    # writes kinks back in (observed on MKR: crawl sections at every hairpin).
    # PCHIP is shape-preserving — bounded by its knot values, so it can never
    # leave the corridor the coarse line already respected. Wrapped ±4 knots
    # for closed-lap continuity at the seam.
    try:
        from scipy.interpolate import PchipInterpolator
        cn_src = np.asarray(coarse.lateral_offset_m, dtype=np.float64).copy()
        cn_src[-1] = cn_src[0]  # exact closure
        pad = 4
        cd_w = np.concatenate((
            cd[-1 - pad:-1] - cd[-1], cd, cd[1:1 + pad] + cd[-1]))
        cn_w = np.concatenate((cn_src[-1 - pad:-1], cn_src, cn_src[1:1 + pad]))
        interp = PchipInterpolator(cd_w, cn_w)
        cons_n = interp(np.clip(s_coords, cd[0], cd[-1]))
    except (ImportError, ValueError):
        cons_n = np.interp(s_coords, cd, np.asarray(coarse.lateral_offset_m))
    cons_v = np.clip(cons_v, 5.0, 120.0)

    def _repair_speed(v_arr, n_arr):
        """Boundary pins are equalities — a consensus speed the physics cannot
        hold makes a sector infeasible by construction. Produce PIN TARGETS
        (the output trajectory is the raw blend, never this haircut): lateral
        grip cap at the consensus line, then the forward-backward reachability
        clamp with friction-ellipse longitudinal headroom (braking while
        cornering has less grip to brake with)."""
        from telemetry_tool.lap_oracle.solver.ocp_2d import (
            central_second_diff_periodic,
        )
        mu_line = np.array([
            float(mu_lut(ca.DM([s_coords[i], n_arr[i]])))
            for i in range(N)
        ])
        mu_line = np.clip(mu_line, EPS_GRIP, mu_ceiling)
        v_arr = _lateral_speed_cap(
            v_arr, n_arr, kappa, ds, mu_line, vehicle, weather=weather)
        # lateral utilization at the capped speed -> longitudinal headroom
        mu_lat = vehicle.tyre_lat.D * weather.grip_multiplier * mu_line
        denom_ref = np.maximum(1.0 - n_arr * kappa, 0.1)
        d2n = central_second_diff_periodic(n_arr, ds)
        kappa_line = np.abs(kappa / denom_ref + d2n)
        ay_lim = mu_lat * (G + 0.5 * RHO_AIR * vehicle.cla * v_arr ** 2
                           / vehicle.mass_kg)
        u = np.clip(v_arr ** 2 * kappa_line / np.maximum(ay_lim, 1e-9), 0.0, 1.0)
        long_scale = np.sqrt(np.maximum(1.0 - u ** 2, 0.0))
        mu_long = vehicle.tyre_long.D * weather.grip_multiplier * mu_line
        ax_grip = mu_long * (G + 0.5 * RHO_AIR * vehicle.cla * v_arr ** 2
                             / vehicle.mass_kg)
        v_arr = _clamp_consensus_speed(
            v_arr, ds, vehicle, envelope_caps=envelope_caps,
            long_scale=long_scale, ax_grip_lim=ax_grip)
        return np.clip(v_arr, 5.0, 120.0)

    lo_arr = np.array([b[0] for b in n_bounds])
    hi_arr = np.array([b[1] for b in n_bounds])
    cons_n = np.clip(cons_n, lo_arr, hi_arr)
    cons_n[N - 1] = cons_n[0]
    cons_v[N - 1] = cons_v[0]

    sectors = partition_sectors(ds, kappa, sector_length_m=sector_length_m)

    def _speed_step(n_arr, v_guess_arr):
        """Block-coordinate speed step: the EXACT optimal speed for the
        current line, from the global speed-only pass. This is what makes
        the pins spiral-free: capping pin speeds at the current line (the
        old _repair_speed-only scheme) removed the incentive to apex — at a
        lower speed the time-optimal line is the SHORT inside path, which
        tightens the line, which lowers the next cap (observed: lap blew up
        +50% while every sector stayed feasible). The speed pass has no
        margins and is friction-ellipse/jerk/steering-rate exact, so pins
        derived from it are feasible-on-the-line by construction; sectors
        then improve the LINE around those speeds, raising the next pass.
        Falls back to the margin-based repair if IPOPT fails."""
        sp_st, v_line, _ = _solve_speed_on_line(
            ds=ds, kappa=kappa, kv=kv, s_coords=s_coords, mu_lut=mu_lut,
            n_line=n_arr, v_guess=v_guess_arr, vehicle=vehicle,
            weather=weather, max_time_s=max_time_s, mu_ceiling=mu_ceiling,
            ax_drive_interp=ax_drive_interp, ax_brake_interp=ax_brake_interp,
            grade_n=grade_n, camber_n=camber_n,
        )
        if sp_st == "suboptimal":
            return "suboptimal", _repair_speed(v_guess_arr.copy(), n_arr)
        return sp_st, np.clip(v_line, 5.0, 120.0)

    pin_status, pin_v = _speed_step(cons_n, cons_v)
    cons_v = pin_v.copy()

    def _stitch_metrics(v_arr, n_arr):
        lap = _candidate_lap_time(v_arr, ds, n_arr, kappa)
        d2n = central_second_diff_periodic(n_arr, ds)
        jumps = []
        for a, _b in sectors:
            jumps.append(abs(d2n[a] - d2n[a - 1]))
            jumps.append(abs(d2n[(a + 1) % len(d2n)] - d2n[a]))
        return lap, float(np.max(jumps))

    # Best-tracking: the pinned-window iteration is not guaranteed monotone
    # (its fixed point is not the global optimum), so keep the best
    # (lap, line, speed, status) seen — including the anchor itself — and
    # return THAT. Makes the output monotone-in-sweeps by construction and
    # immune to late-sweep drift. Strict < keeps the earliest on ties
    # (deterministic).
    best_lap, _ = _stitch_metrics(pin_v, cons_n)
    best_n = cons_n.copy()
    best_v = pin_v.copy()
    best_status = pin_status if pin_status != "suboptimal" else "acceptable"
    prev_lap = best_lap
    sweeps_run = 0
    stale_sweeps = 0
    worst = "optimal"

    for _sweep in range(n_sweeps):
        sweeps_run += 1
        acc_v = np.zeros(ring)
        acc_n = np.zeros(ring)
        cnt = np.zeros(ring)
        sweep_worst = "optimal"
        for a, b in sectors:
            idx = _ring_window(a, b, overlap_nodes, ring)
            n_w = len(idx)
            ds_w = np.array([ds[idx[j]] for j in range(n_w - 1)])
            cv = pin_v[idx]
            cn = cons_n[idx]
            ax_g = (cv[1:] ** 2 - cv[:-1] ** 2) / (2.0 * np.maximum(ds_w, 1e-6))
            ghost = float(cons_n[(idx[0] - 1) % ring])
            status, v_s, n_s, _ax_s = _solve_sector(
                ds=ds_w, kappa=kappa[idx], kv=kv[idx],
                s_coords=s_coords[idx],
                mu_lut=mu_lut, n_bounds=[n_bounds[k] for k in idx],
                cons_v=cv, cons_n=cn, ax_guess=np.clip(ax_g, -50.0, 50.0),
                vehicle=vehicle, weather=weather, max_time_s=max_time_s,
                mu_ceiling=mu_ceiling, n_ghost_prev=ghost,
                ax_drive_interp=ax_drive_interp,
                ax_brake_interp=ax_brake_interp,
                grade_n=None if grade_n is None else grade_n[idx],
                camber_n=None if camber_n is None else camber_n[idx],
            )
            if status == "suboptimal":
                # deterministic fallback: this window contributes the OLD
                # consensus (never poisons neighbours with garbage iterates)
                sweep_worst = "acceptable"
                v_s, n_s = cv, cn
            elif status == "acceptable" and sweep_worst == "optimal":
                sweep_worst = "acceptable"
            # Partition-of-unity blend over the FREE zone: triangular weight
            # peaking mid-window, fading to (near) zero at the free-zone
            # edges, so each window hands off smoothly inside the overlap
            # instead of being spliced (see _BLEND_DAMP note at module top).
            for j in range(_N_PIN, n_w - _N_PIN):
                k = idx[j]
                w = float(min(j - _N_PIN + 1, n_w - 1 - _N_PIN - j + 1))
                acc_v[k] += w * v_s[j]
                acc_n[k] += w * n_s[j]
                cnt[k] += w
        live = cnt > 0
        new_v = cons_v.copy()
        new_n = cons_n.copy()
        # damped update: consensus + DAMP * (blend - consensus)
        new_v[:ring][live] = ((1.0 - _BLEND_DAMP) * cons_v[:ring][live]
                              + _BLEND_DAMP * acc_v[live] / cnt[live])
        new_n[:ring][live] = ((1.0 - _BLEND_DAMP) * cons_n[:ring][live]
                              + _BLEND_DAMP * acc_n[live] / cnt[live])
        new_v[N - 1] = new_v[0]
        new_n[N - 1] = new_n[0]
        cons_n = np.clip(new_n, lo_arr, hi_arr)
        cons_v = np.clip(new_v, 5.0, 120.0)          # OUTPUT: raw blend
        # next sweep's pins: EXACT speed for the blended line (speed step)
        pin_status, pin_v = _speed_step(cons_n, cons_v)
        if pin_status == "suboptimal":
            sweep_worst = "acceptable"
        worst = sweep_worst

        lap, seam = _stitch_metrics(pin_v, cons_n)
        logger.info(
            "stitched sweep %d: lap=%.4fs seam=%.5f", sweeps_run, lap, seam)
        if (lap < best_lap and seam < seam_d2n_tol
                and pin_status != "suboptimal"):
            best_lap = lap
            best_n = cons_n.copy()
            best_v = pin_v.copy()
            best_status = ("acceptable" if (sweep_worst != "optimal"
                                            or pin_status != "optimal")
                           else "optimal")
            stale_sweeps = 0
        else:
            stale_sweeps += 1
        # exit when sweeps stop improving the BEST (2 stale sweeps), or on
        # plain convergence (no change). Best-tracking already guards the
        # output, so this is purely a wall-time economy.
        if stale_sweeps >= 2 or (
                sweeps_run >= 2
                and abs(lap - prev_lap) / max(prev_lap, 1e-9) < 5e-4):
            prev_lap = lap
            break
        prev_lap = lap

    # ── output: the BEST (line, exact speed) seen across the anchor and all
    # sweeps (the pinned-window iteration is not monotone; best-tracking
    # makes the returned solution monotone-in-sweeps by construction).
    n_sol = best_n
    v_sol = best_v
    ax_sol = (v_sol[1:] ** 2 - v_sol[:-1] ** 2) / (
        2.0 * np.maximum(ds, 1e-6))
    worst = best_status  # status of the returned snapshot, not the last sweep

    elapsed = _time.perf_counter() - t0
    solution = _build_solution(
        track, vehicle, weather, tk, v_sol, n_sol, ax_sol, ds, worst, elapsed,
    )
    solution.optimal_lap_time_s = _candidate_lap_time(v_sol, ds, n_sol, kappa)
    if return_info:
        lap, seam = _stitch_metrics(v_sol, n_sol)
        info = {
            "sectors": sectors,
            "sweeps_run": sweeps_run,
            "seam_max_jump": seam,
            "coarse_lap_s": float(coarse.optimal_lap_time_s),
        }
        return solution, info
    return solution
