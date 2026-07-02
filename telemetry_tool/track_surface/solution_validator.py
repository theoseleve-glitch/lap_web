"""Physics self-consistency validator (spec section 5).

Audits an already-solved :class:`OCPSolution` from its OUTPUTS ONLY --
speed, lateral offset, and track geometry -- independent of solver
internals. This is the program's honesty instrument: it never reads a
solver's internal decision variables (there are none available on
``OCPSolution`` anyway) and never trusts the track's precomputed planar
``curvature`` array either -- centerline curvature is always re-derived
from ``centerline_xy`` (see ``_centerline_curvature``). The offset path's
arc length is reconstructed from the reported ``distance_m``/
``lateral_offset_m`` arrays by finite differences; its CURVATURE (used by
``friction_ellipse``) instead uses the analytic offset-curve formula
``kappa_c/(1 - n*kappa_c) + d2n/ds2`` -- the SAME formula
``lap_oracle.solver.ocp_2d._solve_once`` enforces (see
``_offset_curvature``). A raw finite-difference of heading reconstructed
from offset (x, y) is itself an ill-conditioned measurement wherever
kappa_c changes fastest (straight/arc transitions) while n(s) is also
changing fastest (corner entry) at the same time -- confirmed root cause
of a 9.8x false-positive friction_ellipse failure, see
b1-task-6b-debug-report.md. A solver bug must not also corrupt the audit,
but neither should the audit's OWN reconstruction manufacture a false one.

The friction-ellipse limits (fz, mu, camber boost) mirror
``lap_oracle.solver.ocp_2d._solve_once`` exactly -- module constants
(G, RHO_AIR, EPS_GRIP, K_CAMBER, DKAPPA_MAX) and the mu lookup
(``_make_mu_interpolant_smooth``, the SAME C2 bspline the solver's NLP
reads grip through, not the layout-locked linear variant -- measured up to
0.1116 divergence from the smooth one on a real grip field, per
``--mu-divergence`` in scripts/validate_b1_quasi3d.py) are imported and
reused, never re-hardcoded. The mu VALUE is additionally floored/capped at
``[EPS_GRIP, max(mu_grid.max(), EPS_GRIP)]`` in ``_check_friction_ellipse``
-- the SAME clamp ``_solve_once`` applies via ``ca.fmax``/``ca.fmin`` right
after its own bspline lookup, so bspline undershoot/overshoot ringing near a
sharp grip step is bounded identically on both sides (verified equal to the
solver's own clamp to machine precision on a real grip field, round 2).

``a_lon`` (used by ``friction_ellipse``) mirrors the solver's ``Ax`` decision
variable EXACTLY (see ``_solver_a_lon``): the solver's speed ODE
(``V[i+1]**2 == V[i]**2 + 2*Ax[i]*ds_path_i``) is an EQUALITY constraint with
no drag/rolling-resistance/grade term in it, so ``Ax[i]`` IS the net
kinematic accel, not a separate "tire demand" needing a drag/rr recovery --
drag/rr/grade only narrow ``Ax``'s FEASIBLE range via separate inequality
constraints, never its definition or the ellipse itself (round-2 hypothesis
tested and REFUTED with evidence, see b1-task-6c-debug2-report.md). What the
ellipse actually checks is a per-SEGMENT FORWARD difference of v^2 over the
Frenet-adjusted path length (``ds_path_i``), evaluated at the segment's
START node together with that SAME node's ax_lim/ay_lim -- never blended
with a neighbouring segment. A node-centered central difference over the
reconstructed offset-path chord length (the prior formula here) instead
averages two adjacent segments into one node, which at a sharp mu step
smears a high-grip segment's kinematics into a low-grip neighbour's own
(tiny) limit -- confirmed root cause of a 24.7x friction_ellipse
false-positive on a real track.
"""
from __future__ import annotations

from dataclasses import dataclass

import casadi as ca
import numpy as np

from lap_oracle.config import OCPSolution, TrackModel, VehicleParams
from lap_oracle.solver.ocp_2d import (
    DKAPPA_MAX,
    EPS_GRIP,
    G,
    K_CAMBER,
    RHO_AIR,
    MuField,
    _make_mu_interpolant,
    _make_mu_interpolant_smooth,
    _PATH_LEN_FLOOR,
    central_second_diff_periodic,
)
from track_surface.geom_field import GeomField

# Task 6's smoothness rail check is 1.2x the solver's own hard cap on |d2n|
# (DKAPPA_MAX) -- generous enough to never bind the clean line, tight enough
# to catch a real seam kink. Derived from the imported constant, never a
# copied literal.
SMOOTHNESS_BOUND: float = 1.2 * DKAPPA_MAX

# Nodes excluded from the friction_ellipse residual at each end of the array:
# finite-difference curvature/dv-ds stencils are least accurate there.
_EDGE_EXCLUDE: int = 3

# ca.interpolant(..., "bspline", ...) hard-errors ("Need more data points")
# below this many knots per axis (empirically verified: 3 fails, 4 works) --
# mirrors ocp_2d._make_geom_interpolants' identical >=4 bspline/linear
# fallback threshold for the same reason.
_MU_BSPLINE_MIN_KNOTS: int = 4

# NOTE on closure convention: smoothness check uses solver's periodic second-difference
# (central_second_diff_periodic for closed track); heading/curvature for friction_ellipse
# and lap_time_consistent use open-endpoint stencils + 3-node edge exclusion. Do not
# unify these -- they reflect the distinct boundary semantics (closed path vs. interval).


@dataclass
class CheckResult:
    check: str
    passed: bool
    worst: float
    detail: str


@dataclass
class ValidationReport:
    passed: bool
    checks: list[CheckResult]

    def to_dict(self) -> dict:
        return {
            "passed": bool(self.passed),
            "checks": [
                {
                    "check": c.check,
                    "passed": bool(c.passed),
                    "worst": float(c.worst),
                    "detail": c.detail,
                }
                for c in self.checks
            ],
        }


# ---------------------------------------------------------------------------
# Geometry reconstruction helpers (pure numpy)
# ---------------------------------------------------------------------------

def _track_s(track: TrackModel) -> np.ndarray:
    """Cumulative arclength at each centerline node (0 at the first node)."""
    if track.n_points == 0:
        return np.zeros(0)
    if track.n_points == 1:
        return np.zeros(1)
    return np.concatenate(([0.0], np.cumsum(track.ds)))


def _heading(xy: np.ndarray) -> np.ndarray:
    """Tangent heading (radians) via central differences; one-sided at ends.

    Mirrors track_surface.frenet._compute_heading's stencil exactly (kept
    local/self-contained so this module reconstructs geometry from OUTPUTS
    only, without importing FrenetFrame machinery it doesn't otherwise need).
    """
    n = len(xy)
    if n == 0:
        return np.zeros(0)
    if n == 1:
        return np.zeros(1)
    dx = np.empty(n)
    dy = np.empty(n)
    dx[1:-1] = xy[2:, 0] - xy[:-2, 0]
    dy[1:-1] = xy[2:, 1] - xy[:-2, 1]
    dx[0] = xy[1, 0] - xy[0, 0]
    dy[0] = xy[1, 1] - xy[0, 1]
    dx[-1] = xy[-1, 0] - xy[-2, 0]
    dy[-1] = xy[-1, 1] - xy[-2, 1]
    return np.arctan2(dy, dx)


def _offset_path_xy(track: TrackModel, distance_m: np.ndarray, n: np.ndarray) -> np.ndarray:
    """Reconstruct the actually-driven path: centerline + n * unit normal.

    Same convention as track_surface.frenet.FrenetFrame.sn_to_xy (normal =
    90 deg CCW from tangent, + = track-left): interpolate the centerline
    position and heading to the solution's own ``distance_m`` grid, then
    offset laterally by ``n``.
    """
    s_track = _track_s(track)
    cxy = track.centerline_xy
    if len(s_track) < 2:
        return cxy.copy()
    heading = _heading(cxy)
    d = np.clip(np.asarray(distance_m, dtype=float), s_track[0], s_track[-1])
    x_c = np.interp(d, s_track, cxy[:, 0])
    y_c = np.interp(d, s_track, cxy[:, 1])
    h = np.interp(d, s_track, heading)
    nx, ny = -np.sin(h), np.cos(h)
    n = np.asarray(n, dtype=float)
    return np.column_stack([x_c + n * nx, y_c + n * ny])


def _bilinear(s_bins: np.ndarray, n_bins: np.ndarray, grid: np.ndarray,
              s: np.ndarray, n: np.ndarray) -> np.ndarray:
    """Vectorised bilinear lookup -- same formula as GripSurface.mu_at,
    generalised to arbitrary (s_bins, n_bins, grid) and array queries.
    Used for GeomField kv/camber (pure-numpy geometry path); the mu lookup
    itself uses the solver's own casadi interpolant (see _check_friction_ellipse)."""
    s_bins = np.asarray(s_bins, dtype=float)
    n_bins = np.asarray(n_bins, dtype=float)
    s = np.clip(np.asarray(s, dtype=float), s_bins[0], s_bins[-1])
    n = np.clip(np.asarray(n, dtype=float), n_bins[0], n_bins[-1])
    si = np.clip(np.searchsorted(s_bins, s) - 1, 0, len(s_bins) - 2)
    ni = np.clip(np.searchsorted(n_bins, n) - 1, 0, len(n_bins) - 2)
    s0, s1 = s_bins[si], s_bins[si + 1]
    n0, n1 = n_bins[ni], n_bins[ni + 1]
    ws = (s - s0) / np.maximum(s1 - s0, 1e-9)
    wn = (n - n0) / np.maximum(n1 - n0, 1e-9)
    v00 = grid[si, ni]
    v10 = grid[si + 1, ni]
    v01 = grid[si, ni + 1]
    v11 = grid[si + 1, ni + 1]
    return v00 * (1 - ws) * (1 - wn) + v10 * ws * (1 - wn) + v01 * (1 - ws) * wn + v11 * ws * wn


def _make_mu_lut(mu_field: MuField):
    """mu(s, n) lookup for the friction-ellipse audit.

    Prefers the SAME smooth C2 bspline interpolant the solver's NLP reads
    grip through (``_make_mu_interpolant_smooth``), so the audit validates
    against the mu surface the solver actually respected -- the
    layout-locked LINEAR variant measured max|mu_linear - mu_bspline| =
    0.1116 on a real grip field (``--mu-divergence``), i.e. a different mu
    surface than the one the solver enforced limits against. Falls back to
    the linear interpolant when the grid is too sparse for a cubic bspline
    (< 4 knots per axis; CasADi hard-errors "Need more data points"
    otherwise) -- mirrors ``ocp_2d._make_geom_interpolants``'s identical
    >=4 fallback. Real grip fields are always dense enough for bspline in
    practice; only minimal hand-built test fixtures hit this fallback.
    """
    if (len(mu_field.s_bins) >= _MU_BSPLINE_MIN_KNOTS
            and len(mu_field.n_bins) >= _MU_BSPLINE_MIN_KNOTS):
        return _make_mu_interpolant_smooth(mu_field)
    return _make_mu_interpolant(mu_field)


def _centerline_curvature(track: TrackModel) -> np.ndarray:
    """Reference (centerline) curvature at each of the track's OWN nodes.

    Mirrors ``lap_oracle.track.model.build_from_xy``'s finite-difference
    recipe exactly (np.gradient twice), but is NOT imported from there --
    same self-contained convention as ``_heading`` (this module reconstructs
    geometry from raw coordinates only, without pulling in track-construction
    machinery it doesn't otherwise need). Deliberately ignores
    ``track.curvature`` even when populated: the solver's own reference
    curvature (``ocp_2d.solve_minimum_time_2d``'s ``kappa``) always comes
    from a fresh ``resample_track`` -> ``build_from_xy`` recompute too, never
    from a source track's pre-existing ``curvature`` field, so re-deriving
    here keeps the validator consistent with what the solver actually
    enforces rather than trusting a possibly stale/differently-sourced input.
    """
    xy = track.centerline_xy
    m = len(xy)
    if m < 2:
        return np.zeros(m)
    x, y = xy[:, 0], xy[:, 1]
    dx, dy = np.gradient(x), np.gradient(y)
    ddx, ddy = np.gradient(dx), np.gradient(dy)
    denom = (dx ** 2 + dy ** 2) ** 1.5
    denom = np.where(denom < 1e-12, 1e-12, denom)
    return (dx * ddy - dy * ddx) / denom


def _offset_curvature(track: TrackModel, d: np.ndarray, n: np.ndarray) -> np.ndarray:
    """Analytic offset-curve curvature from the SOLVED (s, n) arrays.

    Mirrors ``lap_oracle.solver.ocp_2d._solve_once``'s own
    ``kappa_line_i = kappa_i / denom_i + d2n_i`` EXACTLY (``denom_i`` floored
    at 0.1, same as the solver's constraint) -- this is the curvature the
    solver's friction-ellipse constraint actually enforces, so it is what the
    audit must reconstruct too. ``kappa_c(s)`` is TRACK geometry (an input,
    not a solver output): computed once by ``_centerline_curvature`` and
    interpolated onto ``d``. ``d2n/ds2`` uses the SAME periodic stencil as
    the smoothness check (``central_second_diff_periodic``), applied to
    n(s) alone -- n is smooth (the solver hard-bounds |d2n| <= DKAPPA_MAX) --
    unlike a raw finite-difference of heading re-derived from reconstructed
    (x, y), which compounds two finite differences (position -> heading ->
    curvature) on a path that ALSO carries n(s)'s own excursions, and is
    where the original friction_ellipse false-positive lived (see
    b1-task-6b-debug-report.md: root-caused to this reconstruction, not a
    real solver violation).
    """
    N = len(d)
    if N == 0:
        return np.zeros(0)
    s_track = _track_s(track)
    if len(s_track) < 2:
        return np.zeros(N)
    d_c = np.clip(d, s_track[0], s_track[-1])
    kappa_c = np.interp(d_c, s_track, _centerline_curvature(track))
    d2n = central_second_diff_periodic(n, np.diff(d)) if N >= 3 else np.zeros(N)
    denom = np.maximum(1.0 - n * kappa_c, 0.1)
    return kappa_c / denom + d2n


def _solver_a_lon(track: TrackModel, d: np.ndarray, n: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Longitudinal accel from the SOLVED (s, n, v) arrays, mirroring
    ``lap_oracle.solver.ocp_2d._solve_once``'s ``Ax`` EXACTLY.

    The solver's speed ODE is the EQUALITY constraint
    ``V[i+1]**2 == V[i]**2 + 2*Ax[i]*ds_path_i``, so ``Ax[i]`` is a per-
    SEGMENT forward difference of v^2 over the Frenet-adjusted path length
    ``ds_path_i = ds[i] * max(1 - n_mid_i*kappa_c_i, _PATH_LEN_FLOOR)`` (the
    SAME Jacobian ``_offset_curvature``/the solver's own ``ds_path_i`` use --
    ``kappa_c`` is centerline curvature, interpolated the same way
    ``_offset_curvature`` does). This is a DIFFERENT quantity from a
    node-centered central difference of v over the reconstructed offset-path
    chord length (this function's predecessor here): the solver never
    blends segment i with segment i-1 the way a central difference at node i
    does, and it Jacobian-scales by the offset path's own length, not the
    raw geometric chord -- both matter at a sharp mu/grip step, where
    blending smears a high-grip neighbour's kinematics into a low-grip
    segment's own (tiny) limit (see b1-task-6c-debug2-report.md).

    Returns an N-length array: index i (0..N-2) is segment i's Ax, aligned
    with that SAME index's ax_lim/ay_lim/a_lat in ``_check_friction_ellipse``
    -- exactly how the solver pairs them. Index N-1 (the last node) has no
    solver segment to mirror (``Ax`` has only N-1 entries; N_lat[0]==N_lat[N-1]
    make it a periodic duplicate of node 0 anyway) -- repeats the last real
    value; ``_EDGE_EXCLUDE`` always drops it from the residual, so its exact
    value is inert.
    """
    N = len(v)
    if N < 2:
        return np.zeros(N)
    ds = np.diff(d)
    ds_safe = np.where(np.abs(ds) > 1e-9, ds, 1e-9)
    s_track = _track_s(track)
    if len(s_track) >= 2:
        d_c = np.clip(d, s_track[0], s_track[-1])
        kappa_c = np.interp(d_c, s_track, _centerline_curvature(track))
        n_mid = 0.5 * (n[:-1] + n[1:])
        ds_path = ds_safe * np.maximum(1.0 - n_mid * kappa_c[:-1], _PATH_LEN_FLOOR)
    else:
        ds_path = ds_safe
    ax_forward = (v[1:] ** 2 - v[:-1] ** 2) / (2.0 * ds_path)
    return np.concatenate([ax_forward, ax_forward[-1:]])


@dataclass
class _Kinematics:
    """Reconstructed-from-outputs bundle shared by friction_ellipse and
    lap_time_consistent so the offset path is computed exactly once."""
    d: np.ndarray
    n: np.ndarray
    v: np.ndarray
    xy: np.ndarray
    seg_ds: np.ndarray
    s_off: np.ndarray
    kappa_path: np.ndarray
    a_lat: np.ndarray
    a_lon: np.ndarray


def _reconstruct(sol: OCPSolution, track: TrackModel) -> _Kinematics:
    d = np.asarray(sol.distance_m, dtype=float)
    n = np.asarray(sol.lateral_offset_m, dtype=float)
    v = np.asarray(sol.speed_mps, dtype=float)
    xy = _offset_path_xy(track, d, n)
    if len(xy) >= 2:
        seg = np.diff(xy, axis=0)
        seg_ds = np.sqrt((seg ** 2).sum(axis=1))
        s_off = np.concatenate(([0.0], np.cumsum(seg_ds)))
    else:
        seg_ds = np.zeros(0)
        s_off = np.zeros(len(xy))
    kappa_path = _offset_curvature(track, d, n)
    a_lat = v ** 2 * kappa_path
    a_lon = _solver_a_lon(track, d, n, v)
    return _Kinematics(d=d, n=n, v=v, xy=xy, seg_ds=seg_ds, s_off=s_off,
                        kappa_path=kappa_path, a_lat=a_lat, a_lon=a_lon)


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def _check_finite_speed(sol: OCPSolution) -> CheckResult:
    v = np.asarray(sol.speed_mps, dtype=float)
    if v.size == 0:
        return CheckResult("finite_speed", False, 0.0, "speed array is empty")
    bad = ~np.isfinite(v) | (v <= 0)
    n_bad = int(np.count_nonzero(bad))
    passed = n_bad == 0
    detail = (
        f"all {v.size} nodes finite and positive (min={float(v.min()):.3f} m/s)"
        if passed else
        f"{n_bad}/{v.size} nodes have non-finite or non-positive speed"
    )
    return CheckResult("finite_speed", passed, float(n_bad), detail)


def _check_track_limits(sol: OCPSolution, track: TrackModel) -> CheckResult:
    n = np.asarray(sol.lateral_offset_m, dtype=float)
    d = np.asarray(sol.distance_m, dtype=float)
    s_track = _track_s(track)
    if track.n_points < 2 or n.size == 0 or len(s_track) < 2:
        return CheckResult("track_limits", True, 0.0, "insufficient track/solution data -- skipped")
    d_c = np.clip(d, s_track[0], s_track[-1])
    w_left = np.interp(d_c, s_track, track.width_left)
    w_right = np.interp(d_c, s_track, track.width_right)
    hi = w_left + 0.05
    lo = -w_right - 0.05
    viol = np.maximum(np.maximum(n - hi, lo - n), 0.0)
    worst = float(np.max(viol))
    passed = bool(worst <= 1e-9)
    detail = f"max excursion beyond corridor (+/-0.05 m margin) = {worst:.4f} m"
    return CheckResult("track_limits", passed, worst, detail)


def _check_controls_bounded(sol: OCPSolution) -> CheckResult:
    lo, hi = -0.01, 1.01
    arrays = []
    if sol.throttle is not None and len(sol.throttle) > 0:
        arrays.append(np.asarray(sol.throttle, dtype=float))
    if sol.brake is not None and len(sol.brake) > 0:
        arrays.append(np.asarray(sol.brake, dtype=float))
    if not arrays:
        return CheckResult("controls_bounded", True, 0.0, "no throttle/brake arrays present -- skipped")
    combined = np.concatenate(arrays)
    viol = np.maximum(np.maximum(combined - hi, lo - combined), 0.0)
    worst = float(np.max(viol))
    passed = bool(worst <= 1e-9)
    detail = f"max out-of-[{lo}, {hi}] margin = {worst:.4f}"
    return CheckResult("controls_bounded", passed, worst, detail)


def _check_smoothness(sol: OCPSolution) -> CheckResult:
    d = np.asarray(sol.distance_m, dtype=float)
    n = np.asarray(sol.lateral_offset_m, dtype=float)
    if n.size < 3:
        return CheckResult("smoothness", True, 0.0, "too few nodes -- skipped")
    ds = np.diff(d)
    ds = np.where(np.abs(ds) > 1e-9, ds, 1e-9)
    d2n = central_second_diff_periodic(n, ds)
    if not np.all(np.isfinite(d2n)):
        finite = d2n[np.isfinite(d2n)]
        worst = float(np.max(np.abs(finite))) if finite.size else 0.0
        return CheckResult("smoothness", True, worst,
                            "skipped: non-finite lateral_offset_m upstream (see finite_speed/track_limits)")
    worst = float(np.max(np.abs(d2n)))
    passed = bool(worst <= SMOOTHNESS_BOUND)
    detail = f"max |d2n/ds2| = {worst:.4f} (threshold {SMOOTHNESS_BOUND:.4f} = 1.2 x DKAPPA_MAX)"
    return CheckResult("smoothness", passed, worst, detail)


def _check_lap_time_consistent(kin: _Kinematics, sol: OCPSolution, *, eps: float) -> CheckResult:
    if kin.v.size < 2:
        return CheckResult("lap_time_consistent", True, 0.0, "too few nodes -- skipped")
    v_avg = 0.5 * (kin.v[:-1] + kin.v[1:])
    with np.errstate(divide="ignore", invalid="ignore"):
        lap_time = float(np.sum(kin.seg_ds / v_avg))
    target = float(sol.optimal_lap_time_s)
    if not np.isfinite(lap_time) or not np.isfinite(target) or target == 0.0:
        return CheckResult("lap_time_consistent", True, 0.0,
                            "reconstructed or reported lap time non-finite/zero -- skipped "
                            "(see finite_speed for the likely root cause)")
    rel_err = abs(lap_time - target) / abs(target)
    passed = bool(rel_err <= eps)
    detail = (f"reconstructed {lap_time:.4f}s vs reported {target:.4f}s "
              f"({rel_err * 100:.2f}% rel. error, tolerance {eps * 100:.1f}%)")
    return CheckResult("lap_time_consistent", passed, float(rel_err), detail)


def _check_friction_ellipse(
    kin: _Kinematics, track: TrackModel, mu_field: MuField, vehicle: VehicleParams,
    weather_grip_multiplier: float, *, geom_field: GeomField | None,
    camber_s: np.ndarray | None = None, eps: float,
) -> CheckResult:
    v, n, d = kin.v, kin.n, kin.d
    N = len(v)
    if N <= 2 * _EDGE_EXCLUDE:
        lo_i, hi_i = 0, N
    else:
        lo_i, hi_i = _EDGE_EXCLUDE, N - _EDGE_EXCLUDE

    s_track = _track_s(track)
    d_c = np.clip(d, s_track[0], s_track[-1]) if len(s_track) else d

    # g_eff from vertical curvature: geom_field at (s, n) if given, else the
    # track's own vert_curvature interpolated to distance_m, else flat (kv=0
    # -> g_eff falls back to plain G). Mirrors _solve_once's kv_i/g_eff_i.
    if geom_field is not None:
        kv = _bilinear(geom_field.s_bins, geom_field.n_bins, geom_field.kv_grid, d_c, n)
        camber = _bilinear(geom_field.s_bins, geom_field.n_bins, geom_field.camber_grid, d_c, n)
    else:
        if track.vert_curvature is not None and len(track.vert_curvature) == len(s_track) and len(s_track):
            kv = np.interp(d_c, s_track, track.vert_curvature)
        else:
            kv = np.zeros(N)
        camber = np.zeros(N)

    g_eff = np.maximum(G + v ** 2 * kv, 1.0)
    fz_total = vehicle.mass_kg * g_eff + 0.5 * RHO_AIR * vehicle.cla * v ** 2

    # mu(s, n): the solver's own numeric lookup, evaluated pointwise (not
    # inside an Opti) -- float(lut(ca.DM([s, n]))) is the documented pattern.
    # See _make_mu_lut: bspline (matches the solver's NLP) with a linear
    # fallback for grids too sparse for a cubic bspline.
    mu_lut = _make_mu_lut(mu_field)
    s_mu = np.clip(d, mu_field.s_bins[0], mu_field.s_bins[-1])
    n_mu = np.clip(n, mu_field.n_bins[0], mu_field.n_bins[-1])
    grip_raw = np.array([float(mu_lut(ca.DM([float(si), float(ni)]))) for si, ni in zip(s_mu, n_mu)])
    mu_ceiling = max(float(mu_field.mu_grid.max()), EPS_GRIP)
    grip = np.clip(grip_raw, EPS_GRIP, mu_ceiling)

    mu_lat = vehicle.tyre_lat.D * weather_grip_multiplier * grip
    mu_long = vehicle.tyre_long.D * weather_grip_multiplier * grip
    ax_lim = mu_long * fz_total / vehicle.mass_kg
    ay_lim = mu_lat * fz_total / vehicle.mass_kg
    # Mirror solver's precedence: geom_field's camber boost takes precedence;
    # if not available, use legacy camber_s 1D boost.
    if geom_field is not None:
        ay_lim = ay_lim * (1.0 + K_CAMBER * np.abs(camber))
    elif camber_s is not None:
        # Resample camber_s (track-space) to solution's distance_m grid via interpolation.
        s_track_grid = _track_s(track)
        if len(s_track_grid) >= 2:
            camber_resampled = np.interp(d, s_track_grid, camber_s)
            ay_lim = ay_lim * (1.0 + K_CAMBER * np.abs(camber_resampled))

    with np.errstate(divide="ignore", invalid="ignore"):
        r = (kin.a_lon / ax_lim) ** 2 + (kin.a_lat / ay_lim) ** 2

    r_interior = r[lo_i:hi_i]
    if r_interior.size == 0:
        return CheckResult("friction_ellipse", True, 0.0, "no interior nodes to check")
    if not np.all(np.isfinite(r_interior)):
        # A non-finite residual here means an upstream input (speed, offset
        # path) was already invalid -- that is finite_speed's (or another
        # check's) finding to report, not a friction-ellipse violation in
        # its own right.
        finite = r_interior[np.isfinite(r_interior)]
        worst = float(np.max(finite)) if finite.size else 0.0
        return CheckResult("friction_ellipse", True, worst,
                            "skipped: non-finite inputs upstream (see finite_speed)")

    worst = float(np.max(r_interior))
    passed = bool(worst <= 1.0 + eps)
    detail = (f"max (a_lon/ax_lim)^2+(a_lat/ay_lim)^2 = {worst:.4f} over "
              f"{r_interior.size} interior nodes (threshold {1.0 + eps:.4f})")
    return CheckResult("friction_ellipse", passed, worst, detail)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def validate_solution(
    sol: OCPSolution,
    track: TrackModel,
    mu_field: MuField,
    vehicle: VehicleParams,
    *,
    geom_field: GeomField | None = None,
    camber_s: np.ndarray | None = None,
    eps: float = 0.02,
) -> ValidationReport:
    """Audit ``sol`` from its outputs only. ``eps`` is the shared slack: the
    friction-ellipse residual tolerance (pass iff max(r) <= 1+eps) and the
    lap-time relative tolerance both default to the same 2%.

    Legacy 1D camber boost: if camber_s is provided (and geom_field is None),
    the ay_lim friction limit is boosted by (1 + K_CAMBER * |camber|) where
    camber is resampled from the track's arclength grid to the solution's
    distance_m grid.
    """
    weather = getattr(sol, "weather", None)
    grip_multiplier = float(weather.grip_multiplier) if weather is not None else 1.0

    kin = _reconstruct(sol, track)

    checks = [
        _check_finite_speed(sol),
        _check_track_limits(sol, track),
        _check_friction_ellipse(
            kin, track, mu_field, vehicle, grip_multiplier,
            geom_field=geom_field, camber_s=camber_s, eps=eps,
        ),
        _check_controls_bounded(sol),
        _check_lap_time_consistent(kin, sol, eps=eps),
        _check_smoothness(sol),
    ]
    return ValidationReport(passed=all(c.passed for c in checks), checks=checks)
